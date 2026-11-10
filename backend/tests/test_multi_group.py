"""GÖREV 35 — Çoklu grup (api_contract "Çoklu grup", db_schema "Çoklu grup").

Kapsam (kabul ölçütleri):
  a) İzolasyon: A'ya ingest edilen maç/oyuncu B'nin okuma uçlarında görünmez.
  b) source_game_id UNIQUE grup başınadır.
  c) Admin anahtarı yalnız isteğin grubununkiyle geçer; tanımsızsa 503.
  d) /admin/replay yalnız çağıranın grubunu etkiler.
  e) Meta ORTAKTIR: ana grubun DB'sindeki meta_snapshots kullanılır.
  f) Yapılandırma: 401, yinelenen anahtar, boş değer, geçersiz <AD>.
  g) Açılışta her grubun DB dosyası oluşur ve tüm migration'lar uygulanır.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest
from conftest import ADMIN_KEY, API_KEY, make_role_payload
from test_meta_api import CHAMPIONS_JSON, SEED_COUNTERS, SEED_TIERS, VENDORED, FakeNet

from app.db import MIGRATIONS_DIR
from app.services import meta_source, meta_store

B_KEY = "group-b-test-key"
B_ADMIN = "group-b-admin-test-key"
C_KEY = "group-c-test-key"  # admin anahtarı TANIMSIZ grup

A = {"X-API-Key": API_KEY, "X-Admin-Key": ADMIN_KEY}
B = {"X-API-Key": B_KEY, "X-Admin-Key": B_ADMIN}
C = {"X-API-Key": C_KEY}


def _clear_group_env(monkeypatch):
    """Ortamdan sızabilecek GROUP_* değişkenlerini temizler (test izolasyonu)."""
    import os

    for key in list(os.environ):
        if key.upper().startswith("GROUP_"):
            monkeypatch.delenv(key, raising=False)


def _set_env(monkeypatch, tmp_path, extra: dict[str, str] | None = None,
             webui_dir: Path | None = None) -> Path:
    _clear_group_env(monkeypatch)
    db_dir = tmp_path / "data"
    monkeypatch.setenv("API_KEY", API_KEY)
    monkeypatch.setenv("ADMIN_KEY", ADMIN_KEY)
    monkeypatch.setenv("DB_PATH", str(db_dir / "main.db"))
    monkeypatch.setenv("WEBUI_DIR", str(webui_dir or tmp_path / "_no_webui_"))
    for k, v in (extra or {}).items():
        monkeypatch.setenv(k, v)
    return db_dir


@contextmanager
def _app(monkeypatch, tmp_path, extra=None, webui_dir=None, drop=()):
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app

    _set_env(monkeypatch, tmp_path, extra, webui_dir)
    for key in drop:
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as c:
            yield c
    finally:
        get_settings.cache_clear()


DEFAULT_GROUPS = {
    "GROUP_B_API_KEY": B_KEY,
    "GROUP_B_ADMIN_KEY": B_ADMIN,
    "GROUP_C_API_KEY": C_KEY,
}


@pytest.fixture
def mg(monkeypatch, tmp_path):
    with _app(monkeypatch, tmp_path, DEFAULT_GROUPS) as c:
        yield c


@pytest.fixture
def db_dir(tmp_path):
    return tmp_path / "data"


def _q(path: Path, sql: str, args=()):
    conn = sqlite3.connect(path)
    try:
        return [tuple(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def _ingest(c, headers, payload):
    r = c.post("/api/v1/ingest/match", json=payload, headers=headers)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _heartbeat(c, headers, client_id):
    r = c.post("/api/v1/health/heartbeat", json={"client_id": client_id}, headers=headers)
    assert r.status_code < 300, r.text


def _read_surface(c, headers) -> dict:
    out = {}
    for path in ("/api/v1/players", "/api/v1/matches", "/api/v1/leaderboard",
                 "/api/v1/health/collectors", "/api/v1/roulette/current"):
        r = c.get(path, headers=headers)
        out[path] = (r.status_code, r.json() if r.content else None)
    return out


# ── a) İzolasyon ─────────────────────────────────────────────────────────


def test_a_ingest_in_one_group_invisible_in_other(mg):
    empty_b = _read_surface(mg, B)
    empty_a = _read_surface(mg, A)
    assert empty_a == empty_b  # iki boş grup aynı görünür

    _ingest(mg, A, make_role_payload("A-1"))
    _heartbeat(mg, A, "A-PC")
    pids = [p["id"] for p in mg.get("/api/v1/players", headers=A).json()]
    assert len(pids) == 10

    # A'nın verisi B'de (ve C'de) görünmez.
    assert _read_surface(mg, B) == empty_b
    assert _read_surface(mg, C) == empty_b
    a_after = _read_surface(mg, A)
    assert a_after["/api/v1/players"][1] and a_after["/api/v1/matches"][1]
    assert a_after["/api/v1/health/collectors"] != empty_a["/api/v1/health/collectors"]

    # Tersi: B'ye ayrı oyuncular/maç + rulet oturumu → A değişmez.
    payload = make_role_payload("B-1")
    for i, p in enumerate(payload["participants"]):
        p["puuid"] = f"b-puuid-{i}"
        p["riot_id"] = f"BPlayer{i}#FAKE"
    _ingest(mg, B, payload)
    _heartbeat(mg, B, "B-PC")
    b_ids = [p["id"] for p in mg.get("/api/v1/players", headers=B).json()]
    assignments = [
        {"player_id": pid, "team": 100 if i < 5 else 200,
         "position": ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"][i % 5],
         "champion": f"Champ{i}", "item_ids": [1000 + i, 2000 + i]}
        for i, pid in enumerate(b_ids)
    ]
    r = mg.post("/api/v1/roulette", json={"assignments": assignments}, headers=B)
    assert r.status_code == 201, r.text
    assert mg.get("/api/v1/roulette/current", headers=B).json() is not None

    assert _read_surface(mg, A) == a_after
    names_b = {p["display_name"] for p in mg.get("/api/v1/players", headers=B).json()}
    names_a = {p["display_name"] for p in mg.get("/api/v1/players", headers=A).json()}
    assert names_a.isdisjoint(names_b)
    # Tekil uçlar da grubun dosyasından: A'nın maç id'si B'de başka maçtır/yoktur.
    a_match = mg.get("/api/v1/matches", headers=A).json()[0]
    b_match = mg.get(f"/api/v1/matches/{a_match['id']}", headers=B).json()
    assert b_match["source_game_id"] == "B-1"


def test_a_data_lands_in_group_files(mg, db_dir):
    _ingest(mg, B, make_role_payload("B-only"))
    assert _q(db_dir / "group_b.db", "SELECT source_game_id FROM matches") == [("B-only",)]
    assert _q(db_dir / "main.db", "SELECT COUNT(*) FROM matches") == [(0,)]
    assert _q(db_dir / "group_c.db", "SELECT COUNT(*) FROM matches") == [(0,)]


# ── b) Idempotency grup başına ───────────────────────────────────────────


def test_b_same_source_game_id_per_group(mg):
    p = make_role_payload("SAME-GAME")
    assert _ingest(mg, A, p)["duplicate"] is False
    assert _ingest(mg, B, p)["duplicate"] is False
    assert _ingest(mg, A, p)["duplicate"] is True
    assert _ingest(mg, B, p)["duplicate"] is True
    assert _ingest(mg, C, p)["duplicate"] is False


# ── c) Admin anahtarı grup başına ────────────────────────────────────────


def test_c_admin_key_bound_to_group(mg):
    ping = "/api/v1/admin/ping"
    assert mg.get(ping, headers=A).status_code == 204
    assert mg.get(ping, headers=B).status_code == 204
    # Çapraz eşleşme: A'nın admini + B'nin API anahtarı → 403 (ve tersi).
    assert mg.get(ping, headers={"X-API-Key": B_KEY, "X-Admin-Key": ADMIN_KEY}).status_code == 403
    assert mg.get(ping, headers={"X-API-Key": API_KEY, "X-Admin-Key": B_ADMIN}).status_code == 403
    # Admin anahtarı tanımsız grup → 503 (hangi admin anahtarı verilirse verilsin).
    for admin in (ADMIN_KEY, B_ADMIN, None):
        h = {"X-API-Key": C_KEY} | ({"X-Admin-Key": admin} if admin else {})
        r = mg.get(ping, headers=h)
        assert r.status_code == 503
        assert "GROUP_C_ADMIN_KEY" in r.json()["detail"]
    # Bilinmeyen API anahtarı → 401, admin anahtarı doğru olsa bile.
    r = mg.get(ping, headers={"X-API-Key": "nope", "X-Admin-Key": ADMIN_KEY})
    assert r.status_code == 401


def test_c_main_group_detail_unchanged(monkeypatch, tmp_path):
    """Ana grubun 503 mesajı tek gruplu kurulumla birebir aynı."""
    with _app(monkeypatch, tmp_path, DEFAULT_GROUPS, drop=("ADMIN_KEY",)) as c:
        r = c.get("/api/v1/admin/ping", headers={"X-API-Key": API_KEY})
        assert r.status_code == 503
        assert r.json()["detail"] == (
            "Yönetim anahtarı sunucuda yapılandırılmamış (ADMIN_KEY); "
            "idari uçlar kapalı."
        )
        # B'nin admin yüzeyi ana grubun eksik anahtarından etkilenmez.
        assert c.get("/api/v1/admin/ping", headers=B).status_code == 204


def test_c_rate_limit_shared_across_groups(mg, monkeypatch):
    """Hız sınırı sayacı IP başına, gruplar arası ORTAK (contract)."""
    from app import deps

    monkeypatch.setattr(deps, "ADMIN_FAIL_LIMIT", 3)
    for _ in range(3):
        r = mg.get("/api/v1/admin/ping", headers={"X-API-Key": B_KEY, "X-Admin-Key": "x"})
        assert r.status_code == 403
    r = mg.get("/api/v1/admin/ping", headers=A)
    assert r.status_code == 429


# ── d) Replay yalnız çağıranın grubunu etkiler ───────────────────────────


def _history(path: Path):
    return _q(path, "SELECT * FROM rating_history ORDER BY id")


def _role_history(path: Path):
    return _q(path, "SELECT * FROM role_rating_history ORDER BY id")


def test_d_replay_only_caller_group(mg, db_dir):
    _ingest(mg, A, make_role_payload("A-1", played_at="2026-08-11T20:00:00Z"))
    _ingest(mg, A, make_role_payload("A-2", played_at="2026-08-12T20:00:00Z", winner_team=200))
    _ingest(mg, B, make_role_payload("B-1", played_at="2026-08-11T20:00:00Z"))
    _ingest(mg, B, make_role_payload("B-2", played_at="2026-08-13T20:00:00Z"))
    main_before = (_history(db_dir / "main.db"), _role_history(db_dir / "main.db"))
    b_before = (_history(db_dir / "group_b.db"), _role_history(db_dir / "group_b.db"))
    assert main_before[0] and b_before[0]

    r = mg.post("/api/v1/admin/replay", headers=B)
    assert r.status_code == 200, r.text
    assert r.json()["matches_replayed"] == 2

    # A'nın (ana grubun) satırları bit-bit aynı — id'ler dahil (yeniden yazılmadı).
    assert (_history(db_dir / "main.db"), _role_history(db_dir / "main.db")) == main_before
    # B yeniden üretildi: id'ler değişebilir, içerik (id hariç) incremental ile aynı.
    def strip_id(rows):
        return [row[1:] for row in rows]
    b_after = (_history(db_dir / "group_b.db"), _role_history(db_dir / "group_b.db"))
    assert strip_id(b_after[0]) == strip_id(b_before[0])
    assert strip_id(b_after[1]) == strip_id(b_before[1])


# ── e) Meta ORTAK ────────────────────────────────────────────────────────


@pytest.fixture
def meta_webui(tmp_path):
    root = tmp_path / "webui"
    (root / "assets" / "meta").mkdir(parents=True)
    (root / "assets" / "ddragon").mkdir(parents=True)
    (root / "assets" / "meta" / "tiers.json").write_text(json.dumps(SEED_TIERS), encoding="utf-8")
    (root / "assets" / "meta" / "counters.json").write_text(
        json.dumps(SEED_COUNTERS), encoding="utf-8")
    (root / "assets" / "ddragon" / "manifest.json").write_text(
        json.dumps({"version": VENDORED}), encoding="utf-8")
    (root / "assets" / "ddragon" / "champions.json").write_text(
        json.dumps(CHAMPIONS_JSON), encoding="utf-8")
    return root


@pytest.fixture
def meta_mg(monkeypatch, tmp_path, meta_webui):
    meta_store.reset_state()
    monkeypatch.setattr(meta_source, "fetch_json", FakeNet())
    with _app(monkeypatch, tmp_path, DEFAULT_GROUPS, webui_dir=meta_webui) as c:
        yield c
    meta_store.reset_state()


def test_e_meta_shared_written_by_extra_group(meta_mg, db_dir):
    snaps = "SELECT id, is_active FROM meta_snapshots ORDER BY id"
    r = meta_mg.post("/api/v1/admin/meta/refresh", json={}, headers=B)
    assert r.status_code == 200, r.text
    sid = r.json()["snapshot_id"]
    assert r.json()["written"] is True

    # Ana grubun dosyasına yazıldı; ek grupların dosyalarındaki tablo boş.
    assert _q(db_dir / "main.db", snaps) == [(sid, 1)]
    assert _q(db_dir / "group_b.db", snaps) == []
    assert _q(db_dir / "group_c.db", snaps) == []

    # A (ana) ve C GET /meta/tiers ile aynı snapshot'ı görür.
    for headers in (A, B, C):
        body = meta_mg.get("/api/v1/meta/tiers", headers=headers).json()
        assert body["origin"] == "snapshot" and body["snapshot_id"] == sid
        body = meta_mg.get("/api/v1/meta/counters", headers=headers).json()
        assert body["snapshot_id"] == sid

    # A'nın admin history'si B'nin yazdığını gösterir.
    hist = meta_mg.get("/api/v1/admin/meta/history", headers=A).json()
    assert hist["active_id"] == sid
    assert sid in [s["id"] for s in hist["items"]]


def test_e_meta_activate_from_extra_group_visible_in_main(meta_mg, db_dir):
    first = meta_mg.post("/api/v1/admin/meta/refresh", json={}, headers=A).json()["snapshot_id"]
    second = meta_mg.post("/api/v1/admin/meta/refresh", json={"force": True},
                          headers=A).json()["snapshot_id"]
    assert first != second
    assert meta_mg.get("/api/v1/meta/tiers", headers=A).json()["snapshot_id"] == second

    r = meta_mg.post(f"/api/v1/admin/meta/activate/{first}", headers=B)
    assert r.status_code == 200, r.text
    assert meta_mg.get("/api/v1/meta/tiers", headers=A).json()["snapshot_id"] == first
    st = meta_mg.get("/api/v1/admin/meta/status", headers=B)
    assert st.status_code == 200
    assert _q(db_dir / "group_b.db", "SELECT COUNT(*) FROM meta_snapshots") == [(0,)]


def test_e_meta_admin_uses_callers_own_admin_key(meta_mg):
    # B'nin API anahtarı + A'nın admin anahtarı → 403; C (admin tanımsız) → 503.
    r = meta_mg.post("/api/v1/admin/meta/refresh", json={},
                     headers={"X-API-Key": B_KEY, "X-Admin-Key": ADMIN_KEY})
    assert r.status_code == 403
    r = meta_mg.post("/api/v1/admin/meta/refresh", json={},
                     headers={"X-API-Key": C_KEY, "X-Admin-Key": ADMIN_KEY})
    assert r.status_code == 503
    # Herkese açık GET'ler admin istemez, ama bilinmeyen anahtar 401.
    assert meta_mg.get("/api/v1/meta/tiers", headers=C).status_code == 200
    assert meta_mg.get("/api/v1/meta/tiers", headers={"X-API-Key": "x"}).status_code == 401


# ── f) Yapılandırma ──────────────────────────────────────────────────────


def test_f_unknown_key_401(mg):
    for h in ({}, {"X-API-Key": "nope"}, {"X-API-Key": B_KEY + "x"}, {"X-API-Key": ""}):
        assert mg.get("/api/v1/players", headers=h).status_code == 401


@pytest.mark.parametrize("extra", [
    {"GROUP_B_API_KEY": API_KEY},                               # ana grupla aynı
    {"GROUP_B_API_KEY": "dup", "GROUP_C_API_KEY": "dup"},        # iki ek grup aynı
])
def test_f_duplicate_api_key_fails_startup(monkeypatch, tmp_path, extra):
    from app.config import get_settings
    from app.main import create_app

    _set_env(monkeypatch, tmp_path, extra)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="Yinelenen API anahtarı"):
            create_app()
    finally:
        get_settings.cache_clear()


def test_f_db_path_collision_fails_startup(monkeypatch, tmp_path):
    """DB_PATH'in kendisi group_<ad>.db ise iki grup aynı dosyaya düşerdi."""
    from app.config import get_settings

    _set_env(monkeypatch, tmp_path, {"GROUP_B_API_KEY": B_KEY})
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "group_b.db"))
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="aynı DB dosyasını"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_f_empty_and_invalid_groups_ignored(monkeypatch, tmp_path, caplog):
    from app.config import get_settings

    _set_env(monkeypatch, tmp_path, {
        "GROUP_EMPTY_API_KEY": "",
        "GROUP_BLANK_API_KEY": "   ",
        "GROUP_BAD_NAME_API_KEY": "bad-key",          # alt çizgili <AD>
        "GROUP_" + "X" * 33 + "_API_KEY": "long-key",  # 33 karakter
        "GROUP_ORPHAN_ADMIN_KEY": "orphan-admin",      # API anahtarsız admin
        "GROUP_OK1_API_KEY": "ok-key",
    })
    get_settings.cache_clear()
    try:
        with caplog.at_level(logging.WARNING, logger="app.config"):
            s = get_settings()
        assert [g.name for g in s.groups] == [None, "ok1"]
        assert s.resolve_group("bad-key") is None
        assert s.resolve_group("long-key") is None
        assert s.resolve_group("ok-key").db_path == str(tmp_path / "data" / "group_ok1.db")
        msgs = " ".join(r.getMessage() for r in caplog.records)
        for name in ("GROUP_EMPTY_API_KEY", "GROUP_BLANK_API_KEY",
                     "GROUP_BAD_NAME_API_KEY", "GROUP_ORPHAN_ADMIN_KEY"):
            assert name in msgs, name
        # Log'a anahtar DEĞERİ yazılmaz.
        assert "bad-key" not in msgs and "orphan-admin" not in msgs
    finally:
        get_settings.cache_clear()


