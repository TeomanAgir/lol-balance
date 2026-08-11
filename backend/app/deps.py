"""Ortak FastAPI dependency'leri: DB bağlantısı ve X-API-Key doğrulaması."""
from __future__ import annotations

import sqlite3
from typing import Iterator, Optional

from fastapi import Depends, Header, HTTPException

from .config import Settings, get_settings
from .db import connect


def get_db(settings: Settings = Depends(get_settings)) -> Iterator[sqlite3.Connection]:
    conn = connect(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def require_api_key(
    x_api_key: Optional[str] = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="API anahtarı eksik veya hatalı.")
