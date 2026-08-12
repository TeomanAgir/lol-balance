"""İlk açılış sihirbazı (GÖREV 5) + backend erişim doğrulaması.

`.env` yoksa (frozen'da exe'nin yanında) kullanıcıya önce dil (GÖREV 6,
contract §1: sihirbazın İLK sorusu İngilizce dil seçimidir; config'de
`LANGUAGE` varsa sorulmaz), sonra üç şey sorulur:

1. BACKEND_URL — varsayılan canlı adres, Enter = kabul.
2. API_KEY — zorunlu, boş geçilemez.
3. LOL_DIR — önce otomatik aranır (kayıt defteri → Riot metadata → bilinen yollar),
   bulunursa onaylatılır (Enter = evet), bulunamazsa sorulur.

Sonuç `.env`'e yazılır ve backend'e hızlı bir doğrulama isteği atılır; anahtar/adres
hatası ilk dakikada seçilen dilde raporlanır.

Tüm G/Ç enjekte edilebilir (`input_fn`, `print_fn`, `check`), böylece sihirbaz
mock'lanmış girdilerle test edilebilir.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

import httpx

from .config import app_dir
from .i18n import (
    LANGUAGE_KEY,
    get_language,
    language_from_env_file,
    msg,
    prompt_language,
    set_language,
)

DEFAULT_BACKEND_URL = "https://lol.teomanagir.com"

PLAYERS_PATH = "/api/v1/players"

#: LoL kurulum dizinini işaret eden dosya/dizinler (biri yeterli).
LOL_DIR_MARKERS = (
    "lockfile",  # client açıkken oluşur — collector'ın asıl beklediği dosya
    "LeagueClient.exe",
    "LeagueClientUx.exe",
    "League of Legends.exe",
    "Game",
    "Config",
)

#: Kayıt defteri adayları: (hive adı, alt anahtar, değer adı)
REGISTRY_CANDIDATES = (
    ("HKLM", r"SOFTWARE\WOW6432Node\Riot Games, Inc\League of Legends", "Location"),
    ("HKLM", r"SOFTWARE\Riot Games, Inc\League of Legends", "Location"),
    ("HKLM", r"SOFTWARE\WOW6432Node\Riot Games\League of Legends", "Location"),
    ("HKLM", r"SOFTWARE\Riot Games\League of Legends", "Location"),
    ("HKCU", r"Software\Riot Games\League of Legends", "Location"),
    (
        "HKLM",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
        r"\Riot Game league_of_legends.live",
        "InstallLocation",
    ),
    (
        "HKLM",
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
        r"\Riot Game league_of_legends.live",
        "InstallLocation",
    ),
)

#: Sürücü köküne göre denenen bilinen kurulum yolları.
KNOWN_SUBPATHS = (
    r"Riot Games\League of Legends",
    r"Program Files\Riot Games\League of Legends",
    r"Program Files (x86)\Riot Games\League of Legends",
    r"Games\Riot Games\League of Legends",
    r"Oyunlar\Riot Games\League of Legends",
)

RIOT_METADATA_PATHS = (
    r"C:\ProgramData\Riot Games\Metadata\league_of_legends.live"
    r"\league_of_legends.live.product_settings.yaml",
)


# --------------------------------------------------------------------------- #
# LOL_DIR tespiti
# --------------------------------------------------------------------------- #


def looks_like_lol_dir(path: Path) -> bool:
    """Dizin var ve içinde LoL kurulumuna ait bir işaret var mı?"""
    try:
        if not path.is_dir():
            return False
        return any((path / marker).exists() for marker in LOL_DIR_MARKERS)
    except OSError:
        return False


def _logical_drive_roots() -> list[Path]:
    """Windows'ta takılı (çıkarılabilir olmayan) sürücü kökleri; hata olursa makul varsayılan."""
    roots: list[Path] = []
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        mask = kernel32.GetLogicalDrives()
        for index in range(26):
            if not mask & (1 << index):
                continue
            letter = chr(ord("A") + index)
            root = f"{letter}:\\"
            # 2 = DRIVE_REMOVABLE, 5 = DRIVE_CDROM → taramaya değmez / yavaş
            if kernel32.GetDriveTypeW(root) in (2, 5):
                continue
            roots.append(Path(root))
    except Exception:
        roots = [Path("C:\\"), Path("D:\\")]
    return roots


def find_lol_dir_from_registry() -> Optional[Path]:
    try:
        import winreg  # type: ignore
    except ImportError:
        return None

    hives = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER}
    for hive_name, subkey, value_name in REGISTRY_CANDIDATES:
        hive = hives.get(hive_name)
        if hive is None:
            continue
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
        except OSError:
            continue
        if not value:
            continue
        candidate = Path(str(value).strip().strip('"'))
        if looks_like_lol_dir(candidate):
            return candidate
    return None


