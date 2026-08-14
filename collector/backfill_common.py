"""Arşivden backend'e yazan backfill komutlarının ortak parçaları.

`backfill-positions` (GÖREV 0) ve `backfill-items` (GÖREV 14) aynı iskeleti
paylaşır: `raw_archive/*.json` okunur, backend'deki maç/oyuncu listeleriyle
eşlenir, maç başına tek bir `PUT` atılır. LCU'ya ihtiyaç YOKTUR; kaynak arşiv,
hedef backend'dir. Eşleşmeyen maç/oyuncu ölümcül değildir: uyarı yazılır,
tarama devam eder — komutlar idempotenttir.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import httpx

from .config import Config

log = logging.getLogger("collector.backfill")

MATCHES_PATH = "/api/v1/matches"
PLAYERS_PATH = "/api/v1/players"

#: Backend `GET /matches` limitini 200'de sınırlar (api_contract §3 / Query le=200)
MATCH_LIST_LIMIT = 200


def open_client(config: Config, transport: httpx.BaseTransport | None) -> httpx.Client:
    return httpx.Client(
        base_url=config.backend_url,
        headers={"X-API-Key": config.api_key},
        timeout=30.0,
        transport=transport,
    )


def fetch_match_index(client: httpx.Client, limit: int = MATCH_LIST_LIMIT) -> dict[str, dict]:
    """`source_game_id → {"id": int, "player_ids": set[int], "status": str}`."""
    response = client.get(MATCHES_PATH, params={"limit": limit})
    response.raise_for_status()
    index: dict[str, dict] = {}
    for match in response.json() or []:
        source_game_id = match.get("source_game_id")
        if source_game_id is None:
            continue
        index[str(source_game_id)] = {
            "id": match.get("id"),
            "status": match.get("status"),
            "player_ids": {
                p.get("player_id") for p in match.get("participants") or []
            },
        }
    return index


def fetch_player_index(client: httpx.Client) -> dict[str, int]:
    """`puuid → player_id` (puuid'i olmayan oyuncular atlanır)."""
    response = client.get(PLAYERS_PATH)
    response.raise_for_status()
    index: dict[str, int] = {}
    for player in response.json() or []:
        puuid, player_id = player.get("puuid"), player.get("id")
        if puuid and player_id is not None:
            index[str(puuid)] = int(player_id)
    return index


def archive_files(config: Config, archive_dir: Optional[Path]) -> list[Path]:
    directory = archive_dir or config.raw_archive_dir
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.json"))


def load_raw(path: Path) -> Optional[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.error("Could not read raw match file, skipping: %s (%s)", path.name, exc)
        return None
    return data if isinstance(data, dict) else None
