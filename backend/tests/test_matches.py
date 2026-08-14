from conftest import make_payload


def test_list_matches_with_participants_and_rating_changes(client):
    client.post("/api/v1/ingest/match", json=make_payload())
    matches = client.get("/api/v1/matches").json()
    assert len(matches) == 1
    m = matches[0]
    assert m["winner_team"] == 100
    assert m["status"] == "valid"
    assert len(m["participants"]) == 10
    for p in m["participants"]:
        assert p["display_name"]
        change = p["rating_change"]
        assert change is not None
        assert change["mu_before"] != change["mu_after"]


def test_list_matches_limit_and_order(client):
    for i in range(3):
        client.post(
            "/api/v1/ingest/match",
            json=make_payload(
                source_game_id=f"game-{i}",
                played_at=f"2026-08-11T2{i}:00:00Z",
            ),
        )
    matches = client.get("/api/v1/matches", params={"limit": 2}).json()
    assert len(matches) == 2
    assert matches[0]["played_at"] > matches[1]["played_at"]


def test_get_match_identical_to_list_element(client):
    """api_contract §3 (GÖREV 10): tekil maç liste elemanıyla BİREBİR aynı şekil."""
    r = client.post("/api/v1/ingest/match", json=make_payload())
    match_id = r.json()["match_id"]

    detail = client.get(f"/api/v1/matches/{match_id}")
    assert detail.status_code == 200
    listed = client.get("/api/v1/matches").json()[0]
    assert detail.json() == listed
    assert detail.json()["id"] == match_id


def test_get_match_unknown_404(client):
    r = client.get("/api/v1/matches/999")
    assert r.status_code == 404


def test_get_void_match_still_returned(client):
    match_id = client.post(
        "/api/v1/ingest/match", json=make_payload()
    ).json()["match_id"]
    assert client.post(f"/api/v1/matches/{match_id}/void").status_code == 200

    body = client.get(f"/api/v1/matches/{match_id}").json()
    assert body["status"] == "void"
    # Void sonrası rating satırları silinir → rating_change null döner.
    assert all(p["rating_change"] is None for p in body["participants"])


def test_void_triggers_replay(client, db):
    client.post("/api/v1/ingest/match", json=make_payload(source_game_id="g1"))
    client.post(
        "/api/v1/ingest/match",
        json=make_payload(source_game_id="g2", played_at="2026-08-11T22:00:00Z"),
    )
    conn = db()
    match2 = conn.execute(
        "SELECT id FROM matches WHERE source_game_id='g2'"
    ).fetchone()["id"]

    r = client.post(f"/api/v1/matches/{match2}/void")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "void"
    assert body["matches_replayed"] == 1  # sadece g1 kaldı

    conn = db()
    assert (
        conn.execute(
            "SELECT COUNT(*) c FROM rating_history WHERE match_id=?", (match2,)
        ).fetchone()["c"]
        == 0
    )
    # g1 rating'leri hâlâ mevcut.
    assert conn.execute("SELECT COUNT(*) c FROM rating_history").fetchone()["c"] == 10


def test_void_unknown_match_404(client):
    r = client.post("/api/v1/matches/999/void")
    assert r.status_code == 404
