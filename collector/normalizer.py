"""Ham LCU payload'ları → ingest contract modeli.

İki kaynak formatı desteklenir:
- EOG stats block (`/lol-end-of-game/v1/eog-stats-block`): canlı mod.
- Match history game (`/lol-match-history/v1/games/{id}`): fallback + backfill.

LCU alan adları patch'lerde değişebildiği için stat eşlemeleri aday-anahtar
listeleriyle yapılır (eski UPPER_SNAKE + yeni camelCase birlikte denenir).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .models import VALID_POSITIONS, MatchPayload, Participant, Stats
from .role_infer import infer_positions, position_for


class NormalizeError(Exception):
    """Ham payload contract'a çevrilemiyor (eksik/bozuk alan)."""


# stat adı → ham payload'da denenecek anahtarlar (sıra: legacy EOG, match-history camelCase)
_STAT_KEYS: dict[str, list[str]] = {
    "kills": ["CHAMPIONS_KILLED", "kills", "championsKilled"],
    "deaths": ["NUM_DEATHS", "deaths", "numDeaths"],
    "assists": ["ASSISTS", "assists"],
    "gold": ["GOLD_EARNED", "goldEarned"],
    "damage_to_champs": ["TOTAL_DAMAGE_DEALT_TO_CHAMPIONS", "totalDamageDealtToChampions"],
    "vision_score": ["VISION_SCORE", "visionScore"],
}
_CS_LANE_KEYS = ["MINIONS_KILLED", "totalMinionsKilled", "minionsKilled"]
_CS_NEUTRAL_KEYS = ["NEUTRAL_MINIONS_KILLED", "neutralMinionsKilled"]

_POSITION_ALIASES = {"MID": "MIDDLE", "BOT": "BOTTOM", "SUPPORT": "UTILITY", "SUP": "UTILITY"}

#: Envanterdeki en fazla eşya sayısı: 6 slot + trinket (ingest_contract "items").
MAX_ITEMS = 7
#: Match-history kayıtlarında envanter slotlarının alan adları (sıra = slot sırası).
MH_ITEM_KEYS = tuple(f"item{index}" for index in range(MAX_ITEMS))


def _pick_int(raw: dict[str, Any], candidates: list[str]) -> Optional[int]:
    for key in candidates:
        value = raw.get(key)
        if value is not None:
            try:
                return int(round(float(value)))
            except (TypeError, ValueError):
                continue
    return None


def _extract_stats(raw_stats: dict[str, Any]) -> Stats:
    values = {name: _pick_int(raw_stats, keys) for name, keys in _STAT_KEYS.items()}
    lane = _pick_int(raw_stats, _CS_LANE_KEYS)
    neutral = _pick_int(raw_stats, _CS_NEUTRAL_KEYS)
    if lane is None and neutral is None:
        values["cs"] = None
    else:
        values["cs"] = (lane or 0) + (neutral or 0)
    return Stats(**values)


def normalize_position(value: Any) -> Optional[str]:
    """Açık position alanının normalizasyonu: yalnızca geçerli, açık bir değer
    kabul edilir; boş/NONE/tanınmayan her şey null'a düşer. Bu fonksiyon TAHMİN
    YAPMAZ — tahmin `role_infer` modülünün işidir (bkz. GÖREV 0)."""
    if not value or not isinstance(value, str):
        return None
    upper = value.strip().upper()
    upper = _POSITION_ALIASES.get(upper, upper)
    return upper if upper in VALID_POSITIONS else None


def _explicit_position(raw_player: dict[str, Any]) -> Optional[str]:
    """Bir katılımcının AÇIK position alanı (tahmin yok) — 1. katman."""
    return normalize_position(raw_player.get("selectedPosition") or raw_player.get("position"))


def _detected_position(raw_player: dict[str, Any]) -> Optional[str]:
    """Riot'un kendi tespiti `detectedTeamPosition` — 2. katman (2026-08-13).

    Makine alanıdır: yalnızca kanonik rol adları (VALID_POSITIONS) kabul edilir,
    alias çözümü YAPILMAZ ("MID" gibi tanınmayan bir değer olduğu gibi
    yayılamaz). Boş/NONE/tanınmayan her şey None döner → zincire düşülür.
    """
    value = raw_player.get("detectedTeamPosition")
    if not value or not isinstance(value, str):
        return None
    upper = value.strip().upper()
    return upper if upper in VALID_POSITIONS else None


