"""Rol rating evreni (GÖREV 0) — uygunluk, determinizm, PUT positions,
players/leaderboard role_ratings ve admin/replay yeni yanıt şekli.

Spec: docs/rating_contract.md "Rol Rating Evreni", docs/api_contract.md §2/§3/§5.
"""
from conftest import POSITIONS, ROLES_SET, make_payload, make_role_payload

DEFAULT_MU = 25.0
DEFAULT_SIGMA = 25.0 / 3.0


def _role_snapshot(conn):
    return [
        tuple(row)
        for row in conn.execute(
            "SELECT player_id, match_id, role, engine_version,"
            " round(mu_before, 9), round(sigma_before, 9),"
            " round(mu_after, 9), round(sigma_after, 9), round(perf_score, 9) "
            "FROM role_rating_history ORDER BY match_id, player_id"
        )
    ]


def _main_snapshot(conn):
    return [
        tuple(row)
        for row in conn.execute(
            "SELECT player_id, match_id, engine_version,"
            " round(mu_before, 9), round(sigma_before, 9),"
            " round(mu_after, 9), round(sigma_after, 9), round(perf_score, 9) "
            "FROM rating_history ORDER BY match_id, player_id"
        )
    ]


def _ingest_events(conn):
    return [
        tuple(row)
        for row in conn.execute(
            "SELECT id, source, source_game_id, payload_json FROM ingest_events "
            "ORDER BY id"
        )
    ]


def _match_id(conn, source_game_id="6874231955"):
    return conn.execute(
        "SELECT id FROM matches WHERE source_game_id = ?", (source_game_id,)
    ).fetchone()["id"]


# ── Uygunluk kuralı ────────────────────────────────────────────────────────


def test_eligible_match_enters_role_universe(client, db):
    r = client.post("/api/v1/ingest/match", json=make_role_payload())
    assert r.status_code == 201
    conn = db()
    rows = conn.execute(
        "SELECT player_id, role FROM role_rating_history"
    ).fetchall()
    assert len(rows) == 10
    # Her takımda 5 farklı rol → toplamda her rol 2 kez.
    roles = sorted(row["role"] for row in rows)
    assert roles == sorted(POSITIONS * 2)


def test_ineligible_match_does_not_enter_role_universe(client, db):
    """make_payload'ın rol dağılımı bozuktur (team100: MIDDLE iki kez, TOP yok)."""
    r = client.post("/api/v1/ingest/match", json=make_payload())
    assert r.status_code == 201
    conn = db()
    assert (
        conn.execute("SELECT COUNT(*) c FROM role_rating_history").fetchone()["c"]
        == 0
    )
    # Ana evren yine işlemiştir.
    assert conn.execute("SELECT COUNT(*) c FROM rating_history").fetchone()["c"] == 10


def test_null_position_blocks_role_universe(client, db):
    payload = make_role_payload()
    payload["participants"][3]["position"] = None
    client.post("/api/v1/ingest/match", json=payload)
    conn = db()
    assert (
        conn.execute("SELECT COUNT(*) c FROM role_rating_history").fetchone()["c"]
        == 0
    )
    assert conn.execute("SELECT COUNT(*) c FROM rating_history").fetchone()["c"] == 10


def test_duplicate_role_in_team_blocks_role_universe(client, db):
    payload = make_role_payload()
    # team100'de JUNGLE iki kez, TOP hiç.
    payload["participants"][0]["position"] = "JUNGLE"
    client.post("/api/v1/ingest/match", json=payload)
    conn = db()
    assert (
        conn.execute("SELECT COUNT(*) c FROM role_rating_history").fetchone()["c"]
        == 0
    )


def test_void_match_excluded_from_role_universe(client, db):
    client.post(
        "/api/v1/ingest/match",
        json=make_role_payload(source_game_id="remake", duration_s=120),
    )
    conn = db()
    assert (
        conn.execute("SELECT COUNT(*) c FROM role_rating_history").fetchone()["c"]
        == 0
    )


# ── Determinizm ────────────────────────────────────────────────────────────


def test_role_replay_matches_incremental_bit_for_bit(client, db):
    for i, winner in enumerate([100, 200, 100]):
        client.post(
            "/api/v1/ingest/match",
            json=make_role_payload(
                source_game_id=f"game-{i}",
                played_at=f"2026-08-1{i + 1}T20:00:00Z",
                winner_team=winner,
            ),
        )
    conn = db()
    incremental = _role_snapshot(conn)
    assert len(incremental) == 30

    r = client.post("/api/v1/admin/replay")
    assert r.json() == {
        "matches_replayed": 3,
        "role_matches_replayed": 3,
        "engine_version": "openskill-pl-blend30-s2-v1",
    }
    conn = db()
    assert _role_snapshot(conn) == incremental

    # İki kez koşmak da aynı sonucu verir.
    client.post("/api/v1/admin/replay")
    conn = db()
    assert _role_snapshot(conn) == incremental


