"""GET /nemesis — nemesis çifti (api_contract §2 "Nemesis (GÖREV 3)").

Salt-okur: rating'e girmez, hiçbir tablo yazılmaz.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from ..deps import get_db
from ..schemas import NemesisOut
from ..services.nemesis import nemesis_pairs

router = APIRouter()


@router.get("/nemesis")
def nemesis(conn: sqlite3.Connection = Depends(get_db)) -> NemesisOut:
    # Haftalık pencere gerçek UTC şimdiye göre kurulur; `now` enjeksiyonu
    # yalnız servis katmanındadır (deterministik test için).
    return nemesis_pairs(conn)
