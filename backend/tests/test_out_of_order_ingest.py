"""Sıra-dışı ingest'te otomatik replay (api_contract §5, ingest_contract
"Sıra-dışı geliş" 2026-08-13).

Değişmez: hangi SIRAYLA gelirlerse gelsinler, aynı maç kümesi aynı
rating_history + role_rating_history'yi üretir — yani ingest sırası sonucu
etkilemez.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from conftest import ADMIN_KEY, API_KEY, make_payload, make_role_payload

INGEST_URL = "/api/v1/ingest/match"


@contextmanager
def _client_for(db_path, monkeypatch):
    """conftest'teki `client` fixture'ının elle kurulabilen hâli.

    Tek testte İKİ ayrı DB'ye (iki farklı ingest sırası) ihtiyaç var; fixture
    test başına tek DB verdiği için burada aynı kurulum parametrik tekrarlanır.
    """
    monkeypatch.setenv("API_KEY", API_KEY)
    monkeypatch.setenv("ADMIN_KEY", ADMIN_KEY)
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("WEBUI_DIR", str(db_path.parent / "_no_webui_"))

    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as c:
        c.headers.update({"X-API-Key": API_KEY, "X-Admin-Key": ADMIN_KEY})
        yield c
    get_settings.cache_clear()


def _connect(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# Snapshot'lar match_id YERİNE source_game_id'ye göre alınır: aynı maç kümesi
# farklı ingest sırasında farklı match_id alır, ama karşılaştırma maçın
# kimliği üzerinden yapılmalıdır.
def _rating_snapshot(conn) -> list[tuple]:
    return [
        tuple(row)
        for row in conn.execute(
            "SELECT m.source_game_id, h.player_id, h.engine_version,"
            " round(h.mu_before, 9), round(h.sigma_before, 9),"
            " round(h.mu_after, 9), round(h.sigma_after, 9),"
            " round(h.perf_score, 9) "
            "FROM rating_history h JOIN matches m ON m.id = h.match_id "
            "ORDER BY m.source_game_id, h.player_id"
        )
    ]


def _role_snapshot(conn) -> list[tuple]:
    return [
        tuple(row)
        for row in conn.execute(
            "SELECT m.source_game_id, h.player_id, h.role, h.engine_version,"
            " round(h.mu_before, 9), round(h.sigma_before, 9),"
            " round(h.mu_after, 9), round(h.sigma_after, 9),"
            " round(h.perf_score, 9) "
            "FROM role_rating_history h JOIN matches m ON m.id = h.match_id "
            "ORDER BY m.source_game_id, h.player_id, h.role"
        )
    ]


# (source_game_id, played_at, winner_team) — t1 < t2 < t3, kazananlar farklı ki
# sıralama sonucu gerçekten etkilesin.
MATCHES = [
    ("t1", "2026-08-10T20:00:00Z", 100),
    ("t2", "2026-08-11T20:00:00Z", 200),
    ("t3", "2026-08-12T20:00:00Z", 100),
]


def _ingest_order(client, order, payload_factory) -> None:
    by_id = {m[0]: m for m in MATCHES}
    for key in order:
        sgid, played_at, winner = by_id[key]
        r = client.post(
            INGEST_URL,
            json=payload_factory(
                source_game_id=sgid, played_at=played_at, winner_team=winner
            ),
        )
        assert r.status_code == 201, r.text
        assert r.json()["duplicate"] is False


def _spy_replays(monkeypatch) -> dict[str, int]:
    """replay / replay_roles çağrı sayaçları (orijinal davranış korunur)."""
    from app.services import ratings as rating_service
    from app.services import role_ratings as role_rating_service

    calls = {"replay": 0, "replay_roles": 0}
    original = rating_service.replay
    original_roles = role_rating_service.replay_roles

    def spy(conn, engine_version):
        calls["replay"] += 1
        return original(conn, engine_version)

    def spy_roles(conn, engine_version):
        calls["replay_roles"] += 1
        return original_roles(conn, engine_version)

    monkeypatch.setattr(rating_service, "replay", spy)
    monkeypatch.setattr(role_rating_service, "replay_roles", spy_roles)
    return calls


def test_out_of_order_ingest_equals_chronological(tmp_path, monkeypatch):
    """t1, t3, sonra t2 → sonuç t1, t2, t3 kronolojik ingest'le BİREBİR aynı."""
    out_of_order_db = tmp_path / "out_of_order.db"
    chronological_db = tmp_path / "chronological.db"

    with _client_for(out_of_order_db, monkeypatch) as client:
        calls = _spy_replays(monkeypatch)
        _ingest_order(client, ["t1", "t3", "t2"], make_payload)
        # Yalnız t2 sıra-dışıdır; t1 ve t3 incremental kalır.
        assert calls == {"replay": 1, "replay_roles": 1}

    with _client_for(chronological_db, monkeypatch) as client:
        _ingest_order(client, ["t1", "t2", "t3"], make_payload)

    out_of_order = _rating_snapshot(_connect(out_of_order_db))
    assert len(out_of_order) == 30
    assert out_of_order == _rating_snapshot(_connect(chronological_db))