def test_replay_counts_only_eligible_matches(client):
    client.post("/api/v1/ingest/match", json=make_role_payload(source_game_id="ok"))
    client.post(
        "/api/v1/ingest/match",
        json=make_payload(
            source_game_id="bozuk", played_at="2026-08-12T20:00:00Z"
        ),
    )
    body = client.post("/api/v1/admin/replay").json()
    assert body["matches_replayed"] == 2
    assert body["role_matches_replayed"] == 1


def test_void_replays_both_universes(client, db):
    client.post("/api/v1/ingest/match", json=make_role_payload(source_game_id="g1"))
    client.post(
        "/api/v1/ingest/match",
        json=make_role_payload(
            source_game_id="g2", played_at="2026-08-11T22:00:00Z"
        ),
    )
    conn = db()
    match2 = _match_id(conn, "g2")

    body = client.post(f"/api/v1/matches/{match2}/void").json()
    assert body["matches_replayed"] == 1
    assert body["role_matches_replayed"] == 1

    conn = db()
    assert (
        conn.execute(
            "SELECT COUNT(*) c FROM role_rating_history WHERE match_id = ?",
            (match2,),
        ).fetchone()["c"]
        == 0
    )
    assert (
        conn.execute("SELECT COUNT(*) c FROM role_rating_history").fetchone()["c"]
        == 10
    )


# ── PUT /matches/{id}/positions ────────────────────────────────────────────


def test_positions_unknown_match_404(client):
    r = client.put("/api/v1/matches/999/positions", json={"positions": {}})
    assert r.status_code == 404
    assert "999" in r.json()["detail"]


def test_positions_player_not_in_match_422(client, db):
    client.post("/api/v1/ingest/match", json=make_role_payload())
    conn = db()
    mid = _match_id(conn)
    r = client.put(
        f"/api/v1/matches/{mid}/positions", json={"positions": {"9999": "TOP"}}
    )
    assert r.status_code == 422
    assert "9999" in r.json()["detail"]


def test_positions_invalid_role_422(client, db):
    client.post("/api/v1/ingest/match", json=make_role_payload())
    conn = db()
    mid = _match_id(conn)
    pid = conn.execute(
        "SELECT player_id FROM match_participants WHERE match_id = ? ORDER BY id",
        (mid,),
    ).fetchone()["player_id"]
    r = client.put(
        f"/api/v1/matches/{mid}/positions", json={"positions": {str(pid): "SUPPORT"}}
    )
    assert r.status_code == 422
    assert "SUPPORT" in r.json()["detail"]


def test_positions_non_integer_key_422(client, db):
    client.post("/api/v1/ingest/match", json=make_role_payload())
    conn = db()
    mid = _match_id(conn)
    r = client.put(
        f"/api/v1/matches/{mid}/positions", json={"positions": {"abc": "TOP"}}
    )
    assert r.status_code == 422


def test_positions_invalid_input_does_not_touch_db(client, db):
    client.post("/api/v1/ingest/match", json=make_role_payload())
    conn = db()
    mid = _match_id(conn)
    before = _role_snapshot(conn)
    pids = [
        row["player_id"]
        for row in conn.execute(
            "SELECT player_id FROM match_participants WHERE match_id = ? ORDER BY id",
            (mid,),
        )
    ]
    # İlk anahtar geçerli, ikincisi değil → hiçbiri uygulanmamalı.
    r = client.put(
        f"/api/v1/matches/{mid}/positions",
        json={"positions": {str(pids[0]): "UTILITY", "9999": "TOP"}},
    )
    assert r.status_code == 422
    conn = db()
    assert _role_snapshot(conn) == before
    assert (
        conn.execute(
            "SELECT position FROM match_participants "
            "WHERE match_id = ? AND player_id = ?",
            (mid, pids[0]),
        ).fetchone()["position"]
        == POSITIONS[0]
    )


def test_positions_fix_makes_match_eligible(client, db):
    """Bozuk rol setli maç, düzeltmeden sonra rol evrenine girer."""
    client.post("/api/v1/ingest/match", json=make_payload())
    conn = db()
    mid = _match_id(conn)
    assert (
        conn.execute("SELECT COUNT(*) c FROM role_rating_history").fetchone()["c"]
        == 0
    )
    rows = conn.execute(
        "SELECT player_id FROM match_participants WHERE match_id = ? ORDER BY id",
        (mid,),
    ).fetchall()
    fixed = {
        str(row["player_id"]): POSITIONS[i % 5] for i, row in enumerate(rows)
    }
    main_before = _main_snapshot(conn)
    events_before = _ingest_events(conn)

    r = client.put(f"/api/v1/matches/{mid}/positions", json={"positions": fixed})
    assert r.status_code == 200
    assert r.json() == {"updated": 10, "role_matches_replayed": 1}

    conn = db()
    assert (
        conn.execute("SELECT COUNT(*) c FROM role_rating_history").fetchone()["c"]
        == 10
    )
    # Ana evren ve ham ingest bit-bit değişmemiştir.
    assert _main_snapshot(conn) == main_before
    assert _ingest_events(conn) == events_before


