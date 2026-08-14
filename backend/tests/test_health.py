"""GÖREV 13 — Collector sağlığı (api_contract §6 + ingest_contract "client_id").

Kapsam: heartbeat upsert'i, 422'ler, /health/collectors sıralaması ve son maç
izi, ingest'in `matches.client_id` yazımı (+ duplicate'ta değişmezlik ve alansız
eski payload uyumu).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from conftest import make_payload

HEARTBEAT = "/api/v1/health/heartbeat"
COLLECTORS = "/api/v1/health/collectors"


def _rows(db):
    return db().execute(
        "SELECT * FROM collector_health ORDER BY client_id"
    ).fetchall()


# ── Heartbeat ─────────────────────────────────────────────────────────────


def test_heartbeat_creates_row_with_server_assigned_last_seen(client, db):
    before = datetime.now(timezone.utc).replace(microsecond=0)
    r = client.post(
        HEARTBEAT,
        json={"client_id": "Ali-PC", "version": "1.5.0", "outbox_pending": 0},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    rows = _rows(db)
    assert len(rows) == 1
    row = rows[0]
    assert (row["client_id"], row["version"], row["outbox_pending"]) == (
        "Ali-PC",
        "1.5.0",
        0,
    )
    # last_seen SUNUCUDA atanır: UTC "…Z", istek anıyla tutarlı.
    seen = datetime.strptime(row["last_seen"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    assert before <= seen <= datetime.now(timezone.utc) + timedelta(seconds=1)


def test_heartbeat_ignores_client_supplied_last_seen(client, db):
    """Gövdedeki last_seen YOK SAYILIR (client saatine güvenilmez)."""
    client.post(
        HEARTBEAT, json={"client_id": "Ali-PC", "last_seen": "1999-01-01T00:00:00Z"}
    )
    assert not _rows(db)[0]["last_seen"].startswith("1999")


def test_heartbeat_is_upsert_single_row_and_last_seen_advances(client, db):
    """İki heartbeat → tek satır; last_seen ilerler, alanlar tazelenir."""
    from app.services.health import record_heartbeat

    client.post(
        HEARTBEAT,
        json={"client_id": "Ali-PC", "version": "1.5.0", "outbox_pending": 3},
    )
    first = _rows(db)[0]["last_seen"]

    # Saniye altı çözünürlükte iki isteğin last_seen'i eşit olabilirdi; ilerlemeyi
    # kanıtlamak için ikinci heartbeat servis katmanından `now` enjeksiyonuyla
    # atılır (aynı upsert yolu, deterministik zaman).
    later = datetime.now(timezone.utc) + timedelta(minutes=5)
    from app.db import connect
    from app.config import get_settings

    conn = connect(get_settings().db_path)
    try:
        record_heartbeat(conn, "Ali-PC", "1.6.0", 0, now=later)
    finally:
        conn.close()

    rows = _rows(db)
    assert len(rows) == 1  # PRIMARY KEY upsert, ikinci satır açılmadı
    assert rows[0]["last_seen"] > first
    assert (rows[0]["version"], rows[0]["outbox_pending"]) == ("1.6.0", 0)


def test_heartbeat_optional_fields_may_be_omitted(client, db):
    r = client.post(HEARTBEAT, json={"client_id": "Bos-PC"})
    assert r.status_code == 200
    row = _rows(db)[0]
    assert row["version"] is None and row["outbox_pending"] is None


def test_heartbeat_trims_client_id(client, db):
    client.post(HEARTBEAT, json={"client_id": "  Ali-PC  "})
    assert _rows(db)[0]["client_id"] == "Ali-PC"
    # Trim sonrası aynı kimlik → hâlâ tek satır.
    client.post(HEARTBEAT, json={"client_id": "Ali-PC"})
    assert len(_rows(db)) == 1


@pytest.mark.parametrize("body", [{}, {"client_id": None}, {"client_id": ""},
                                  {"client_id": "   "}])
def test_heartbeat_requires_non_empty_client_id(client, db, body):
    r = client.post(HEARTBEAT, json=body)
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str)
    assert not _rows(db)


def test_heartbeat_client_id_max_64(client, db):
    r = client.post(HEARTBEAT, json={"client_id": "x" * 64})
    assert r.status_code == 200

    r = client.post(HEARTBEAT, json={"client_id": "y" * 65})
    assert r.status_code == 422
    assert "64" in r.json()["detail"]
    assert [row["client_id"] for row in _rows(db)] == ["x" * 64]


def test_heartbeat_requires_api_key(client):
    r = client.post(
        HEARTBEAT, json={"client_id": "Ali-PC"}, headers={"X-API-Key": "wrong"}
    )
    assert r.status_code == 401


# ── GET /health/collectors ────────────────────────────────────────────────


def test_collectors_empty_list_when_no_heartbeat(client):
    r = client.get(COLLECTORS)
    assert r.status_code == 200
    assert r.json() == []


def test_collectors_sorted_by_last_seen_desc(client):
    from app.config import get_settings
    from app.db import connect
    from app.services.health import record_heartbeat

    base = datetime(2026, 8, 14, 20, 0, 0, tzinfo=timezone.utc)
    conn = connect(get_settings().db_path)
    try:
        record_heartbeat(conn, "eski-PC", now=base)
        record_heartbeat(conn, "yeni-PC", now=base + timedelta(hours=2))
        record_heartbeat(conn, "orta-PC", now=base + timedelta(hours=1))
    finally:
        conn.close()

    body = client.get(COLLECTORS).json()
    assert [c["client_id"] for c in body] == ["yeni-PC", "orta-PC", "eski-PC"]
    assert body[0]["last_seen"] == "2026-08-14T22:00:00Z"


def test_collectors_reports_last_ingest_trace(client):
    """Son maç izi cihazın `matches.client_id` kayıtlarından gelir."""
    client.post(
        "/api/v1/ingest/match",
        json={**make_payload(source_game_id="1000", played_at="2026-08-10T20:00:00Z"),
              "client_id": "Ali-PC"},
    )
    client.post(
        "/api/v1/ingest/match",
        json={**make_payload(source_game_id="1001", played_at="2026-08-12T20:00:00Z"),
              "client_id": "Ali-PC"},
    )
    # Başka cihazın maçı Ali-PC'nin izini kirletmemeli (daha yeni olsa bile).
    client.post(
        "/api/v1/ingest/match",
        json={**make_payload(source_game_id="1002", played_at="2026-08-13T20:00:00Z"),
              "client_id": "Veli-PC"},
    )
    client.post(HEARTBEAT, json={"client_id": "Ali-PC"})
    client.post(HEARTBEAT, json={"client_id": "Hic-Mac-Yok-PC"})

    body = {c["client_id"]: c for c in client.get(COLLECTORS).json()}
    assert body["Ali-PC"]["last_ingest_at"] == "2026-08-12T20:00:00Z"
    assert body["Ali-PC"]["last_ingest_game_id"] == "1001"
    # Heartbeat atmış ama hiç maç göndermemiş cihaz: iz null.
    assert body["Hic-Mac-Yok-PC"]["last_ingest_at"] is None
    assert body["Hic-Mac-Yok-PC"]["last_ingest_game_id"] is None
    # Heartbeat atmamış cihaz (Veli-PC) listede yer almaz.
    assert "Veli-PC" not in body


def test_collectors_last_ingest_includes_void_matches(client):
    """İz OPERASYONELDİR: void maç da sayılır (rating süzgeci değil)."""
    client.post(
        "/api/v1/ingest/match",
        json={**make_payload(source_game_id="2000", played_at="2026-08-10T20:00:00Z"),
              "client_id": "Ali-PC"},
    )
    client.post(
        "/api/v1/ingest/match",
        json={**make_payload(source_game_id="2001", played_at="2026-08-12T20:00:00Z",
                             duration_s=120),  # < 300 sn → void
              "client_id": "Ali-PC"},
    )
    client.post(HEARTBEAT, json={"client_id": "Ali-PC"})

    row = client.get(COLLECTORS).json()[0]
    assert row["last_ingest_game_id"] == "2001"


def test_collectors_shape_matches_contract(client):
    client.post(
        HEARTBEAT,
        json={"client_id": "Ali-PC", "version": "1.5.0", "outbox_pending": 0},
    )
    row = client.get(COLLECTORS).json()[0]
    assert set(row) == {
        "client_id", "last_seen", "version", "outbox_pending",
        "last_ingest_at", "last_ingest_game_id",
    }


def test_collectors_requires_api_key(client):
    assert client.get(COLLECTORS, headers={"X-API-Key": "wrong"}).status_code == 401


# ── Ingest'te client_id (ingest_contract "client_id") ─────────────────────


def test_ingest_stores_client_id_and_keeps_raw_payload(client, db):
    payload = {**make_payload(), "client_id": "  Ali-PC  "}
    r = client.post("/api/v1/ingest/match", json=payload)
    assert r.status_code == 201

    conn = db()
    assert conn.execute("SELECT client_id FROM matches").fetchone()[0] == "Ali-PC"
    # Ham ingest_events AYNEN saklanır (trim edilmemiş hâliyle) — db_schema ilke 1.
    raw = conn.execute("SELECT payload_json FROM ingest_events").fetchone()[0]
    assert json.loads(raw) == payload


def test_ingest_without_client_id_stays_null(client, db):
    """Eski exe'ler alanı hiç göndermez (geriye uyumluluk)."""
    r = client.post("/api/v1/ingest/match", json=make_payload())
    assert r.status_code == 201
    assert db().execute("SELECT client_id FROM matches").fetchone()[0] is None


