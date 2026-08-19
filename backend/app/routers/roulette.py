"""Rulet oturumu endpoint'leri (api_contract §4.5, GÖREV 23).

Maç tarafındaki uçlar (`roulette` alanı, unlink) matches router'ındadır;
otomatik eşleşme ingest servisindedir. İş kuralları services/roulette'ta.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from ..deps import get_db
from ..schemas import (
    RouletteClearResponse,
    RouletteCreate,
    RouletteCreateResponse,
    RouletteCurrentResponse,
)
from ..services.roulette import (
    clear_unlinked_sessions,
    create_session,
    current_session,
    validate_assignments,
)

router = APIRouter()


@router.post("/roulette", status_code=201)
def create_roulette_session(
    body: RouletteCreate,
    conn: sqlite3.Connection = Depends(get_db),
) -> RouletteCreateResponse:
    """Yeni rulet oturumu açar (tek açık oturum değişmezi: önceki `open`
    oturumların TÜMÜ `cancelled` olur). Doğrulama contract §4.5'tedir."""
    assignments = validate_assignments(conn, body.assignments)
    session_id, created_at = create_session(conn, assignments)
    return RouletteCreateResponse(session_id=session_id, created_at=created_at)


@router.get("/roulette/current")
def get_current_session(
    conn: sqlite3.Connection = Depends(get_db),
) -> RouletteCurrentResponse:
    """Açık oturum ya da `{"session": null}` (api_contract §4.5)."""
    return RouletteCurrentResponse(session=current_session(conn))


@router.post("/roulette/clear")
def clear_roulette_sessions(
    conn: sqlite3.Connection = Depends(get_db),
) -> RouletteClearResponse:
    """`match_id IS NULL` (open+cancelled) oturumları siler; `linked`
    korunur, rating'e/replay'e etkisi yok (api_contract §4.5, Teoman 2026-08-19)."""
    return RouletteClearResponse(deleted=clear_unlinked_sessions(conn))
