"""Oto-yetişme: canlı moda geçmeden önce koşan sınırlı backfill.

Neden (docs/ingest_contract.md "Oto-yetişme", CHANGE_REQUESTS 2026-08-13):
collector yalnız açıkken maç yakalar; kapalıyken oynanan custom'lar için
`--backfill` vardır ama exe'yi çift tıklayan kullanıcı onu bilmez. Bu yüzden
canlı mod LCU'ya HER bağlandığında (ilk bağlantı + yeniden bağlanmalar) canlı
döngüden ÖNCE son `CATCHUP_DAYS` günü tarar.

Tasarım notları:
- Tam tarama mantığı kopyalanmaz: `backfill.run_backfill` aynen `since` ile
  çağrılır (roster filtresi, remake atlama, kronolojik gönderim hep aynı).
- Aynı proseste tekrar tekrar bağlanmada yeniden koşabilir; idempotency
  (`source_game_id`) sayesinde zararsızdır, ekstra durum tutulmaz.
- Yetişme HİÇBİR koşulda canlı modu engellemez: her hata yutulur ve loglanır.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from .backfill import BackfillStats, run_backfill
from .config import Config
from .i18n import msg
from .lcu import LcuClient
from .sender import Sender

log = logging.getLogger("collector.catchup")


def catchup_since(days: int, today: Optional[date] = None) -> date:
    """Yetişme penceresinin başlangıcı — kaba gün hesabı yeterli (kesinlik gerekmez)."""
    return (today or date.today()) - timedelta(days=days)


def run_catchup(
    config: Config,
    lcu: LcuClient,
    sender: Sender,
    *,
    today: Optional[date] = None,
) -> Optional[BackfillStats]:
    """Sınırlı backfill koşar; kapalıysa ya da hata olursa None döner.

    Dönüş None olması canlı modun devam etmesini ENGELLEMEZ — çağıran taraf
    sonucu yalnızca raporlama için kullanır.
    """
    days = config.catchup_days
    if days <= 0:
        log.info("Auto-catchup disabled (CATCHUP_DAYS=%d)", days)
        return None

    since = catchup_since(days, today)
    log.info("Auto-catchup: scanning match history since %s (%d days)", since, days)
    print(msg("catchup.start", days=days, since=since.isoformat()))
    try:
        sender.flush_outbox()
        stats = run_backfill(config, lcu, sender, since=since)
    except Exception as exc:  # noqa: BLE001 — yetişme canlı modu asla engellemez
        log.warning("Auto-catchup failed, continuing to live mode: %s", exc, exc_info=True)
        print(msg("catchup.failed", error=exc))
        return None

    print(msg("catchup.done", scanned=stats.scanned, sent=stats.sent))
    if stats.errors:
        log.warning("Auto-catchup finished with %d errors", len(stats.errors))
    return stats
