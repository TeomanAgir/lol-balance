"""SQLite bağlantısı ve yalın SQL migration runner."""
from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: bağlantı istek başına açılır ve tek istek kullanır;
    # FastAPI sync dependency'yi threadpool'da, async endpoint'i event loop'ta koşturur.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def run_migrations(db_path: str) -> list[str]:
    """migrations/*.sql dosyalarını isim sırasıyla uygular.

    Uygulananlar schema_migrations'a işlenir; tekrar çalıştırmak güvenlidir.
    Uygulanan dosya adlarının listesini döner.
    """
    conn = connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " filename   TEXT PRIMARY KEY,"
            " applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        done = {
            row["filename"]
            for row in conn.execute("SELECT filename FROM schema_migrations")
        }
        applied = []
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in done:
                continue
            with conn:  # migration + kayıt tek transaction
                conn.executescript(path.read_text(encoding="utf-8"))
                conn.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (?)", (path.name,)
                )
            applied.append(path.name)
        return applied
    finally:
        conn.close()
