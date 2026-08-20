"""Harman engine (openskill-pl-blend30-s2-v1) backend yolu.

Formül matematiği rating paketinde test edilir; buradaki testler backend'in
perf_score'u yazdığını, P_avg/score'u doğru servis ettiğini ve replay
determinizmini doğrular. Default ENGINE_VERSION = blend30-s2 olduğundan
conftest'in `client` fixture'ı doğrudan kullanılır.
"""
from __future__ import annotations

import sqlite3

from conftest import make_payload, make_role_payload

# ENGINE_VERSION seçilebilen client (conftest.client'ın kopyası) — versionlar
# arası karşılaştırma için; dördüncü bir kopya çıkarılmaz.
from test_perf_rating import _client as engine_client

# blend30-s2 sabitleri (rating_contract "Harman Engine — blend30-s2"):
# W = perf ağırlığı, S = sigma katsayısı (blend20/blend50'de 3, burada 2).
MU_0, K, W, S = 25.0, 20.0, 0.70, 2.0

GOOD_STATS = {
    "kills": 15, "deaths": 1, "assists": 12,
    "gold": 18000, "cs": 260,
    "damage_to_champs": 42000, "vision_score": 45,
}
BAD_STATS = {
    "kills": 1, "deaths": 9, "assists": 2,
    "gold": 8000, "cs": 90,
    "damage_to_champs": 7000, "vision_score": 5,
}


def _null_stats_payload(source_game_id="manual:blend-null-1",
                        played_at="2026-08-11T20:00:00Z"):
    payload = make_payload(source_game_id=source_game_id, played_at=played_at)
    payload["source"] = "manual"
    for p in payload["participants"]:
        p["stats"] = None
    return payload


def _by_puuid(players, puuid):
    return next(p for p in players if p["puuid"] == puuid)


def _full_history(conn):
    return [
        tuple(row)
        for row in conn.execute(
            "SELECT player_id, match_id, engine_version, mu_before,"
            " sigma_before, mu_after, sigma_after, perf_score "
            "FROM rating_history ORDER BY match_id, player_id"
        )
    ]


# (a) Statlı ingest'te perf_score kolonu dolu ve banda uygun.
def test_perf_score_written_on_stats_ingest(client, db):
    r = client.post("/api/v1/ingest/match", json=make_payload())
    assert r.status_code == 201

    conn = db()
    rows = conn.execute(
        "SELECT perf_score, engine_version FROM rating_history"
    ).fetchall()
    assert len(rows) == 10
    for row in rows:
        assert row["engine_version"] == "openskill-pl-blend30-s2-v1"
        assert row["perf_score"] is not None
        assert 0.5 <= row["perf_score"] <= 2.0


# (b) Leaderboard score sıralaması: düşük W/L + yüksek perf, salt ordinal
# sıralamasından farklı konumlanabilir.
def test_leaderboard_high_perf_loser_outranks_low_perf_winner(client):
    payload = make_payload(winner_team=100)
    payload["participants"][0]["stats"] = dict(BAD_STATS)   # kazanan, kötü perf
    payload["participants"][5]["stats"] = dict(GOOD_STATS)  # kaybeden, iyi perf
    assert client.post("/api/v1/ingest/match", json=payload).status_code == 201

    board = client.get("/api/v1/leaderboard").json()
    bad_winner = _by_puuid(board, "abc-123-...")  # participants[0], team100
    good_loser = _by_puuid(board, "puuid-05")     # participants[5], team200

    # W/L çekirdeği yönü korur: kazananın ordinal'ı kaybedenden yüksek...
    assert bad_winner["rating"]["ordinal"] > good_loser["rating"]["ordinal"]
    # ...ama harman score'da yüksek perf'li kaybeden öne geçer.
    assert good_loser["rating"]["score"] > bad_winner["rating"]["score"]
    assert good_loser["rating"]["perf_avg"] > bad_winner["rating"]["perf_avg"]
    # Leaderboard bu score sırasını yansıtır.
    assert board.index(good_loser) < board.index(bad_winner)
    scores = [p["rating"]["score"] for p in board]
    assert scores == sorted(scores, reverse=True)
    # GET /players da aynı alanları dolu döner.
    players = client.get("/api/v1/players").json()
    assert _by_puuid(players, "puuid-05")["rating"]["score"] == \
        good_loser["rating"]["score"]


