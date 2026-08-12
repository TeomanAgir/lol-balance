"""LCU lockfile bulma ve parse etme.

Format (client açıkken LoL kurulum dizininde): ``name:pid:port:password:protocol``
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class LockfileNotFound(Exception):
    """Lockfile yok — client kapalı ya da LOL_DIR yanlış."""


@dataclass(frozen=True)
class LockfileInfo:
    name: str
    pid: int
    port: int
    password: str
    protocol: str

    @property
    def base_url(self) -> str:
        return f"https://127.0.0.1:{self.port}"


def parse_lockfile(text: str) -> LockfileInfo:
    parts = text.strip().split(":")
    if len(parts) < 5:
        raise ValueError(f"Unexpected lockfile format: {text!r}")
    # password içinde ':' olabilir; ilk üç ve son alan sabittir
    return LockfileInfo(
        name=parts[0],
        pid=int(parts[1]),
        port=int(parts[2]),
        password=":".join(parts[3:-1]),
        protocol=parts[-1],
    )


def read_lockfile(lol_dir: Path) -> LockfileInfo:
    path = lol_dir / "lockfile"
    if not path.is_file():
        raise LockfileNotFound(str(path))
    return parse_lockfile(path.read_text(encoding="utf-8"))
