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
        "0005_participant_items.sql",
        "0006_roulette.sql",
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


def test_0005_adds_participant_items_json(tmp_path):
    """GÖREV 14: match_participants.items_json (db_schema migration 0005)."""
    db_path = tmp_path / "items.db"
    run_migrations(str(db_path))
    assert "items_json" in _columns(db_path, "match_participants")
    # Tekrar koşmak no-op: ALTER ikinci kez uygulanırsa "duplicate column".
    assert run_migrations(str(db_path)) == []


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
        "0005_participant_items.sql",
        "0006_roulette.sql",
    ]
    assert "perf_score" in _columns(db_path, "rating_history")
    assert "role_rating_history" in _objects(db_path)
    assert "client_id" in _columns(db_path, "matches")
    assert "items_json" in _columns(db_path, "match_participants")

    # Mevcut (veri dolu) DB üstünde tekrar koşmak no-op: 0004/0005 iki kez
    # uygulanırsa "duplicate column" ile patlardı.
    assert run_migrations(str(db_path)) == []


def test_0006_creates_roulette_tables_and_extends_status_check(tmp_path):
    """GÖREV 23: rulet tabloları + matches.status CHECK genişlemesi (0006)."""
    db_path = tmp_path / "roulette.db"
    run_migrations(str(db_path))
    assert {"roulette_sessions", "roulette_assignments"} <= _objects(db_path)
    assert _columns(db_path, "roulette_sessions") == {
        "id", "created_at", "status", "match_id",
    }
    assert _columns(db_path, "roulette_assignments") == {
        "id", "session_id", "player_id", "team", "position", "champion",
        "item_ids_json",
    }
    # Rebuild sonrası matches kolon kümesi aynen korunur (client_id dahil).
    assert _columns(db_path, "matches") == {
        "id", "ingest_event_id", "source_game_id", "played_at", "duration_s",
        "winner_team", "status", "created_at", "client_id",
    }
    # View'lar yeniden kuruldu, bozulmadı.
    assert {"current_ratings", "current_role_ratings"} <= _objects(db_path)

    conn = connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO ingest_events (id, source, source_game_id,"
            " payload_json) VALUES (1, 'lcu_eog', 'g1', '{}'),"
            " (2, 'lcu_eog', 'g2', '{}')"
        )
        # Yeni 'roulette' durumu kabul edilir...
        conn.execute(
            "INSERT INTO matches (ingest_event_id, source_game_id, played_at,"
            " winner_team, status) VALUES (1, 'g1', '2026-08-17T19:00:00Z',"
            " 100, 'roulette')"
        )
        # ...tanımsız durum hâlâ reddedilir (CHECK yaşıyor).
        import sqlite3 as _sqlite3

        try:
            conn.execute(
                "INSERT INTO matches (ingest_event_id, source_game_id,"
                " played_at, winner_team, status) VALUES (2, 'g2',"
                " '2026-08-17T19:00:00Z', 100, 'bogus')"
            )
            raise AssertionError("CHECK 'bogus' durumunu kabul etti")
        except _sqlite3.IntegrityError as exc:
            assert "CHECK" in str(exc) or "constraint" in str(exc).lower()
        conn.rollback()
    finally:
        conn.close()


def test_0006_rebuild_preserves_matches_rows_and_foreign_keys(tmp_path):
    """0006, veri DOLU bir 0001-0005 kurulumunda satırları birebir taşır.

    Rebuild id'leri korur; child tabloların (match_participants,
    rating_history) FK'ları rename sonrası da tutarlıdır
    (PRAGMA foreign_key_check temiz).
    """
    db_path = tmp_path / "old_data.db"
    conn = connect(str(db_path))
    try:
        for name in (
            "0001_init.sql", "0002_perf_score.sql", "0003_role_ratings.sql",
            "0004_collector_health.sql", "0005_participant_items.sql",
        ):
            conn.executescript(
                (MIGRATIONS_DIR / name).read_text(encoding="utf-8")
            )
        conn.execute(
            "CREATE TABLE schema_migrations ("
            " filename   TEXT PRIMARY KEY,"
            " applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        conn.executemany(
            "INSERT INTO schema_migrations (filename) VALUES (?)",
            [
                ("0001_init.sql",), ("0002_perf_score.sql",),
                ("0003_role_ratings.sql",), ("0004_collector_health.sql",),
                ("0005_participant_items.sql",),
            ],
        )
        conn.execute(
            "INSERT INTO players (id, display_name) VALUES (1, 'Teoman')"
        )
        conn.execute(
            "INSERT INTO ingest_events (id, source, source_game_id,"
            " payload_json) VALUES (7, 'lcu_eog', 'g-keep', '{}')"
        )
        conn.execute(
            "INSERT INTO matches (id, ingest_event_id, source_game_id,"
            " played_at, duration_s, winner_team, status, created_at,"
            " client_id) VALUES (42, 7, 'g-keep', '2026-08-11T20:41:03Z',"
            " 1874, 100, 'void', '2026-08-11T20:45:00Z', 'Ali-PC')"
        )
        conn.execute(
            "INSERT INTO match_participants (match_id, player_id, team)"
            " VALUES (42, 1, 100)"
        )
        conn.execute(
            "INSERT INTO rating_history (player_id, match_id, engine_version,"
            " mu_before, sigma_before, mu_after, sigma_after)"
            " VALUES (1, 42, 'v-test', 25.0, 8.333, 26.1, 7.9)"
        )
        conn.commit()
    finally:
        conn.close()

    assert run_migrations(str(db_path)) == ["0006_roulette.sql"]

    conn = connect(str(db_path))
    try:
        row = conn.execute("SELECT * FROM matches WHERE id = 42").fetchone()
        assert dict(row) == {
            "id": 42, "ingest_event_id": 7, "source_game_id": "g-keep",
            "played_at": "2026-08-11T20:41:03Z", "duration_s": 1874,
            "winner_team": 100, "status": "void",
            "created_at": "2026-08-11T20:45:00Z", "client_id": "Ali-PC",
        }
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        # View'lar sorgulanabilir durumda (yeniden kuruldu).
        conn.execute("SELECT * FROM current_ratings").fetchall()
        conn.execute("SELECT * FROM current_role_ratings").fetchall()
    finally:
        conn.close()

    # Tekrar koşmak no-op (rebuild ikinci kez uygulanmaz).
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


def test_0001_does_not_define_items_json():
    """Aynı koruma items_json için: tek kaynak 0005'tir (bkz. 0002 notu)."""
    assert not any("items_json" in line for line in _code_lines("0001_init.sql"))
