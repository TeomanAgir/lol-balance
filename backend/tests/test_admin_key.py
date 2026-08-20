"""Admin anahtarı + unvoid (api_contract "Admin anahtarı" + §3 + §5, fix-2).

Kapsam:
  1. `ADMIN_KEY` yapılandırılmamışsa idari uçlar 503 (kapalı).
  2. Yanlış/eksik `X-Admin-Key` → 403; `X-API-Key` katmanı AYRICA sürer (401).
  3. Doğru anahtarla void / unvoid / replay / ping çalışır.
  4. unvoid: void → valid + rating_history yeniden kuruldu; sonuç maç hiç
     void edilmemiş gibi BİT-BİT aynıdır (determinizm).
  5. Durum kuralları: valid maça unvoid 409, roulette maça unvoid 409,
     roulette maça void 409 (fix-2 öncesi davranış korunur).
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from conftest import ADMIN_KEY, API_KEY, make_role_payload

ADMIN_ENDPOINTS = [
    ("GET", "/api/v1/admin/ping"),
    ("POST", "/api/v1/admin/replay"),
    ("POST", "/api/v1/matches/1/void"),
    ("POST", "/api/v1/matches/1/unvoid"),
]


@contextmanager
def _client(db_path, monkeypatch, admin_key: str | None):
    """conftest.client'ın ADMIN_KEY'i seçilebilen (ya da hiç verilmeyen) kopyası."""
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


def _history(db_conn) -> list[tuple]:
    conn = db_conn()
    rows = [
        tuple(r)
        for r in conn.execute(
            "SELECT match_id, player_id, mu_before, sigma_before, mu_after,"
            " sigma_after, perf_score, engine_version FROM rating_history"
            " ORDER BY match_id, player_id"
        )
    ]
    conn.close()
    return rows


def _role_history(db_conn) -> list[tuple]:
    conn = db_conn()
    rows = [
        tuple(r)
        for r in conn.execute(
            "SELECT match_id, player_id, role, mu_before, sigma_before,"
            " mu_after, sigma_after, engine_version FROM role_rating_history"
            " ORDER BY match_id, player_id, role"
        )
    ]
    conn.close()
    return rows


def _ingest(client, game_id: str, played_at: str) -> int:
    r = client.post(
        "/api/v1/ingest/match",
        json=make_role_payload(source_game_id=game_id, played_at=played_at),
    )
    assert r.status_code == 201, r.text
    return r.json()["match_id"]


def _status(db_conn, match_id: int) -> str:
    conn = db_conn()
    row = conn.execute(
        "SELECT status FROM matches WHERE id = ?", (match_id,)
    ).fetchone()
    conn.close()
    return row["status"]


# ── 1) ADMIN_KEY yapılandırılmamış → 503 ────────────────────────


def test_admin_endpoints_503_when_key_not_configured(db_path, monkeypatch):
    with _client(db_path, monkeypatch, admin_key=None) as c:
        for method, path in ADMIN_ENDPOINTS:
            r = c.request(method, path)
            assert r.status_code == 503, f"{method} {path}: {r.status_code}"
            assert "ADMIN_KEY" in r.json()["detail"]


def test_empty_admin_key_counts_as_not_configured(db_path, monkeypatch):
    """Secret'ta anahtar var ama değeri boş → uçlar herkese AÇILMAZ, kapalıdır."""
    with _client(db_path, monkeypatch, admin_key="   ") as c:
        r = c.get("/api/v1/admin/ping")
        assert r.status_code == 503


def test_missing_admin_key_does_not_block_normal_endpoints(db_path, monkeypatch):
    """503 yalnız idari yüzeyi kapatır; uygulamanın geri kalanı çalışır."""
    with _client(db_path, monkeypatch, admin_key=None) as c:
        assert c.get("/api/v1/players").status_code == 200
        assert c.get("/api/v1/leaderboard").status_code == 200


# ── 2) Yanlış/eksik anahtar → 403; API anahtarı katmanı ayrıca sürer ──


def test_admin_endpoints_403_without_header(db_path, monkeypatch):
    with _client(db_path, monkeypatch, admin_key=ADMIN_KEY) as c:
        for method, path in ADMIN_ENDPOINTS:
            r = c.request(method, path)
            assert r.status_code == 403, f"{method} {path}: {r.status_code}"
            assert r.json()["detail"]


def test_admin_endpoints_403_with_wrong_header(db_path, monkeypatch):
    with _client(db_path, monkeypatch, admin_key=ADMIN_KEY) as c:
        for method, path in ADMIN_ENDPOINTS:
            r = c.request(method, path, headers={"X-Admin-Key": "yanlis"})
            assert r.status_code == 403, f"{method} {path}: {r.status_code}"


