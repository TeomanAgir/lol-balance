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
    """Custom'larda position güvenilmezdir: yalnızca geçerli, açık bir değer varsa
    kullanılır; boş/NONE/tanınmayan her şey null'a düşer — tahmin edilmez."""
    if not value or not isinstance(value, str):
        return None
    upper = value.strip().upper()
    upper = _POSITION_ALIASES.get(upper, upper)
    return upper if upper in VALID_POSITIONS else None


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
    """EOG stats block → contract. `captured_at`: maçın yakalandığı an (≈ bitiş anı)."""
    game_id = raw.get("gameId")
    if not game_id:
        raise NormalizeError("EOG bloğunda gameId yok")

    duration_raw = raw.get("gameLength", raw.get("gameDuration"))
    if duration_raw is None:
        raise NormalizeError(f"EOG bloğunda süre alanı yok (gameId={game_id})")

    teams = raw.get("teams") or []
    winner_team: Optional[int] = None
    participants: list[Participant] = []

    for team in teams:
        team_id = team.get("teamId")
        if team.get("isWinningTeam"):
            winner_team = int(team_id)
        for player in team.get("players") or []:
            puuid = player.get("puuid")
            if not puuid:
                raise NormalizeError(
                    f"puuid eksik (gameId={game_id}, oyuncu={player.get('summonerName')!r}) — "
                    f"contract puuid zorunlu tutar, maç gönderilemez"
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
                    position=normalize_position(
                        player.get("selectedPosition") or player.get("position")
                    ),
                    champion=champion or None,
                    stats=_extract_stats(player.get("stats") or {}),
                )
            )

    if winner_team not in (100, 200):
        raise NormalizeError(f"Kazanan takım belirlenemedi (gameId={game_id})")

    return MatchPayload(
        source_game_id=str(game_id),
        played_at=to_utc_z(captured_at),
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
        raise NormalizeError("Match history kaydında gameId yok")

    duration_raw = raw.get("gameDuration")
    if duration_raw is None:
        raise NormalizeError(f"Match history kaydında gameDuration yok (gameId={game_id})")
    duration_s = _duration_seconds(duration_raw)

    winner_team = _mh_winner_team(raw)
    if winner_team is None:
        raise NormalizeError(f"Kazanan takım belirlenemedi (gameId={game_id})")

    identities: dict[int, dict[str, Any]] = {}
    for identity in raw.get("participantIdentities") or []:
        identities[int(identity.get("participantId", -1))] = identity.get("player") or {}

    participants: list[Participant] = []
    for p in raw.get("participants") or []:
        player = identities.get(int(p.get("participantId", -1)), {})
        puuid = player.get("puuid") or p.get("puuid")
        if not puuid:
            raise NormalizeError(
                f"puuid eksik (gameId={game_id}, participantId={p.get('participantId')}) — "
                f"contract puuid zorunlu tutar, maç gönderilemez"
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
                # timeline.lane custom'larda Riot'un tahminidir, güvenilmez → yalnızca
                # açık position alanı varsa kullan, yoksa null (tahmin etme)
                position=normalize_position(p.get("selectedPosition") or p.get("position")),
                champion=champion,
                stats=_extract_stats(p.get("stats") or {}),
            )
        )

    created = game_creation_datetime(raw)
    if created is None:
        raise NormalizeError(f"Maç zamanı belirlenemedi (gameId={game_id})")
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