def _declared_position(raw_player: dict[str, Any]) -> Optional[str]:
    """Ham katılımcı kaydında BEYAN edilen rol: açık seçim > Riot tespiti.

    Rol önceliğinin ilk iki katmanı (ingest_contract "Rol önceliği",
    2026-08-13 revizyonu): (a) `selectedPosition`/`position` boş değilse o
    kazanır; (b) boşsa `detectedTeamPosition` kullanılır — bazı patch'lerde
    custom draft EOG'unda `selectedPosition` 10/10 boş string gelirken
    `detectedTeamPosition` 10/10 dolu gelir (kanıt: gameId 1734940206).
    Boş string hiçbir katmanda değer DEĞİLDİR. İkisi de yoksa None → 3. katman
    (kısıt zinciri) `positions_from_raw`'da devrededir.
    """
    return _explicit_position(raw_player) or _detected_position(raw_player)


def _keyed_participants(raw: dict[str, Any]) -> list[tuple[Any, dict[str, Any]]]:
    """Ham maçtaki katılımcılar → `[(anahtar, ham katılımcı kaydı)]`.

    Anahtarlama `role_infer.infer_positions` ile BİREBİR aynıdır (puuid varsa
    puuid, yoksa participantId/index) — bu sayede buradan üretilen sözlükler
    (rol, eşya) tahmin sözlükleriyle birleştirilebilir ve `backfill-*`
    komutlarında aynı puuid → player_id eşlemesi kullanılabilir.
    """
    if raw.get("participants"):  # match-history formatı
        identities: dict[int, dict[str, Any]] = {}
        for identity in raw.get("participantIdentities") or []:
            try:
                identities[int(identity.get("participantId", -1))] = identity.get("player") or {}
            except (TypeError, ValueError):
                continue
        keyed: list[tuple[Any, dict[str, Any]]] = []
        for index, p in enumerate(raw["participants"]):
            try:
                participant_id = int(p.get("participantId", index))
            except (TypeError, ValueError):
                participant_id = index
            player = identities.get(participant_id, {})
            keyed.append((player.get("puuid") or p.get("puuid") or participant_id, p))
        return keyed

    keyed = []  # EOG formatı
    index = 0
    for team in raw.get("teams") or []:
        for player in team.get("players") or []:
            keyed.append((player.get("puuid") or index, player))
            index += 1
    return keyed


def _declared_positions(raw: dict[str, Any]) -> dict[Any, Optional[str]]:
    """Ham maçtaki beyan edilen position alanları (açık > tespit) → `{key: rol}`."""
    return {key: _declared_position(p) for key, p in _keyed_participants(raw)}


def positions_from_raw(raw: dict[str, Any]) -> dict[Any, Optional[str]]:
    """Ham maç (EOG veya match-history) → `{key: rol veya None}`.

    Öncelik kuralı TEK YERDE burada durur (üç katman, 2026-08-13 revizyonu):
    **açık position alanı kazanır**, boşsa **Riot tespiti `detectedTeamPosition`**
    kullanılır, o da yoksa `role_infer` kısıt zincirinin sonucu kullanılır,
    zincir de çözemezse None kalır (tahmin ZORLANMAZ — GÖREV 0). `normalize_eog`,
    `normalize_match_history_game` ve `backfill_positions` aynı sonucu almak
    için bu fonksiyonu kullanır.
    """
    resolved = dict(infer_positions(raw))
    for key, position in _declared_positions(raw).items():
        if position:
            resolved[key] = position
    return resolved


def _clean_item_ids(values: Any) -> list[int]:
    """Ham eşya id dizisi → contract'a uygun liste (GÖREV 14).

    Kurallar (ingest_contract "items"): ham SIRA korunur, boş slotlar (`0`) ve
    anlamsız değerler (negatif, int'e çevrilemeyen) ATILIR, en fazla `MAX_ITEMS`
    eleman kalır. Boş envanter `[]` döner — "bilgi var ama envanter boş".
    """
    cleaned: list[int] = []
    for value in values or []:
        if isinstance(value, bool):  # True/False int'e çevrilebilir ama eşya değildir
            continue
        try:
            item_id = int(value)
        except (TypeError, ValueError):
            continue
        if item_id <= 0:  # 0 = boş slot, negatif = bozuk veri
            continue
        cleaned.append(item_id)
        if len(cleaned) >= MAX_ITEMS:
            break
    return cleaned


def eog_items(raw_player: dict[str, Any]) -> Optional[list[int]]:
    """Canlı EOG oyuncusunun maç sonu envanteri (`items` dizisi) → id listesi.

    Alan hiç yoksa (eski şema) `None` döner — "bilgi yok"; bu durumda payload'a
    `items` alanı KONMAZ (bkz. `models.Participant`).
    """
    values = raw_player.get("items")
    if not isinstance(values, list):
        return None
    return _clean_item_ids(values)


