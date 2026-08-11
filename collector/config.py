"""Config: .env dosyası + ortam değişkenlerinden yüklenir (ortam değişkeni öncelikli)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent


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
    raw_archive_dir: Path = field(default_factory=lambda: PACKAGE_DIR / "raw_archive")
    outbox_dir: Path = field(default_factory=lambda: PACKAGE_DIR / "outbox")
    seed_roster_path: Path = field(default_factory=lambda: PACKAGE_DIR / "seed_roster.json")


def load_config(env_file: Path | None = None) -> Config:
    """`collector/.env` → `./.env` sırasıyla ilk bulunan dosyayı okur; os.environ her zaman ezer."""
    file_env: dict[str, str] = {}
    candidates = [env_file] if env_file else [PACKAGE_DIR / ".env", Path.cwd() / ".env"]
    for candidate in candidates:
        if candidate and candidate.is_file():
            file_env = _load_env_file(candidate)
            break
    merged = {**file_env, **os.environ}

    missing = [k for k in ("LOL_DIR", "BACKEND_URL", "API_KEY") if not merged.get(k)]
    if missing:
        raise SystemExit(
            f"Eksik config: {', '.join(missing)}. "
            f"collector/.env dosyasını doldurun (bkz. collector/.env.example)."
        )

    return Config(
        lol_dir=Path(merged["LOL_DIR"]),
        backend_url=merged["BACKEND_URL"].rstrip("/"),
        api_key=merged["API_KEY"],
        min_known=int(merged.get("MIN_KNOWN", "6")),
        poll_interval_s=float(merged.get("POLL_INTERVAL_S", "2.5")),
    )
