"""POST /balance — rol atamalı 126 ayrımın brute force değerlendirmesi
(api_contract §4 + rating_contract "Rol Rating Evreni → Dengeleme").

Ayrım/atama üretimi ve kazanma olasılığı rating paketinden gelir; burada
yalnızca harman uygulaması, oyuncu id eşlemesi ve contract'taki quality
formülü (1 - 2*|p - 0.5| = 1 - 2*imbalance) vardır.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from rating import ROLES, Engine, Rating, balance_roles

from ..config import Settings, get_settings
from ..deps import get_db
from ..schemas import (
    BalanceRequest,
    BalanceResponse,
    BalanceSuggestionOut,
    TeamSlotOut,
)
from ..services.ratings import is_blend
from ..services.role_ratings import current_role_ratings, role_perf_averages

router = APIRouter()


@router.post("/balance")
def balance(
    body: BalanceRequest,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> BalanceResponse:
    ids = body.player_ids
    if len(ids) != 10 or len(set(ids)) != 10:
        raise HTTPException(
            422, detail="player_ids tam 10 farklı oyuncu id'si içermeli."
        )
    if body.top_n < 1:
        raise HTTPException(422, detail="top_n en az 1 olmalı.")

    placeholders = ",".join("?" * len(ids))
    found = {
        row["id"]
        for row in conn.execute(
            f"SELECT id FROM players WHERE id IN ({placeholders})", ids
        )
    }
    missing = [i for i in ids if i not in found]
    if missing:
        raise HTTPException(
            422, detail=f"Bilinmeyen oyuncu id'leri: {missing}."
        )

    engine = Engine(version=settings.engine_version)
    default = engine.default_rating()
    known = current_role_ratings(conn, settings.engine_version)
    blend = is_blend(engine)
    # Harman version'da rating paketine mu_eff_role geçilir (rating paketi
    # harmanı bilmez; mevcut desenle tutarlı). Hiç oynanmamış rol: default
    # prior + P_avg=1.0 → mu_eff = 25, score 0 (nötr).
    role_p_avgs = role_perf_averages(conn, settings.engine_version) if blend else {}

    ratings_by_role: list[dict[str, Rating]] = []
    for pid in ids:
        by_role: dict[str, Rating] = {}
        for role in ROLES:
            key = (pid, role)
            r = known.get(key, default)
            if blend:
                mu_eff = engine.effective(
                    r.mu, r.sigma, role_p_avgs.get(key, 1.0)
                ).mu_eff
                by_role[role] = Rating(mu=mu_eff, sigma=r.sigma)
            else:
                by_role[role] = r
        ratings_by_role.append(by_role)

    suggestions = [
        BalanceSuggestionOut(
            team_100=[
                TeamSlotOut(player_id=ids[i], position=pos)
                for i, pos in zip(s.team100, s.positions100)
            ],
            team_200=[
                TeamSlotOut(player_id=ids[i], position=pos)
                for i, pos in zip(s.team200, s.positions200)
            ],
            p_win_team_100=s.p_team100,
            quality=1.0 - 2.0 * s.imbalance,
        )
        # balance_roles zaten (imbalance, team100) artan sıralar → quality azalan.
        for s in balance_roles(ratings_by_role, body.top_n)
    ]
    return BalanceResponse(
        engine_version=settings.engine_version, suggestions=suggestions
    )
