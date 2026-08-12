"""Backfill modu: kendi hesabının match history'sini geriye tarar,
custom + roster filtresinden geçen maçları normalize edip gönderir.

Çift gönderim zararsızdır (backend `source_game_id` ile idempotent), bu yüzden
daha önce gönderilmiş maçlar tekrar gönderilebilir.

Sağlamlık notları:
- Gerçek LCU bazı sürümlerde begIndex/endIndex'i yok sayıp hep aynı listeyi
  döndürür; görülen gameId'ler set'te tutulur ve yeni maç içermeyen sayfada
  tarama biter.
- Kazananı olmayan < 300 sn maçlar remake sayılır ve sessizce atlanır (hata değil).
- Gönderim, tarama bittikten sonra played_at'e göre eskiden-yeniye yapılır ki
  backend incremental rating doğru sırayla işlesin (manuel replay gerekmesin).
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
    mh_is_remake,
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
    skipped_remake: int = 0
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
            "Known player set is empty: no players in the backend and seed_roster.json is empty. "
            "For the first backfill, add riot_ids to collector/seed_roster.json."
        )
        return stats

    puuid = lcu.get_current_summoner().get("puuid")
    if not puuid:
        log.error("Could not get puuid from current-summoner")
        return stats

    try:
        champion_map = champion_map_from_summary(lcu.get_champion_summary()) or None
    except Exception as exc:
        log.warning("Could not fetch champion list (champion will be sent as null): %s", exc)
        champion_map = None

    seen_game_ids: set = set()
    candidates = []  # normalize edilmiş MatchPayload'lar; tarama sonunda sıralanıp gönderilir

    stop = False
    for page in range(_MAX_PAGES):
        beg = page * PAGE_SIZE
        games = lcu.get_match_list(puuid, beg, beg + PAGE_SIZE)
        if not games:
            break
        # Gerçek LCU bazı sürümlerde begIndex/endIndex'i yok sayıp hep aynı listeyi
        # döndürür: sayfa hiç yeni gameId içermiyorsa liste ilerlemiyordur.
        if all(g.get("gameId") in seen_game_ids for g in games):
            log.info("Page %d contains no new matches: the list is not advancing, scan finished", page)
            break
        for game_summary in games:
            game_id = game_summary.get("gameId")
            if game_id in seen_game_ids:
                continue  # aynı maç önceki bir sayfada işlendi
            seen_game_ids.add(game_id)
            stats.scanned += 1
            created = game_creation_datetime(game_summary)
            if since and created and created.date() < since:
                stop = True  # liste yeniden-eskiye sıralı; gerisi daha da eski
                break
            if not is_custom(game_summary):
                continue
            stats.customs += 1
            try:
                full = lcu.get_game(game_id)
            except Exception as exc:
                stats.errors.append(f"{game_id}: could not fetch detail ({exc})")
                log.error("Could not fetch match detail (%s): %s", game_id, exc)
                continue

            known = roster.count_known(mh_identity_pairs(full))
            if known < config.min_known:
                stats.skipped_roster += 1
                log.info("Roster filter: %s skipped (%d/%d known < threshold %d)",
                         game_id, known, len(full.get("participantIdentities") or []),
                         config.min_known)
                continue

            if mh_is_remake(full):
                stats.skipped_remake += 1
                log.info("Remake skipped (%s): no winner and duration < 300 s", game_id)
                continue

            try:
                payload = normalize_match_history_game(full, champion_map)
            except NormalizeError as exc:
                stats.errors.append(f"{game_id}: {exc}")
                log.error("Could not normalize (%s): %s", game_id, exc)
                continue

            archive_raw(config, str(game_id), full)
            candidates.append(payload)
        if stop:
            break

    # Kronolojik gönderim: backend incremental rating'in doğru sırayla işlemesi
    # için eskiden-yeniye gönder (played_at UTC "Z" formatında, string sırası =
    # kronolojik sıra). Böylece backfill sonrası manuel replay gerekmez.
    for payload in sorted(candidates, key=lambda p: p.played_at):
        sender.send_or_outbox(payload.model_dump())
        stats.sent += 1

    log.info(
        "Backfill finished: %d matches scanned, %d custom, %d sent, "
        "%d blocked by roster filter, %d remakes skipped, %d errors",
        stats.scanned, stats.customs, stats.sent, stats.skipped_roster,
        stats.skipped_remake, len(stats.errors),
    )
    return stats
