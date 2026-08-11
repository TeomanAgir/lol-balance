"""CLI girişi.

Canlı mod:    python -m collector            (exe: çift tıklama)
Backfill:     python -m collector --backfill [--since YYYY-MM-DD]
Rol backfill: python -m collector backfill-positions [--dry-run]
Kurulum:      python -m collector --setup    (.env'i yeniden oluşturur)

Paketlenmiş exe'de (`sys.frozen`) tüm kalıcı dosyalar exe'nin yanındadır ve
`.env` yoksa ilk açılış sihirbazı çalışır (bkz. wizard.py).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import traceback
from datetime import date

from . import __version__
from .backfill import run_backfill
from .backfill_positions import run_position_backfill
from .config import app_dir, find_env_file, is_frozen, load_config
from .lcu import HttpLcuClient
from .live import LcuConnectionLost, LiveRunner
from .lockfile import LockfileNotFound, read_lockfile
from .sender import Sender
from .wizard import report_backend_check, run_wizard, stdin_is_interactive

log = logging.getLogger("collector")

_LOCKFILE_WAIT_S = 10.0
_RECONNECT_WAIT_S = 5.0

REQUIRED_ENV_KEYS = ("LOL_DIR", "BACKEND_URL", "API_KEY")


def _parse_since(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"--since YYYY-MM-DD formatında olmalı: {value!r}")


def _mode_label(args: argparse.Namespace) -> str:
    if args.setup:
        return "kurulum sihirbazı"
    if args.command == "backfill-positions":
        return "rol backfill" + (" (dry-run)" if args.dry_run else "")
    if args.backfill:
        return "geçmiş maç backfill"
    return "canlı mod"


def _print_banner(args: argparse.Namespace) -> None:
    print(f"LoL Balance Collector v{__version__} — {_mode_label(args)}")
    print(f"Çalışma klasörü: {app_dir()}")


def _ensure_env(force_setup: bool = False) -> None:
    """`.env` yoksa (ya da --setup verildiyse) ilk açılış sihirbazını çalıştırır."""
    if force_setup:
        run_wizard()
        return
    if find_env_file() is not None:
        return
    if all(os.environ.get(key) for key in REQUIRED_ENV_KEYS):
        return  # ortam değişkenleriyle yapılandırılmış (CI / geliştirici kurulumu)
    if not stdin_is_interactive():
        raise SystemExit(
            f"Ayar dosyası yok ({app_dir() / '.env'}) ve kurulum sihirbazı çalıştırılamıyor "
            "(stdin kapalı). .env.example'ı kopyalayıp doldurun."
        )
    run_wizard()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="collector", description="LoL custom maç toplayıcı")
    parser.add_argument("command", nargs="?", choices=["backfill-positions"], default=None,
                        help="backfill-positions: raw_archive'daki maçların rollerini "
                             "tahmin edip backend'e yazar")
    parser.add_argument("--backfill", action="store_true",
                        help="Match history'yi geriye tara (roster filtresiyle)")
    parser.add_argument("--since", type=_parse_since, default=None, metavar="YYYY-MM-DD",
                        help="Backfill'de bu tarihten eski maçlara bakma")
    parser.add_argument("--dry-run", action="store_true",
                        help="backfill-positions: ne gönderileceğini yazdır, gönderme")
    parser.add_argument("--setup", action="store_true",
                        help="Kurulum sihirbazını yeniden çalıştır (.env'i yeniden yazar)")
    parser.add_argument("--version", action="version", version=f"collector {__version__}")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    _print_banner(args)
    _ensure_env(force_setup=args.setup)

    config = load_config()

    # Hızlı doğrulama: anahtar/adres hatası ilk saniyede görünsün (bloklamaz).
    # --setup'ta sihirbaz zaten doğruladı, tekrarlanmaz.
    if not args.setup:
        report_backend_check(config.backend_url, config.api_key)

    if args.setup:
        print("Kurulum bitti. Toplamayı başlatmak için programı normal (argümansız) çalıştır.")
        return 0

    if args.command == "backfill-positions":
        # LCU'ya ihtiyaç yok: kaynak raw_archive, hedef backend.
        stats = run_position_backfill(config, dry_run=args.dry_run)
        return 0 if not stats.errors else 1

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
    print("LoL client'ini aç ve custom maç oyna — maç biter bitmez otomatik gönderilir.")
    print("Durdurmak için: Ctrl+C (ya da pencereyi kapat).")
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


def _pause_if_frozen() -> None:
    """Çift tıklamayla açılan exe penceresi anında kapanmasın (yalnız frozen'da)."""
    if not is_frozen():
        return
    try:
        input("\nKapatmak için Enter'a bas...")
    except (EOFError, KeyboardInterrupt, OSError):
        pass


def _configure_console() -> None:
    """Frozen exe: konsolu UTF-8'e al ki Türkçe karakterler çökme/mojibake yapmasın."""
    if not is_frozen():
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)  # type: ignore[attr-defined]
        ctypes.windll.kernel32.SetConsoleCP(65001)  # type: ignore[attr-defined]
    except Exception:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            # line_buffering: çıktı dosyaya yönlendirildiğinde de anında görünsün
            stream.reconfigure(  # type: ignore[union-attr]
                encoding="utf-8", errors="replace", line_buffering=True
            )
        except Exception:
            pass


def run(argv: list[str] | None = None) -> int:
    """Exe girişi: hataları yakalar, çıkışta pencereyi bekletir."""
    _configure_console()
    try:
        code = main(argv)
    except SystemExit as exc:  # load_config / sihirbaz iptali gibi kontrollü çıkışlar
        if isinstance(exc.code, str):
            print(exc.code)
            code = 1
        else:
            code = exc.code or 0
    except KeyboardInterrupt:
        print("Durduruldu.")
        code = 0
    except Exception:  # noqa: BLE001 — pencere kapanmadan yığın izi görünsün
        traceback.print_exc()
        code = 1
    _pause_if_frozen()
    return code


if __name__ == "__main__":
    sys.exit(run())
