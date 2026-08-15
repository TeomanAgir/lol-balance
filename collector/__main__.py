"""CLI girişi.

Arayüz:       python -m collector            (exe: çift tıklama → tkinter penceresi)
Konsol canlı: python -m collector --console  (arayüzsüz eski canlı mod)
Backfill:     python -m collector --backfill [--since YYYY-MM-DD]
              python -m collector backfill  [--since YYYY-MM-DD]   (aynısı)
Rol backfill: python -m collector backfill-positions [--dry-run]
Eşya backfill:python -m collector backfill-items [--dry-run]
Kurulum:      python -m collector --setup    (.env'i yeniden oluşturur)

GÖREV 16 Faz C: ARGÜMANSIZ çalıştırma arayüzü açar (`gui.py`); argümanlı her
komut eskisi gibi terminalden çalışır. tkinter bulunamazsa (kaynaktan koşan
minimal Python) sessizce eski konsol canlı moduna düşülür.

Canlı mod, LCU'ya her bağlandığında canlı döngüden ÖNCE sınırlı bir "oto-yetişme"
backfill'i koşar (son `CATCHUP_DAYS` gün, varsayılan 14, `0` = kapalı) — böylece
collector kapalıyken oynanan custom'lar da toplanır (bkz. catchup.py). Canlı
döngü ve LCU'lu backfill mantığı `commands.py`'dedir: arayüz aynı fonksiyonları
çağırır, kopya yoktur.

Paketlenmiş exe'de (`sys.frozen`) tüm kalıcı dosyalar exe'nin yanındadır ve
`.env` yoksa ilk açılış sihirbazı çalışır (bkz. wizard.py). Exe `--windowed`
derlenir: konsol YOKTUR, `sys.stdout`/`stdin` `None` olabilir — `print()` bu
durumda sessizdir, `input()` ise ÇAĞRILMAZ (bkz. `_pause_if_frozen`).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback
from datetime import date

from . import __version__, i18n
from .backfill_items import run_items_backfill
from .backfill_positions import run_position_backfill
from .commands import run_backfill_command, run_live_command
from .config import REQUIRED_ENV_KEYS, app_dir, find_env_file, is_frozen, load_config
from .i18n import msg
from .lockfile import LockfileNotFound
from .sender import Sender
from .wizard import report_backend_check, run_wizard, stdin_is_interactive

log = logging.getLogger("collector")

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
LOG_DATEFMT = "%H:%M:%S"


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
    if args.command in ("backfill-positions", "backfill-items"):
        label = msg(
            "cli.mode.backfill_positions"
            if args.command == "backfill-positions"
            else "cli.mode.backfill_items"
        )
        return label + (msg("cli.mode.dry_run_suffix") if args.dry_run else "")
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
    parser.add_argument("command", nargs="?",
                        choices=["backfill", "backfill-positions", "backfill-items"],
                        default=None, help=msg("cli.help.command"))
    parser.add_argument("--backfill", action="store_true", help=msg("cli.help.backfill"))
    parser.add_argument("--since", type=_parse_since, default=None, metavar="YYYY-MM-DD",
                        help=msg("cli.help.since"))
    parser.add_argument("--dry-run", action="store_true", help=msg("cli.help.dry_run"))
    parser.add_argument("--setup", action="store_true", help=msg("cli.help.setup"))
    parser.add_argument("--console", action="store_true", help=msg("cli.help.console"))
    parser.add_argument("--version", action="version", version=f"collector {__version__}")
    return parser


def _configure_logging() -> None:
    """Kök logger. `--windowed` exe'de `sys.stderr` YOKTUR: StreamHandler kurulmaz."""
    handlers = None if sys.stderr is not None else [logging.NullHandler()]
    logging.basicConfig(
        level=logging.INFO, format=LOG_FORMAT, datefmt=LOG_DATEFMT, handlers=handlers
    )


