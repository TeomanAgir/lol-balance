"""fix-3 — idari yüzey sertleştirme (api_contract "Admin anahtarı" + §5).

Kapsam:
  1. Admin kapsamının GENİŞLEMESİ: `roulette/unlink`, `POST /players`,
     `PATCH /players/{id}` artık `X-Admin-Key` ister.
  2. Kapsam DIŞINDA kalanların regresyon koruması: `PUT /positions` ve
     `PUT /items` admin anahtarı OLMADAN çalışmaya devam eder — collector'ın
     `backfill-positions`/`backfill-items` komutları bu uçları arkadaşların
     PC'sinden çağırır (contract'taki bilinçli açık uç kararı).
  3. ASCII kuralı: ASCII olmayan `ADMIN_KEY` → 503 + teşhis edici detail;
     uygulamanın geri kalanı ayakta kalır.
  4. Hız sınırı: başarısız denemede sabit gecikme, IP başına kayan pencerede
     N denemeden sonra 429 + `Retry-After`, başarılı doğrulama sayacı sıfırlar.
  5. Atomiklik: void ve unlink'te durum yazımı + iki evren replay TEK
     transaction — replay patlarsa durum yazımı da geri alınır.
"""
from __future__ import annotations

import time
from contextlib import contextmanager

import pytest
from conftest import ADMIN_KEY, API_KEY, POSITIONS, make_role_payload, make_roster_payload

# ASCII olmayan (Türkçe karakterli) anahtar — contract'taki kilitlenme senaryosu.
NON_ASCII_ADMIN_KEY = "şifreğüç-123"


@contextmanager
def _client_with_admin_key(db_path, monkeypatch, admin_key: str | None):
    """conftest.client'ın ADMIN_KEY'i seçilebilen kopyası (test_admin_key deseni)."""
    monkeypatch.setenv("API_KEY", API_KEY)
    if admin_key is None:
        monkeypatch.delenv("ADMIN_KEY", raising=False)
    else:
        monkeypatch.setenv("ADMIN_KEY", admin_key)
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("WEBUI_DIR", str(db_path.parent / "_no_webui_"))

    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    try:
        with TestClient(app) as c:
            c.headers.update({"X-API-Key": API_KEY})
            yield c
    finally:
        get_settings.cache_clear()


def _drop_admin_header(client) -> None:
    """İstemciyi "admin anahtarı olmayan çağıran" (ör. collector) hâline getirir."""
    client.headers.pop("X-Admin-Key", None)


def _ingest(client, game_id: str, played_at: str = "2026-08-11T20:00:00Z") -> int:
    r = client.post(
        "/api/v1/ingest/match",
        json=make_role_payload(source_game_id=game_id, played_at=played_at),
    )
    assert r.status_code == 201, r.text
    return r.json()["match_id"]


def _status(db, match_id: int) -> str:
    conn = db()
    try:
        return conn.execute(
            "SELECT status FROM matches WHERE id = ?", (match_id,)
        ).fetchone()["status"]
    finally:
        conn.close()


def _history(db) -> tuple[list, list]:
    conn = db()
    try:
        main = [
            tuple(r)
            for r in conn.execute(
                "SELECT match_id, player_id, mu_after, sigma_after"
                " FROM rating_history ORDER BY match_id, player_id"
            )
        ]
        roles = [
            tuple(r)
            for r in conn.execute(
                "SELECT match_id, player_id, role, mu_after"
                " FROM role_rating_history ORDER BY match_id, player_id, role"
            )
        ]
        return main, roles
    finally:
        conn.close()


def _link_setup(client):
    """10 oyuncu + açık rulet oturumu + eşleşen ingest → (session_id, match_id)."""
    ids = [
        client.post(
            "/api/v1/players", json={"display_name": f"H{i}"}
        ).json()["id"]
        for i in range(10)
    ]
    assignments = [
        {
            "player_id": pid,
            "team": 100 if i < 5 else 200,
            "position": POSITIONS[i % 5],
            "champion": f"Champ{i}",
            "item_ids": [1000 + 2 * i, 1001 + 2 * i],
        }
        for i, pid in enumerate(ids)
    ]
    session = client.post("/api/v1/roulette", json={"assignments": assignments})
    assert session.status_code == 201, session.text
    match = client.post(
        "/api/v1/ingest/match",
        json=make_roster_payload(
            "hard-rlt-1", "2026-08-17T20:00:00Z", ids[:5], ids[5:]
        ),
    )
    assert match.status_code == 201, match.text
    return session.json()["session_id"], match.json()["match_id"]


