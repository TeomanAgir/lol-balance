"""Test altyapısı: her test taze bir SQLite dosyası ve app instance'ı alır.

Fixture'lar docs/ingest_contract.md'deki örnek payload'ı birebir temel alır.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

API_KEY = "test-key"

# ingest_contract.md "Request body" örneğindeki participant — birebir.
CONTRACT_PARTICIPANT = {
    "puuid": "abc-123-...",
    "riot_id": "Teoman#TR1",
    "team": 100,
    "position": "MIDDLE",
    "champion": "Ahri",
    "stats": {
        "kills": 7, "deaths": 2, "assists": 9,
        "gold": 13250, "cs": 201,
        "damage_to_champs": 24810, "vision_score": 21,
    },
}

POSITIONS = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]
ROLES_SET = set(POSITIONS)


def make_payload(
    source_game_id: str = "6874231955",
    played_at: str = "2026-08-11T20:41:03Z",
    duration_s: int = 1874,
    winner_team: int = 100,
):
    """Contract örneğini 10 katılımcıya tamamlar; participants[0] örneğin aynısıdır."""
    participants = [dict(CONTRACT_PARTICIPANT)]
    for i in range(1, 10):
        team = 100 if i < 5 else 200
        participants.append(
            {
                "puuid": f"puuid-{i:02d}",
                "riot_id": f"Player{i}#TR1",
                "team": team,
                "position": POSITIONS[i % 5],
                "champion": "Ahri",
                "stats": dict(CONTRACT_PARTICIPANT["stats"]),
            }
        )
    return {
        "source": "lcu_eog",
        "source_game_id": source_game_id,
        "played_at": played_at,
        "duration_s": duration_s,
        "winner_team": winner_team,
        "participants": participants,
    }


def make_role_payload(
    source_game_id: str = "6874231955",
    played_at: str = "2026-08-11T20:41:03Z",
    duration_s: int = 1874,
    winner_team: int = 100,
):
    """make_payload'ın rol evrenine UYGUN hâli.

    make_payload'ın rol dağılımı bilinçli olarak bozuktur (team100'de MIDDLE
    iki kez, TOP hiç); burada her takım 5 farklı rolü tam 1'er kez alır
    (rating_contract "Rol Rating Evreni" §3).
    """
    payload = make_payload(source_game_id, played_at, duration_s, winner_team)
    for i, p in enumerate(payload["participants"]):
        p["position"] = POSITIONS[i % 5]
    return payload


def make_roster_payload(
    source_game_id: str,
    played_at: str,
    team100_ids: list[int],
    team200_ids: list[int],
    winner_team: int = 100,
    duration_s: int = 1874,
):
    """Var olan oyuncu id'leriyle rol evrenine uygun maç payload'ı.

    ingest_contract participant'ı puuid YERİNE player_id kabul eder; bu, hangi
    oyuncunun hangi rolde oynadığını testte tam kontrol etmeyi sağlar.
    Statlar tüm katılımcılarda aynıdır → perf = 1.0 (nötr), sonuç saf W/L.
    """
    participants = []
    for team, ids in ((100, team100_ids), (200, team200_ids)):
        for i, pid in enumerate(ids):
            participants.append(
                {
                    "player_id": pid,
                    "team": team,
                    "position": POSITIONS[i],
                    "champion": "Ahri",
                    "stats": dict(CONTRACT_PARTICIPANT["stats"]),
                }
            )
    return {
        "source": "lcu_eog",
        "source_game_id": source_game_id,
        "played_at": played_at,
        "duration_s": duration_s,
        "winner_team": winner_team,
        "participants": participants,
    }


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def client(db_path, monkeypatch):
    monkeypatch.setenv("API_KEY", API_KEY)
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("WEBUI_DIR", str(db_path.parent / "_no_webui_"))

    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as c:
        c.headers.update({"X-API-Key": API_KEY})
        yield c
    get_settings.cache_clear()


@pytest.fixture
def db(db_path):
    """Testin doğrudan DB'ye bakması için salt-okur amaçlı bağlantı."""
    def _connect() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    return _connect