def find_lol_dir_from_riot_metadata() -> Optional[Path]:
    """Riot'un product_settings.yaml'ındaki `product_install_full_path` alanı."""
    for raw_path in RIOT_METADATA_PATHS:
        path = Path(raw_path)
        try:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            if "product_install_full_path" not in line:
                continue
            _, _, value = line.partition(":")
            candidate = Path(value.strip().strip('"').strip("'"))
            if str(candidate) and looks_like_lol_dir(candidate):
                return candidate
    return None


def find_lol_dir_from_known_paths() -> Optional[Path]:
    for root in _logical_drive_roots():
        for subpath in KNOWN_SUBPATHS:
            candidate = root / subpath
            if looks_like_lol_dir(candidate):
                return candidate
    return None


#: Arama sırası — brief'teki öncelik (kayıt defteri önce, bilinen yollar sonra).
LOL_DIR_SOURCES: tuple[tuple[str, Callable[[], Optional[Path]]], ...] = (
    ("kayıt defteri", find_lol_dir_from_registry),
    ("Riot metadata", find_lol_dir_from_riot_metadata),
    ("bilinen yollar", find_lol_dir_from_known_paths),
)

#: Kaynak kimliği → sözlük anahtarı (gösterim dili için; kimlikler sabit kalır).
_SOURCE_LABEL_KEYS = {
    "kayıt defteri": "wizard.source.registry",
    "Riot metadata": "wizard.source.riot_metadata",
    "bilinen yollar": "wizard.source.known_paths",
}


def _source_label(name: str) -> str:
    key = _SOURCE_LABEL_KEYS.get(name)
    return msg(key) if key else name


def detect_lol_dir(
    sources: Iterable[tuple[str, Callable[[], Optional[Path]]]] | None = None,
) -> tuple[Optional[Path], Optional[str]]:
    """İlk sonuç veren kaynağın (yol, kaynak adı) çiftini döner."""
    for name, source in sources or LOL_DIR_SOURCES:
        try:
            found = source()
        except Exception:
            found = None
        if found is not None:
            return found, name
    return None, None


# --------------------------------------------------------------------------- #
# Backend doğrulaması
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BackendCheck:
    ok: bool
    message: str


def check_backend(
    backend_url: str,
    api_key: str,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 10.0,
) -> BackendCheck:
    """`GET /api/v1/players` ile adres+anahtarı doğrular. Seçili dilde, eyleme dönük mesaj döner."""
    url = backend_url.rstrip("/")
    try:
        with httpx.Client(
            base_url=url,
            headers={"X-API-Key": api_key},
            timeout=timeout,
            transport=transport,
            follow_redirects=True,
        ) as client:
            response = client.get(PLAYERS_PATH)
    except httpx.HTTPError as exc:
        return BackendCheck(False, msg("check.unreachable", url=url, error=exc))

    status = response.status_code
    if 200 <= status < 300:
        try:
            count = len(response.json() or [])
        except ValueError:
            return BackendCheck(False, msg("check.not_json", status=status, url=url))
        return BackendCheck(True, msg("check.ok", url=url, count=count))

    if status in (401, 403):
        return BackendCheck(False, msg("check.key_rejected", status=status))
    if status == 404:
        return BackendCheck(False, msg("check.not_found", url=url, path=PLAYERS_PATH))
    return BackendCheck(False, msg("check.unexpected", status=status, body=response.text[:200]))


# --------------------------------------------------------------------------- #
# Sihirbaz
# --------------------------------------------------------------------------- #

Printer = Callable[[str], None]
Reader = Callable[[str], str]


def _ask(prompt: str, input_fn: Reader) -> str:
    try:
        return input_fn(prompt).strip()
    except EOFError:
        return ""


def _ask_backend_url(input_fn: Reader, print_fn: Printer) -> str:
    answer = _ask(msg("wizard.ask_backend_url", default=DEFAULT_BACKEND_URL), input_fn)
    url = (answer or DEFAULT_BACKEND_URL).strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
        print_fn(msg("wizard.scheme_added", url=url))
    return url


def _ask_api_key(input_fn: Reader, print_fn: Printer, max_tries: int = 5) -> str:
    for _ in range(max_tries):
        key = _ask(msg("wizard.ask_api_key"), input_fn)
        if key:
            return key
        print_fn(msg("wizard.api_key_empty"))
    raise SystemExit(msg("wizard.api_key_aborted"))


