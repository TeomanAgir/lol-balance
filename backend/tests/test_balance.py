from conftest import make_payload


def _ten_players(client):
    return [
        client.post("/api/v1/players", json={"display_name": f"P{i}"}).json()["id"]
        for i in range(10)
    ]


def test_balance_contract_response(client):
    ids = _ten_players(client)
    r = client.post("/api/v1/balance", json={"player_ids": ids, "top_n": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["engine_version"] == "openskill-pl-perf-v1"
    assert len(body["suggestions"]) == 3
    for s in body["suggestions"]:
        assert len(s["team_100"]) == 5
        assert len(s["team_200"]) == 5
        assert sorted(s["team_100"] + s["team_200"]) == sorted(ids)
        assert 0.0 <= s["p_win_team_100"] <= 1.0
    qualities = [s["quality"] for s in body["suggestions"]]
    assert qualities == sorted(qualities, reverse=True)
    # Herkes default prior'da → mükemmel denge mümkün.
    assert abs(qualities[0] - 1.0) < 1e-6


def test_balance_default_top_n(client):
    ids = _ten_players(client)
    r = client.post("/api/v1/balance", json={"player_ids": ids})
    assert len(r.json()["suggestions"]) == 3


def test_balance_uses_ratings_after_match(client):
    client.post("/api/v1/ingest/match", json=make_payload())
    players = client.get("/api/v1/players").json()
    ids = [p["id"] for p in players]
    r = client.post("/api/v1/balance", json={"player_ids": ids, "top_n": 1})
    s = r.json()["suggestions"][0]
    # Kazananlar/kaybedenler ayrıştığı için orijinal 5-5 ayrımı artık en dengeli olamaz.
    assert s["quality"] > 0.9


def test_balance_not_ten_rejected(client):
    ids = _ten_players(client)
    r = client.post("/api/v1/balance", json={"player_ids": ids[:9]})
    assert r.status_code == 422


def test_balance_duplicate_ids_rejected(client):
    ids = _ten_players(client)
    ids[9] = ids[0]
    r = client.post("/api/v1/balance", json={"player_ids": ids})
    assert r.status_code == 422


def test_balance_unknown_player_rejected(client):
    ids = _ten_players(client)
    ids[9] = 9999
    r = client.post("/api/v1/balance", json={"player_ids": ids})
    assert r.status_code == 422
    assert "9999" in r.json()["detail"]
