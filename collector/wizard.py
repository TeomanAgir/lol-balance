"""İlk açılış sihirbazı (GÖREV 5) + backend erişim doğrulaması.

`.env` yoksa (frozen'da exe'nin yanında) kullanıcıya üç şey sorulur:

1. BACKEND_URL — varsayılan canlı adres, Enter = kabul.
2. API_KEY — zorunlu, boş geçilemez.
3. LOL_DIR — önce otomatik aranır (kayıt defteri → Riot metadata → bilinen yollar),
   bulunursa onaylatılır (Enter = evet), bulunamazsa sorulur.

Sonuç `.env`'e yazılır ve backend'e hızlı bir doğrulama isteği atılır; anahtar/adres
hatası ilk dakikada Türkçe olarak raporlanır.

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
    """`GET /api/v1/players` ile adres+anahtarı doğrular. Türkçe, eyleme dönük mesaj döner."""
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
        return BackendCheck(
            False,
            f"Backend'e ULAŞILAMADI ({url}): {exc}\n"
            "  → BACKEND_URL doğru mu, internet bağlantın var mı? "
            "Adresi tarayıcıda açıp kontrol edebilirsin.",
        )

    status = response.status_code
    if 200 <= status < 300:
        try:
            count = len(response.json() or [])
        except ValueError:
            return BackendCheck(
                False,
                f"Backend yanıt verdi ama JSON değil (HTTP {status}) — "
                f"BACKEND_URL bu sisteme ait olmayabilir: {url}",
            )
        return BackendCheck(True, f"Backend doğrulandı ({url}): {count} kayıtlı oyuncu.")

    if status in (401, 403):
        return BackendCheck(
            False,
            f"API anahtarı REDDEDİLDİ (HTTP {status}). "
            "→ .env içindeki API_KEY yanlış; Teoman'dan doğru anahtarı iste.",
        )
    if status == 404:
        return BackendCheck(
            False,
            f"Adres bulunamadı (HTTP 404): {url}{PLAYERS_PATH}\n"
            "  → BACKEND_URL yanlış olabilir (sonunda /api/v1 OLMAMALI).",
        )
    return BackendCheck(
        False,
        f"Backend beklenmedik yanıt verdi (HTTP {status}): {response.text[:200]}",
    )


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
    answer = _ask(f"Backend adresi [{DEFAULT_BACKEND_URL}]: ", input_fn)
    url = (answer or DEFAULT_BACKEND_URL).strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
        print_fn(f"  (şema eksikti, https:// eklendi → {url})")
    return url


def _ask_api_key(input_fn: Reader, print_fn: Printer, max_tries: int = 5) -> str:
    for _ in range(max_tries):
        key = _ask("API anahtarı (Teoman'dan al): ", input_fn)
        if key:
            return key
        print_fn("  API anahtarı boş olamaz, tekrar dene.")
    raise SystemExit("API anahtarı girilmedi, kurulum iptal edildi.")


def _ask_lol_dir(input_fn: Reader, print_fn: Printer, max_tries: int = 5) -> str:
    detected, source = detect_lol_dir()
    if detected is not None:
        print_fn(f"LoL klasörü bulundu ({source}): {detected}")
        answer = _ask("  Doğru mu? [E/h]: ", input_fn).lower()
        if answer in ("", "e", "evet", "y", "yes"):
            return str(detected)
        if answer not in ("h", "hayir", "hayır", "n", "no"):
            # Anlaşılmayan cevap: güvenli taraf = bulunanı kullan
            print_fn("  (cevap anlaşılmadı, bulunan klasör kullanılıyor)")
            return str(detected)
        print_fn("  Tamam, klasörü elle gir.")
    else:
        print_fn("LoL klasörü otomatik bulunamadı.")

    for _ in range(max_tries):
        raw = _ask(r"LoL klasörü (ör. C:\Riot Games\League of Legends): ", input_fn)
        if not raw:
            print_fn("  Boş olamaz, tekrar dene.")
            continue
        candidate = Path(raw.strip().strip('"'))
        if looks_like_lol_dir(candidate):
            return str(candidate)
        if candidate.is_dir():
            print_fn(
                "  UYARI: klasör var ama içinde LeagueClient.exe / lockfile gibi bir "
                "işaret yok. Yine de kaydediliyor — yanlışsa .env'i düzelt."
            )
            return str(candidate)
        print_fn(f"  Böyle bir klasör yok: {candidate}")
    raise SystemExit("Geçerli bir LoL klasörü girilmedi, kurulum iptal edildi.")


def render_env(values: dict[str, str]) -> str:
    return (
        "# LoL Balance Collector — ilk açılış sihirbazı tarafından oluşturuldu\n"
        "\n"
        "# LoL kurulum dizini (içinde client açıkken 'lockfile' oluşur)\n"
        f"LOL_DIR={values['LOL_DIR']}\n"
        "\n"
        "# Backend adresi (sondaki / olmadan) ve paylaşılan API anahtarı\n"
        f"BACKEND_URL={values['BACKEND_URL']}\n"
        f"API_KEY={values['API_KEY']}\n"
        "\n"
        "# Opsiyonel:\n"
        "#MIN_KNOWN=6\n"
        "#POLL_INTERVAL_S=2.5\n"
    )


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

    print_fn("")
    print_fn("=" * 62)
    print_fn(" LoL Balance Collector — ilk kurulum")
    print_fn("=" * 62)
    print_fn(f"Ayarlar buraya yazılacak: {target}")
    print_fn("(Köşeli parantezdeki varsayılanı kabul etmek için Enter'a bas.)")
    print_fn("")

    backend_url = _ask_backend_url(input_fn, print_fn)
    api_key = _ask_api_key(input_fn, print_fn)
    lol_dir = _ask_lol_dir(input_fn, print_fn)

    values = {"BACKEND_URL": backend_url, "API_KEY": api_key, "LOL_DIR": lol_dir}
    write_env(target, values)

    masked = api_key[:3] + "*" * max(0, len(api_key) - 3)
    print_fn("")
    print_fn("Kaydedildi:")
    print_fn(f"  dosya       : {target}")
    print_fn(f"  BACKEND_URL : {backend_url}")
    print_fn(f"  API_KEY     : {masked}")
    print_fn(f"  LOL_DIR     : {lol_dir}")
    print_fn("")

    result = check(backend_url, api_key)
    print_fn(("OK  " if result.ok else "HATA  ") + result.message)
    if not result.ok:
        print_fn(
            "Ayarları düzeltmek için .env dosyasını elle düzenleyebilir "
            "ya da programı `--setup` ile yeniden çalıştırabilirsin."
        )
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
    print_fn(("OK  " if result.ok else "HATA  ") + result.message)
    return result


def stdin_is_interactive() -> bool:
    """Sihirbaz sorabilir mi? (borulanmış girdi de kabul edilir; kapalı stdin edilmez)"""
    if os.environ.get("COLLECTOR_NO_WIZARD"):
        return False
    return sys.stdin is not None and not sys.stdin.closed
