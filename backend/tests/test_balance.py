"""POST /balance — rol atamalı yanıt (api_contract §4, GÖREV 0).

Dengeleme artık HER ZAMAN rol bazlıdır; yanıt şekli değişti
(team_100/team_200 = [{player_id, position}]). Eski salt-id şekli kaldırıldı.
"""
from conftest import ROLES_SET, make_role_payload, make_roster_payload


def _ten_players(client):
    return [
        client.post("/api/v1/players", json={"display_name": f"P{i}"}).json()["id"]
        for i in range(10)
    ]


def _ids(team):
    return [slot["player_id"] for slot in team]


def test_balance_contract_response(client):
    ids = _ten_players(client)
    r = client.post("/api/v1/balance", json={"player_ids": ids, "top_n": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["engine_version"] == "openskill-pl-blend20-v1"
    assert len(body["suggestions"]) == 3
    for s in body["suggestions"]:
        assert len(s["team_100"]) == 5
        assert len(s["team_200"]) == 5
        assert sorted(_ids(s["team_100"]) + _ids(s["team_200"])) == sorted(ids)
        # Her takımda 5 farklı rol tam 1'er kez.
        assert {slot["position"] for slot in s["team_100"]} == ROLES_SET
        assert {slot["position"] for slot in s["team_200"]} == ROLES_SET
        assert 0.0 <= s["p_win_team_100"] <= 1.0
    qualities = [s["quality"] for s in body["suggestions"]]
    assert qualities == sorted(qualities, reverse=True)
    # Herkes default prior'da → mükemmel denge mümkün.
    assert abs(qualities[0] - 1.0) < 1e-6


def test_balance_default_top_n(client):
    ids = _ten_players(client)
    r = client.post("/api/v1/balance", json={"player_ids": ids})
    assert len(r.json()["suggestions"]) == 3


def test_balance_uses_role_ratings_after_match(client):
    client.post("/api/v1/ingest/match", json=make_role_payload())
    players = client.get("/api/v1/players").json()
    ids = [p["id"] for p in players]
    r = client.post("/api/v1/balance", json={"player_ids": ids, "top_n": 1})
    s = r.json()["suggestions"][0]
    # Kazananlar/kaybedenler ayrıştığı için orijinal 5-5 ayrımı artık en dengeli olamaz.
    assert s["quality"] > 0.9
    assert {slot["position"] for slot in s["team_100"]} == ROLES_SET


def test_balance_deterministic(client):
    client.post("/api/v1/ingest/match", json=make_role_payload())
    ids = [p["id"] for p in client.get("/api/v1/players").json()]
    first = client.post("/api/v1/balance", json={"player_ids": ids}).json()
    second = client.post("/api/v1/balance", json={"player_ids": ids}).json()
    assert first == second


def test_balance_splits_two_strong_top_laners(client):
    """rating_contract: sadece TOP verisi olan iki güçlü oyuncu aynı takıma düşmez.

    A ve B yalnızca TOP oynar ve hep kazanır → TOP'ta güçlü, diğer 4 rolde
    nötr. Aynı takıma konurlarsa yalnız biri TOP oynayabilir (diğeri nötr bir
    rolde ziyan olur) ve takımlar ayrışır; ayrı takımlarda ikisi de TOP oynar
    ve denge korunur.
    """
    ids = [
        client.post("/api/v1/players", json={"display_name": f"P{i}"}).json()["id"]
        for i in range(12)
    ]
    a, b = ids[0], ids[1]
    fill = ids[2:]  # 10 dolgu oyuncusu

    # A ve B, dolgu oyuncularının sabit bir dizilimine karşı hep kazanır.
    for n in range(3):
        for strong, slot in ((a, 0), (b, 1)):
            client.post(
                "/api/v1/ingest/match",
                json=make_roster_payload(
                    source_game_id=f"g-{strong}-{n}",
                    played_at=f"2026-08-{10 + n * 2 + slot:02d}T20:00:00Z",
                    team100_ids=[strong, *fill[0:4]],
                    team200_ids=fill[4:9],
                    winner_team=100,
                ),
            )

    pool = [a, b, *fill[0:8]]
    body = client.post(
        "/api/v1/balance", json={"player_ids": pool, "top_n": 1}
    ).json()
    s = body["suggestions"][0]
    t100, t200 = _ids(s["team_100"]), _ids(s["team_200"])
    assert (a in t100) != (b in t100), "iki güçlü TOP aynı takıma düştü"
    assert (a in t200) != (b in t200)


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
