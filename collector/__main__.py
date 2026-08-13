"""CLI girişi.

Canlı mod:    python -m collector            (exe: çift tıklama)
Backfill:     python -m collector --backfill [--since YYYY-MM-DD]
              python -m collector backfill  [--since YYYY-MM-DD]   (aynısı)
Rol backfill: python -m collector backfill-positions [--dry-run]
Kurulum:      python -m collector --setup    (.env'i yeniden oluşturur)

Canlı mod, LCU'ya her bağlandığında canlı döngüden ÖNCE sınırlı bir "oto-yetişme"
backfill'i koşar (son `CATCHUP_DAYS` gün, varsayılan 14, `0` = kapalı) — böylece
collector kapalıyken oynanan custom'lar da toplanır (bkz. catchup.py).

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

from . import __version__, i18n
from .backfill import run_backfill
from .backfill_positions import run_position_backfill
from .catchup import run_catchup
from .config import app_dir, find_env_file, is_frozen, load_config
from .i18n import msg
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
        raise argparse.ArgumentTypeError(msg("cli.since_format", value=repr(value)))


def _wants_backfill(args: argparse.Namespace) -> bool:
    """`--backfill` bayrağı ve pozisyonel `backfill` komutu aynı moddur (alias)."""
    return bool(args.backfill) or args.command == "backfill"


def _mode_label(args: argparse.Namespace) -> str:
    if args.setup:
        return msg("cli.mode.setup")
    if args.command == "backfill-positions":
        return msg("cli.mode.backfill_positions") + (
            msg("cli.mode.dry_run_suffix") if args.dry_run else ""
        )
    if _wants_backfill(args):
        return msg("cli.mode.backfill")
    return msg("cli.mode.live")


def _print_banner(args: argparse.Namespace) -> None:
    print(msg("cli.banner", version=__version__, mode=_mode_label(args)))
    print(msg("cli.workdir", path=app_dir()))


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
        raise SystemExit(msg("cli.no_env_no_tty", path=app_dir() / ".env"))
    run_wizard()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="collector", description=msg("cli.description"))
    parser.add_argument("command", nargs="?", choices=["backfill", "backfill-positions"],
                        default=None, help=msg("cli.help.command"))
    parser.add_argument("--backfill", action="store_true", help=msg("cli.help.backfill"))
    parser.add_argument("--since", type=_parse_since, default=None, metavar="YYYY-MM-DD",
                        help=msg("cli.help.since"))
    parser.add_argument("--dry-run", action="store_true", help=msg("cli.help.dry_run"))
    parser.add_argument("--setup", action="store_true", help=msg("cli.help.setup"))
    parser.add_argument("--version", action="version", version=f"collector {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    # Dil, config'de varsa daha --help/banner basılmadan sessizce yüklenir.
    i18n.resolve_language(allow_prompt=False)
    args = _build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Config var ama dil alanı yoksa (i18n öncesi kurulum): ilk soru dil seçimi.
    # --setup'ta sihirbaz kendi sorar; .env hiç yoksa da ilk soruyu sihirbaz sorar.
    if not args.setup and stdin_is_interactive():
        i18n.resolve_language()

    _print_banner(args)
    _ensure_env(force_setup=args.setup)

    config = load_config()

    # Hızlı doğrulama: anahtar/adres hatası ilk saniyede görünsün (bloklamaz).
    # --setup'ta sihirbaz zaten doğruladı, tekrarlanmaz.
    if not args.setup:
        report_backend_check(config.backend_url, config.api_key)

    if args.setup:
        print(msg("cli.setup_done"))
        return 0

    if args.command == "backfill-positions":
        # LCU'ya ihtiyaç yok: kaynak raw_archive, hedef backend.
        stats = run_position_backfill(config, dry_run=args.dry_run)
        return 0 if not stats.errors else 1

    sender = Sender(config)

    if _wants_backfill(args):
        try:
            info = read_lockfile(config.lol_dir)
        except LockfileNotFound as exc:
            log.error("Lockfile not found: %s — is the LoL client running, is LOL_DIR correct?", exc)
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
    log.info("Live mode started (poll interval %.1fs)", config.poll_interval_s)
    print(msg("cli.live_hint"))
    print(msg("cli.live_stop_hint"))
    lockfile_warned = False
    try:
        while True:
            try:
                info = read_lockfile(config.lol_dir)
            except LockfileNotFound:
                if not lockfile_warned:
                    log.info("LoL client appears closed (no lockfile), waiting...")
                    lockfile_warned = True
                time.sleep(_LOCKFILE_WAIT_S)
                continue
            lockfile_warned = False

            lcu = HttpLcuClient(info)
            runner = LiveRunner(config, lcu, sender)
            try:
                # Her bağlantıda (ilk + yeniden) canlı döngüden ÖNCE sınırlı
                # yetişme; hata yutulur, canlı mod engellenmez (catchup.py).
                run_catchup(config, lcu, sender)
                runner.poll_forever()
            except LcuConnectionLost:
                log.info("LCU connection lost, will reconnect...")
                time.sleep(_RECONNECT_WAIT_S)
            finally:
                lcu.close()
    except KeyboardInterrupt:
        log.info("Stopped.")
        return 0
    finally:
        sender.close()


def _pause_if_frozen() -> None:
    """Çift tıklamayla açılan exe penceresi anında kapanmasın (yalnız frozen'da)."""
    if not is_frozen():
        return
    try:
        input(msg("cli.press_enter"))
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
        print(msg("cli.stopped"))
        code = 0
    except Exception:  # noqa: BLE001 — pencere kapanmadan yığın izi görünsün
        traceback.print_exc()
        code = 1
    _pause_if_frozen()
    return code


if __name__ == "__main__":
    sys.exit(run())
