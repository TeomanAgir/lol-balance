"""Rozet kataloğu ucu (api_contract §2 "Rozet kataloğu ucu", GÖREV 24)."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from ..config import Settings, get_settings
from ..deps import get_db
from ..schemas import BadgeCatalogOut
from ..services.badges import badge_catalog

router = APIRouter()


@router.get("/badges")
def badge_catalog_list(
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> BadgeCatalogOut:
    """27 rozetlik katalog + `holders` nadirliği (api_contract §2).

    SALT-OKUR: DB'ye yazmaz, rating'e dokunmaz. Maliyet global'dir (tüm
    oyuncuların rozetleri toplanır) ama tek toplu geçişle hesaplanır
    (services/badges.compute_badges) ve per-player ucun SAF TOPLAMI olduğu için
    replay-deterministiktir.
    """
    return badge_catalog(conn, settings.engine_version)
