"""Perf-v1 backend yolu: statlı ingest, nötr çarpan garantisi, replay determinizmi.

Çarpan matematiğinin kendisi rating paketinde test edilir; buradaki testler
yalnızca backend'in statları DB'den doğru taşıyıp Engine'e geçirdiğini doğrular.

Default ENGINE_VERSION artık blend20 olduğundan (çarpan YOK), bu dosyadaki
testler perf-v1'i AÇIKÇA seçer. Harman testleri: tests/test_blend_rating.py.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from conftest import API_KEY, make_payload

GOOD_STATS = {
    "kills": 15, "deaths": 1, "assists": 12,
    "gold": 18000, "cs": 260,
    "damage_to_champs": 42000, "vision_score": 45,
}
BAD_STATS = {
    "kills": 1, "deaths": 9, "assists": 2,
    "gold": 8000, "cs": 90,
    "damage_to_champs": 7000, "vision_score": 5,
}


def _varied_stats_payload(source_game_id: str, played_at: str, winner_team: int = 100):
    """team100 kazanır; participants[0] çok iyi, participants[1] çok kötü statlı."""
    payload = make_payload(
        source_game_id=source_game_id, played_at=played_at, winner_team=winner_team
    )
    payload["participants"][0]["stats"] = dict(GOOD_STATS)
    payload["participants"][1]["stats"] = dict(BAD_STATS)
    return payload


def _null_stats_payload(source_game_id: str = "manual:perf-null-1"):
    payload = make_payload(source_game_id=source_game_id)
    payload["source"] = "manual"
    for p in payload["participants"]:
        p["stats"] = None
    return payload


def _history_rows(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [
        tuple(row)
        for row in conn.execute(
            "SELECT player_id, match_id, mu_before, sigma_before,"
            " mu_after, sigma_after "
            "FROM rating_history ORDER BY match_id, player_id"
        )
    ]
    conn.close()
    return rows


@contextmanager
def _client(db_path, monkeypatch, engine_version: str | None = None):
    """conftest.client'ın ENGINE_VERSION seçilebilen kopyası."""
    monkeypatch.setenv("API_KEY", API_KEY)
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("WEBUI_DIR", str(db_path.parent / "_no_webui_"))
    if engine_version is None:
        monkeypatch.delenv("ENGINE_VERSION", raising=False)
    else:
        monkeypatch.setenv("ENGINE_VERSION", engine_version)

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


def test_good_stats_winner_gains_more_than_bad_stats_winner(tmp_path, monkeypatch):
    db_path = tmp_path / "perf.db"
    with _client(db_path, monkeypatch, engine_version="openskill-pl-perf-v1") as c:
        r = c.post(
            "/api/v1/ingest/match",
            json=_varied_stats_payload("perf-varied-1", "2026-08-11T20:00:00Z"),
        )
        assert r.status_code == 201
        match_id = r.json()["match_id"]

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    def gain(puuid: str) -> float:
        row = conn.execute(
            "SELECT rh.mu_before, rh.mu_after FROM rating_history rh "
            "JOIN players p ON p.id = rh.player_id "
            "WHERE rh.match_id = ? AND p.puuid = ?",
            (match_id, puuid),
        ).fetchone()
        assert row is not None
        return row["mu_after"] - row["mu_before"]

    good_gain = gain("abc-123-...")   # participants[0]
    bad_gain = gain("puuid-01")       # participants[1]

    # İkisi de kazanan takımda: yön asla değişmez, ikisi de kazanır.
    assert good_gain > 0
    assert bad_gain > 0
    # Ama iyi statlı kazanan, kötü statlı kazanandan daha çok kazanır.
    assert good_gain > bad_gain


def test_null_stats_match_identical_to_plain_v1(tmp_path, monkeypatch):
    """Statsız manuel maçta perf-v1, openskill-pl-v1 ile birebir aynı mu/sigma
    üretmeli (nötr çarpan garantisinin backend yolu)."""
    payload = _null_stats_payload()

    db_perf = tmp_path / "perf.db"
    with _client(db_perf, monkeypatch, engine_version="openskill-pl-perf-v1") as c:
        r = c.post("/api/v1/ingest/match", json=payload)
        assert r.status_code == 201

    db_v1 = tmp_path / "v1.db"
    with _client(db_v1, monkeypatch, engine_version="openskill-pl-v1") as c:
        r = c.post("/api/v1/ingest/match", json=payload)
        assert r.status_code == 201

    rows_perf = _history_rows(db_perf)
    rows_v1 = _history_rows(db_v1)
    assert len(rows_perf) == 10
    assert rows_perf == rows_v1  # yuvarlama yok: bit-bit aynı olmalı


def test_replay_deterministic_with_varied_stats(tmp_path, monkeypatch):
    """Perf-v1'de statlı maçlar replay'de incremental ile birebir aynı sonucu verir."""
    payloads = [
        _varied_stats_payload("perf-r1", "2026-08-11T20:00:00Z", winner_team=100),
        _varied_stats_payload("perf-r2", "2026-08-12T20:00:00Z", winner_team=200),
        _null_stats_payload("manual:perf-r3"),
    ]
    payloads[2]["played_at"] = "2026-08-13T20:00:00Z"

    db_path = tmp_path / "perf.db"
    with _client(db_path, monkeypatch, engine_version="openskill-pl-perf-v1") as c:
        for p in payloads:
            assert c.post("/api/v1/ingest/match", json=p).status_code == 201

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        versions = {
            row["engine_version"]
            for row in conn.execute(
                "SELECT DISTINCT engine_version FROM rating_history"
            )
        }
        assert versions == {"openskill-pl-perf-v1"}
        incremental = _history_rows(db_path)
        assert len(incremental) == 30

        r = c.post("/api/v1/admin/replay")
        assert r.status_code == 200
        assert r.json()["matches_replayed"] == 3

    assert _history_rows(db_path) == incremental