def mh_items(raw_participant: dict[str, Any]) -> Optional[list[int]]:
    """Match-history katılımcısının `item0..item6` slotları → id listesi.

    Gerçek kayıtlarda slotlar `stats` altındadır (bkz.
    `fixtures/mh_game_custom_real.json`); bazı sürümler katılımcı kaydının
    kendisinde taşır, ikisi de denenir. Hiçbir slot alanı yoksa `None`.
    """
    stats = raw_participant.get("stats")
    sources = [stats if isinstance(stats, dict) else {}, raw_participant]
    values: list[Any] = []
    found = False
    for key in MH_ITEM_KEYS:
        for source in sources:
            if key in source:
                values.append(source[key])
                found = True
                break
    return _clean_item_ids(values) if found else None


def items_from_raw(raw: dict[str, Any]) -> dict[Any, Optional[list[int]]]:
    """Ham maç (EOG veya match-history) → `{key: eşya listesi veya None}`.

    Anahtarlama `positions_from_raw` ile aynıdır (puuid varsa puuid), böylece
    `backfill-items` rolle aynı oyuncu eşleme yolunu kullanabilir. `None`,
    kaynakta o katılımcı için hiç eşya bilgisi olmadığı anlamına gelir.
    """
    extract = mh_items if raw.get("participants") else eog_items
    return {key: extract(participant) for key, participant in _keyed_participants(raw)}


def _riot_id(gamename: Any, tagline: Any, fallback_name: Any = None) -> Optional[str]:
    if gamename and tagline:
        return f"{gamename}#{tagline}"
    if fallback_name:
        return str(fallback_name)
    return None


def to_utc_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _duration_seconds(value: Any) -> int:
    """gameLength/gameDuration bazı sürümlerde ms döner; 20000'den büyük değer
    saniye olamaz (5.5 saat) → ms varsayıp böl."""
    seconds = int(value)
    return seconds // 1000 if seconds > 20_000 else seconds


def is_custom(raw: dict[str, Any]) -> bool:
    """Hem EOG bloğu hem match-history kaydı için custom maç tespiti."""
    game_type = raw.get("gameType")
    if isinstance(game_type, str) and game_type.strip().upper() == "CUSTOM_GAME":
        return True
    queue_id = raw.get("queueId")
    if queue_id is not None:
        try:
            return int(queue_id) == 0
        except (TypeError, ValueError):
            pass
    queue_type = raw.get("queueType")
    if isinstance(queue_type, str) and "CUSTOM" in queue_type.upper():
        return True
    return False


#: Sihirdar Vadisi'nin harita kimliği (match-history kayıtlarında `mapId`).
SUMMONERS_RIFT_MAP_ID = 11
#: SR maçlarının oyun modu; ARAM/URF/One for All gibi modlar başka değer taşır.
SUMMONERS_RIFT_GAME_MODE = "CLASSIC"


def is_summoners_rift(raw: dict[str, Any]) -> bool:
    """Maç Sihirdar Vadisi'nde mi oynandı? (Teoman, 2026-08-13 — davranışsal karar)

    Yalnız SR custom'ları toplanır; custom ARAM/URF/One for All gibi maçlar
    custom-olmayanlar gibi sessizce atlanır. `is_custom` ile AYNI çağrı
    noktalarında uygulanır.

    Sinyaller (gerçek veride doğrulandı):
    - `gameMode`: ANA kontrol. Canlı EOG bloğunda `mapId` YOKTUR ama `gameMode`
      vardır (bkz. `fixtures/eog_custom_real.json`).
    - `mapId`: kemer-askı. Match-history kayıtlarında hem `gameMode` hem
      `mapId: 11` gelir; SR dışı bir mapId tek başına elemeye yeter (Twisted
      Treeline gibi eski haritalar da `gameMode: "CLASSIC"` taşırdı).

    TOLERANS: `gameMode` alanı hiç yoksa (ve mapId de SR-dışını göstermiyorsa)
    maç ATLANMAZ — eski/eksik şemalarda geriye dönük kayıt kaybı yaşanmasın
    diye custom tespiti geçmiş maç işlenmeye devam eder.
    """
    game_mode = raw.get("gameMode")
    if isinstance(game_mode, str) and game_mode.strip():
        if game_mode.strip().upper() != SUMMONERS_RIFT_GAME_MODE:
            return False
    map_id = raw.get("mapId")
    if map_id is not None:
        try:
            if int(map_id) != SUMMONERS_RIFT_MAP_ID:
                return False
        except (TypeError, ValueError):
            pass  # okunamayan mapId sinyal sayılmaz; gameMode kararı geçerli kalır
    return True