def _ask_lol_dir(input_fn: Reader, print_fn: Printer, max_tries: int = 5) -> str:
    detected, source = detect_lol_dir()
    if detected is not None:
        print_fn(msg("wizard.lol_dir_found", source=_source_label(source), path=detected))
        answer = _ask(msg("wizard.lol_dir_confirm"), input_fn).lower()
        if answer in ("", "e", "evet", "y", "yes"):
            return str(detected)
        if answer not in ("h", "hayir", "hayır", "n", "no"):
            # Anlaşılmayan cevap: güvenli taraf = bulunanı kullan
            print_fn(msg("wizard.lol_dir_unclear"))
            return str(detected)
        print_fn(msg("wizard.lol_dir_manual"))
    else:
        print_fn(msg("wizard.lol_dir_not_found"))

    for _ in range(max_tries):
        raw = _ask(msg("wizard.ask_lol_dir"), input_fn)
        if not raw:
            print_fn(msg("wizard.lol_dir_empty"))
            continue
        candidate = Path(raw.strip().strip('"'))
        if looks_like_lol_dir(candidate):
            return str(candidate)
        if candidate.is_dir():
            print_fn(msg("wizard.lol_dir_no_marker"))
            return str(candidate)
        print_fn(msg("wizard.lol_dir_missing", path=candidate))
    raise SystemExit(msg("wizard.lol_dir_aborted"))


def render_env(values: dict[str, str]) -> str:
    """`.env` içeriği. `LANGUAGE` yalnızca values'ta varsa yazılır — böylece
    dil alanı mevcut alanların YANINA eklenir, dosya yapısı değişmez."""
    lines = [msg("env.header"), ""]
    if LANGUAGE_KEY in values:
        lines += [msg("env.comment_language"), f"{LANGUAGE_KEY}={values[LANGUAGE_KEY]}", ""]
    lines += [
        msg("env.comment_lol_dir"),
        f"LOL_DIR={values['LOL_DIR']}",
        "",
        msg("env.comment_backend"),
        f"BACKEND_URL={values['BACKEND_URL']}",
        f"API_KEY={values['API_KEY']}",
        "",
        msg("env.comment_optional"),
        "#MIN_KNOWN=6",
        "#POLL_INTERVAL_S=2.5",
    ]
    return "\n".join(lines) + "\n"


def write_env(path: Path, values: dict[str, str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_env(values), encoding="utf-8")
    return path


def run_wizard(
    env_path: Path | None = None,
    input_fn: Reader = input,
    print_fn: Printer = print,
    check: Callable[[str, str], BackendCheck] = check_backend,
) -> Path:
    """İnteraktif kurulum; `.env`'i yazar ve yolunu döner."""
    target = env_path or (app_dir() / ".env")

    # Contract §1: sihirbazın İLK sorusu İngilizce dil seçimidir; hedef config'de
    # LANGUAGE zaten varsa sessizce kullanılır ve soru tekrar sorulmaz.
    existing_lang = language_from_env_file(target) if target.is_file() else None
    if existing_lang:
        set_language(existing_lang)
    else:
        set_language(prompt_language(input_fn))

    print_fn("")
    print_fn("=" * 62)
    print_fn(msg("wizard.title"))
    print_fn("=" * 62)
    print_fn(msg("wizard.target", path=target))
    print_fn(msg("wizard.enter_hint"))
    print_fn("")

    backend_url = _ask_backend_url(input_fn, print_fn)
    api_key = _ask_api_key(input_fn, print_fn)
    lol_dir = _ask_lol_dir(input_fn, print_fn)

    values = {
        "BACKEND_URL": backend_url,
        "API_KEY": api_key,
        "LOL_DIR": lol_dir,
        LANGUAGE_KEY: get_language(),
    }
    write_env(target, values)

    masked = api_key[:3] + "*" * max(0, len(api_key) - 3)
    print_fn("")
    print_fn(msg("wizard.saved"))
    print_fn(msg("wizard.saved_file", path=target))
    print_fn(msg("wizard.saved_language", lang=get_language()))
    print_fn(msg("wizard.saved_backend", url=backend_url))
    print_fn(msg("wizard.saved_api_key", masked=masked))
    print_fn(msg("wizard.saved_lol_dir", path=lol_dir))
    print_fn("")

    result = check(backend_url, api_key)
    print_fn((msg("check.ok_prefix") if result.ok else msg("check.fail_prefix")) + result.message)
    if not result.ok:
        print_fn(msg("wizard.fix_hint"))
    print_fn("")
    return target


def report_backend_check(
    backend_url: str,
    api_key: str,
    print_fn: Printer = print,
    check: Callable[[str, str], BackendCheck] = check_backend,
) -> BackendCheck:
    """Normal başlangıçtaki hızlı doğrulama — bloklamaz, yalnız raporlar."""
    result = check(backend_url, api_key)
    print_fn((msg("check.ok_prefix") if result.ok else msg("check.fail_prefix")) + result.message)
    return result


def stdin_is_interactive() -> bool:
    """Sihirbaz sorabilir mi? (borulanmış girdi de kabul edilir; kapalı stdin edilmez)"""
    if os.environ.get("COLLECTOR_NO_WIZARD"):
        return False
    return sys.stdin is not None and not sys.stdin.closed