def _maybe_run_gui() -> int | None:
    """Argümansız çalıştırma: arayüzü aç. tkinter yoksa None (konsola düşülür)."""
    from . import gui

    if not gui.tkinter_available():
        log.warning("tkinter is not available, falling back to console live mode")
        print(msg("gui.unavailable"))
        return None
    return gui.run_gui()


def main(argv: list[str] | None = None) -> int:
    # Dil, config'de varsa daha --help/banner basılmadan sessizce yüklenir.
    i18n.resolve_language(allow_prompt=False)
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    args = _build_parser().parse_args(effective_argv)

    _configure_logging()

    # GÖREV 16 Faz C: çift tıklama (argüman YOK) → tkinter arayüzü. Argümanlı
    # her komut (ve `--console`) aşağıdaki eski akıştan geçer.
    if not effective_argv:
        code = _maybe_run_gui()
        if code is not None:
            return code

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

    if args.command == "backfill-items":
        # Aynı desen (GÖREV 14): kaynak raw_archive, hedef backend, LCU yok.
        stats = run_items_backfill(config, dry_run=args.dry_run)
        return 0 if not stats.errors else 1

    sender = Sender(config)

    if _wants_backfill(args):
        try:
            stats = run_backfill_command(config, sender, since=args.since)
        except LockfileNotFound as exc:
            log.error("Lockfile not found: %s — is the LoL client running, is LOL_DIR correct?", exc)
            return 1
        finally:
            sender.close()
        return 0 if not stats.errors else 1

    # Canlı mod: client kapalıysa bekle, bağlantı koparsa yeniden bağlan
    # (döngünün kendisi commands.run_live_command'dedir — arayüz de onu çağırır).
    print(msg("cli.live_hint"))
    print(msg("cli.live_stop_hint"))
    try:
        run_live_command(config, sender)
        return 0
    except KeyboardInterrupt:
        log.info("Stopped.")
        return 0
    finally:
        sender.close()


def _has_console() -> bool:
    """`--windowed` exe'de konsol yoktur: stdin/stdout `None` olur."""
    return sys.stdin is not None and sys.stdout is not None


def _pause_if_frozen() -> None:
    """Çift tıklamayla açılan exe penceresi anında kapanmasın (yalnız frozen'da).

    `--windowed` derlemede bekletilecek konsol penceresi YOKTUR ve `input()`
    "lost sys.stdin" ile patlar — bu durumda hiç çağrılmaz.
    """
    if not is_frozen() or not _has_console():
        return
    try:
        input(msg("cli.press_enter"))
    except (EOFError, KeyboardInterrupt, OSError, RuntimeError):
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
        if stream is None:  # --windowed: yönlendirilecek akış yok
            continue
        try:
            # line_buffering: çıktı dosyaya yönlendirildiğinde de anında görünsün
            stream.reconfigure(  # type: ignore[union-attr]
                encoding="utf-8", errors="replace", line_buffering=True
            )
        except Exception:
            pass


#: Konsolsuz (`--windowed`) exe çökerse yığın izinin yazıldığı dosya.
CRASH_LOG_NAME = "collector-error.log"


def _report_crash() -> None:
    """Yığın izini konsola; konsol yoksa exe'nin yanındaki dosyaya yazar.

    `--windowed` derlemede `sys.stderr` `None`'dır: `traceback.print_exc()` orada
    AttributeError'a döner ve asıl hata büsbütün kaybolur. Bu yüzden hem yazma
    denemesi korunaklıdır hem de konsolsuzken diske düşülür (arkadaşın PC'sinde
    çıkan hatayı teşhis etmenin tek yolu).
    """
    text = traceback.format_exc()
    if sys.stderr is not None:
        try:
            sys.stderr.write(text)
            return
        except Exception:  # noqa: BLE001
            pass
    try:
        (app_dir() / CRASH_LOG_NAME).write_text(text, encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — teşhis dosyası yazılamıyorsa da çıkış temiz olsun
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
        _report_crash()
        code = 1
    _pause_if_frozen()
    return code


if __name__ == "__main__":
    sys.exit(run())
