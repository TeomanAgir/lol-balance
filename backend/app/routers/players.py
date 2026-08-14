"""Oyuncu endpoint'leri + leaderboard (api_contract §2, §5)."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from rating import ROLES, Engine, Rating

from ..config import Settings, get_settings
from ..deps import get_db
from ..schemas import (
    PlayerBadgesOut,
    PlayerCreate,
    PlayerOut,
    PlayerPatch,
    PlayerStatsOut,
    RatingHistoryOut,
    RatingOut,
    RoleRatingOut,
)
from ..services.badges import player_badges
from ..services.player_stats import player_stats
from ..services.rating_history import rating_history
from ..services.ratings import (
    current_ratings,
    effective_score,
    is_blend,
    perf_averages,
)
from ..services.role_ratings import (
    current_role_ratings,
    role_match_counts,
    role_perf_averages,
)

router = APIRouter()


def _role_ratings_out(
    engine: Engine,
    blend: bool,
    default: Rating,
    player_id: int,
    role_ratings: dict[tuple[int, str], Rating],
    role_p_avgs: dict[tuple[int, str], float],
    role_counts: dict[tuple[int, str], int],
) -> dict[str, RoleRatingOut]:
    """5 rolün tamamı için rol rating nesnesi (api_contract §2).

    Hiç oynanmamış rol default prior + P_avg=1.0 alır → score 0 (nötr).
    """
    out: dict[str, RoleRatingOut] = {}
    for role in ROLES:
        key = (player_id, role)
        r = role_ratings.get(key, default)
        p_avg = role_p_avgs.get(key, 1.0) if blend else None
        score = effective_score(engine, blend, r, p_avg)
        out[role] = RoleRatingOut(
            mu=r.mu,
            sigma=r.sigma,
            perf_avg=p_avg,
            score=score,
            matches=role_counts.get(key, 0),
        )
    return out


def _player_list(
    conn: sqlite3.Connection, engine_version: str
) -> list[PlayerOut]:
    engine = Engine(version=engine_version)
    default = engine.default_rating()
    ratings = current_ratings(conn, engine_version)
    blend = is_blend(engine)
    p_avgs = perf_averages(conn, engine_version) if blend else {}
    role_ratings = current_role_ratings(conn, engine_version)
    role_p_avgs = role_perf_averages(conn, engine_version) if blend else {}
    role_counts = role_match_counts(conn, engine_version)
    rows = conn.execute(
        "SELECT p.id, p.display_name, p.riot_id, p.puuid,"
        " (SELECT COUNT(*) FROM match_participants mp"
        "  JOIN matches m ON m.id = mp.match_id"
        "  WHERE mp.player_id = p.id AND m.status = 'valid') AS matches_played "
        "FROM players p ORDER BY p.id"
    ).fetchall()
    out = []
    for row in rows:
        r = ratings.get(row["id"], default)
        # Harman: score efektif rating'tir; maçsız oyuncuda P_avg=1.0 (nötr)
        # kabul edilir (rating_contract "Harman Engine" §4).
        p_avg = p_avgs.get(row["id"], 1.0) if blend else None
        score = effective_score(engine, blend, r, p_avg)
        out.append(
            PlayerOut(
                id=row["id"],
                display_name=row["display_name"],
                riot_id=row["riot_id"],
                puuid=row["puuid"],
                matches_played=row["matches_played"],
                rating=RatingOut(
                    mu=r.mu,
                    sigma=r.sigma,
                    ordinal=r.ordinal,
                    perf_avg=p_avg,
                    score=score,
                ),
                role_ratings=_role_ratings_out(
                    engine,
                    blend,
                    default,
                    row["id"],
                    role_ratings,
                    role_p_avgs,
                    role_counts,
                ),
            )
        )
    return out


@router.get("/players")
def list_players(
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[PlayerOut]:
    return _player_list(conn, settings.engine_version)


@router.get("/leaderboard")
def leaderboard(
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[PlayerOut]:
    # api_contract §5: score'a göre sıralanır (harman olmayan version'da
    # score = ordinal olduğundan eski davranışla aynıdır).
    players = _player_list(conn, settings.engine_version)
    players.sort(key=lambda p: p.rating.score, reverse=True)
    return players


@router.get("/players/{player_id}/stats")
def player_profile_stats(
    player_id: int,
    conn: sqlite3.Connection = Depends(get_db),
) -> PlayerStatsOut:
    """Oyuncu profil istatistikleri (api_contract §2 "Oyuncu profili").

    Yalnız GÖSTERİM: rating'e girmez, hiçbir tablo yazılmaz.
    """
    stats = player_stats(conn, player_id)
    if stats is None:
        raise HTTPException(404, detail=f"Oyuncu bulunamadı: {player_id}.")
    return stats


@router.get("/players/{player_id}/rating-history")
def player_rating_history(
    player_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RatingHistoryOut:
    """Oyuncunun rating eğrisi (api_contract §2 "Rating tarihçesi", GÖREV 10).

    Yalnız GÖSTERİM: rating'e girmez, hiçbir tablo yazılmaz. Hiç valid maçı
    olmayan oyuncuda `points: []`.
    """
    history = rating_history(conn, player_id, settings.engine_version)
    if history is None:
        raise HTTPException(404, detail=f"Oyuncu bulunamadı: {player_id}.")
    return history


@router.get("/players/{player_id}/badges")
def player_badge_list(
    player_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PlayerBadgesOut:
    """Oyuncunun rozetleri (api_contract §2 "Rozetler", GÖREV 11+12).

    Yalnız GÖSTERİM: rating'e girmez, hiçbir tablo yazılmaz — rozetler her
    istekte mevcut maç/rating satırlarından hesaplanır. Rozetsiz oyuncuda
    `badges: []`.
    """
    badges = player_badges(conn, player_id, settings.engine_version)
    if badges is None:
        raise HTTPException(404, detail=f"Oyuncu bulunamadı: {player_id}.")
    return badges


@router.post("/players", status_code=201)
def create_player(
    body: PlayerCreate,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    with conn:
        cur = conn.execute(
            "INSERT INTO players (riot_id, display_name) VALUES (?, ?)",
            (body.riot_id, body.display_name),
        )
    return {"id": cur.lastrowid}


@router.patch("/players/{player_id}")
def patch_player(
    player_id: int,
    body: PlayerPatch,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    row = conn.execute(
        "SELECT id FROM players WHERE id = ?", (player_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, detail=f"Oyuncu bulunamadı: {player_id}.")
    if body.display_name is not None:
        with conn:
            conn.execute(
                "UPDATE players SET display_name = ? WHERE id = ?",
                (body.display_name, player_id),
            )
    updated = conn.execute(
        "SELECT id, display_name, riot_id FROM players WHERE id = ?", (player_id,)
    ).fetchone()
    return dict(updated)
