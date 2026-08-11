"""POST /balance — 126 ayrımın brute force değerlendirmesi (api_contract §4).

Ayrım üretimi ve kazanma olasılığı rating paketinden gelir; burada yalnızca
oyuncu id eşlemesi ve contract'taki quality formülü (1 - 2*|p - 0.5|) vardır.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from rating import Engine, Rating, enumerate_splits

from ..config import Settings, get_settings
from ..deps import get_db
from ..schemas import BalanceRequest, BalanceResponse, BalanceSuggestionOut
from ..services.ratings import current_ratings, is_blend, perf_averages

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
    known = current_ratings(conn, settings.engine_version)
    # 0 maçlı oyuncu default prior ile hesaba katılır (api_contract §4).
    ratings = [known.get(i, engine.default_rating()) for i in ids]
    if is_blend(engine):
        # Harman version'da öneriler efektif mu üzerinden hesaplanır
        # (rating_contract "Harman Engine" §5). Rating'i olmayan oyuncu:
        # default mu/sigma + P_avg=1.0 → mu_eff = 25 (nötr).
        p_avgs = perf_averages(conn, settings.engine_version)
        ratings = [
            Rating(
                mu=engine.effective(r.mu, r.sigma, p_avgs.get(i, 1.0)).mu_eff,
                sigma=r.sigma,
            )
            for i, r in zip(ids, ratings)
        ]

    suggestions = []
    for idx100, idx200 in enumerate_splits(10):
        p = engine.predict_win(
            [ratings[i] for i in idx100], [ratings[i] for i in idx200]
        )
        suggestions.append(
            BalanceSuggestionOut(
                team_100=[ids[i] for i in idx100],
                team_200=[ids[i] for i in idx200],
                p_win_team_100=p,
                quality=1.0 - 2.0 * abs(p - 0.5),
            )
        )
    suggestions.sort(key=lambda s: s.quality, reverse=True)
    return BalanceResponse(
        engine_version=settings.engine_version,
        suggestions=suggestions[: body.top_n],
    )
