"""Backfill roster filtresi: bilinen oyuncu kümesi.

Küme = backend `GET /players` (riot_id; yanıt ileride puuid içerirse o da alınır)
∪ lokal `collector/seed_roster.json` (riot_id listesi, sistem boşken elle doldurulur).

Not: api_contract.md'de GET /players yanıtında puuid alanı yok; bkz.
docs/CHANGE_REQUESTS.md kaydı. riot_id eşleşmesi büyük/küçük harf duyarsızdır.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import httpx

from .config import Config

log = logging.getLogger("collector.roster")

PLAYERS_PATH = "/api/v1/players"


def _norm(riot_id: str) -> str:
    return riot_id.strip().casefold()


@dataclass
class KnownRoster:
    puuids: set[str] = field(default_factory=set)
    riot_ids: set[str] = field(default_factory=set)  # normalize edilmiş halde tutulur

    def is_empty(self) -> bool:
        return not self.puuids and not self.riot_ids

    def contains(self, puuid: Optional[str], riot_id: Optional[str]) -> bool:
        if puuid and puuid in self.puuids:
            return True
        return bool(riot_id) and _norm(riot_id) in self.riot_ids

    def count_known(self, entries: Iterable[tuple[Optional[str], Optional[str]]]) -> int:
        return sum(1 for puuid, riot_id in entries if self.contains(puuid, riot_id))


def load_seed_roster(path: Path) -> set[str]:
    """JSON dosyası: ["Ad#TAG", ...]. Dosya yoksa boş küme."""
    if not path.is_file():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path} bir JSON listesi olmalı (riot_id string'leri)")
    return {_norm(item) for item in data if isinstance(item, str) and item.strip()}


def fetch_backend_roster(
    config: Config, transport: httpx.BaseTransport | None = None
) -> KnownRoster:
    """Backend erişilemezse boş roster döner (backfill seed ile devam edebilir)."""
    roster = KnownRoster()
    try:
        with httpx.Client(
            base_url=config.backend_url,
            headers={"X-API-Key": config.api_key},
            timeout=15.0,
            transport=transport,
        ) as client:
            response = client.get(PLAYERS_PATH)
            response.raise_for_status()
            players = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Backend roster alınamadı, seed_roster ile devam: %s", exc)
        return roster

    for player in players or []:
        if player.get("puuid"):  # contract'ta yok; backend eklerse kullanılır
            roster.puuids.add(str(player["puuid"]))
        if player.get("riot_id"):
            roster.riot_ids.add(_norm(str(player["riot_id"])))
    return roster


def build_known_roster(
    config: Config, transport: httpx.BaseTransport | None = None
) -> KnownRoster:
    roster = fetch_backend_roster(config, transport=transport)
    seed = load_seed_roster(config.seed_roster_path)
    roster.riot_ids |= seed
    log.info(
        "Bilinen oyuncu kümesi: %d puuid, %d riot_id (seed: %d)",
        len(roster.puuids), len(roster.riot_ids), len(seed),
    )
    return roster
