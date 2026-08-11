"""POST /balance ve POST /balance/nemesis — rol atamalı brute force dengeleme
(api_contract §4 + rating_contract "Rol Rating Evreni → Dengeleme").

Ayrım/atama üretimi ve kazanma olasılığı rating paketinden gelir; burada
yalnızca harman uygulaması, oyuncu id eşlemesi ve contract'taki quality
formülü (1 - 2*|p - 0.5| = 1 - 2*imbalance) vardır. İki endpoint doğrulama,
rating kurulumu ve yanıt üretimini ORTAK yardımcılardan alır; fark yalnızca
çağrılan balancer fonksiyonu (serbest / kısıtlı) ve ek `nemesis` alanıdır.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from rating import (
    ROLES,
    Engine,
    Rating,
    RoleBalanceSuggestion,
    balance_roles,
    balance_roles_constrained,
)

from ..config import Settings, get_settings
from ..deps import get_db
from ..schemas import (
    BalanceRequest,
    BalanceResponse,
    BalanceSuggestionOut,
    NemesisBalanceResponse,
    NemesisMatchOut,
    TeamSlotOut,
)
from ..services.nemesis import nemesis_pairs
from ..services.ratings import is_blend
from ..services.role_ratings import current_role_ratings, role_perf_averages

router = APIRouter()


def _validated_ids(body: BalanceRequest, conn: sqlite3.Connection) -> list[int]:
    """Tam 10 farklı ve BİLİNEN oyuncu id'si; aksi 422 (Türkçe detail)."""
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
    return ids


def _ratings_by_role(
    conn: sqlite3.Connection, engine_version: str, ids: list[int]
) -> list[dict[str, Rating]]:
    """`ids` sırasını koruyan {rol: Rating} listesi (rating paketinin girdisi).

    Harman version'da rating paketine mu_eff_role geçilir (rating paketi
    harmanı bilmez; mevcut desenle tutarlı). Hiç oynanmamış rol: default
    prior + P_avg=1.0 → mu_eff = 25, score 0 (nötr).
    """
    engine = Engine(version=engine_version)
    default = engine.default_rating()
    known = current_role_ratings(conn, engine_version)
    blend = is_blend(engine)
    role_p_avgs = role_perf_averages(conn, engine_version) if blend else {}

    out: list[dict[str, Rating]] = []
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
        out.append(by_role)
    return out


def _suggestions_out(
    ids: list[int], suggestions: list[RoleBalanceSuggestion]
) -> list[BalanceSuggestionOut]:
    """Index bazlı öneriler → contract'ın (player_id, position) şekli.

    Balancer zaten (imbalance, team100) artan sıralar → quality azalan.
    """
    return [
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
        for s in suggestions
    ]


@router.post("/balance")
def balance(
    body: BalanceRequest,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> BalanceResponse:
    ids = _validated_ids(body, conn)
    ratings_by_role = _ratings_by_role(conn, settings.engine_version, ids)
    return BalanceResponse(
        engine_version=settings.engine_version,
        suggestions=_suggestions_out(
            ids, balance_roles(ratings_by_role, body.top_n)
        ),
    )


@router.post("/balance/nemesis")
def balance_nemesis(
    body: BalanceRequest,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> NemesisBalanceResponse:
    """Nemesis maçı (api_contract §4 "Nemesis maçı", GÖREV 3).

    Aktif çift (weekly > all_time) KARŞI takımlara ayrılır ve İKİSİ DE nemesis
    rolüne sabitlenir; kalan 8 oyuncu normal rol-bazlı optimizasyonla dağıtılır.
    Sıralama/quality tanımı /balance ile aynıdır.
    """
    ids = _validated_ids(body, conn)

    # Pencere gerçek UTC şimdiye göre kurulur; `now` enjeksiyonu yalnız servis
    # katmanındadır (highlights ile aynı desen).
    pairs = nemesis_pairs(conn)
    source = pairs["active"]
    if source is None:
        raise HTTPException(
            409,
            detail=(
                "Aktif nemesis çifti yok — aynı koridorda en az 3 kez "
                "karşılaşmış bir rakip çifti gerekiyor."
            ),
        )

    pair = pairs[source]
    pair_ids = [p["player_id"] for p in pair["players"]]
    outside = [pid for pid in pair_ids if pid not in ids]
    if outside:
        raise HTTPException(
            422,
            detail=(
                "Nemesis çiftinin üyeleri seçilen 10 oyuncu arasında değil: "
                f"{outside}."
            ),
        )

    ratings_by_role = _ratings_by_role(conn, settings.engine_version, ids)
    # DİKKAT: `separate` player id DEĞİL, `ids` listesindeki INDEX'lerdir.
    separate = (ids.index(pair_ids[0]), ids.index(pair_ids[1]))
    suggestions = balance_roles_constrained(
        ratings_by_role,
        body.top_n,
        separate=separate,
        fixed_role=pair["role"],
    )
    return NemesisBalanceResponse(
        engine_version=settings.engine_version,
        suggestions=_suggestions_out(ids, suggestions),
        nemesis=NemesisMatchOut(
            source=source, role=pair["role"], player_ids=pair_ids
        ),
    )
