"""POST /ingest/match — bkz. docs/ingest_contract.md."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ..config import Settings, get_settings
from ..deps import get_db
from ..schemas import IngestMatch
from ..services.ingest import ingest_match

router = APIRouter()


@router.post("/ingest/match")
async def post_ingest_match(
    body: IngestMatch,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    # Ham gövde ingest_events'e AYNEN yazılır (db_schema ilke 1).
    raw_payload = (await request.body()).decode("utf-8")
    match_id, duplicate = ingest_match(
        conn, body, raw_payload, settings.engine_version
    )
    return JSONResponse(
        status_code=200 if duplicate else 201,
        content={"match_id": match_id, "duplicate": duplicate},
    )
