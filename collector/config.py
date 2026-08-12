"""Config: .env dosyası + ortam değişkenlerinden yüklenir (ortam değişkeni öncelikli).

Kalıcı dosyaların (`.env`, `raw_archive/`, `outbox/`, `seed_roster.json`) kök dizini
`app_dir()` ile belirlenir:

- Kaynaktan çalışırken (``python -m collector``): paket dizini (`collector/`) — eski davranış.
- PyInstaller onefile exe'sinde (`sys.frozen`): exe'nin YANINDAKİ dizin.
  Bu şart: onefile'da paket dosyaları her çalıştırmada silinen geçici `sys._MEIPASS`
  dizinine açılır, oraya yazılan arşiv/outbox kaybolur (bkz. docs/CHANGE_REQUESTS.md GÖREV 5).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent


def is_frozen() -> bool:
    """PyInstaller ile paketlenmiş exe içinde miyiz?"""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Kalıcı dosyaların kök dizini: frozen'da exe'nin yanı, kaynakta paket dizini."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return PACKAGE_DIR


def env_candidates() -> list[Path]:
    """`.env` arama sırası: önce uygulama dizini, sonra çalışma dizini."""
    candidates = [app_dir() / ".env"]
    cwd_env = Path.cwd() / ".env"
    if cwd_env not in candidates:
        candidates.append(cwd_env)
    return candidates


def find_env_file() -> Path | None:
    """Var olan ilk `.env`; hiçbiri yoksa None (ilk açılış sihirbazı buna bakar)."""
    for candidate in env_candidates():
        if candidate.is_file():
            return candidate
    return None


def _load_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.is_file():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


@dataclass
class Config:
    lol_dir: Path
    backend_url: str  # sondaki / olmadan, ör. http://127.0.0.1:8000
    api_key: str
    min_known: int = 6
    poll_interval_s: float = 2.5
    raw_archive_dir: Path = field(default_factory=lambda: app_dir() / "raw_archive")
    outbox_dir: Path = field(default_factory=lambda: app_dir() / "outbox")
    seed_roster_path: Path = field(default_factory=lambda: app_dir() / "seed_roster.json")


def load_config(env_file: Path | None = None) -> Config:
    """`<app_dir>/.env` → `./.env` sırasıyla ilk bulunan dosyayı okur; os.environ her zaman ezer."""
    file_env: dict[str, str] = {}
    candidates = [env_file] if env_file else env_candidates()
    for candidate in candidates:
        if candidate and candidate.is_file():
            file_env = _load_env_file(candidate)
            break
    merged = {**file_env, **os.environ}

    missing = [k for k in ("LOL_DIR", "BACKEND_URL", "API_KEY") if not merged.get(k)]
    if missing:
        location = app_dir() / ".env"
        raise SystemExit(
            f"Eksik config: {', '.join(missing)}. "
            f"{location} dosyasını doldurun (bkz. collector/.env.example)."
        )

    return Config(
        lol_dir=Path(merged["LOL_DIR"]),
        backend_url=merged["BACKEND_URL"].rstrip("/"),
        api_key=merged["API_KEY"],
        min_known=int(merged.get("MIN_KNOWN", "6")),
        poll_interval_s=float(merged.get("POLL_INTERVAL_S", "2.5")),
    )
