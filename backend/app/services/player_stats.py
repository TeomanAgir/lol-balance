"""Oyuncu profil istatistikleri (api_contract §2 "Oyuncu profili").

Tamamı GÖSTERİM istatistiğidir: rating'e hiçbir etkisi yoktur, hiçbir tablo
yazılmaz, şema değişmez — her şey mevcut `matches` / `match_participants` /
`players` satırlarından türetilir. Faz 2 pair-synergy rating modeli AYRIDIR ve
hâlâ kapsam dışıdır (CHANGE_REQUESTS: GÖREV 1, 2026-08-12).

Tüm metrikler yalnız `status='valid'` maçlar üzerinden hesaplanır; void maç
hiçbir metriğe girmez.
"""
from __future__ import annotations

import sqlite3
from fractions import Fraction

from rating import ROLES

# api_contract §2: sinerji için en az 2 ortak maç, en fazla 3 kayıt döner.
SYNERGY_MIN_MATCHES = 2
SYNERGY_LIMIT = 3

# Yuvarlama: contract örneğindeki değerler (kills_avg 5.2, ratio 4.06,
# winrate 0.6) 2 basamağa yuvarlanmış hâldedir; float gürültüsünü UI'a
# taşımamak için tüm oran/ortalamalar aynı hassasiyetle döner. Sıralama
# ve eşitlik kırılımları YUVARLANMAMIŞ değerlerle yapılır.
_PRECISION = 2


def _round(value: float) -> float:
    return round(value, _PRECISION)


def _winrate(wins: int, matches: int) -> float:
    return _round(wins / matches)


def _totals(rows: list[sqlite3.Row]) -> dict:
    """Valid maç sayısı + W/L; maçsız oyuncuda winrate null (api_contract §2)."""
    matches = len(rows)
    wins = sum(1 for r in rows if r["team"] == r["winner_team"])
    return {
        "matches": matches,
        "wins": wins,
        "losses": matches - wins,
        "winrate": _winrate(wins, matches) if matches else None,
    }


def _kda(rows: list[sqlite3.Row]) -> dict | None:
    """Yalnız kills/deaths/assists ÜÇÜ DE dolu maçlardan; hiç yoksa None.

    `ratio = (ΣK + ΣA) / max(1, ΣD)` (CHANGE_REQUESTS GÖREV 1 tanımı).
    """
    stat_rows = [
        r
        for r in rows
        if r["kills"] is not None
        and r["deaths"] is not None
        and r["assists"] is not None
    ]
    if not stat_rows:
        return None
    n = len(stat_rows)
    kills = sum(r["kills"] for r in stat_rows)
    deaths = sum(r["deaths"] for r in stat_rows)
    assists = sum(r["assists"] for r in stat_rows)
    return {
        "kills_avg": _round(kills / n),
        "deaths_avg": _round(deaths / n),
        "assists_avg": _round(assists / n),
        "ratio": _round((kills + assists) / max(1, deaths)),
    }


def _favorite_champion(rows: list[sqlite3.Row]) -> dict | None:
    """En çok oynanan şampiyon; eşitlikte ad alfabetik küçük olan.

    champion NULL olan satırlar hariçtir; hiç kalmazsa None.
    """
    counts: dict[str, list[int]] = {}  # champion -> [matches, wins]
    for r in rows:
        champion = r["champion"]
        if champion is None:
            continue
        entry = counts.setdefault(champion, [0, 0])
        entry[0] += 1
        if r["team"] == r["winner_team"]:
            entry[1] += 1
    if not counts:
        return None
    champion, (matches, wins) = min(
        counts.items(), key=lambda item: (-item[1][0], item[0])
    )
    return {
        "champion": champion,
        "matches": matches,
        "winrate": _winrate(wins, matches),
    }


def _favorite_role(rows: list[sqlite3.Row]) -> dict | None:
    """En çok oynanan rol; eşitlikte kanonik sıra (TOP<JUNGLE<MIDDLE<BOTTOM<UTILITY).

    position NULL olan satırlar hariçtir; hiç kalmazsa None.
    """
    counts: dict[str, int] = {}
    for r in rows:
        position = r["position"]
        if position is None:
            continue
        counts[position] = counts.get(position, 0) + 1
    if not counts:
        return None
    role, matches = min(
        counts.items(), key=lambda item: (-item[1], ROLES.index(item[0]))
    )
    return {"role": role, "matches": matches}


def _synergy(conn: sqlite3.Connection, player_id: int) -> list[dict]:
    """AYNI TAKIMDA ≥2 valid maç oynanmış takım arkadaşları (api_contract §2).

    Sıralama: winrate azalan → matches_together azalan → display_name
    alfabetik; ilk 3 kayıt. Winrate karşılaştırması Fraction ile tam yapılır
    (float yuvarlaması eşitlikleri bozmasın).
    """
    rows = conn.execute(
        "SELECT o.player_id AS player_id, p.display_name AS display_name,"
        " COUNT(*) AS matches_together,"
        " SUM(CASE WHEN o.team = m.winner_team THEN 1 ELSE 0 END) AS wins_together "
        "FROM match_participants me "
        "JOIN matches m ON m.id = me.match_id "
        "JOIN match_participants o ON o.match_id = me.match_id"
        "  AND o.team = me.team AND o.player_id <> me.player_id "
        "JOIN players p ON p.id = o.player_id "
        "WHERE me.player_id = ? AND m.status = 'valid' "
        "GROUP BY o.player_id, p.display_name "
        "HAVING COUNT(*) >= ? "
        "ORDER BY o.player_id",
        (player_id, SYNERGY_MIN_MATCHES),
    ).fetchall()
    ordered = sorted(
        rows,
        key=lambda r: (
            -Fraction(r["wins_together"], r["matches_together"]),
            -r["matches_together"],
            r["display_name"],
        ),
    )
    return [
        {
            "player_id": r["player_id"],
            "display_name": r["display_name"],
            "matches_together": r["matches_together"],
            "wins_together": r["wins_together"],
            "winrate": _winrate(r["wins_together"], r["matches_together"]),
        }
        for r in ordered[:SYNERGY_LIMIT]
    ]


def player_stats(conn: sqlite3.Connection, player_id: int) -> dict | None:
    """Oyuncu profil istatistikleri; oyuncu yoksa None (router 404 üretir)."""
    player = conn.execute(
        "SELECT id, display_name, riot_id FROM players WHERE id = ?", (player_id,)
    ).fetchone()
    if player is None:
        return None

    rows = conn.execute(
        "SELECT mp.team, mp.position, mp.champion,"
        " mp.kills, mp.deaths, mp.assists, m.winner_team "
        "FROM match_participants mp "
        "JOIN matches m ON m.id = mp.match_id "
        "WHERE mp.player_id = ? AND m.status = 'valid' "
        "ORDER BY mp.match_id, mp.id",
        (player_id,),
    ).fetchall()

    return {
        "player": {
            "id": player["id"],
            "display_name": player["display_name"],
            "riot_id": player["riot_id"],
        },
        "totals": _totals(rows),
        "kda": _kda(rows),
        "favorite_champion": _favorite_champion(rows),
        "favorite_role": _favorite_role(rows),
        "synergy": _synergy(conn, player_id),
    }
