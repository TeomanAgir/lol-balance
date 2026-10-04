"""GÖREV 30b-A — sıra-dışı ingest'in auto-replay'i ATOMİKTİR (api_contract §5).

Hata: `replay`/`replay_roles` ingest'in transaction'ına katılmıyordu; içteki
`with conn:` dıştakini erken commit ettiği için rol replay'i patladığında maç +
ana evren kalıcı, rol evreni eksik kalıyordu ve aynı maç tekrar gelince
`duplicate:true` döndüğü için durum kendiliğinden düzelmiyordu.

Beklenen: herhangi bir replay patlarsa maçın HİÇBİR izi kalmaz (matches,
ingest_events, match_participants, rating_history, role_rating_history);
aynı payload tekrar gönderilince 201 döner ve iki evren de dolar.
`test_admin_hardening.py` §5'teki void/unvoid/unlink rollback testlerinin
ingest ikizidir.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import make_role_payload

INGEST_URL = "/api/v1/ingest/match"


def _boom(*args, **kwargs):
    raise RuntimeError("replay patladı (test)")


def _ingest(client, game_id: str, played_at: str):
    return client.post(
        INGEST_URL,
        json=make_role_payload(source_game_id=game_id, played_at=played_at),
    )


def _count(db, sql: str, params=()) -> int:
    conn = db()
    try:
        return conn.execute(sql, params).fetchone()[0]
    finally:
        conn.close()


def _traces(db, game_id: str) -> dict[str, int]:
    """Bir source_game_id'nin dört tablodaki satır sayıları."""
    match_q = "SELECT id FROM matches WHERE source_game_id = ?"
    return {
        "matches": _count(
            db, "SELECT COUNT(*) FROM matches WHERE source_game_id = ?", (game_id,)
        ),
        "ingest_events": _count(
            db,
            "SELECT COUNT(*) FROM ingest_events WHERE source_game_id = ?",
            (game_id,),
        ),
        "rating_history": _count(
            db,
            f"SELECT COUNT(*) FROM rating_history WHERE match_id IN ({match_q})",
            (game_id,),
        ),
        "role_rating_history": _count(
            db,
            f"SELECT COUNT(*) FROM role_rating_history WHERE match_id IN ({match_q})",
            (game_id,),
        ),
    }


def _snapshot(db) -> tuple:
    conn = db()
    try:
        return tuple(
            [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2")]
            for t in ("matches", "ingest_events", "players",
                      "rating_history", "role_rating_history")
        )
    finally:
        conn.close()


@pytest.mark.parametrize("target", ["replay_roles", "replay"])
def test_out_of_order_ingest_rolls_back_when_replay_fails(
    client, db, monkeypatch, target
):
    from app.services import ratings, role_ratings

    # Sonraki maç önce gelir; ardından ondan ÖNCE oynanmış maç = sıra-dışı.
    assert _ingest(client, "late", "2026-08-12T20:00:00Z").status_code == 201
    before = _snapshot(db)

    module = role_ratings if target == "replay_roles" else ratings
    with monkeypatch.context() as m:
        m.setattr(module, target, _boom)
        # Ayrı istemci: 500'ü yanıt olarak görmek için (lifespan zaten koştu).
        raw = TestClient(client.app, raise_server_exceptions=False)
        raw.headers.update(client.headers)
        r = _ingest(raw, "early", "2026-08-11T20:00:00Z")
        assert r.status_code == 500

    # Maçın hiçbir izi yok; önceki durum bit-bit aynı.
    assert _traces(db, "early") == {
        "matches": 0, "ingest_events": 0,
        "rating_history": 0, "role_rating_history": 0,
    }
    assert _snapshot(db) == before

    # Tekrar gönderim duplicate SAYILMAZ: 201 ve iki evren dolu.
    r = _ingest(client, "early", "2026-08-11T20:00:00Z")
    assert r.status_code == 201, r.text
    assert r.json()["duplicate"] is False
    traces = _traces(db, "early")
    assert traces["matches"] == 1 and traces["ingest_events"] == 1
    assert traces["rating_history"] == 10
    assert traces["role_rating_history"] == 10
    # Sıra-dışı replay "late"in satırlarını da yeniden kurdu.
    assert _traces(db, "late")["role_rating_history"] == 10


def test_out_of_order_ingest_matches_full_replay(client, db):
    """Mutlu yol: join_transaction değişikliği değişmez 3'ü bozmaz."""
    assert _ingest(client, "b", "2026-08-12T20:00:00Z").status_code == 201
    assert _ingest(client, "a", "2026-08-11T20:00:00Z").status_code == 201
    incremental = _snapshot(db)
    r = client.post("/api/v1/admin/replay")
    assert r.status_code == 200, r.text
    assert _snapshot(db) == incremental
