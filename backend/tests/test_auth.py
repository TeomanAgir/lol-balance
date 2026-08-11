def test_missing_key(client):
    client.headers.pop("X-API-Key")
    r = client.get("/api/v1/players")
    assert r.status_code == 401
    assert "detail" in r.json()


def test_wrong_key(client):
    r = client.get("/api/v1/players", headers={"X-API-Key": "yanlis"})
    assert r.status_code == 401
