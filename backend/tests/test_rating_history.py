"""GET /players/{id}/rating-history (api_contract §2 "Rating tarihçesi", GÖREV 10).

Harman formülünün matematiği rating paketinde test edilir; buradaki testler
backend'in doğru noktaları, doğru sırada ve TARİHSEL P_avg ile servis ettiğini,
replay determinizmini ve leaderboard'la son nokta eşleşmesini doğrular.
"""
from __future__ import annotations

import sqlite3

from conftest import make_payload
from rating import Engine

# ENGINE_VERSION seçilebilen client (conftest.client'ın kopyası) zaten burada
# tanımlı; üçüncü bir kopya çıkarmamak için yeniden kullanılır.
from test_perf_rating import _client as engine_client

ENGINE_VERSION = "openskill-pl-blend30-s2-v1"

GOOD_STATS = {
    "kills": 15, "deaths": 1, "assists": 12,
    "gold": 18000, "cs": 260,
    "damage_to_champs": 42000, "vision_score": 45,
}

FIRST_PUUID = "abc-123-..."  # make_payload participants[0] (team100)


def _player_id(client, puuid=FIRST_PUUID):
    players = client.get("/api/v1/players").json()
    return next(p["id"] for p in players if p["puuid"] == puuid)


def _history(client, player_id):
    r = client.get(f"/api/v1/players/{player_id}/rating-history")
    assert r.status_code == 200
    return r.json()


def _ingest(client, **kwargs):
    r = client.post("/api/v1/ingest/match", json=make_payload(**kwargs))
    assert r.status_code == 201
    return r.json()["match_id"]


# --- Happy path ---------------------------------------------------------


def test_history_returns_point_per_valid_match_in_chronological_order(client):
    m1 = _ingest(client, source_game_id="rh-1", played_at="2026-08-11T20:00:00Z")
    m2 = _ingest(
        client, source_game_id="rh-2", played_at="2026-08-12T20:00:00Z",
        winner_team=200,
    )
    body = _history(client, _player_id(client))

    assert body["engine_version"] == ENGINE_VERSION
    points = body["points"]
    assert [p["match_id"] for p in points] == [m1, m2]
    assert [p["played_at"] for p in points] == [
        "2026-08-11T20:00:00Z", "2026-08-12T20:00:00Z"
    ]
    # participants[0] team100: 1. maçı kazandı, 2. maçı kaybetti.
    assert [p["win"] for p in points] == [True, False]
    assert points[0]["champion"] == "Ahri"
    assert points[0]["position"] == "MIDDLE"
    assert points[0]["stats"] == {"kills": 7, "deaths": 2, "assists": 9}
    for p in points:
        assert p["score_after"] == round(p["score_after"], 2)


def test_history_score_after_matches_blend_formula_with_running_p_avg(client, db):
    """score_after tarihseldir: P_avg o maça kadarki önekten gelir."""
    payload = make_payload(source_game_id="rh-p1", played_at="2026-08-11T20:00:00Z")
    payload["participants"][0]["stats"] = dict(GOOD_STATS)
    assert client.post("/api/v1/ingest/match", json=payload).status_code == 201
    assert client.post(
        "/api/v1/ingest/match",
        json=make_payload(source_game_id="rh-p2", played_at="2026-08-12T20:00:00Z"),
    ).status_code == 201

    player_id = _player_id(client)
    points = _history(client, player_id)["points"]

    conn = db()
    rows = conn.execute(
        "SELECT rh.mu_after, rh.sigma_after, rh.perf_score FROM rating_history rh "
        "JOIN matches m ON m.id = rh.match_id "
        "WHERE rh.player_id = ? ORDER BY m.played_at, m.id",
        (player_id,),
    ).fetchall()
    assert len(rows) == 2
    # Senaryo anlamlı olsun: iki maçın perf'i farklı, yani kümülatif ortalama
    # ikinci noktada değişiyor.
    assert rows[0]["perf_score"] != rows[1]["perf_score"]

    engine = Engine(version=ENGINE_VERSION)
    running = []
    total = 0.0
    for i, row in enumerate(rows, start=1):
        total += row["perf_score"]
        running.append(
            engine.effective(row["mu_after"], row["sigma_after"], total / i).score
        )
    assert [p["score_after"] for p in points] == [round(v, 2) for v in running]
    # İlk noktanın P_avg'i SADECE ilk maçtan gelir: kariyer ortalamasıyla
    # hesaplanmış olsaydı farklı çıkardı.
    career = (rows[0]["perf_score"] + rows[1]["perf_score"]) / 2
    assert round(
        engine.effective(rows[0]["mu_after"], rows[0]["sigma_after"], career).score, 2
    ) != points[0]["score_after"]


