"""Migration runner doğrulaması: 0002_perf_score her iki kurulum yolunda da
tutarlı şema üretir (taze DB: 0001+0002 sırayla; mevcut DB: yalnız 0002).

perf_score kolonunun TEK kaynağı 0002'dir; 0001'e de eklenirse taze kurulumda
ALTER "duplicate column" ile patlar (SQLite'ta ADD COLUMN IF NOT EXISTS yok).
"""
from __future__ import annotations

from pathlib import Path

from app.db import MIGRATIONS_DIR, connect, run_migrations


def _columns(db_path, table: str) -> set[str]:
    conn = connect(str(db_path))
    try:
        return {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})")
        }
    finally:
        conn.close()


def test_fresh_db_applies_all_migrations_in_name_order(tmp_path):
    db_path = tmp_path / "fresh.db"
    applied = run_migrations(str(db_path))
    assert applied == ["0001_init.sql", "0002_perf_score.sql"]  # sıra garantisi
    assert "perf_score" in _columns(db_path, "rating_history")
    # Tekrar koşmak güvenli ve no-op.
    assert run_migrations(str(db_path)) == []


def test_existing_db_gets_only_0002(tmp_path):
    """0001'i zaten uygulanmış (perf_score'suz) mevcut kurulum simülasyonu."""
    db_path = tmp_path / "existing.db"
    conn = connect(str(db_path))
    try:
        conn.executescript(
            (MIGRATIONS_DIR / "0001_init.sql").read_text(encoding="utf-8")
        )
        conn.execute(
            "CREATE TABLE schema_migrations ("
            " filename   TEXT PRIMARY KEY,"
            " applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        conn.execute(
            "INSERT INTO schema_migrations (filename) VALUES ('0001_init.sql')"
        )
        conn.commit()
    finally:
        conn.close()
    assert "perf_score" not in _columns(db_path, "rating_history")

    applied = run_migrations(str(db_path))
    assert applied == ["0002_perf_score.sql"]  # 0001 atlandı, çakışma yok
    assert "perf_score" in _columns(db_path, "rating_history")


def test_0001_does_not_define_perf_score():
    """Koruma: kolon 0001'e geri eklenirse taze kurulum 0002'de patlar."""
    ddl = (MIGRATIONS_DIR / "0001_init.sql").read_text(encoding="utf-8")
    # Yorum satırları hariç gerçek tanım aranır.
    code_lines = [
        line for line in ddl.splitlines() if not line.lstrip().startswith("--")
    ]
    assert not any("perf_score" in line for line in code_lines)
