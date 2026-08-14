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


def _objects(db_path) -> set[str]:
    conn = connect(str(db_path))
    try:
        return {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master")
        }
    finally:
        conn.close()


def test_fresh_db_applies_all_migrations_in_name_order(tmp_path):
    db_path = tmp_path / "fresh.db"
    applied = run_migrations(str(db_path))
    assert applied == [
        "0001_init.sql",
        "0002_perf_score.sql",
        "0003_role_ratings.sql",
        "0004_collector_health.sql",
    ]  # sıra garantisi
    assert "perf_score" in _columns(db_path, "rating_history")
    # Tekrar koşmak güvenli ve no-op.
    assert run_migrations(str(db_path)) == []


def test_0003_creates_role_rating_objects(tmp_path):
    """GÖREV 0: rol evreni tablosu + view'ü (db_schema migration 0003)."""
    db_path = tmp_path / "roles.db"
    run_migrations(str(db_path))
    assert {"role_rating_history", "current_role_ratings"} <= _objects(db_path)
    assert _columns(db_path, "role_rating_history") == {
        "id", "player_id", "match_id", "role", "engine_version",
        "mu_before", "sigma_before", "mu_after", "sigma_after", "perf_score",
    }


def test_0004_creates_collector_health_and_matches_client_id(tmp_path):
    """GÖREV 13: sağlık tablosu + matches.client_id (db_schema migration 0004)."""
    db_path = tmp_path / "health.db"
    run_migrations(str(db_path))
    assert "collector_health" in _objects(db_path)
    assert _columns(db_path, "collector_health") == {
        "client_id", "last_seen", "version", "outbox_pending",
    }
    assert "client_id" in _columns(db_path, "matches")


def test_existing_db_gets_0002_and_0003(tmp_path):
    """0001'i zaten uygulanmış kurulum eksik migration'ları sırayla alır."""
    db_path = tmp_path / "old.db"
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

    # 0001 atlandı, çakışma yok.
    assert run_migrations(str(db_path)) == [
        "0002_perf_score.sql",
        "0003_role_ratings.sql",
        "0004_collector_health.sql",
    ]
    assert "perf_score" in _columns(db_path, "rating_history")
    assert "role_rating_history" in _objects(db_path)
    assert "client_id" in _columns(db_path, "matches")

    # Mevcut (veri dolu) DB üstünde tekrar koşmak no-op: 0004 iki kez
    # uygulanırsa "duplicate column" ile patlardı.
    assert run_migrations(str(db_path)) == []


def _code_lines(filename: str) -> list[str]:
    ddl = (MIGRATIONS_DIR / filename).read_text(encoding="utf-8")
    # Yorum satırları hariç gerçek tanım aranır.
    return [line for line in ddl.splitlines() if not line.lstrip().startswith("--")]


def test_0001_does_not_define_perf_score():
    """Koruma: kolon 0001'e geri eklenirse taze kurulum 0002'de patlar."""
    assert not any("perf_score" in line for line in _code_lines("0001_init.sql"))


def test_0001_does_not_define_matches_client_id():
    """Aynı koruma client_id için: tek kaynak 0004'tür (bkz. 0002 notu)."""
    assert not any("client_id" in line for line in _code_lines("0001_init.sql"))