def test_positions_partial_update_can_break_eligibility(client, db):
    client.post("/api/v1/ingest/match", json=make_role_payload())
    conn = db()
    mid = _match_id(conn)
    main_before = _main_snapshot(conn)
    pid = conn.execute(
        "SELECT player_id FROM match_participants WHERE match_id = ? ORDER BY id",
        (mid,),
    ).fetchone()["player_id"]

    r = client.put(
        f"/api/v1/matches/{mid}/positions", json={"positions": {str(pid): None}}
    )
    assert r.status_code == 200
    assert r.json() == {"updated": 1, "role_matches_replayed": 0}

    conn = db()
    assert (
        conn.execute("SELECT COUNT(*) c FROM role_rating_history").fetchone()["c"]
        == 0
    )
    assert _main_snapshot(conn) == main_before


def test_positions_survive_role_replay(client, db):
    """Düzeltilmiş roller replay'de kaybolmaz (payload'dan değil, kolondan okunur)."""
    client.post("/api/v1/ingest/match", json=make_role_payload())
    conn = db()
    mid = _match_id(conn)
    pids = [
        row["player_id"]
        for row in conn.execute(
            "SELECT player_id FROM match_participants WHERE match_id = ? "
            "AND team = 100 ORDER BY id",
            (mid,),
        )
    ]
    # team100'de TOP ile UTILITY'yi yer değiştir (rol seti hâlâ geçerli).
    client.put(
        f"/api/v1/matches/{mid}/positions",
        json={"positions": {str(pids[0]): "UTILITY", str(pids[4]): "TOP"}},
    )
    conn = db()
    after_fix = _role_snapshot(conn)
    assert (
        conn.execute(
            "SELECT role FROM role_rating_history WHERE player_id = ?", (pids[0],)
        ).fetchone()["role"]
        == "UTILITY"
    )

    client.post("/api/v1/admin/replay")
    conn = db()
    assert _role_snapshot(conn) == after_fix


# ── players / leaderboard role_ratings ─────────────────────────────────────


def test_role_ratings_default_shape(client):
    client.post("/api/v1/players", json={"display_name": "Teo"})
    p = client.get("/api/v1/players").json()[0]
    assert set(p["role_ratings"]) == ROLES_SET
    for role, rr in p["role_ratings"].items():
        assert rr["mu"] == DEFAULT_MU
        assert abs(rr["sigma"] - DEFAULT_SIGMA) < 1e-9
        assert rr["perf_avg"] == 1.0
        # Rol evreni ANA evrenle AYNI S'i kullanır (aktif blend30-s2: S=2):
        # 25 - 2*25/3 ≈ 8.33 (nötr nokta; blend20'de 0 idi).
        assert abs(rr["score"] - (DEFAULT_MU - 2.0 * DEFAULT_SIGMA)) < 1e-9
        assert rr["matches"] == 0


def test_role_ratings_after_eligible_match(client, db):
    client.post("/api/v1/ingest/match", json=make_role_payload())
    conn = db()
    played = {
        row["player_id"]: row["position"]
        for row in conn.execute(
            "SELECT player_id, position FROM match_participants"
        )
    }
    for p in client.get("/api/v1/players").json():
        role = played[p["id"]]
        for r, rr in p["role_ratings"].items():
            if r == role:
                assert rr["matches"] == 1
                assert rr["mu"] != DEFAULT_MU
                assert rr["perf_avg"] is not None
            else:
                assert rr["matches"] == 0
                assert rr["mu"] == DEFAULT_MU


def test_role_ratings_not_populated_by_ineligible_match(client):
    client.post("/api/v1/ingest/match", json=make_payload())
    for p in client.get("/api/v1/players").json():
        for rr in p["role_ratings"].values():
            assert rr["matches"] == 0
            assert rr["mu"] == DEFAULT_MU
    # Ana rating yine değişmiştir.
    assert all(
        p["rating"]["mu"] != DEFAULT_MU for p in client.get("/api/v1/players").json()
    )


def test_leaderboard_includes_role_ratings(client):
    client.post("/api/v1/ingest/match", json=make_role_payload())
    board = client.get("/api/v1/leaderboard").json()
    assert board
    for p in board:
        assert set(p["role_ratings"]) == ROLES_SET
