"""Geçmiş maçların eşya envanterlerini backend'e yazan backfill (GÖREV 14).

`python -m collector backfill-items [--dry-run]`

`backfill-positions` ile birebir aynı desen (ortak parçalar:
`backfill_common.py`), tek fark taşınan veridir:

1. `raw_archive/*.json` içindeki her ham maçtan katılımcı envanterleri çözülür
   (`normalizer.items_from_raw`: canlı EOG bloğunda oyuncunun `items` dizisi,
   match-history kaydında `item0..item6` slotları; boş slotlar atılır, ham sıra
   korunur — ingest_contract "items").
2. `GET /api/v1/matches` ile `source_game_id → match.id` eşlenir.
3. `GET /api/v1/players` ile `puuid → player_id` eşlenir (api_contract §2).
4. `PUT /api/v1/matches/{id}/items` ile `{"items": {"<player_id>": [...]}}`
   gönderilir. Arşivde eşya BİLGİSİ olmayan katılımcı (None) GÖNDERİLMEZ;
   kısmi güncelleme serbesttir. Boş envanter (`[]`) ise gönderilir — "bilgi
   var, envanter boş" ile "bilgi yok" backend'de farklı şeylerdir.

Rating'e etkisi yoktur (replay koşmaz). Eşleşmeyen maç/oyuncu ölümcül değildir:
uyarı yazılır, tarama devam eder. Komut idempotenttir; ham arşiv otoritedir,
aynı maç için tekrar koşmak aynı sonucu yazar.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx

from .backfill_common import (
    MATCH_LIST_LIMIT,
    archive_files,
    fetch_match_index,
    fetch_player_index,
    load_raw,
    open_client,
)
from .config import Config
from .normalizer import items_from_raw

log = logging.getLogger("collector.backfill_items")

ITEMS_PATH = "/api/v1/matches/{match_id}/items"


@dataclass
class ItemsBackfillStats:
    archives: int = 0  # okunan ham maç dosyası
    matched: int = 0  # backend'de karşılığı bulunan maç
    updated: int = 0  # PUT gönderilen (dry-run'da gönderilecek olan) maç
    participants_sent: int = 0  # gönderilen envanter sayısı
    without_items: int = 0  # arşivde eşya bilgisi yok → gönderilmedi
    unmatched_matches: list[str] = field(default_factory=list)
    unknown_players: int = 0
    errors: list[str] = field(default_factory=list)


def run_items_backfill(
    config: Config,
    *,
    dry_run: bool = False,
    transport: httpx.BaseTransport | None = None,
    archive_dir: Optional[Path] = None,
    limit: int = MATCH_LIST_LIMIT,
) -> ItemsBackfillStats:
    stats = ItemsBackfillStats()
    files = archive_files(config, archive_dir)
    if not files:
        log.warning(
            "Raw match archive is empty (%s): backfill-items found nothing to do",
            archive_dir or config.raw_archive_dir,
        )
        return stats

    with open_client(config, transport) as client:
        try:
            matches = fetch_match_index(client, limit=min(limit, MATCH_LIST_LIMIT))
            players = fetch_player_index(client)
        except (httpx.HTTPError, ValueError) as exc:
            log.error("Could not fetch match/player list from the backend: %s", exc)
            stats.errors.append(f"backend list: {exc}")
            return stats

        log.info(
            "Backend has %d matches, %d players with puuid; %d raw match files to scan%s",
            len(matches), len(players), len(files), " (DRY-RUN)" if dry_run else "",
        )

        for path in files:
            raw = load_raw(path)
            if raw is None:
                continue
            stats.archives += 1
            source_game_id = str(raw.get("gameId") or path.stem)

            match = matches.get(source_game_id)
            if match is None:
                stats.unmatched_matches.append(source_game_id)
                log.warning(
                    "Match not found in the backend, skipping: %s "
                    "(may not be ingested or may be outside the list limit)",
                    source_game_id,
                )
                continue
            stats.matched += 1

            items: dict[str, list[int]] = {}
            for key, inventory in items_from_raw(raw).items():
                if inventory is None:  # kaynakta eşya bilgisi yok — üzerine yazma
                    stats.without_items += 1
                    continue
                player_id = players.get(str(key))
                if player_id is None:
                    stats.unknown_players += 1
                    log.warning(
                        "Player not matched (match %s): puuid=%s — no record with this puuid in the backend",
                        source_game_id, key,
                    )
                    continue
                if match["player_ids"] and player_id not in match["player_ids"]:
                    stats.unknown_players += 1
                    log.warning(
                        "Player %s is not a participant of this match (%s), skipping",
                        player_id, source_game_id,
                    )
                    continue
                items[str(player_id)] = inventory

            if not items:
                log.warning("No items to send: %s", source_game_id)
                continue

            if dry_run:
                log.info(
                    "[dry-run] PUT %s ← %s",
                    ITEMS_PATH.format(match_id=match["id"]),
                    json.dumps(items, ensure_ascii=False, sort_keys=True),
                )
                stats.updated += 1
                stats.participants_sent += len(items)
                continue

            try:
                response = client.put(
                    ITEMS_PATH.format(match_id=match["id"]),
                    json={"items": items},
                )
            except httpx.HTTPError as exc:
                stats.errors.append(f"{source_game_id}: {exc}")
                log.error("Could not send item update (%s): %s", source_game_id, exc)
                continue

            if 200 <= response.status_code < 300:
                stats.updated += 1
                stats.participants_sent += len(items)
                log.info(
                    "Items updated: match %s (id=%s), %d participants",
                    source_game_id, match["id"], len(items),
                )
            else:
                stats.errors.append(
                    f"{source_game_id}: HTTP {response.status_code} {response.text[:300]}"
                )
                log.error(
                    "Backend rejected the item update (%s, HTTP %s): %s",
                    source_game_id, response.status_code, response.text[:300],
                )

    log.info(
        "backfill-items finished%s: %d raw matches, %d matched, %d matches updated, "
        "%d inventories sent, %d participants without item data, %d matches missing in "
        "backend, %d players unmatched, %d errors",
        " (DRY-RUN — nothing was sent)" if dry_run else "",
        stats.archives, stats.matched, stats.updated, stats.participants_sent,
        stats.without_items, len(stats.unmatched_matches), stats.unknown_players,
        len(stats.errors),
    )
    return stats
