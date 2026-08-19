"""Ortak FastAPI dependency'leri: DB bağlantısı, X-API-Key ve X-Admin-Key doğrulaması."""
from __future__ import annotations

import secrets
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


def require_admin_key(
    x_admin_key: Optional[str] = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """İdari uçların EK katmanı (api_contract "Admin anahtarı", fix-2).

    Global `X-API-Key` zorunluluğunun YERİNE geçmez, üstüne biner: bu
    dependency'yi taşıyan uç hem API anahtarını hem admin anahtarını ister.
    `ADMIN_KEY` yapılandırılmamışsa uç 503'tür (kapalı) — 403 DEĞİL, çünkü
    sorun istemcinin gönderdiği değerde değil sunucu yapılandırmasındadır.
    """
    if not settings.admin_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "Yönetim anahtarı sunucuda yapılandırılmamış (ADMIN_KEY); "
                "idari uçlar kapalı."
            ),
        )
    # Sabit zamanlı karşılaştırma: anahtar uzunluğu/öneki zamanlamadan sızmasın.
    # UTF-8'e kodlanır — compare_digest str üzerinde yalnız ASCII kabul eder,
    # anahtar Türkçe karakter taşıyabilir.
    if x_admin_key is None or not secrets.compare_digest(
        x_admin_key.encode("utf-8"), settings.admin_key.encode("utf-8")
    ):
        raise HTTPException(
            status_code=403, detail="Yönetim anahtarı eksik veya hatalı."
        )