def test_api_key_layer_still_applies_on_admin_endpoints(db_path, monkeypatch):
    """Admin anahtarı EK katmandır: X-API-Key olmadan hâlâ 401."""
    with _client(db_path, monkeypatch, admin_key=ADMIN_KEY) as c:
        c.headers.pop("X-API-Key")
        r = c.get("/api/v1/admin/ping", headers={"X-Admin-Key": ADMIN_KEY})
        assert r.status_code == 401


# ── 3) Doğru anahtarla uçlar çalışır ────────────────────────────


def test_ping_204_with_correct_key_and_no_side_effect(client, db):
    """Ping YAN ETKİSİZDİR: rating tarihçesi çağrı öncesi/sonrası birebir aynı."""
    _ingest(client, "ping-1", "2026-08-11T20:00:00Z")
    before = _history(db)
    r = client.get("/api/v1/admin/ping")
    assert r.status_code == 204
    assert r.content == b""
    assert _history(db) == before


def test_replay_and_void_and_unvoid_work_with_correct_key(client, db):
    _ingest(client, "ok-1", "2026-08-11T20:00:00Z")
    m2 = _ingest(client, "ok-2", "2026-08-12T20:00:00Z")

    assert client.post("/api/v1/admin/replay").status_code == 200

    r = client.post(f"/api/v1/matches/{m2}/void")
    assert r.status_code == 200
    assert r.json()["status"] == "void"
    assert _status(db, m2) == "void"

    r = client.post(f"/api/v1/matches/{m2}/unvoid")
    assert r.status_code == 200
    body = r.json()
    assert body["match_id"] == m2
    assert body["status"] == "valid"
    assert body["matches_replayed"] == 2
    assert _status(db, m2) == "valid"


# ── 4) unvoid: tarihçe yeniden kuruldu + determinizm ────────────


def test_unvoid_restores_history_bit_for_bit(client, db):
    """void → unvoid, hiç void edilmemiş duruma BİT-BİT döner (iki evren)."""
    _ingest(client, "u-1", "2026-08-11T20:00:00Z")
    m2 = _ingest(client, "u-2", "2026-08-12T20:00:00Z")
    _ingest(client, "u-3", "2026-08-13T20:00:00Z")
    baseline, baseline_roles = _history(db), _role_history(db)
    assert baseline and baseline_roles

    assert client.post(f"/api/v1/matches/{m2}/void").status_code == 200
    voided = _history(db)
    # Void, m2'nin satırlarını tarihçeden çıkarır (rating türetilmiş veridir).
    assert not any(row[0] == m2 for row in voided)
    assert voided != baseline

    assert client.post(f"/api/v1/matches/{m2}/unvoid").status_code == 200
    assert _history(db) == baseline
    assert _role_history(db) == baseline_roles


def test_unvoid_result_equals_full_replay(client, db):
    """unvoid sonrası `POST /admin/replay` tarihçeyi DEĞİŞTİRMEZ (determinizm)."""
    _ingest(client, "d-1", "2026-08-11T20:00:00Z")
    m2 = _ingest(client, "d-2", "2026-08-12T20:00:00Z")
    _ingest(client, "d-3", "2026-08-13T20:00:00Z")

    client.post(f"/api/v1/matches/{m2}/void")
    client.post(f"/api/v1/matches/{m2}/unvoid")
    after_unvoid, after_unvoid_roles = _history(db), _role_history(db)

    assert client.post("/api/v1/admin/replay").status_code == 200
    assert _history(db) == after_unvoid
    assert _role_history(db) == after_unvoid_roles


def test_unvoid_ingest_events_untouched(client, db):
    """Ham ingest immutable: void/unvoid yalnız türetilmiş veriyi oynatır."""
    _ingest(client, "i-1", "2026-08-11T20:00:00Z")
    m1 = _ingest(client, "i-2", "2026-08-12T20:00:00Z")

    conn: sqlite3.Connection = db()
    before = [tuple(r) for r in conn.execute("SELECT * FROM ingest_events")]
    conn.close()

    client.post(f"/api/v1/matches/{m1}/void")
    client.post(f"/api/v1/matches/{m1}/unvoid")

    conn = db()
    after = [tuple(r) for r in conn.execute("SELECT * FROM ingest_events")]
    conn.close()
    assert after == before


# ── 5) Durum kuralları ──────────────────────────────────────────


def test_unvoid_unknown_match_404(client):
    r = client.post("/api/v1/matches/9999/unvoid")
    assert r.status_code == 404


def test_void_unknown_match_404(client):
    """void'un unvoid ile simetrik durum kuralı (api_contract §3)."""
    r = client.post("/api/v1/matches/9999/void")
    assert r.status_code == 404
    assert "9999" in r.json()["detail"]


