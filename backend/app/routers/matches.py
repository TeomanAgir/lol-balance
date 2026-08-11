"""Maç listesi ve void işlemi (api_contract §3)."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from ..config import Settings, get_settings
from ..deps import get_db
from ..services.ratings import replay

router = APIRouter()


@router.get("/matches")
def list_matches(
    limit: int = Query(default=20, ge=1, le=200),
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    matches = conn.execute(
        "SELECT id, source_game_id, played_at, duration_s, winner_team, status "
        "FROM matches ORDER BY played_at DESC, id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    out = []
    for m in matches:
        participants = conn.execute(
            "SELECT mp.player_id, p.display_name, mp.team, mp.position, mp.champion,"
            " mp.kills, mp.deaths, mp.assists, mp.gold, mp.cs,"
            " mp.damage_to_champs, mp.vision_score,"
            " rh.mu_before, rh.sigma_before, rh.mu_after, rh.sigma_after "
            "FROM match_participants mp "
            "JOIN players p ON p.id = mp.player_id "
            "LEFT JOIN rating_history rh ON rh.match_id = mp.match_id"
            " AND rh.player_id = mp.player_id AND rh.engine_version = ? "
            "WHERE mp.match_id = ? ORDER BY mp.team, mp.id",
            (settings.engine_version, m["id"]),
        ).fetchall()
        out.append(
            {
                **dict(m),
                "participants": [
                    {
                        "player_id": row["player_id"],
                        "display_name": row["display_name"],
                        "team": row["team"],
                        "position": row["position"],
                        "champion": row["champion"],
                        "stats": {
                            "kills": row["kills"],
                            "deaths": row["deaths"],
                            "assists": row["assists"],
                            "gold": row["gold"],
                            "cs": row["cs"],
                            "damage_to_champs": row["damage_to_champs"],
                            "vision_score": row["vision_score"],
                        },
                        "rating_change": (
                            {
                                "mu_before": row["mu_before"],
                                "sigma_before": row["sigma_before"],
                                "mu_after": row["mu_after"],
                                "sigma_after": row["sigma_after"],
                            }
                            if row["mu_after"] is not None
                            else None
                        ),
                    }
                    for row in participants
                ],
            }
        )
    return out


@router.post("/matches/{match_id}/void")
def void_match(
    match_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    row = conn.execute(
        "SELECT id, status FROM matches WHERE id = ?", (match_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, detail=f"Maç bulunamadı: {match_id}.")
    with conn:
        conn.execute(
            "UPDATE matches SET status = 'void' WHERE id = ?", (match_id,)
        )
    # Void, geçmişi değiştirir → otomatik replay (api_contract §5).
    matches_replayed = replay(conn, settings.engine_version)
    return {
        "match_id": match_id,
        "status": "void",
        "matches_replayed": matches_replayed,
        "engine_version": settings.engine_version,
    }