def test_last_point_equals_current_leaderboard_score(client):
    for i, played_at in enumerate(
        ["2026-08-11T20:00:00Z", "2026-08-12T20:00:00Z", "2026-08-13T20:00:00Z"]
    ):
        payload = make_payload(
            source_game_id=f"rh-lb-{i}", played_at=played_at,
            winner_team=100 if i % 2 == 0 else 200,
        )
        payload["participants"][i]["stats"] = dict(GOOD_STATS)
        assert client.post("/api/v1/ingest/match", json=payload).status_code == 201

    board = client.get("/api/v1/leaderboard").json()
    assert len(board) == 10
    for player in board:
        points = _history(client, player["id"])["points"]
        assert points, "her oyuncu 3 maçın hepsinde oynadı"
        assert points[-1]["score_after"] == round(player["rating"]["score"], 2)


# --- Kenar durumlar -----------------------------------------------------


def test_unknown_player_404(client):
    r = client.get("/api/v1/players/999/rating-history")
    assert r.status_code == 404


def test_player_without_matches_returns_empty_points(client):
    created = client.post(
        "/api/v1/players", json={"display_name": "Maçsız", "riot_id": None}
    )
    assert created.status_code == 201
    body = _history(client, created.json()["id"])
    assert body["points"] == []
    assert body["engine_version"] == ENGINE_VERSION


def test_void_match_excluded_from_history(client):
    m1 = _ingest(client, source_game_id="rh-v1", played_at="2026-08-11T20:00:00Z")
    m2 = _ingest(client, source_game_id="rh-v2", played_at="2026-08-12T20:00:00Z")
    player_id = _player_id(client)
    assert len(_history(client, player_id)["points"]) == 2

    assert client.post(f"/api/v1/matches/{m2}/void").status_code == 200
    points = _history(client, player_id)["points"]
    assert [p["match_id"] for p in points] == [m1]


def test_stats_null_when_kda_all_null(client):
    payload = make_payload(source_game_id="rh-nostats")
    payload["source"] = "manual"
    payload["participants"][0]["stats"] = None
    # k/d/a yok ama başka stat var → yine stats: null (üçü de null kuralı).
    payload["participants"][1]["stats"] = {
        "gold": 12000, "cs": 180, "damage_to_champs": 20000, "vision_score": 15,
    }
    assert client.post("/api/v1/ingest/match", json=payload).status_code == 201

    for puuid in (FIRST_PUUID, "puuid-01"):
        points = _history(client, _player_id(client, puuid))["points"]
        assert len(points) == 1
        assert points[0]["stats"] is None
    # Statlı katılımcıda stats dolu kalır.
    other = _history(client, _player_id(client, "puuid-02"))["points"]
    assert other[0]["stats"] == {"kills": 7, "deaths": 2, "assists": 9}


