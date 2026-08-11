from conftest import make_payload

DEFAULT_MU = 25.0
DEFAULT_SIGMA = 25.0 / 3.0


def test_create_and_list_with_default_prior(client):
    r = client.post(
        "/api/v1/players", json={"display_name": "Teo", "riot_id": "Teoman#TR1"}
    )
    assert r.status_code == 201
    pid = r.json()["id"]

    players = client.get("/api/v1/players").json()
    assert len(players) == 1
    p = players[0]
    assert p["id"] == pid
    assert p["display_name"] == "Teo"
    assert p["riot_id"] == "Teoman#TR1"
    assert p["puuid"] is None  # manuel oluşturulan oyuncuda puuid ilk maça kadar NULL
    assert p["matches_played"] == 0
    assert p["rating"]["mu"] == DEFAULT_MU
    assert abs(p["rating"]["sigma"] - DEFAULT_SIGMA) < 1e-9
    assert abs(p["rating"]["ordinal"] - (DEFAULT_MU - 3 * DEFAULT_SIGMA)) < 1e-9


def test_patch_display_name(client):
    pid = client.post("/api/v1/players", json={"display_name": "Eski"}).json()["id"]
    r = client.patch(f"/api/v1/players/{pid}", json={"display_name": "Yeni"})
    assert r.status_code == 200
    assert r.json()["display_name"] == "Yeni"


def test_patch_unknown_player_404(client):
    r = client.patch("/api/v1/players/12345", json={"display_name": "X"})
    assert r.status_code == 404


def test_matches_played_and_rating_after_ingest(client):
    client.post("/api/v1/ingest/match", json=make_payload())
    players = client.get("/api/v1/players").json()
    assert len(players) == 10
    for p in players:
        assert p["matches_played"] == 1
        assert p["rating"]["mu"] != DEFAULT_MU
        assert p["puuid"] is not None  # ingest'ten gelen oyuncularda puuid dolu


def test_leaderboard_sorted_by_ordinal(client):
    client.post("/api/v1/ingest/match", json=make_payload())
    board = client.get("/api/v1/leaderboard").json()
    ordinals = [p["rating"]["ordinal"] for p in board]
    assert ordinals == sorted(ordinals, reverse=True)
    # Kazanan takım üstte olmalı: winner_team=100 → ilk 5 participant.
    assert board[0]["rating"]["mu"] > DEFAULT_MU