# (c) Statsız (manuel) maç: perf_score = 1.0 ve score, P_avg=1 harman formülü.
def test_null_stats_match_writes_neutral_perf_score(client, db):
    assert (
        client.post("/api/v1/ingest/match", json=_null_stats_payload())
        .status_code == 201
    )

    conn = db()
    rows = conn.execute("SELECT perf_score FROM rating_history").fetchall()
    assert len(rows) == 10
    assert all(row["perf_score"] == 1.0 for row in rows)

    for p in client.get("/api/v1/players").json():
        r = p["rating"]
        assert r["perf_avg"] == 1.0
        # P_avg=1 → mu_eff = (1-W)*mu + W*MU_0; score = mu_eff - S*sigma
        expected = (1 - W) * r["mu"] + W * MU_0 - S * r["sigma"]
        assert abs(r["score"] - expected) < 1e-9


# (d) Balance harman version'da çalışmaya devam eder.
def test_balance_works_under_blend(client):
    payload = make_payload(winner_team=100)
    payload["participants"][0]["stats"] = dict(GOOD_STATS)
    payload["participants"][5]["stats"] = dict(BAD_STATS)
    assert client.post("/api/v1/ingest/match", json=payload).status_code == 201

    ids = [p["id"] for p in client.get("/api/v1/players").json()]
    r = client.post("/api/v1/balance", json={"player_ids": ids, "top_n": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["engine_version"] == "openskill-pl-blend30-s2-v1"
    assert len(body["suggestions"]) == 3
    for s in body["suggestions"]:
        assert len(s["team_100"]) == 5
        assert len(s["team_200"]) == 5
        # GÖREV 0: takımlar (player_id, position) çiftleri döner (api_contract §4).
        got = [slot["player_id"] for slot in s["team_100"] + s["team_200"]]
        assert sorted(got) == sorted(ids)
        assert 0.0 <= s["p_win_team_100"] <= 1.0


def test_balance_mixes_rated_and_unrated_players_under_blend(client):
    # 5 maçlı + 5 maçsız oyuncu: maçsızlar default mu/sigma + P_avg=1.0 alır.
    payload = make_payload()
    payload["participants"] = payload["participants"][:5] + [
        {
            "puuid": f"fresh-{i}", "riot_id": f"Fresh{i}#TR1", "team": 200,
            "position": None, "champion": None, "stats": None,
        }
        for i in range(5)
    ]
    # 5v5 korunmalı: ilk 5 team100'de, yeniler team200'de. Maç ingest edilir,
    # sonra 10 oyuncunun tamamı balance'a verilir.
    assert client.post("/api/v1/ingest/match", json=payload).status_code == 201
    ids = [p["id"] for p in client.get("/api/v1/players").json()]
    assert len(ids) == 10
    r = client.post("/api/v1/balance", json={"player_ids": ids})
    assert r.status_code == 200
    assert len(r.json()["suggestions"]) == 3


# (e) Replay determinizmi: mu/sigma VE perf_score birebir yeniden üretilir.
def test_replay_reproduces_perf_scores_exactly(client, db):
    payloads = [
        make_payload(source_game_id="blend-r1",
                     played_at="2026-08-11T20:00:00Z", winner_team=100),
        make_payload(source_game_id="blend-r2",
                     played_at="2026-08-12T20:00:00Z", winner_team=200),
        _null_stats_payload("manual:blend-r3", "2026-08-13T20:00:00Z"),
    ]
    payloads[0]["participants"][0]["stats"] = dict(GOOD_STATS)
    payloads[1]["participants"][7]["stats"] = dict(BAD_STATS)
    for p in payloads:
        assert client.post("/api/v1/ingest/match", json=p).status_code == 201

    incremental = _full_history(db())
    assert len(incremental) == 30
    # Statlı maçlarda nötr olmayan skorlar da üretilmiş olmalı (senaryo anlamlı).
    assert any(row[7] != 1.0 for row in incremental)

    r = client.post("/api/v1/admin/replay")
    assert r.status_code == 200
    assert r.json()["matches_replayed"] == 3

    assert _full_history(db()) == incremental  # bit-bit: perf_score dahil


# --- GÖREV 27: sigma katsayısı (S) ekseni ---------------------------------


def test_score_uses_active_sigma_coefficient_ordinal_unchanged(client):
    """Aktif version'da (S=2) `score` = mu_eff − 2σ; `ordinal` (mu − 3σ)
    W/L çekirdeğinin tahmini olarak DEĞİŞMEZ. İkisinin farkı tam olarak σ'dır.
    """
    assert client.post("/api/v1/ingest/match", json=make_role_payload()).status_code \
        == 201
    for p in client.get("/api/v1/players").json():
        r = p["rating"]
        mu_eff = (1 - W) * r["mu"] + W * (MU_0 + K * (r["perf_avg"] - 1.0))
        assert abs(r["score"] - (mu_eff - S * r["sigma"])) < 1e-9
        # ordinal S'ten etkilenmez.
        assert abs(r["ordinal"] - (r["mu"] - 3.0 * r["sigma"])) < 1e-9
        # S=3 → S=2 geçişinin etkisi tam olarak +1σ'dır.
        assert abs((r["score"] - (mu_eff - 3.0 * r["sigma"])) - r["sigma"]) < 1e-9


def test_role_universe_uses_same_sigma_coefficient(client):
    """Rol evreni ana evrenin S'ini kullanır: score_role = mu_eff_role − S*σ_role
    (rating_contract "Rol Rating Evreni" §2 — formül aktif engine ile birebir)."""
    assert client.post("/api/v1/ingest/match", json=make_role_payload()).status_code \
        == 201
    played = 0
    for p in client.get("/api/v1/players").json():
        for role, rr in p["role_ratings"].items():
            mu_eff = (1 - W) * rr["mu"] + W * (MU_0 + K * (rr["perf_avg"] - 1.0))
            assert abs(rr["score"] - (mu_eff - S * rr["sigma"])) < 1e-9
            played += rr["matches"]
    assert played == 10, "senaryo anlamlı: maç rol evrenine girmiş olmalı"


def _core_history(db_path) -> list[tuple]:
    """İki evrenin W/L ÇEKİRDEĞİ (mu/sigma) + perf_score satırları.

    `engine_version` kolonu bilinçli olarak DIŞARIDA bırakılır: karşılaştırma
    "çekirdek version'dan bağımsız mı" sorusunu yanıtlar.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [
        tuple(row)
        for row in conn.execute(
            "SELECT player_id, match_id, mu_before, sigma_before,"
            " mu_after, sigma_after, perf_score "
            "FROM rating_history ORDER BY match_id, player_id"
        )
    ] + [
        tuple(row)
        for row in conn.execute(
            "SELECT player_id, match_id, role, mu_before, sigma_before,"
            " mu_after, sigma_after, perf_score "
            "FROM role_rating_history ORDER BY match_id, player_id"
        )
    ]
    conn.close()
    return rows


def test_core_history_bitwise_identical_to_blend20(tmp_path, monkeypatch):
    """W/L çekirdeği DEĞİŞMEDİ: aynı maç dizisi blend20 ve blend30-s2 altında
    işlendiğinde mu/sigma geçmişi (iki evrende de) ve perf_score BİT-BİT
    aynıdır; yalnız efektif skor KATMANI farklıdır."""
    payloads = [
        make_role_payload(source_game_id="s2-x1",
                          played_at="2026-08-11T20:00:00Z", winner_team=100),
        make_role_payload(source_game_id="s2-x2",
                          played_at="2026-08-12T20:00:00Z", winner_team=200),
        make_role_payload(source_game_id="s2-x3",
                          played_at="2026-08-13T20:00:00Z", winner_team=100),
    ]
    payloads[0]["participants"][0]["stats"] = dict(GOOD_STATS)
    payloads[1]["participants"][7]["stats"] = dict(BAD_STATS)

    def run(version: str, name: str) -> tuple[list[tuple], list[float]]:
        db_path = tmp_path / name
        with engine_client(db_path, monkeypatch, engine_version=version) as c:
            for payload in payloads:
                assert c.post("/api/v1/ingest/match", json=payload).status_code == 201
            scores = [p["rating"]["score"] for p in c.get("/api/v1/players").json()]
        return _core_history(db_path), scores

    core20, scores20 = run("openskill-pl-blend20-v1", "b20.db")
    core_s2, scores_s2 = run("openskill-pl-blend30-s2-v1", "b30s2.db")
    assert len(core_s2) == 60  # 3 maç × 10 oyuncu × 2 evren
    assert core_s2 == core20  # bit-bit
    # Skor KATMANI ise farklıdır ve S farkı yüzünden her oyuncuda YUKARI kayar.
    assert scores_s2 != scores20
    assert all(new > old for new, old in zip(scores_s2, scores20))