def test_history_handles_rows_without_perf_score(client, db):
    """Eski (perf'siz) satır: NULL perf ortalamaya girmez (migration 0002 notu)."""
    _ingest(client, source_game_id="rh-np1", played_at="2026-08-11T20:00:00Z")
    payload = make_payload(source_game_id="rh-np2", played_at="2026-08-12T20:00:00Z")
    payload["participants"][0]["stats"] = dict(GOOD_STATS)
    assert client.post("/api/v1/ingest/match", json=payload).status_code == 201

    player_id = _player_id(client)
    conn = db()
    first_match = conn.execute(
        "SELECT id FROM matches WHERE source_game_id = 'rh-np1'"
    ).fetchone()["id"]
    with conn:
        conn.execute(
            "UPDATE rating_history SET perf_score = NULL "
            "WHERE player_id = ? AND match_id = ?",
            (player_id, first_match),
        )

    points = _history(client, player_id)["points"]
    assert len(points) == 2

    conn = db()
    rows = conn.execute(
        "SELECT rh.mu_after, rh.sigma_after, rh.perf_score FROM rating_history rh "
        "JOIN matches m ON m.id = rh.match_id "
        "WHERE rh.player_id = ? ORDER BY m.played_at, m.id",
        (player_id,),
    ).fetchall()
    assert rows[0]["perf_score"] is None

    engine = Engine(version=ENGINE_VERSION)
    # Hiç perf yokken nötr P_avg=1.0; ikinci noktada ortalama SADECE 2. maçtan.
    assert points[0]["score_after"] == round(
        engine.effective(rows[0]["mu_after"], rows[0]["sigma_after"], 1.0).score, 2
    )
    assert points[1]["score_after"] == round(
        engine.effective(
            rows[1]["mu_after"], rows[1]["sigma_after"], rows[1]["perf_score"]
        ).score,
        2,
    )


def test_history_order_follows_replay_sort_key_after_out_of_order_ingest(client):
    later = _ingest(client, source_game_id="rh-o2", played_at="2026-08-12T20:00:00Z")
    earlier = _ingest(client, source_game_id="rh-o1", played_at="2026-08-11T20:00:00Z")
    points = _history(client, _player_id(client))["points"]
    # Sıra kronolojiktir (ingest sırası değil) — replay sort-key'i (played_at, id).
    assert [p["match_id"] for p in points] == [earlier, later]
    assert points[0]["played_at"] < points[1]["played_at"]


def test_history_under_non_blend_engine_uses_ordinal(tmp_path, monkeypatch):
    """Harman olmayan version: score_after = mu_after - 3*sigma_after."""
    db_path = tmp_path / "nonblend.db"
    with engine_client(db_path, monkeypatch, engine_version="openskill-pl-v1") as c:
        for i, played_at in enumerate(
            ["2026-08-11T20:00:00Z", "2026-08-12T20:00:00Z"]
        ):
            assert c.post(
                "/api/v1/ingest/match",
                json=make_payload(source_game_id=f"rh-nb-{i}", played_at=played_at),
            ).status_code == 201
        player_id = _player_id(c)
        body = _history(c, player_id)

    assert body["engine_version"] == "openskill-pl-v1"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT rh.mu_after, rh.sigma_after FROM rating_history rh "
        "JOIN matches m ON m.id = rh.match_id "
        "WHERE rh.player_id = ? ORDER BY m.played_at, m.id",
        (player_id,),
    ).fetchall()
    conn.close()

    assert len(rows) == 2
    assert [p["score_after"] for p in body["points"]] == [
        round(row["mu_after"] - 3 * row["sigma_after"], 2) for row in rows
    ]


# --- Determinizm --------------------------------------------------------


def test_history_identical_after_replay(client):
    payloads = [
        make_payload(source_game_id="rh-d1", played_at="2026-08-11T20:00:00Z"),
        make_payload(source_game_id="rh-d2", played_at="2026-08-12T20:00:00Z",
                     winner_team=200),
        make_payload(source_game_id="rh-d3", played_at="2026-08-13T20:00:00Z"),
    ]
    payloads[0]["participants"][0]["stats"] = dict(GOOD_STATS)
    payloads[1]["participants"][7]["stats"] = dict(GOOD_STATS)
    for payload in payloads:
        assert client.post("/api/v1/ingest/match", json=payload).status_code == 201

    player_ids = [p["id"] for p in client.get("/api/v1/players").json()]
    before = {pid: _history(client, pid) for pid in player_ids}

    r = client.post("/api/v1/admin/replay")
    assert r.status_code == 200
    assert r.json()["matches_replayed"] == 3

    assert {pid: _history(client, pid) for pid in player_ids} == before
