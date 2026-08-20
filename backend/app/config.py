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
    # İdari uçların İKİNCİ anahtarı (api_contract "Admin anahtarı", fix-2).
    # None = yapılandırılmamış → o uçlar 503 döner (API_KEY'in aksine
    # yokluğu uygulamayı başlatmaz, yalnız idari yüzeyi kapatır).
    # Değer YALNIZ ortamdan gelir; repo public olduğu için hiçbir dosyada
    # varsayılan/örnek gerçek değer bulunmaz.
    admin_key: str | None = None


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
        engine_version=os.environ.get(
            "ENGINE_VERSION", "openskill-pl-blend30-s2-v1"
        ),
        webui_dir=os.environ.get("WEBUI_DIR", str(BACKEND_DIR.parent / "webui")),
        # Boş string de "yapılandırılmamış" sayılır (k8s secret'ta anahtar
        # tanımlı ama değeri boşsa idari uçlar herkese açılmasın).
        admin_key=os.environ.get("ADMIN_KEY", "").strip() or None,
    )
