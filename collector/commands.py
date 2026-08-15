"""CLI ve arayüzün PAYLAŞTIĞI üst seviye komutlar (GÖREV 16 Faz C).

Bu modül, daha önce `__main__.py` içinde gömülü olan iki akışı tek kaynağa taşır:

- `run_backfill_command` — lockfile oku → LCU'ya bağlan → `backfill.run_backfill`.
- `run_live_command`     — client'i bekle → bağlan → yetişme → canlı döngü → yeniden bağlan.

Böylece tkinter arayüzü (`gui.py`) canlı döngüyü/backfill'i KOPYALAMAZ, aynı
fonksiyonları çağırır. Fark yalnızca kesme (`stop`) ve durum bildirimi
(`on_status`, `on_match`) parametrelerindedir; CLI bunları vermez ve davranış
GÖREV 16 öncesiyle birebir aynıdır.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date
from typing import Callable, Optional

from .backfill import BackfillStats, run_backfill
from .catchup import run_catchup
from .config import Config
from .lcu import HttpLcuClient
from .live import LcuConnectionLost, LiveRunner
from .lockfile import LockfileNotFound, read_lockfile
from .sender import Sender

log = logging.getLogger("collector.commands")

LOCKFILE_WAIT_S = 10.0
RECONNECT_WAIT_S = 5.0

#: `on_status` ile bildirilen durum anahtarları (arayüz `gui.status.<anahtar>` ile çevirir).
STATUS_WAITING_CLIENT = "waiting_client"
STATUS_CONNECTED = "connected"
STATUS_CATCHUP = "catchup"
STATUS_LIVE = "live"
STATUS_RECONNECTING = "reconnecting"
STATUS_STOPPED = "stopped"

StatusCallback = Callable[[str], None]
MatchCallback = Callable[[str], None]


def _sleeper(stop: Optional[threading.Event]) -> Callable[[float], None]:
    """Kesilebilir uyku: `stop` verildiyse olay set edilir edilmez uyanır."""
    if stop is None:
        return time.sleep

    def sleep(seconds: float) -> None:
        stop.wait(seconds)

    return sleep


def run_backfill_command(
    config: Config,
    sender: Sender,
    *,
    since: Optional[date] = None,
) -> BackfillStats:
    """`--backfill` / arayüzdeki "Maçları Tara".

    `LockfileNotFound` YUKARI FIRLATILIR: hata mesajını (client kapalı mı,
    LOL_DIR doğru mu) çağıran taraf kendi ortamına uygun biçimde gösterir.
    """
    info = read_lockfile(config.lol_dir)
    lcu = HttpLcuClient(info)
    try:
        sender.send_heartbeat("lcu-connected")
        sender.flush_outbox()
        stats = run_backfill(config, lcu, sender, since=since)
        sender.send_heartbeat("backfill-done")
        return stats
    finally:
        lcu.close()


def run_live_command(
    config: Config,
    sender: Sender,
    *,
    stop: Optional[threading.Event] = None,
    on_status: Optional[StatusCallback] = None,
    on_match: Optional[MatchCallback] = None,
) -> None:
    """Canlı mod: client kapalıysa bekle, bağlantı koparsa yeniden bağlan.

    `stop` verilmezse döngü sonsuzdur (CLI davranışı; `KeyboardInterrupt` ile
    kesilir). Verildiğinde hem uyku hem canlı döngü kesilebilir olur — arayüzün
    "Durdur" düğmesi bunu kullanır.
    """
    sleep = _sleeper(stop)
    stopped: Callable[[], bool] = stop.is_set if stop is not None else (lambda: False)
    notify: StatusCallback = on_status or (lambda key: None)

    log.info("Live mode started (poll interval %.1fs)", config.poll_interval_s)
    lockfile_warned = False
    while not stopped():
        try:
            info = read_lockfile(config.lol_dir)
        except LockfileNotFound:
            if not lockfile_warned:
                log.info("LoL client appears closed (no lockfile), waiting...")
                lockfile_warned = True
            notify(STATUS_WAITING_CLIENT)
            sleep(LOCKFILE_WAIT_S)
            continue
        lockfile_warned = False

        lcu = HttpLcuClient(info)
        runner = LiveRunner(
            config, lcu, sender, sleep=sleep, should_stop=stopped, on_match=on_match
        )
        try:
            # GÖREV 13: bağlantı kurulur kurulmaz haber ver (yetişme uzun sürebilir;
            # panelde cihaz "ayakta" görünsün). Hata yutulur.
            notify(STATUS_CONNECTED)
            sender.send_heartbeat("lcu-connected")
            # Her bağlantıda (ilk + yeniden) canlı döngüden ÖNCE sınırlı yetişme;
            # hata yutulur, canlı mod engellenmez (catchup.py).
            notify(STATUS_CATCHUP)
            run_catchup(config, lcu, sender)
            notify(STATUS_LIVE)
            runner.poll_forever()
        except LcuConnectionLost:
            log.info("LCU connection lost, will reconnect...")
            notify(STATUS_RECONNECTING)
            sleep(RECONNECT_WAIT_S)
        finally:
            lcu.close()

    log.info("Live mode stopped.")
    notify(STATUS_STOPPED)
