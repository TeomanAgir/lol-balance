"""Collector sağlığı uçları (api_contract §6 "Collector sağlığı (GÖREV 13)").

Salt izleme: rating'e etkisi yoktur, `ingest_events` ve maç verisi değişmez.
Diğer uçlar gibi `X-API-Key` ister (main.py'de dependency olarak eklenir).
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from ..deps import get_db
from ..schemas import CollectorHealthOut, HeartbeatIn, HeartbeatResponse
from ..services.health import list_collectors, record_heartbeat, require_client_id

router = APIRouter()


@router.post("/health/heartbeat")
def post_heartbeat(
    body: HeartbeatIn,
    conn: sqlite3.Connection = Depends(get_db),
) -> HeartbeatResponse:
    # last_seen gövdeden ALINMAZ; sunucu saatiyle atanır (api_contract §6).
    client_id = require_client_id(body.client_id)
    record_heartbeat(conn, client_id, body.version, body.outbox_pending)
    return HeartbeatResponse(ok=True)


@router.get("/health/collectors")
def get_collectors(
    conn: sqlite3.Connection = Depends(get_db),
) -> list[CollectorHealthOut]:
    return [CollectorHealthOut(**row) for row in list_collectors(conn)]
