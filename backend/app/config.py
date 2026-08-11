"""Uygulama ayarları — .env / ortam değişkenlerinden okunur."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    api_key: str
    db_path: str
    engine_version: str
    webui_dir: str


@lru_cache
def get_settings() -> Settings:
    load_dotenv(BACKEND_DIR / ".env")
    api_key = os.environ.get("API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "API_KEY tanımlı değil. backend/.env dosyasına API_KEY=<secret> ekleyin "
            "(bkz. .env.example)."
        )
    return Settings(
        api_key=api_key,
        db_path=os.environ.get("DB_PATH", str(BACKEND_DIR / "data" / "lol_balance.db")),
        engine_version=os.environ.get("ENGINE_VERSION", "openskill-pl-v1"),
        webui_dir=os.environ.get("WEBUI_DIR", str(BACKEND_DIR.parent / "webui")),
    )