def _session_status(db, session_id: int) -> str:
    conn = db()
    try:
        return conn.execute(
            "SELECT status FROM roulette_sessions WHERE id = ?", (session_id,)
        ).fetchone()["status"]
    finally:
        conn.close()


# ── 1) Kapsam genişlemesi: üç yeni korunan uç ───────────────────────────


def test_new_admin_endpoints_403_without_admin_key(client, db):
    """unlink / POST players / PATCH players: anahtarsız 403 ve VERİ DEĞİŞMEZ."""
    _session_id, match_id = _link_setup(client)
    player_id = client.post(
        "/api/v1/players", json={"display_name": "Kalsın"}
    ).json()["id"]
    _drop_admin_header(client)

    calls = [
        ("POST", f"/api/v1/matches/{match_id}/roulette/unlink", None),
        ("POST", "/api/v1/players", {"display_name": "Girmemeli"}),
        ("PATCH", f"/api/v1/players/{player_id}", {"display_name": "Değişmemeli"}),
    ]
    for method, path, body in calls:
        r = client.request(method, path, json=body)
        assert r.status_code == 403, f"{method} {path}: {r.status_code} {r.text}"
        assert r.json()["detail"]

    # Hiçbir yan etki oluşmadı.
    assert _status(db, match_id) == "roulette"
    names = [p["display_name"] for p in client.get("/api/v1/players").json()]
    assert "Girmemeli" not in names
    assert "Değişmemeli" not in names


