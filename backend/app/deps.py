"""Ortak FastAPI dependency'leri: DB bağlantısı, X-API-Key ve X-Admin-Key doğrulaması."""
from __future__ import annotations

import math
import secrets
import sqlite3
import threading
import time
from collections import deque
from typing import Iterator, Optional

from fastapi import Depends, Header, HTTPException, Request

from .config import Settings, get_settings
from .db import connect

# ── Admin hız sınırı (api_contract "Hız sınırı", fix-3) ──────────────────
# Amaç: `GET /admin/ping` sınırsız bir şifre oracle'ı olmasın. İki katman:
#   1) her BAŞARISIZ doğrulamada sabit gecikme (sızıntısız; anahtara/uzunluğa
#      bağlı değil, bu yüzden zamanlama bilgisi vermez),
#   2) IP başına kayan pencerede N denemeden sonra 429 + Retry-After.
# Sayaç SÜREÇ BELLEĞİNDEDİR (tek replica; kalıcılık/paylaşım contract'ta
# gerekmiyor). Sabitler modül seviyesindedir ve fonksiyon her çağrıda global'i
# okur — testler monkeypatch ile gecikmeyi/pencereyi kısaltabilsin diye.
ADMIN_FAIL_DELAY_S = 0.25
ADMIN_FAIL_WINDOW_S = 60.0
ADMIN_FAIL_LIMIT = 10

# istemci IP'si → başarısız deneme zaman damgaları (time.monotonic).
_admin_failures: dict[str, deque[float]] = {}
_admin_failures_lock = threading.Lock()


def reset_admin_rate_limit() -> None:
    """Tüm hız sınırı sayaçlarını sıfırlar (testler; süreç içi bakım)."""
    with _admin_failures_lock:
        _admin_failures.clear()


def _client_ip(request: Optional[Request]) -> str:
    """İstemci IP'si; ASLA header'dan (X-Forwarded-For) okunmaz — sahte IP ile
    sayaç seyreltilmesin diye yalnız gerçek soket adresi kullanılır."""
    if request is None or request.client is None:
        return "unknown"
    return request.client.host


def _prune(hits: deque[float], now: float) -> None:
    """Kayan pencerenin dışına düşen denemeleri atar."""
    while hits and now - hits[0] >= ADMIN_FAIL_WINDOW_S:
        hits.popleft()


def _rate_limited_retry_after(ip: str) -> Optional[int]:
    """Pencere dolduysa `Retry-After` (saniye, ≥1); dolmadıysa None."""
    now = time.monotonic()
    with _admin_failures_lock:
        hits = _admin_failures.get(ip)
        if hits is None:
            return None
        _prune(hits, now)
        if len(hits) < ADMIN_FAIL_LIMIT:
            return None
        # En eski deneme pencereden düştüğünde yeni deneme hakkı doğar.
        wait = ADMIN_FAIL_WINDOW_S - (now - hits[0])
    return max(1, math.ceil(wait))


def _record_admin_failure(ip: str) -> None:
    now = time.monotonic()
    with _admin_failures_lock:
        hits = _admin_failures.setdefault(ip, deque())
        _prune(hits, now)
        hits.append(now)


def _clear_admin_failures(ip: str) -> None:
    with _admin_failures_lock:
        _admin_failures.pop(ip, None)


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
    request: Request,
    x_admin_key: Optional[str] = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """İdari uçların EK katmanı (api_contract "Admin anahtarı", fix-2/fix-3).

    Global `X-API-Key` zorunluluğunun YERİNE geçmez, üstüne biner: bu
    dependency'yi taşıyan uç hem API anahtarını hem admin anahtarını ister.
    Korunan uçların tam listesi contract'tadır; `PUT /matches/{id}/positions`
    ve `PUT /matches/{id}/items` bilinçli olarak KAPSAM DIŞIDIR (collector
    backfill'leri arkadaşların PC'sinden çağırır).

    Sıra: yapılandırma hataları (503) → hız sınırı (429) → doğrulama (403).
    Yapılandırma hatası sayaca YAZILMAZ; sorun istemcinin denemesinde değil.
    """
    if not settings.admin_key:
        # 503 — 403 DEĞİL, çünkü sorun istemcinin gönderdiği değerde değil
        # sunucu yapılandırmasındadır.
        raise HTTPException(
            status_code=503,
            detail=(
                "Yönetim anahtarı sunucuda yapılandırılmamış (ADMIN_KEY); "
                "idari uçlar kapalı."
            ),
        )
    if not settings.admin_key.isascii():
        # api_contract "ADMIN_KEY yalnız ASCII olabilir" (fix-3): HTTP
        # header'ları latin-1 ile taşınır ve tarayıcı fetch'i kod birimi > 255
        # olan karakterde TypeError atar — ASCII olmayan anahtar DOĞRU girilse
        # bile doğrulanamaz ve panel sessizce kilitli kalırdı. Uygulama
        # başlamaya devam eder; kapanan yalnız idari yüzeydir. Mesaj teşhis
        # edicidir: yapılandıran sorunu okuyup düzeltebilmelidir.
        raise HTTPException(
            status_code=503,
            detail=(
                "Yönetim anahtarı (ADMIN_KEY) ASCII olmayan karakter içeriyor "
                "(ör. ş, ğ, ı). HTTP header'ları latin-1 ile taşındığı için "
                "böyle bir anahtar doğru girilse bile doğrulanamaz. ADMIN_KEY "
                "yalnız ASCII karakterlerden oluşmalıdır; idari uçlar bu "
                "düzeltilene kadar kapalı."
            ),
        )

    ip = _client_ip(request)
    retry_after = _rate_limited_retry_after(ip)
    if retry_after is not None:
        # 429, anahtarı HİÇ karşılaştırmaz (oracle değildir) ve sayaca yeni
        # deneme eklemez — pencere doğal olarak boşalır. Gecikme uygulanmaz:
        # sınırın kendisi zaten kaba kuvveti yavaşlatıyor.
        raise HTTPException(
            status_code=429,
            detail=(
                "Çok fazla başarısız yönetim anahtarı denemesi; "
                f"{retry_after} saniye sonra tekrar deneyin."
            ),
            headers={"Retry-After": str(retry_after)},
        )

    # Sabit zamanlı karşılaştırma: anahtar uzunluğu/öneki zamanlamadan sızmasın.
    # Byte'a çevrilir çünkü compare_digest str üzerinde YALNIZ ASCII kabul eder:
    # sunucudaki anahtarın ASCII olduğu yukarıda garanti edilir ama GELEN header
    # latin-1 çözüldüğü için ASCII dışı karakter taşıyabilir (o durumda str
    # karşılaştırması TypeError atardı).
    if x_admin_key is None or not secrets.compare_digest(
        x_admin_key.encode("utf-8"), settings.admin_key.encode("utf-8")
    ):
        _record_admin_failure(ip)
        # Sabit gecikme: sync dependency threadpool'da koştuğu için event
        # loop'u bloklamaz.
        time.sleep(ADMIN_FAIL_DELAY_S)
        raise HTTPException(
            status_code=403, detail="Yönetim anahtarı eksik veya hatalı."
        )
    # Başarılı doğrulama sayacı SIFIRLAR (api_contract): panel şifresini
    # yanlış yazıp sonra doğru giren kullanıcı kilitli kalmaz.
    _clear_admin_failures(ip)
