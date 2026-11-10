"""Backfill modu: kendi hesabının match history'sini geriye tarar,
custom + Sihirdar Vadisi + roster filtresinden geçen maçları normalize edip
gönderir.

Çift gönderim zararsızdır (backend `source_game_id` ile idempotent), bu yüzden
daha önce gönderilmiş maçlar tekrar gönderilebilir.

Sağlamlık notları:
- Gerçek LCU bazı sürümlerde begIndex/endIndex'i yok sayıp hep aynı listeyi
  döndürür; görülen gameId'ler set'te tutulur ve yeni maç içermeyen sayfada
  tarama biter.
- Kazananı olmayan < 300 sn maçlar remake sayılır ve sessizce atlanır (hata değil).
- Gönderim, tarama bittikten sonra played_at'e göre eskiden-yeniye yapılır ki
  backend incremental rating doğru sırayla işlesin (manuel replay gerekmesin).

GÖREV 36 (çoklu grup, ingest_contract "Çoklu grup — collector tarafı"):
- `sender` bir `GroupRouter` ise roster filtresi HER grubun kendi roster'ına karşı
  ayrı değerlendirilir ve maç `groups.choose_group` kuralıyla EN FAZLA bir gruba
  gider. Düz `Sender` ile (ve tek profilli router'la) davranış bugünküyle aynıdır.
- "İlk kurulum taraması" (`scan_first_setup` → `send_first_setup`): roster filtresi
  KAPALI tarama hiçbir şey göndermeden aday listesi döner; kullanıcının işaretledikleri
  kronolojik sırayla seçili gruba gönderilir. Tarama döngüsü backfill ile ORTAKTIR.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterator, Optional, Sequence, Union

from .archive import archive_raw
from .config import Config
from .groups import GroupRouter
from .lcu import LcuClient
from .normalizer import (
    NormalizeError,
    champion_map_from_summary,
    game_creation_datetime,
    is_custom,
    is_summoners_rift,
    mh_identity_pairs,
    mh_is_remake,
    normalize_match_history_game,
)
from .roster import KnownRoster, build_known_roster
from .sender import Sender

log = logging.getLogger("collector.backfill")

PAGE_SIZE = 20
_MAX_PAGES = 500  # emniyet supabı; 10k maçtan geriye gitmez

#: İlk kurulum taraması: pencere en az bu kadar gün (yetişme penceresi daha genişse o).
FIRST_SETUP_MIN_DAYS = 30
#: İlk kurulum taramasında listelenecek azami maç (en yeniler).
FIRST_SETUP_MAX_MATCHES = 50

AnySender = Union[Sender, GroupRouter]


@dataclass
class BackfillStats:
    scanned: int = 0
    customs: int = 0
    sent: int = 0
    skipped_roster: int = 0
    skipped_remake: int = 0
    skipped_non_sr: int = 0  # custom ama Sihirdar Vadisi değil (ARAM/URF vb.)
    errors: list[str] = field(default_factory=list)
    #: GÖREV 36: grup kimliği → gönderilen maç (yalnız GroupRouter ile dolar).
    sent_by_group: dict[str, int] = field(default_factory=dict)


def _champion_map(lcu: LcuClient) -> Optional[dict[int, str]]:
    try:
        return champion_map_from_summary(lcu.get_champion_summary()) or None
    except Exception as exc:
        log.warning("Could not fetch champion list (champion will be sent as null): %s", exc)
        return None


def _iter_sr_customs(
    lcu: LcuClient, puuid: str, stats: BackfillStats, since: Optional[date]
) -> Iterator[tuple[Any, dict[str, Any]]]:
    """Match history'yi yeniden-eskiye tarar; her custom SR maçın (gameId, detay)'ını verir.

    Sayfalama/ilerlemeyen liste/`since` kesimi/custom-SR elemesi/detay hatası burada;
    roster filtresi, remake ve normalizasyon çağıranındır.
    """
    seen_game_ids: set = set()
    for page in range(_MAX_PAGES):
        beg = page * PAGE_SIZE
        games = lcu.get_match_list(puuid, beg, beg + PAGE_SIZE)
        if not games:
            return
        # Gerçek LCU bazı sürümlerde begIndex/endIndex'i yok sayıp hep aynı listeyi
        # döndürür: sayfa hiç yeni gameId içermiyorsa liste ilerlemiyordur.
        if all(g.get("gameId") in seen_game_ids for g in games):
            log.info("Page %d contains no new matches: the list is not advancing, scan finished", page)
            return
        for game_summary in games:
            game_id = game_summary.get("gameId")
            if game_id in seen_game_ids:
                continue  # aynı maç önceki bir sayfada işlendi
            seen_game_ids.add(game_id)
            stats.scanned += 1
            created = game_creation_datetime(game_summary)
            if since and created and created.date() < since:
                return  # liste yeniden-eskiye sıralı; gerisi daha da eski
            if not is_custom(game_summary):
                continue
            stats.customs += 1
            if not is_summoners_rift(game_summary):
                stats.skipped_non_sr += 1
                log.info("Not a Summoner's Rift game, skipping: %s (gameMode=%s, mapId=%s)",
                         game_id, game_summary.get("gameMode"), game_summary.get("mapId"))
                continue
            try:
                full = lcu.get_game(game_id)
            except Exception as exc:
                stats.errors.append(f"{game_id}: could not fetch detail ({exc})")
                log.error("Could not fetch match detail (%s): %s", game_id, exc)
                continue
            yield game_id, full


def run_backfill(
    config: Config,
    lcu: LcuClient,
    sender: AnySender,
    since: Optional[date] = None,
    roster: Optional[KnownRoster] = None,
) -> BackfillStats:
    stats = BackfillStats()
    router = sender if isinstance(sender, GroupRouter) else None

    if router is not None:
        rosters = router.build_rosters() if roster is None else {router.first_id: roster}
    else:
        rosters = {"": roster if roster is not None else build_known_roster(config)}
    if all(r.is_empty() for r in rosters.values()):
        log.error(
            "Known player set is empty: no players in the backend and seed_roster.json is empty. "
            "For the first backfill, add riot_ids to collector/seed_roster.json."
        )
        return stats

    puuid = lcu.get_current_summoner().get("puuid")
    if not puuid:
        log.error("Could not get puuid from current-summoner")
        return stats

    champion_map = _champion_map(lcu)
    # (MatchPayload, hedef grup kimliği) — tarama sonunda sıralanıp gönderilir
    candidates: list[tuple[Any, Optional[str]]] = []

    for game_id, full in _iter_sr_customs(lcu, puuid, stats, since):
        pairs = mh_identity_pairs(full)
        if router is not None:
            target: Optional[str] = router.route_pairs(pairs, rosters)
            known = max(n for _, n in router.known_counts(pairs, rosters))
        else:
            known = rosters[""].count_known(pairs)
            target = "" if known >= config.min_known else None
        if target is None:
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
        candidates.append((payload, target))

    # Kronolojik gönderim: backend incremental rating'in doğru sırayla işlemesi
    # için eskiden-yeniye gönder (played_at UTC "Z" formatında, string sırası =
    # kronolojik sıra). Böylece backfill sonrası manuel replay gerekmez.
    for payload, target in sorted(candidates, key=lambda item: item[0].played_at):
        if router is not None:
            router.send_or_outbox(payload.model_dump(), target)
            stats.sent_by_group[target] = stats.sent_by_group.get(target, 0) + 1
        else:
            sender.send_or_outbox(payload.model_dump())
        stats.sent += 1

    log.info(
        "Backfill finished: %d matches scanned, %d custom, %d sent, "
        "%d blocked by roster filter, %d remakes skipped, "
        "%d non-Summoner's-Rift skipped, %d errors",
        stats.scanned, stats.customs, stats.sent, stats.skipped_roster,
        stats.skipped_remake, stats.skipped_non_sr, len(stats.errors),
    )
    return stats


# --------------------------------------------------------------------------- #
# İlk kurulum taraması (GÖREV 36) — listele → işaretle → onayla → gönder
# --------------------------------------------------------------------------- #


@dataclass
class SetupCandidate:
    """Listelenen bir maç. `payload` normalize edilmiş gövdedir; `raw` arşiv içindir."""

    game_id: str
    played_at: str
    duration_s: int
    #: (takım, görünen ad) — takım 100 önce, LCU sırası korunur
    players: list[tuple[int, str]]
    payload: dict[str, Any] = field(repr=False)
    raw: dict[str, Any] = field(repr=False)


@dataclass
class SetupScanResult:
    stats: BackfillStats
    #: En yeniden en eskiye (listeleme sırası); gönderim yine kronolojiktir.
    candidates: list[SetupCandidate] = field(default_factory=list)
    since: Optional[date] = None


def first_setup_days(config: Config) -> int:
    """Varsayılan pencere: yetişme penceresinden dar olmayan, en az 30 gün."""
    return max(config.catchup_days, FIRST_SETUP_MIN_DAYS)


def _display_name(participant: dict[str, Any]) -> str:
    return str(participant.get("riot_id") or "?")


def scan_first_setup(
    config: Config,
    lcu: LcuClient,
    *,
    since: Optional[date] = None,
    limit: int = FIRST_SETUP_MAX_MATCHES,
) -> SetupScanResult:
    """Roster filtresi KAPALI tarama. HİÇBİR ŞEY GÖNDERMEZ ve arşive yazmaz.

    Remake'ler ve SR dışı/custom olmayan maçlar listeye girmez. İmzada sender YOKTUR:
    listeleme adımının gönderim yapamayacağı yapısal olarak garantidir.
    """
    result = SetupScanResult(stats=BackfillStats(), since=since)
    stats = result.stats
    puuid = lcu.get_current_summoner().get("puuid")
    if not puuid:
        log.error("Could not get puuid from current-summoner")
        return result
    champion_map = _champion_map(lcu)

    for game_id, full in _iter_sr_customs(lcu, puuid, stats, since):
        if mh_is_remake(full):
            stats.skipped_remake += 1
            continue
        try:
            payload = normalize_match_history_game(full, champion_map)
        except NormalizeError as exc:
            stats.errors.append(f"{game_id}: {exc}")
            log.error("Could not normalize (%s): %s", game_id, exc)
            continue
        body = payload.model_dump()
        participants = sorted(
            body.get("participants") or [], key=lambda p: 0 if p.get("team") == 100 else 1
        )
        result.candidates.append(
            SetupCandidate(
                game_id=str(game_id),
                played_at=payload.played_at,
                duration_s=payload.duration_s,
                players=[(int(p.get("team") or 0), _display_name(p)) for p in participants],
                payload=body,
                raw=full,
            )
        )
        if len(result.candidates) >= limit:
            log.info("First-setup scan: listing limit (%d) reached", limit)
            break

    result.candidates.sort(key=lambda c: c.played_at, reverse=True)
    log.info(
        "First-setup scan finished: %d matches scanned, %d listed, %d remakes skipped, "
        "%d non-Summoner's-Rift skipped, %d errors (nothing sent)",
        stats.scanned, len(result.candidates), stats.skipped_remake,
        stats.skipped_non_sr, len(stats.errors),
    )
    return result


def send_first_setup(
    config: Config,
    router: GroupRouter,
    candidates: Sequence[SetupCandidate],
    group_id: str,
) -> BackfillStats:
    """Kullanıcının İŞARETLEDİĞİ adayları kronolojik sırayla `group_id` grubuna gönderir.

    Roster filtresi uygulanmaz — filtresiz gönderim yalnız bu açık, onaylı akıştadır.
    """
    if router.settings.get(group_id) is None:
        raise ValueError(f"unknown group: {group_id}")
    stats = BackfillStats()
    for candidate in sorted(candidates, key=lambda c: c.played_at):
        archive_raw(config, candidate.game_id, candidate.raw)
        router.send_or_outbox(dict(candidate.payload), group_id)
        stats.sent += 1
        stats.sent_by_group[group_id] = stats.sent_by_group.get(group_id, 0) + 1
    log.info("First-setup send finished: %d matches sent to group '%s'",
             stats.sent, router.settings.label_of(group_id))
    return stats
