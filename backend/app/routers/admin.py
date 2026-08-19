"""POST /admin/replay + GET /admin/ping (api_contract §5).

İkisi de `X-Admin-Key` ister (fix-2): giriş noktası web UI'daki Kontrol
Paneli'dir. Global `X-API-Key` zorunluluğu (main.py) ayrıca sürer.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Response

from ..config import Settings, get_settings
from ..deps import get_db, require_admin_key
from ..schemas import ReplayResponse
from ..services.ratings import replay
from ..services.role_ratings import replay_roles

router = APIRouter()


@router.get("/admin/ping", status_code=204, dependencies=[Depends(require_admin_key)])
def admin_ping() -> Response:
    """Admin anahtarı doğrulama ucu (api_contract §5): 204, YAN ETKİSİZ.

    Kontrol Paneli giriş şifresini bununla sınar; DB'ye hiç dokunmaz.
    """
    return Response(status_code=204)


@router.post("/admin/replay", dependencies=[Depends(require_admin_key)])
def admin_replay(
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ReplayResponse:
    # api_contract §5: HER İKİ evren yeniden kurulur (ana + rol).
    count = replay(conn, settings.engine_version)
    role_count = replay_roles(conn, settings.engine_version)
    return ReplayResponse(
        matches_replayed=count,
        role_matches_replayed=role_count,
        engine_version=settings.engine_version,
    )
