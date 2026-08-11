"""POST /admin/replay (api_contract §5)."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from ..config import Settings, get_settings
from ..deps import get_db
from ..schemas import ReplayResponse
from ..services.ratings import replay
from ..services.role_ratings import replay_roles

router = APIRouter()


@router.post("/admin/replay")
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
