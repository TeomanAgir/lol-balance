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
    # X-Forwarded-For'una güvenilecek proxy adresleri (GÖREV 30b). Uygulama
    # içi ProxyHeadersMiddleware'e verilir (main.create_app); admin hız
    # sınırının "istemci IP'si başına" sayacı (api_contract "Hız sınırı")
    # ancak böyle gerçek istemciyi görür. "*" = her bağlanana güven; boş
    # liste = header tamamen yok sayılır (soket adresi kullanılır).
    forwarded_allow_ips: tuple[str, ...] = ("*",)


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
        engine_version=os.environ.get("ENGINE_VERSION", "openskill-pl-blend25-v1"),
        webui_dir=os.environ.get("WEBUI_DIR", str(BACKEND_DIR.parent / "webui")),
        # Boş string de "yapılandırılmamış" sayılır (k8s secret'ta anahtar
        # tanımlı ama değeri boşsa idari uçlar herkese açılmasın).
        admin_key=os.environ.get("ADMIN_KEY", "").strip() or None,
        # Varsayılan "*": prod pod'u yalnız ClusterIP Service üzerinden
        # nginx ingress'ten erişilebilir, yani bağlanan her zaman ingress'tir.
        # UYARI: pod'a/porta doğrudan erişilebilen bir dağıtımda bunu proxy
        # adresine DARALTIN — yoksa istemci sahte X-Forwarded-For ile hız
        # sınırı sayacını seyreltebilir. Değişken TANIMLI ama boşsa hiçbir
        # proxy'ye güvenilmez.
        forwarded_allow_ips=_parse_forwarded_allow_ips(
            os.environ.get("FORWARDED_ALLOW_IPS", "*")
        ),
    )


def _parse_forwarded_allow_ips(raw: str) -> tuple[str, ...]:
    """Virgülle ayrılmış listeyi (uvicorn `--forwarded-allow-ips` biçimi) ayrıştırır."""
    return tuple(item.strip() for item in raw.split(",") if item.strip())