def test_out_of_order_ingest_equals_manual_replay(client, db):
    """Auto-replay sonrası elle `POST /admin/replay` hiçbir şeyi değiştirmez."""
    _ingest_order(client, ["t1", "t3", "t2"], make_payload)
    after_ingest = _rating_snapshot(db())

    r = client.post("/api/v1/admin/replay")
    assert r.status_code == 200
    assert r.json()["matches_replayed"] == 3

    assert _rating_snapshot(db()) == after_ingest


def test_out_of_order_ingest_rebuilds_role_universe(tmp_path, monkeypatch):
    """Rol-uygun maçlarda rol evreni de kronolojik sonuca eşitlenir."""
    out_of_order_db = tmp_path / "out_of_order_roles.db"
    chronological_db = tmp_path / "chronological_roles.db"

    with _client_for(out_of_order_db, monkeypatch) as client:
        _ingest_order(client, ["t1", "t3", "t2"], make_role_payload)

    with _client_for(chronological_db, monkeypatch) as client:
        _ingest_order(client, ["t1", "t2", "t3"], make_role_payload)

    out_conn, chrono_conn = _connect(out_of_order_db), _connect(chronological_db)
    roles = _role_snapshot(out_conn)
    assert len(roles) == 30  # 3 uygun maç × 10 katılımcı
    assert roles == _role_snapshot(chrono_conn)
    # Ana evren de aynı ingest'te birlikte kurulur.
    assert _rating_snapshot(out_conn) == _rating_snapshot(chrono_conn)


def test_in_order_ingest_stays_incremental(client, db, monkeypatch):
    """Kronolojik ingest'te replay YOLU hiç çağrılmaz (mevcut davranış)."""
    calls = _spy_replays(monkeypatch)
    _ingest_order(client, ["t1", "t2", "t3"], make_role_payload)
    assert calls == {"replay": 0, "replay_roles": 0}

    conn = db()
    assert len(_rating_snapshot(conn)) == 30
    assert len(_role_snapshot(conn)) == 30


def test_equal_played_at_stays_incremental(client, db, monkeypatch):
    """Mevcut en yeni maçla AYNI played_at replay tetiklemez.

    Replay'in sıralama anahtarı (played_at, id) olduğundan, en büyük id'yi alan
    yeni maç eşitlikte zaten sona düşer → incremental yeterlidir. Sonucun
    replay'le aynı olduğu ayrıca doğrulanır.
    """
    _ingest_order(client, ["t1", "t2"], make_role_payload)

    calls = _spy_replays(monkeypatch)
    r = client.post(
        INGEST_URL,
        json=make_role_payload(
            source_game_id="t2-same-time",
            played_at="2026-08-11T20:00:00Z",  # t2 ile birebir aynı
            winner_team=200,
        ),
    )
    assert r.status_code == 201
    assert calls == {"replay": 0, "replay_roles": 0}

    conn = db()
    incremental_ratings = _rating_snapshot(conn)
    incremental_roles = _role_snapshot(conn)

    assert client.post("/api/v1/admin/replay").status_code == 200
    conn = db()
    assert _rating_snapshot(conn) == incremental_ratings
    assert _role_snapshot(conn) == incremental_roles


def test_duplicate_does_not_trigger_replay(client, monkeypatch):
    """Aynı source_game_id ikinci kez → replay yok, yanıt duplicate: true."""
    _ingest_order(client, ["t1", "t2"], make_role_payload)

    calls = _spy_replays(monkeypatch)
    # Sıra-dışı olsaydı replay tetikleyecek played_at ile, ama zaten alınmış id.
    payload = make_role_payload(
        source_game_id="t1", played_at="2026-08-10T20:00:00Z", winner_team=100
    )
    r = client.post(INGEST_URL, json=payload)
    assert r.status_code == 200
    assert r.json()["duplicate"] is True
    assert calls == {"replay": 0, "replay_roles": 0}


def test_void_out_of_order_match_does_not_trigger_replay(client, monkeypatch):
    """Void (remake) maç rating'e girmez → sıra-dışı olsa da replay gerekmez."""
    _ingest_order(client, ["t1", "t3"], make_role_payload)

    calls = _spy_replays(monkeypatch)
    r = client.post(
        INGEST_URL,
        json=make_role_payload(
            source_game_id="remake",
            played_at="2026-08-11T20:00:00Z",  # t1 ile t3 arasında
            duration_s=120,  # VOID_THRESHOLD_S altında → void
        ),
    )
    assert r.status_code == 201
    assert calls == {"replay": 0, "replay_roles": 0}
