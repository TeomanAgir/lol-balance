from conftest import make_payload
from rating import Engine

# GÖREV 18 testleri rating tarihçesiyle çapraz doğrulama yapar; sabitler
# oradan yeniden kullanılır (üçüncü kopya çıkarmamak için, mevcut desen).
from test_rating_history import ENGINE_VERSION, GOOD_STATS


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


# --- score_before / score_after (api_contract §3, GÖREV 18) ---------------


_RATING_CHANGE_KEYS = {
    "mu_before", "sigma_before", "mu_after", "sigma_after",
    "score_before", "score_after",
}


def _history_points(client, player_id):
    r = client.get(f"/api/v1/players/{player_id}/rating-history")
    assert r.status_code == 200
    return r.json()["points"]


def _default_score() -> float:
    """Hiç maçı olmayan oyuncunun efektif score'u: default rating + nötr P_avg."""
    engine = Engine(version=ENGINE_VERSION)
    default = engine.default_rating()
    return round(engine.effective(default.mu, default.sigma, 1.0).score, 2)


def _ingest_three_varied(client):
    """Perf'leri maçtan maça değişen 3 maç → kümülatif P_avg anlamlı olur."""
    payloads = [
        make_payload(source_game_id="m18-1", played_at="2026-08-11T20:00:00Z"),
        make_payload(source_game_id="m18-2", played_at="2026-08-12T20:00:00Z",
                     winner_team=200),
        make_payload(source_game_id="m18-3", played_at="2026-08-13T20:00:00Z"),
    ]
    payloads[0]["participants"][0]["stats"] = dict(GOOD_STATS)
    payloads[1]["participants"][7]["stats"] = dict(GOOD_STATS)
    payloads[2]["participants"][3]["stats"] = dict(GOOD_STATS)
    for payload in payloads:
        assert client.post("/api/v1/ingest/match", json=payload).status_code == 201


def test_match_scores_cross_consistent_with_rating_history(client):
    """Aynı maçın score_after'ı iki endpoint'te BİREBİR aynıdır; score_before
    oyuncunun önceki noktasının score_after'ıdır (ilk maçta default durum)."""
    _ingest_three_varied(client)
    matches = client.get("/api/v1/matches").json()
    assert len(matches) == 3

    default_score = _default_score()
    histories: dict[int, list[dict]] = {}
    for m in matches:
        for p in m["participants"]:
            change = p["rating_change"]
            assert set(change) == _RATING_CHANGE_KEYS
            assert change["score_after"] == round(change["score_after"], 2)
            assert change["score_before"] == round(change["score_before"], 2)

            pid = p["player_id"]
            points = histories.setdefault(pid, _history_points(client, pid))
            idx = next(
                i for i, pt in enumerate(points) if pt["match_id"] == m["id"]
            )
            # Çapraz tutarlılık: rating-history'nin score_after'ı ile birebir.
            assert change["score_after"] == points[idx]["score_after"]
            expected_before = (
                points[idx - 1]["score_after"] if idx > 0 else default_score
            )
            assert change["score_before"] == expected_before


def test_losing_high_performer_can_gain_score(client):
    """Karar #1'in kabul edilen ödünleşimi: kaybeden ama yüksek perf'li oyuncuda
    W/L çekirdeği (mu) düşerken efektif score DELTASI pozitif olabilir —
    web UI'daki delta bu yüzden mu farkı değil score farkıdır (GÖREV 18)."""
    payload = make_payload(source_game_id="m18-loser", winner_team=200)
    payload["participants"][0]["stats"] = dict(GOOD_STATS)  # team 100 → kaybetti
    assert client.post("/api/v1/ingest/match", json=payload).status_code == 201

    m = client.get("/api/v1/matches").json()[0]
    loser = next(
        p for p in m["participants"] if p["stats"]["kills"] == GOOD_STATS["kills"]
    )
    assert loser["team"] != m["winner_team"]
    change = loser["rating_change"]
    # W/L çekirdeği maçı kaybettiğini söylüyor...
    assert change["mu_after"] < change["mu_before"]
    # ...ama yüksek perf, efektif score'u yükseltti (delta pozitif).
    assert change["score_after"] > change["score_before"]


def test_match_scores_identical_after_replay(client):
    """Determinizm: POST /admin/replay sonrası GET /matches bit-bit aynı.

    Maçlardan biri sıra-dışı ingest edilir ki incremental/replay yolları da
    devreye girsin (auto-replay tetiklenir, sonuç yine aynı kalmalı)."""
    _ingest_three_varied(client)
    # Sıra-dışı: en eski maç en son gelir → ingest auto-replay koşar.
    payload = make_payload(
        source_game_id="m18-old", played_at="2026-08-10T20:00:00Z",
        winner_team=200,
    )
    payload["participants"][5]["stats"] = dict(GOOD_STATS)
    assert client.post("/api/v1/ingest/match", json=payload).status_code == 201

    before = client.get("/api/v1/matches").json()
    r = client.post("/api/v1/admin/replay")
    assert r.status_code == 200
    assert r.json()["matches_replayed"] == 4
    assert client.get("/api/v1/matches").json() == before


def test_void_scores_null_on_voided_and_consistent_on_survivors(client):
    """Void maçta rating_change (score'lar dahil) null kalır; kalan maçların
    score'ları replay sonrası tarihçeyle tutarlı biçimde KAYAR."""
    m1 = client.post(
        "/api/v1/ingest/match",
        json=make_payload(source_game_id="m18-v1", played_at="2026-08-11T20:00:00Z"),
    ).json()["match_id"]
    payload2 = make_payload(
        source_game_id="m18-v2", played_at="2026-08-12T20:00:00Z", winner_team=200,
    )
    payload2["participants"][2]["stats"] = dict(GOOD_STATS)
    m2 = client.post("/api/v1/ingest/match", json=payload2).json()["match_id"]

    assert client.post(f"/api/v1/matches/{m1}/void").status_code == 200

    matches = {m["id"]: m for m in client.get("/api/v1/matches").json()}
    assert all(
        p["rating_change"] is None for p in matches[m1]["participants"]
    )
    # m2 artık herkesin İLK maçı: score_before default duruma döner ve
    # score_after rating-history ile birebir tutar.
    default_score = _default_score()
    for p in matches[m2]["participants"]:
        points = _history_points(client, p["player_id"])
        assert [pt["match_id"] for pt in points] == [m2]
        change = p["rating_change"]
        assert change["score_before"] == default_score
        assert change["score_after"] == points[0]["score_after"]
