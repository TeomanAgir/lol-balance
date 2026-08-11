"""Oyuncu endpoint'leri + leaderboard (api_contract §2, §5)."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from rating import Engine

from ..config import Settings, get_settings
from ..deps import get_db
from ..schemas import PlayerCreate, PlayerOut, PlayerPatch, RatingOut
from ..services.ratings import current_ratings, is_blend, perf_averages

router = APIRouter()


def _player_list(
    conn: sqlite3.Connection, engine_version: str
) -> list[PlayerOut]:
    engine = Engine(version=engine_version)
    default = engine.default_rating()
    ratings = current_ratings(conn, engine_version)
    blend = is_blend(engine)
    p_avgs = perf_averages(conn, engine_version) if blend else {}
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
        if blend:
            # Harman: score efektif rating'tir; maçsız oyuncuda P_avg=1.0
            # (nötr) kabul edilir (rating_contract "Harman Engine" §4).
            p_avg = p_avgs.get(row["id"], 1.0)
            score = engine.effective(r.mu, r.sigma, p_avg).score
        else:
            p_avg = None
            score = r.ordinal
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
