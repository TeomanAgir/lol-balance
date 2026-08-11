"""Backfill modu: kendi hesabının match history'sini geriye tarar,
custom + roster filtresinden geçen maçları normalize edip gönderir.

Çift gönderim zararsızdır (backend `source_game_id` ile idempotent), bu yüzden
daha önce gönderilmiş maçlar tekrar gönderilebilir.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .archive import archive_raw
from .config import Config
from .lcu import LcuClient
from .normalizer import (
    NormalizeError,
    champion_map_from_summary,
    game_creation_datetime,
    is_custom,
    mh_identity_pairs,
    normalize_match_history_game,
)
from .roster import KnownRoster, build_known_roster
from .sender import Sender

log = logging.getLogger("collector.backfill")

PAGE_SIZE = 20
_MAX_PAGES = 500  # emniyet supabı; 10k maçtan geriye gitmez


@dataclass
class BackfillStats:
    scanned: int = 0
    customs: int = 0
    sent: int = 0
    skipped_roster: int = 0
    errors: list[str] = field(default_factory=list)


def run_backfill(
    config: Config,
    lcu: LcuClient,
    sender: Sender,
    since: Optional[date] = None,
    roster: Optional[KnownRoster] = None,
) -> BackfillStats:
    stats = BackfillStats()

    if roster is None:
        roster = build_known_roster(config)
    if roster.is_empty():
        log.error(
            "Bilinen oyuncu kümesi boş: backend'de oyuncu yok ve seed_roster.json boş. "
            "İlk backfill için collector/seed_roster.json dosyasına riot_id'leri ekleyin."
        )
        return stats

    puuid = lcu.get_current_summoner().get("puuid")
    if not puuid:
        log.error("current-summoner'dan puuid alınamadı")
        return stats

    try:
        champion_map = champion_map_from_summary(lcu.get_champion_summary()) or None
    except Exception as exc:
        log.warning("Champion listesi alınamadı (champion=null gidecek): %s", exc)
        champion_map = None

    stop = False
    for page in range(_MAX_PAGES):
        beg = page * PAGE_SIZE
        games = lcu.get_match_list(puuid, beg, beg + PAGE_SIZE)
        if not games:
            break
        for game_summary in games:
            stats.scanned += 1
            created = game_creation_datetime(game_summary)
            if since and created and created.date() < since:
                stop = True  # liste yeniden-eskiye sıralı; gerisi daha da eski
                break
            if not is_custom(game_summary):
                continue
            stats.customs += 1
            game_id = game_summary.get("gameId")
            try:
                full = lcu.get_game(game_id)
            except Exception as exc:
                stats.errors.append(f"{game_id}: detay alınamadı ({exc})")
                log.error("Maç detayı alınamadı (%s): %s", game_id, exc)
                continue

            known = roster.count_known(mh_identity_pairs(full))
            if known < config.min_known:
                stats.skipped_roster += 1
                log.info("Roster filtresi: %s atlandı (%d/%d bilinen < %d eşik)",
                         game_id, known, len(full.get("participantIdentities") or []),
                         config.min_known)
                continue

            try:
                payload = normalize_match_history_game(full, champion_map)
            except NormalizeError as exc:
                stats.errors.append(f"{game_id}: {exc}")
                log.error("Normalize edilemedi (%s): %s", game_id, exc)
                continue

            archive_raw(config, str(game_id), full)
            sender.send_or_outbox(payload.model_dump())
            stats.sent += 1
        if stop:
            break

    log.info(
        "Backfill bitti: %d maç tarandı, %d custom, %d gönderildi, "
        "%d roster filtresine takıldı, %d hata",
        stats.scanned, stats.customs, stats.sent, stats.skipped_roster, len(stats.errors),
    )
    return stats
