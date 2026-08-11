"""Ham payload arşivi: debug + ileride yeniden işleme için raw_archive/{gameId}.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import Config


def archive_path(config: Config, game_id: int | str) -> Path:
    return config.raw_archive_dir / f"{game_id}.json"


def archive_raw(config: Config, game_id: int | str, raw: dict[str, Any]) -> Path:
    config.raw_archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_path(config, game_id)
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