def test_void_and_unvoid_response_shape(client):
    """Yanıt alanları contract'takinin tamamı: iki evrenin sayısı + engine_version."""
    _ingest(client, "shape-1", "2026-08-11T20:00:00Z")
    m2 = _ingest(client, "shape-2", "2026-08-12T20:00:00Z")

    voided = client.post(f"/api/v1/matches/{m2}/void").json()
    assert set(voided) == {
        "match_id",
        "status",
        "matches_replayed",
        "role_matches_replayed",
        "engine_version",
    }
    assert voided["role_matches_replayed"] == 1  # kalan tek valid maç
    assert voided["engine_version"] == "openskill-pl-blend25-v1"

    unvoided = client.post(f"/api/v1/matches/{m2}/unvoid").json()
    assert set(unvoided) == set(voided)
    assert unvoided["role_matches_replayed"] == 2
    assert unvoided["engine_version"] == voided["engine_version"]


def test_unvoid_valid_match_409(client, db):
    m = _ingest(client, "v-1", "2026-08-11T20:00:00Z")
    r = client.post(f"/api/v1/matches/{m}/unvoid")
    assert r.status_code == 409
    assert "void" in r.json()["detail"]
    assert _status(db, m) == "valid"


def test_unvoid_roulette_match_409(client, db):
    """Rulet maçı void DEĞİLDİR → unvoid anlamsız; çözüm unlink'tir."""
    m = _ingest(client, "r-1", "2026-08-11T20:00:00Z")
    conn = db()
    with conn:
        conn.execute("UPDATE matches SET status = 'roulette' WHERE id = ?", (m,))
    conn.close()

    r = client.post(f"/api/v1/matches/{m}/unvoid")
    assert r.status_code == 409
    assert _status(db, m) == "roulette"


def test_void_already_void_match_422_and_no_replay(client, db):
    """api_contract §3: zaten void maçta void → 422; replay TETİKLENMEZ."""
    _ingest(client, "vv-1", "2026-08-11T20:00:00Z")
    m2 = _ingest(client, "vv-2", "2026-08-12T20:00:00Z")
    assert client.post(f"/api/v1/matches/{m2}/void").status_code == 200
    after_void, after_void_roles = _history(db), _role_history(db)

    r = client.post(f"/api/v1/matches/{m2}/void")
    assert r.status_code == 422
    assert r.json()["detail"] == "Bu maç zaten void işaretli."
    # Durum ve İKİ evren de dokunulmadan kalır (replay koşmadı).
    assert _status(db, m2) == "void"
    assert _history(db) == after_void
    assert _role_history(db) == after_void_roles


def test_void_already_void_does_not_call_replay(client, monkeypatch):
    """Replay'in HİÇ çağrılmadığı doğrudan kanıtlanır (spy)."""
    m = _ingest(client, "vs-1", "2026-08-11T20:00:00Z")
    assert client.post(f"/api/v1/matches/{m}/void").status_code == 200

    from app.routers import matches as matches_router

    calls = []
    monkeypatch.setattr(
        matches_router, "replay", lambda *a, **k: calls.append("main") or 0
    )
    monkeypatch.setattr(
        matches_router, "replay_roles", lambda *a, **k: calls.append("role") or 0
    )
    assert client.post(f"/api/v1/matches/{m}/void").status_code == 422
    assert calls == []


def test_void_roulette_match_still_409(client, db):
    """fix-2 öncesi kural korunur: admin anahtarı doğru olsa da rulet void edilemez."""
    m = _ingest(client, "rv-1", "2026-08-11T20:00:00Z")
    conn = db()
    with conn:
        conn.execute("UPDATE matches SET status = 'roulette' WHERE id = ?", (m,))
    conn.close()

    r = client.post(f"/api/v1/matches/{m}/void")
    assert r.status_code == 409
    assert _status(db, m) == "roulette"


def test_unvoid_of_auto_voided_remake_puts_match_into_rating(client, db):
    """Kısa maç otomatik void'lenir; unvoid onu rating'e SOKAR (canlı senaryo)."""
    _ingest(client, "rm-1", "2026-08-11T20:00:00Z")
    r = client.post(
        "/api/v1/ingest/match",
        json=make_role_payload(
            source_game_id="rm-2",
            played_at="2026-08-12T20:00:00Z",
            duration_s=120,  # VOID_THRESHOLD_S altında → otomatik void
        ),
    )
    m2 = r.json()["match_id"]
    assert _status(db, m2) == "void"
    assert not any(row[0] == m2 for row in _history(db))

    body = client.post(f"/api/v1/matches/{m2}/unvoid").json()
    assert body["status"] == "valid"
    assert body["matches_replayed"] == 2
    assert any(row[0] == m2 for row in _history(db))
