"""Haftanın enleri (api_contract §2 "Haftanın enleri (GÖREV 2)").

Salt-okur: rating'e girmez, hiçbir tablo yazılmaz.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from ..config import Settings, get_settings
from ..deps import get_db
from ..schemas import WeeklyHighlightsOut
from ..services.weekly import weekly_highlights

router = APIRouter()


@router.get("/highlights/weekly")
def weekly(
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> WeeklyHighlightsOut:
    # Pencere gerçek UTC şimdiye göre kurulur; `now` enjeksiyonu yalnız
    # servis katmanındadır (deterministik test için).
    return weekly_highlights(conn, settings.engine_version)
