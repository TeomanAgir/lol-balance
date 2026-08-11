from conftest import make_payload


def _history_snapshot(conn):
    return [
        tuple(row)
        for row in conn.execute(
            "SELECT player_id, match_id, engine_version,"
            " round(mu_before, 9), round(sigma_before, 9),"
            " round(mu_after, 9), round(sigma_after, 9) "
            "FROM rating_history ORDER BY match_id, player_id"
        )
    ]


def test_replay_deterministic_equals_incremental(client, db):
    # 3 maç, farklı kazananlarla, kronolojik sırada ingest edilir.
    for i, winner in enumerate([100, 200, 100]):
        r = client.post(
            "/api/v1/ingest/match",
            json=make_payload(
                source_game_id=f"game-{i}",
                played_at=f"2026-08-1{i + 1}T20:00:00Z",
                winner_team=winner,
            ),
        )
        assert r.status_code == 201

    conn = db()
    incremental = _history_snapshot(conn)
    assert len(incremental) == 30

    r = client.post("/api/v1/admin/replay")
    assert r.status_code == 200
    assert r.json() == {
        "matches_replayed": 3,
        "engine_version": "openskill-pl-perf-v1",
    }

    conn = db()
    assert _history_snapshot(conn) == incremental


def test_replay_skips_void_matches(client, db):
    client.post("/api/v1/ingest/match", json=make_payload(source_game_id="g1"))
    client.post(
        "/api/v1/ingest/match",
        json=make_payload(
            source_game_id="g2",
            played_at="2026-08-12T20:00:00Z",
            duration_s=120,  # remake → otomatik void
        ),
    )
    r = client.post("/api/v1/admin/replay")
    assert r.json()["matches_replayed"] == 1

    conn = db()
    assert conn.execute("SELECT COUNT(*) c FROM rating_history").fetchone()["c"] == 10


def test_replay_out_of_order_ingest_reorders_by_played_at(client, db):
    # Önce daha YENİ maç ingest edilir, sonra eski. Replay played_at'e göre sıralar;
    # incremental geçmişten farklı bir rating_history üretebilir, ama deterministiktir.
    client.post(
        "/api/v1/ingest/match",
        json=make_payload(source_game_id="yeni", played_at="2026-08-12T20:00:00Z"),
    )
    client.post(
        "/api/v1/ingest/match",
        json=make_payload(
            source_game_id="eski",
            played_at="2026-08-10T20:00:00Z",
            winner_team=200,
        ),
    )
    client.post("/api/v1/admin/replay")
    conn = db()
    first = _history_snapshot(conn)

    client.post("/api/v1/admin/replay")
    conn = db()
    assert _history_snapshot(conn) == first