def test_new_admin_endpoints_work_with_correct_key(client, db):
    """Aynı üç uç doğru `X-Admin-Key` ile çalışır (client fixture header'ı taşır)."""
    session_id, match_id = _link_setup(client)

    created = client.post("/api/v1/players", json={"display_name": "Yeni"})
    assert created.status_code == 201, created.text
    new_id = created.json()["id"]

    patched = client.patch(
        f"/api/v1/players/{new_id}", json={"display_name": "Yeni Ad"}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["display_name"] == "Yeni Ad"

    unlinked = client.post(f"/api/v1/matches/{match_id}/roulette/unlink")
    assert unlinked.status_code == 200, unlinked.text
    assert unlinked.json()["status"] == "valid"
    assert _status(db, match_id) == "valid"
    assert _session_status(db, session_id) == "cancelled"


def test_new_admin_endpoints_503_when_key_not_configured(db_path, monkeypatch):
    """ADMIN_KEY yoksa yeni korunan uçlar da 403 değil 503 döner (kapalı yüzey)."""
    with _client_with_admin_key(db_path, monkeypatch, None) as c:
        for method, path, body in (
            ("POST", "/api/v1/matches/1/roulette/unlink", None),
            ("POST", "/api/v1/players", {"display_name": "X"}),
            ("PATCH", "/api/v1/players/1", {"display_name": "Y"}),
        ):
            r = c.request(method, path, json=body)
            assert r.status_code == 503, f"{method} {path}: {r.status_code}"
            assert "ADMIN_KEY" in r.json()["detail"]


def test_api_key_layer_still_applies_on_new_admin_endpoints(client):
    """Admin anahtarı EK katmandır: X-API-Key olmadan hâlâ 401 (403 değil)."""
    client.headers.pop("X-API-Key")
    r = client.post("/api/v1/players", json={"display_name": "X"})
    assert r.status_code == 401


# ── 2) Kapsam DIŞI uçlar: collector regresyon koruması ──────────────────


def test_put_positions_and_items_work_without_admin_key(client, db):
    """`PUT /positions` ve `PUT /items` admin anahtarı İSTEMEZ (contract kararı).

    Collector'ın `backfill-positions` / `backfill-items` komutları bu uçları
    arkadaşların PC'sinden yalnız `X-API-Key` ile çağırır; admin'e alınsalardı
    exe'ler 403 alırdı. Bu test o kararın regresyon kilididir.
    """
    match_id = _ingest(client, "collector-1")
    conn = db()
    try:
        player_id = conn.execute(
            "SELECT player_id FROM match_participants WHERE match_id = ?"
            " ORDER BY id LIMIT 1",
            (match_id,),
        ).fetchone()["player_id"]
    finally:
        conn.close()

    _drop_admin_header(client)

    r = client.put(
        f"/api/v1/matches/{match_id}/positions",
        json={"positions": {str(player_id): "TOP"}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 1

    r = client.put(
        f"/api/v1/matches/{match_id}/items",
        json={"items": {str(player_id): [3031, 3026]}},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"updated": 1}


def test_roulette_create_and_clear_stay_open(client):
    """`POST /roulette` ve `POST /roulette/clear` bilinçli olarak AÇIK kalır."""
    ids = [
        client.post("/api/v1/players", json={"display_name": f"O{i}"}).json()["id"]
        for i in range(10)
    ]
    _drop_admin_header(client)
    assignments = [
        {
            "player_id": pid,
            "team": 100 if i < 5 else 200,
            "position": POSITIONS[i % 5],
            "champion": f"Champ{i}",
            "item_ids": [1000 + 2 * i, 1001 + 2 * i],
        }
        for i, pid in enumerate(ids)
    ]
    assert (
        client.post("/api/v1/roulette", json={"assignments": assignments}).status_code
        == 201
    )
    r = client.post("/api/v1/roulette/clear")
    assert r.status_code == 200
    assert r.json() == {"deleted": 1}


# ── 3) ASCII kuralı ─────────────────────────────────────────────────────


def test_non_ascii_admin_key_returns_503_with_diagnostic_detail(
    db_path, monkeypatch
):
    """ASCII olmayan ADMIN_KEY → idari uçlar 503; detail sorunu AÇIKÇA söyler."""
    with _client_with_admin_key(db_path, monkeypatch, NON_ASCII_ADMIN_KEY) as c:
        for method, path in (
            ("GET", "/api/v1/admin/ping"),
            ("POST", "/api/v1/admin/replay"),
            ("POST", "/api/v1/matches/1/void"),
        ):
            # Anahtar DOĞRU bilinse bile 503: sorun istemcide değil
            # yapılandırmadadır (aşağıdaki test, doğru anahtarın gönderilmesinin
            # HTTP katmanında zaten imkânsız olduğunu gösterir).
            r = c.request(method, path, headers={"X-Admin-Key": "ne-gonderirsen"})
            assert r.status_code == 503, f"{method} {path}: {r.status_code}"
            detail = r.json()["detail"]
            assert "ADMIN_KEY" in detail
            assert "ASCII" in detail


def test_non_ascii_admin_key_cannot_even_be_sent_as_header(db_path, monkeypatch):
    """Kuralın GEREKÇESİ: ASCII olmayan anahtar header'a hiç sığmaz.

    İstemci (burada httpx; tarayıcıda `fetch`) header değerini byte'a çevirirken
    patlar — yani doğru şifreyi bilen kullanıcı bile paneli açamaz. Backend'in
    503'ü bu sessiz kilidi teşhis edilebilir hâle getirir.
    """
    with _client_with_admin_key(db_path, monkeypatch, NON_ASCII_ADMIN_KEY) as c:
        with pytest.raises(UnicodeEncodeError):
            c.get(
                "/api/v1/admin/ping",
                headers={"X-Admin-Key": NON_ASCII_ADMIN_KEY},
            )


def test_non_ascii_admin_key_keeps_app_running(db_path, monkeypatch):
    """Uygulama BAŞLAR ve idari olmayan uçlar çalışır (site ayakta kalır)."""
    with _client_with_admin_key(db_path, monkeypatch, NON_ASCII_ADMIN_KEY) as c:
        assert c.get("/api/v1/players").status_code == 200
        assert c.get("/api/v1/leaderboard").status_code == 200
        assert c.get("/api/v1/matches").status_code == 200


def test_ascii_admin_key_is_not_rejected(db_path, monkeypatch):
    """Kural yalnız ASCII DIŞI anahtarı kapatır; normal anahtar etkilenmez."""
    with _client_with_admin_key(db_path, monkeypatch, ADMIN_KEY) as c:
        r = c.get("/api/v1/admin/ping", headers={"X-Admin-Key": ADMIN_KEY})
        assert r.status_code == 204


# ── 4) Hız sınırı ───────────────────────────────────────────────────────


def test_rate_limit_returns_429_with_retry_after(client, monkeypatch):
    """Eşik aşılınca 429 + `Retry-After`; DOĞRU anahtar da artık geçmez."""
    from app import deps

    monkeypatch.setattr(deps, "ADMIN_FAIL_LIMIT", 3)
    _drop_admin_header(client)

    for i in range(3):
        r = client.get("/api/v1/admin/ping", headers={"X-Admin-Key": "yanlis"})
        assert r.status_code == 403, f"{i}. deneme: {r.status_code}"

    r = client.get("/api/v1/admin/ping", headers={"X-Admin-Key": "yanlis"})
    assert r.status_code == 429
    retry_after = r.headers["Retry-After"]
    assert retry_after.isdigit()
    assert 1 <= int(retry_after) <= int(deps.ADMIN_FAIL_WINDOW_S)
    assert r.json()["detail"]

    # Sınır, anahtar karşılaştırmasından ÖNCE uygulanır: doğru anahtar da 429.
    r = client.get("/api/v1/admin/ping", headers={"X-Admin-Key": ADMIN_KEY})
    assert r.status_code == 429


def test_successful_verification_resets_failure_counter(client, monkeypatch):
    """Başarılı doğrulama sayacı SIFIRLAR (yanlış yazıp düzelten kullanıcı kilitlenmez)."""
    from app import deps

    monkeypatch.setattr(deps, "ADMIN_FAIL_LIMIT", 3)

    for _ in range(2):
        assert (
            client.get(
                "/api/v1/admin/ping", headers={"X-Admin-Key": "yanlis"}
            ).status_code
            == 403
        )

    # Doğru anahtar (client fixture header'ı) → 204 ve sayaç sıfırlanır.
    assert client.get("/api/v1/admin/ping").status_code == 204

    # Sayaç sıfırlandığı için 3 başarısız deneme daha 403 olmalı (429 DEĞİL).
    for i in range(3):
        r = client.get("/api/v1/admin/ping", headers={"X-Admin-Key": "yanlis"})
        assert r.status_code == 403, f"sıfırlama sonrası {i}. deneme: {r.status_code}"
    assert (
        client.get(
            "/api/v1/admin/ping", headers={"X-Admin-Key": "yanlis"}
        ).status_code
        == 429
    )


def test_failed_attempt_is_delayed_by_configured_amount(client, monkeypatch):
    """Başarısız denemede sabit gecikme uygulanır ve süre AYARLANABİLİRDİR."""
    from app import deps

    monkeypatch.setattr(deps, "ADMIN_FAIL_DELAY_S", 0.2)

    started = time.monotonic()
    r = client.get("/api/v1/admin/ping", headers={"X-Admin-Key": "yanlis"})
    elapsed = time.monotonic() - started
    assert r.status_code == 403
    assert elapsed >= 0.2

    # Başarılı doğrulama gecikmez (gecikme yalnız başarısız denemededir).
    started = time.monotonic()
    assert client.get("/api/v1/admin/ping").status_code == 204
    assert time.monotonic() - started < 0.2


def test_rate_limit_window_slides(client, monkeypatch):
    """Pencere kayar: süre dolunca deneme hakkı geri gelir (pencere ayarlanabilir)."""
    from app import deps

    monkeypatch.setattr(deps, "ADMIN_FAIL_LIMIT", 2)
    monkeypatch.setattr(deps, "ADMIN_FAIL_WINDOW_S", 0.3)

    for _ in range(2):
        assert (
            client.get(
                "/api/v1/admin/ping", headers={"X-Admin-Key": "yanlis"}
            ).status_code
            == 403
        )
    assert (
        client.get(
            "/api/v1/admin/ping", headers={"X-Admin-Key": "yanlis"}
        ).status_code
        == 429
    )

    time.sleep(0.35)
    assert (
        client.get(
            "/api/v1/admin/ping", headers={"X-Admin-Key": "yanlis"}
        ).status_code
        == 403
    )


def test_rate_limit_does_not_apply_to_non_admin_endpoints(client, monkeypatch):
    """Sınır yalnız idari yüzeydedir: normal uçlar etkilenmez."""
    from app import deps

    monkeypatch.setattr(deps, "ADMIN_FAIL_LIMIT", 2)
    for _ in range(3):
        client.get("/api/v1/admin/ping", headers={"X-Admin-Key": "yanlis"})

    assert client.get("/api/v1/players").status_code == 200
    assert client.get("/api/v1/leaderboard").status_code == 200


# ── 5) Atomiklik: durum yazımı + replay TEK transaction ─────────────────


def _boom(*args, **kwargs):
    raise RuntimeError("replay patladı (test)")


def test_void_rolls_back_status_when_main_replay_fails(client, db, monkeypatch):
    """api_contract §5: ana evren replay'i patlarsa `status` yazımı GERİ ALINIR."""
    from app.routers import matches as matches_router

    _ingest(client, "atom-1", "2026-08-11T20:00:00Z")
    match_id = _ingest(client, "atom-2", "2026-08-12T20:00:00Z")
    before = _history(db)
    assert before[0] and before[1]

    monkeypatch.setattr(matches_router, "replay", _boom)
    with pytest.raises(RuntimeError):
        client.post(f"/api/v1/matches/{match_id}/void")

    assert _status(db, match_id) == "valid"
    assert _history(db) == before


def test_void_rolls_back_status_when_role_replay_fails(client, db, monkeypatch):
    """Rol evreni replay'i patlarsa ANA evrenin silinmesi de geri alınır."""
    from app.routers import matches as matches_router

    _ingest(client, "atom-3", "2026-08-11T20:00:00Z")
    match_id = _ingest(client, "atom-4", "2026-08-12T20:00:00Z")
    before = _history(db)

    monkeypatch.setattr(matches_router, "replay_roles", _boom)
    with pytest.raises(RuntimeError):
        client.post(f"/api/v1/matches/{match_id}/void")

    assert _status(db, match_id) == "valid"
    # Ana evren replay'i void'i uygulamıştı; rollback onu da geri aldı.
    assert _history(db) == before


def test_unvoid_rolls_back_status_when_replay_fails(client, db, monkeypatch):
    """Unvoid de aynı atomiklik kuralına tabidir."""
    from app.routers import matches as matches_router

    _ingest(client, "atom-5", "2026-08-11T20:00:00Z")
    match_id = _ingest(client, "atom-6", "2026-08-12T20:00:00Z")
    assert client.post(f"/api/v1/matches/{match_id}/void").status_code == 200
    before = _history(db)

    monkeypatch.setattr(matches_router, "replay_roles", _boom)
    with pytest.raises(RuntimeError):
        client.post(f"/api/v1/matches/{match_id}/unvoid")

    assert _status(db, match_id) == "void"
    assert _history(db) == before


def test_unlink_rolls_back_status_and_session_when_replay_fails(
    client, db, monkeypatch
):
    """Unlink'te maç durumu VE oturum durumu birlikte geri alınır."""
    from app.routers import matches as matches_router

    session_id, match_id = _link_setup(client)
    before = _history(db)

    monkeypatch.setattr(matches_router, "replay", _boom)
    with pytest.raises(RuntimeError):
        client.post(f"/api/v1/matches/{match_id}/roulette/unlink")

    assert _status(db, match_id) == "roulette"
    assert _session_status(db, session_id) == "linked"
    assert _history(db) == before


def test_void_and_unlink_still_commit_on_success(client, db):
    """Atomiklik değişikliği MUTLU YOLU bozmaz: başarıda her şey kalıcıdır."""
    session_id, roulette_match = _link_setup(client)
    r = client.post(f"/api/v1/matches/{roulette_match}/roulette/unlink")
    assert r.status_code == 200
    assert _status(db, roulette_match) == "valid"
    assert _session_status(db, session_id) == "cancelled"
    main, roles = _history(db)
    assert any(row[0] == roulette_match for row in main)

    r = client.post(f"/api/v1/matches/{roulette_match}/void")
    assert r.status_code == 200
    assert _status(db, roulette_match) == "void"
    main_after, _ = _history(db)
    assert not any(row[0] == roulette_match for row in main_after)