def eog_end_datetime(raw: dict[str, Any]) -> Optional[datetime]:
    """EOG bloğundaki `endOfGameTimestamp` (epoch ms) → maçın gerçek bitiş anı.

    Gerçek LCU EOG payload'ı bu alanı taşır (bkz. `fixtures/eog_custom_real.json`);
    yakalama anından (`captured_at`) bağımsız olduğu için geç işlemede (retry,
    outbox, proses gecikmesi) `played_at`'in kaymasını engeller. Alan yoksa/bozuksa
    None döner ve çağıran `captured_at`'e düşer.

    Match-history kayıtlarında bu alan YOKTUR (gerçek fixture'da da yok); orada
    zaman `gameCreationDate + gameDuration` ile zaten mutlak olarak hesaplanır.
    """
    epoch_ms = raw.get("endOfGameTimestamp")
    if epoch_ms is None:
        return None
    try:
        return datetime.fromtimestamp(int(epoch_ms) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def game_creation_datetime(raw: dict[str, Any]) -> Optional[datetime]:
    iso = raw.get("gameCreationDate")
    if isinstance(iso, str) and iso:
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    epoch_ms = raw.get("gameCreation")
    if epoch_ms is not None:
        try:
            return datetime.fromtimestamp(int(epoch_ms) / 1000, tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            pass
    return None


def normalize_eog(
    raw: dict[str, Any],
    captured_at: datetime,
    champion_map: dict[int, str] | None = None,
) -> MatchPayload:
    """EOG stats block → contract.

    `captured_at`: maçın yakalandığı an. `played_at` için YEDEKTİR — payload
    `endOfGameTimestamp` taşıyorsa (gerçek LCU şeması taşır) maçın gerçek bitiş
    anı kullanılır; böylece geç işlemede (retry/outbox) zaman kaymaz.
    """
    game_id = raw.get("gameId")
    if not game_id:
        raise NormalizeError("EOG block has no gameId")

    duration_raw = raw.get("gameLength", raw.get("gameDuration"))
    if duration_raw is None:
        raise NormalizeError(f"EOG block has no duration field (gameId={game_id})")

    teams = raw.get("teams") or []
    winner_team: Optional[int] = None
    participants: list[Participant] = []
    # Açık position kazanır, boşsa Riot tespiti (detectedTeamPosition), yoksa
    # kısıt-çözümlü rol tahmini (GÖREV 0 + 2026-08-13 revizyonu).
    # `views_from_eog` ile aynı sırada gezildiğimiz için index anahtarı tutar.
    resolved_positions = positions_from_raw(raw)
    player_index = 0

    for team in teams:
        team_id = team.get("teamId")
        if team.get("isWinningTeam"):
            winner_team = int(team_id)
        for player in team.get("players") or []:
            index_key = player_index
            player_index += 1
            puuid = player.get("puuid")
            if not puuid:
                raise NormalizeError(
                    f"puuid missing (gameId={game_id}, player={player.get('summonerName')!r}) — "
                    f"the contract requires puuid, match cannot be sent"
                )
            champion = player.get("championName")
            if not champion and champion_map:
                champion = champion_map.get(_pick_int(player, ["championId"]) or -1)
            participants.append(
                Participant(
                    puuid=puuid,
                    riot_id=_riot_id(
                        player.get("riotIdGameName"),
                        player.get("riotIdTagLine"),
                        player.get("summonerName"),
                    ),
                    team=int(player.get("teamId") or team_id),
                    # Açık position > Riot tespiti > kısıt-çözümlü tahmin
                    position=position_for(resolved_positions, puuid, index_key),
                    champion=champion or None,
                    stats=_extract_stats(player.get("stats") or {}),
                    # GÖREV 14: maç sonu envanteri; alan yoksa None → payload'a girmez
                    items=eog_items(player),
                )
            )

    if winner_team not in (100, 200):
        raise NormalizeError(f"Could not determine the winning team (gameId={game_id})")

    return MatchPayload(
        source_game_id=str(game_id),
        played_at=to_utc_z(eog_end_datetime(raw) or captured_at),
        duration_s=_duration_seconds(duration_raw),
        winner_team=winner_team,
        participants=participants,
    )


REMAKE_MAX_DURATION_S = 300


def _mh_winner_team(raw: dict[str, Any]) -> Optional[int]:
    """Match-history kaydından kazanan takım; belirlenemiyorsa None."""
    winner_team: Optional[int] = None
    for team in raw.get("teams") or []:
        win = team.get("win")
        if win is True or (isinstance(win, str) and win.strip().lower() == "win"):
            winner_team = int(team.get("teamId"))
    return winner_team if winner_team in (100, 200) else None


def mh_is_remake(raw: dict[str, Any]) -> bool:
    """Kazananı olmayan kısa maç (< 300 sn) remake'tir: normalize edilemez ama bu
    bir hata değildir — backend zaten duration < 300 maçları void'ler, göndermeye
    gerek yok. Kazanan yok ama süre >= 300 ise gerçekten anormaldir (remake değil)."""
    duration_raw = raw.get("gameDuration")
    if duration_raw is None:
        return False
    try:
        duration_s = _duration_seconds(duration_raw)
    except (TypeError, ValueError):
        return False
    return duration_s < REMAKE_MAX_DURATION_S and _mh_winner_team(raw) is None


def mh_identity_pairs(raw: dict[str, Any]) -> list[tuple[Optional[str], Optional[str]]]:
    """Match-history kaydından (puuid, riot_id) çiftleri — roster filtresi için."""
    pairs: list[tuple[Optional[str], Optional[str]]] = []
    for identity in raw.get("participantIdentities") or []:
        player = identity.get("player") or {}
        pairs.append(
            (
                player.get("puuid"),
                _riot_id(
                    player.get("gameName"), player.get("tagLine"), player.get("summonerName")
                ),
            )
        )
    return pairs


def normalize_match_history_game(
    raw: dict[str, Any],
    champion_map: dict[int, str] | None = None,
) -> MatchPayload:
    """Match history game → contract. Backfill ve EOG fallback yolu."""
    game_id = raw.get("gameId")
    if not game_id:
        raise NormalizeError("Match history record has no gameId")

    duration_raw = raw.get("gameDuration")
    if duration_raw is None:
        raise NormalizeError(f"Match history record has no gameDuration (gameId={game_id})")
    duration_s = _duration_seconds(duration_raw)

    winner_team = _mh_winner_team(raw)
    if winner_team is None:
        raise NormalizeError(f"Could not determine the winning team (gameId={game_id})")

    identities: dict[int, dict[str, Any]] = {}
    for identity in raw.get("participantIdentities") or []:
        identities[int(identity.get("participantId", -1))] = identity.get("player") or {}

    # açık position > Riot tespiti > kısıt-çözümlü rol tahmini (GÖREV 0 + 2026-08-13)
    resolved_positions = positions_from_raw(raw)

    participants: list[Participant] = []
    for p in raw.get("participants") or []:
        participant_id = int(p.get("participantId", -1))
        player = identities.get(participant_id, {})
        puuid = player.get("puuid") or p.get("puuid")
        if not puuid:
            raise NormalizeError(
                f"puuid missing (gameId={game_id}, participantId={p.get('participantId')}) — "
                f"the contract requires puuid, match cannot be sent"
            )
        champion = None
        if champion_map:
            champion = champion_map.get(_pick_int(p, ["championId"]) or -1)
        participants.append(
            Participant(
                puuid=puuid,
                riot_id=_riot_id(
                    player.get("gameName"), player.get("tagLine"), player.get("summonerName")
                ),
                team=int(p.get("teamId")),
                # timeline.lane tek başına custom'larda güvenilmez (Riot tahmini);
                # açık position alanı varsa O kazanır, yoksa Smite + lane/role
                # kısıt zincirinin sonucu kullanılır — belirsizse null kalır.
                position=position_for(resolved_positions, puuid, participant_id),
                champion=champion,
                stats=_extract_stats(p.get("stats") or {}),
                # GÖREV 14: item0..item6 slotları; hiç slot yoksa None → payload'a girmez
                items=mh_items(p),
            )
        )

    created = game_creation_datetime(raw)
    if created is None:
        raise NormalizeError(f"Could not determine match time (gameId={game_id})")
    played_at = to_utc_z(created + timedelta(seconds=duration_s))

    return MatchPayload(
        source_game_id=str(game_id),
        played_at=played_at,
        duration_s=duration_s,
        winner_team=winner_team,
        participants=participants,
    )


def champion_map_from_summary(summary: list[dict[str, Any]]) -> dict[int, str]:
    """`/lol-game-data/assets/v1/champion-summary.json` → {championId: görünen ad}."""
    result: dict[int, str] = {}
    for entry in summary:
        cid, name = entry.get("id"), entry.get("name")
        if isinstance(cid, int) and cid > 0 and name:
            result[cid] = str(name)
    return result