@pytest.mark.parametrize("value", [None, "", "   "])
def test_ingest_empty_client_id_normalized_to_null(client, db, value):
    """Boş/boşluk değer alan gönderilmemiş sayılır — maç REDDEDİLMEZ."""
    r = client.post(
        "/api/v1/ingest/match", json={**make_payload(), "client_id": value}
    )
    assert r.status_code == 201
    assert db().execute("SELECT client_id FROM matches").fetchone()[0] is None


def test_ingest_too_long_client_id_rejected(client, db):
    r = client.post(
        "/api/v1/ingest/match", json={**make_payload(), "client_id": "z" * 65}
    )
    assert r.status_code == 422
    assert "64" in r.json()["detail"]
    conn = db()
    # Reddedilen istek hiçbir şey yazmamalı.
    assert conn.execute("SELECT COUNT(*) c FROM matches").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM ingest_events").fetchone()["c"] == 0


def test_ingest_client_id_max_64_accepted(client, db):
    r = client.post(
        "/api/v1/ingest/match", json={**make_payload(), "client_id": "z" * 64}
    )
    assert r.status_code == 201
    assert db().execute("SELECT client_id FROM matches").fetchone()[0] == "z" * 64


def test_duplicate_ingest_does_not_change_client_id(client, db):
    """Idempotency "işlem yok" demektir: ilk gönderenin izi korunur."""
    payload = {**make_payload(), "client_id": "Ali-PC"}
    r1 = client.post("/api/v1/ingest/match", json=payload)
    r2 = client.post(
        "/api/v1/ingest/match", json={**payload, "client_id": "Veli-PC"}
    )
    assert r1.status_code == 201
    assert r2.status_code == 200 and r2.json()["duplicate"] is True

    conn = db()
    assert conn.execute("SELECT COUNT(*) c FROM matches").fetchone()["c"] == 1
    assert conn.execute("SELECT client_id FROM matches").fetchone()[0] == "Ali-PC"


def test_duplicate_ingest_without_client_id_does_not_clear_trace(client, db):
    payload = {**make_payload(), "client_id": "Ali-PC"}
    client.post("/api/v1/ingest/match", json=payload)
    client.post("/api/v1/ingest/match", json=make_payload())  # alansız tekrar
    assert db().execute("SELECT client_id FROM matches").fetchone()[0] == "Ali-PC"


def test_heartbeat_does_not_touch_ratings(client, db):
    """Sağlık uçları izlemedir: rating/maç verisine dokunmaz."""
    client.post("/api/v1/ingest/match", json={**make_payload(), "client_id": "Ali-PC"})
    conn = db()
    before = conn.execute(
        "SELECT player_id, mu_after, sigma_after FROM rating_history "
        "ORDER BY player_id"
    ).fetchall()

    client.post(HEARTBEAT, json={"client_id": "Ali-PC", "outbox_pending": 7})
    client.get(COLLECTORS)

    after = db().execute(
        "SELECT player_id, mu_after, sigma_after FROM rating_history "
        "ORDER BY player_id"
    ).fetchall()
    assert [tuple(r) for r in after] == [tuple(r) for r in before]
