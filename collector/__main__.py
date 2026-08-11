"""CLI girişi.

Canlı mod:   python -m collector
Backfill:    python -m collector --backfill [--since YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date

from .backfill import run_backfill
from .config import load_config
from .lcu import HttpLcuClient
from .live import LcuConnectionLost, LiveRunner
from .lockfile import LockfileNotFound, read_lockfile
from .sender import Sender

log = logging.getLogger("collector")

_LOCKFILE_WAIT_S = 10.0
_RECONNECT_WAIT_S = 5.0


def _parse_since(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"--since YYYY-MM-DD formatında olmalı: {value!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="collector", description="LoL custom maç toplayıcı")
    parser.add_argument("--backfill", action="store_true",
                        help="Match history'yi geriye tara (roster filtresiyle)")
    parser.add_argument("--since", type=_parse_since, default=None, metavar="YYYY-MM-DD",
                        help="Backfill'de bu tarihten eski maçlara bakma")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    config = load_config()
    sender = Sender(config)

    if args.backfill:
        try:
            info = read_lockfile(config.lol_dir)
        except LockfileNotFound as exc:
            log.error("Lockfile bulunamadı: %s — LoL client açık mı, LOL_DIR doğru mu?", exc)
            return 1
        lcu = HttpLcuClient(info)
        try:
            sender.flush_outbox()
            stats = run_backfill(config, lcu, sender, since=args.since)
        finally:
            lcu.close()
            sender.close()
        return 0 if not stats.errors else 1

    # Canlı mod: client kapalıysa bekle, bağlantı koparsa yeniden bağlan
    log.info("Canlı mod başladı (poll aralığı %.1fs)", config.poll_interval_s)
    lockfile_warned = False
    try:
        while True:
            try:
                info = read_lockfile(config.lol_dir)
            except LockfileNotFound:
                if not lockfile_warned:
                    log.info("LoL client kapalı görünüyor (lockfile yok), bekleniyor...")
                    lockfile_warned = True
                time.sleep(_LOCKFILE_WAIT_S)
                continue
            lockfile_warned = False

            lcu = HttpLcuClient(info)
            runner = LiveRunner(config, lcu, sender)
            try:
                runner.poll_forever()
            except LcuConnectionLost:
                log.info("LCU bağlantısı koptu, yeniden bağlanılacak...")
                time.sleep(_RECONNECT_WAIT_S)
            finally:
                lcu.close()
    except KeyboardInterrupt:
        log.info("Durduruldu.")
        return 0
    finally:
        sender.close()


if __name__ == "__main__":
    sys.exit(main())