def test_f_ignored_group_key_gets_401(monkeypatch, tmp_path):
    with _app(monkeypatch, tmp_path, {"GROUP_BAD_NAME_API_KEY": "bad-key",
                                      "GROUP_E_API_KEY": ""}) as c:
        assert c.get("/api/v1/players", headers={"X-API-Key": "bad-key"}).status_code == 401
        assert c.get("/api/v1/players", headers={"X-API-Key": ""}).status_code == 401
        assert c.get("/api/v1/players", headers={"X-API-Key": API_KEY}).status_code == 200
    assert sorted(p.name for p in (tmp_path / "data").iterdir() if p.suffix == ".db") == [
        "main.db"]


def test_f_single_group_setup_unchanged(monkeypatch, tmp_path):
    """Yalnız API_KEY: tek grup, tek dosya, eski davranış."""
    from app.config import get_settings

    with _app(monkeypatch, tmp_path) as c:
        s = get_settings()
        assert len(s.groups) == 1 and s.groups[0].is_main
        assert s.groups[0].db_path == s.db_path
        assert c.get("/api/v1/players", headers=A).status_code == 200
        assert c.get("/api/v1/players", headers={"X-API-Key": "x"}).status_code == 401
        _ingest(c, A, make_role_payload("S-1"))
    assert sorted(p.name for p in (tmp_path / "data").iterdir() if p.suffix == ".db") == [
        "main.db"]


# ── g) Açılışta migration'lar her gruba ──────────────────────────────────


def test_g_startup_creates_and_migrates_every_group(mg, db_dir):
    expected = sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))
    for name in ("main.db", "group_b.db", "group_c.db"):
        path = db_dir / name
        assert path.exists(), name
        assert [r[0] for r in _q(path, "SELECT filename FROM schema_migrations ORDER BY filename")
                ] == expected, name
        tables = {r[0] for r in _q(path, "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"players", "matches", "rating_history", "meta_snapshots"} <= tables
