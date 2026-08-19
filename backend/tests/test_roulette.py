"""GÖREV 23 — Rulet eğlence modu (api_contract §4.5 + §3 `roulette` alanı +
§2 rulet rozetleri; db_schema migration 0006).

Kapsam: POST /roulette doğrulama sınıfları, tek açık oturum değişmezi,
GET /roulette/current, ingest'te otomatik eşleşme (pencere/küme/remake
öncelik), unlink + çift evren replay, maç yanıtındaki `roulette` alanı
(bought/won küme mantığı, null envanter), rulet rozetleri (gambler eşiği,
determinizm) ve "status='valid' süzgeçli sorgular değişmez" değişmezleri.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from conftest import POSITIONS, make_roster_payload

# api_contract §4.5 örneğinin ilk kaydı — birebir.
CONTRACT_ASSIGNMENT = {
    "player_id": 1,
    "team": 100,
    "position": "TOP",
    "champion": "Aatrox",
    "item_ids": [3031, 3026],
}


def _create_players(client, n=10, prefix="R"):
    return [
        client.post("/api/v1/players", json={"display_name": f"{prefix}{i}"}).json()[
            "id"
        ]
        for i in range(n)
    ]


def _assignments(player_ids):
    """Contract örneğini 10 kayda tamamlar; [0] örneğin aynısıdır (player_id
    dışında — o, testin oluşturduğu ilk oyuncudur, ki fixture'da id=1 çıkar)."""
    out = []
    for i, pid in enumerate(player_ids):
        rec = {
            "player_id": pid,
            "team": 100 if i < 5 else 200,
            "position": POSITIONS[i % 5],
            "champion": f"Champ{i}",
            "item_ids": [1000 + 2 * i, 1001 + 2 * i],
        }
        if i == 0:
            rec.update(
                {k: v for k, v in CONTRACT_ASSIGNMENT.items() if k != "player_id"}
            )
        out.append(rec)
    return out


def _post_session(client, player_ids):
    resp = client.post(
        "/api/v1/roulette", json={"assignments": _assignments(player_ids)}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _ingest(client, payload):
    resp = client.post("/api/v1/ingest/match", json=payload)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def _link_setup(client, game_id="rlt-1", played_at="2026-08-17T20:00:00Z"):
    """10 oyuncu + açık oturum + eşleşen ingest: (player_ids, session, match_id)."""
    ids = _create_players(client)
    session = _post_session(client, ids)
    body = _ingest(
        client,
        make_roster_payload(game_id, played_at, ids[:5], ids[5:], winner_team=100),
    )
    return ids, session, body["match_id"]


def _match_status(db, match_id):
    conn = db()
    try:
        return conn.execute(
            "SELECT status FROM matches WHERE id = ?", (match_id,)
        ).fetchone()["status"]
    finally:
        conn.close()


def _session_row(db, session_id):
    conn = db()
    try:
        return dict(
            conn.execute(
                "SELECT status, match_id FROM roulette_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        )
    finally:
        conn.close()


def _rating_rows(db):
    conn = db()
    try:
        return (
            conn.execute("SELECT COUNT(*) AS n FROM rating_history").fetchone()["n"],
            conn.execute(
                "SELECT COUNT(*) AS n FROM role_rating_history"
            ).fetchone()["n"],
        )
    finally:
        conn.close()


# ── POST /roulette + GET /roulette/current ──────────────────────────────────

def test_post_roulette_happy_path_and_current(client):
    ids = _create_players(client)
    body = _post_session(client, ids)
    assert set(body) == {"session_id", "created_at"}
    # created_at SUNUCUDA, played_at ile aynı UTC "…Z" biçiminde atanır.
    datetime.strptime(body["created_at"], "%Y-%m-%dT%H:%M:%SZ")

    current = client.get("/api/v1/roulette/current").json()
    assert current["session"]["session_id"] == body["session_id"]
    assert current["session"]["created_at"] == body["created_at"]
    # Atamalar POST gövdesindeki 10 kayıt, giriş sırasıyla.
    assert current["session"]["assignments"] == _assignments(ids)


def test_current_is_null_without_open_session(client):
    assert client.get("/api/v1/roulette/current").json() == {"session": None}


def test_post_cancels_previous_open_sessions(client, db):
    ids = _create_players(client)
    first = _post_session(client, ids)
    second = _post_session(client, ids)
    assert _session_row(db, first["session_id"])["status"] == "cancelled"
    assert _session_row(db, second["session_id"])["status"] == "open"
    current = client.get("/api/v1/roulette/current").json()
    assert current["session"]["session_id"] == second["session_id"]


# ── POST /roulette doğrulama sınıfları (422 + Türkçe detail) ────────────────

def _expect_422(client, assignments, fragment):
    resp = client.post("/api/v1/roulette", json={"assignments": assignments})
    assert resp.status_code == 422, resp.text
    assert fragment in resp.json()["detail"]


def test_422_wrong_record_count(client, db):
    ids = _create_players(client)
    _expect_422(client, _assignments(ids)[:9], "tam 10 kayıt")
    # Hata durumunda DB'ye hiç oturum yazılmaz.
    conn = db()
    try:
        assert (
            conn.execute("SELECT COUNT(*) AS n FROM roulette_sessions").fetchone()["n"]
            == 0
        )
    finally:
        conn.close()


def test_422_repeated_player_id(client):
    ids = _create_players(client)
    bad = _assignments(ids)
    bad[9]["player_id"] = bad[0]["player_id"]
    _expect_422(client, bad, "tam 1 kez")


def test_422_unknown_player_id(client):
    ids = _create_players(client)
    bad = _assignments(ids)
    bad[3]["player_id"] = 9999
    _expect_422(client, bad, "player_id 9999 bulunamadı")


def test_422_team_split_not_5v5(client):
    ids = _create_players(client)
    bad = _assignments(ids)
    bad[9]["team"] = 100  # 6/4
    _expect_422(client, bad, "tam 5 oyuncu")


def test_422_team_role_not_unique(client):
    ids = _create_players(client)
    bad = _assignments(ids)
    bad[1]["position"] = bad[0]["position"]  # team 100'de aynı rol 2 kez
    _expect_422(client, bad, "5 rolün her biri tam 1 kez")


def test_422_empty_champion(client):
    ids = _create_players(client)
    bad = _assignments(ids)
    bad[4]["champion"] = "   "
    _expect_422(client, bad, "champion boş olmayan")


def test_422_duplicate_champion(client):
    ids = _create_players(client)
    bad = _assignments(ids)
    bad[7]["champion"] = bad[2]["champion"]
    _expect_422(client, bad, "birbirinden farklı")


def test_422_item_ids_classes(client):
    ids = _create_players(client)
    for value, fragment in [
        (None, "bir dizi olmalı"),
        ([3031], "tam 2 eleman"),
        ([3031, 3026, 3036], "tam 2 eleman"),
        ([3031, "x"], "pozitif tam sayı"),
        ([3031, True], "pozitif tam sayı"),
        ([3031, 0], "pozitif tam sayı"),
        ([3031, -5], "pozitif tam sayı"),
        ([3031, 3031], "birbirinden farklı olmalı"),
    ]:
        bad = _assignments(ids)
        bad[6]["item_ids"] = value
        _expect_422(client, bad, fragment)


# ── Otomatik eşleşme (ingest) ────────────────────────────────────────────────

def test_ingest_auto_links_open_session(client, db):
    ids, session, match_id = _link_setup(client)
    # Ingest yanıt şekli DEĞİŞMEZ (match_id + duplicate).
    assert _match_status(db, match_id) == "roulette"
    assert _session_row(db, session["session_id"]) == {
        "status": "linked",
        "match_id": match_id,
    }
    # Rulet maçı HİÇBİR rating evrenine girmez.
    assert _rating_rows(db) == (0, 0)
    # Açık oturum kalmadı.
    assert client.get("/api/v1/roulette/current").json() == {"session": None}


def test_ingest_response_shape_unchanged_on_link(client):
    ids = _create_players(client)
    _post_session(client, ids)
    body = _ingest(
        client,
        make_roster_payload("rlt-shape", "2026-08-17T20:00:00Z", ids[:5], ids[5:]),
    )
    assert set(body) == {"match_id", "duplicate"}
    assert body["duplicate"] is False


def test_ingest_outside_24h_window_stays_valid(client, db):
    ids = _create_players(client)
    session = _post_session(client, ids)
    stale = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    conn = db()
    try:
        conn.execute(
            "UPDATE roulette_sessions SET created_at = ? WHERE id = ?",
            (stale, session["session_id"]),
        )
        conn.commit()
    finally:
        conn.close()

    body = _ingest(
        client,
        make_roster_payload("rlt-old", "2026-08-17T20:00:00Z", ids[:5], ids[5:]),
    )
    assert _match_status(db, body["match_id"]) == "valid"
    # Oturum açık kalır (koşullar sağlanmadı); maç normal rating'e girdi.
    assert _session_row(db, session["session_id"])["status"] == "open"
    assert _rating_rows(db)[0] == 10


def test_ingest_player_set_mismatch_stays_valid(client, db):
    ids = _create_players(client, n=11)
    session = _post_session(client, ids[:10])
    # 10 kişilik küme birebir aynı DEĞİL (bir oyuncu farklı).
    body = _ingest(
        client,
        make_roster_payload(
            "rlt-mismatch", "2026-08-17T20:00:00Z", ids[:5], ids[5:9] + [ids[10]]
        ),
    )
    assert _match_status(db, body["match_id"]) == "valid"
    assert _session_row(db, session["session_id"])["status"] == "open"


def test_remake_auto_void_has_priority_session_stays_open(client, db):
    ids = _create_players(client)
    session = _post_session(client, ids)
    body = _ingest(
        client,
        make_roster_payload(
            "rlt-remake", "2026-08-17T20:00:00Z", ids[:5], ids[5:], duration_s=120
        ),
    )
    assert _match_status(db, body["match_id"]) == "void"
    assert _session_row(db, session["session_id"])["status"] == "open"

    # Maç yeniden oynanır → bu sefer eşleşir.
    body2 = _ingest(
        client,
        make_roster_payload("rlt-replayed", "2026-08-17T21:00:00Z", ids[:5], ids[5:]),
    )
    assert _match_status(db, body2["match_id"]) == "roulette"
    assert _session_row(db, session["session_id"]) == {
        "status": "linked",
        "match_id": body2["match_id"],
    }


def test_duplicate_ingest_after_link_changes_nothing(client, db):
    ids, session, match_id = _link_setup(client, game_id="rlt-dup")
    payload = make_roster_payload(
        "rlt-dup", "2026-08-17T20:00:00Z", ids[:5], ids[5:]
    )
    body = _ingest(client, payload)
    assert body == {"match_id": match_id, "duplicate": True}
    assert _match_status(db, match_id) == "roulette"
    assert _session_row(db, session["session_id"])["status"] == "linked"
    assert _rating_rows(db) == (0, 0)


# ── Unlink ───────────────────────────────────────────────────────────────────

def test_unlink_unknown_match_404(client):
    resp = client.post("/api/v1/matches/999/roulette/unlink")
    assert resp.status_code == 404


def test_unlink_non_roulette_match_409(client):
    ids = _create_players(client)
    body = _ingest(
        client,
        make_roster_payload("plain-1", "2026-08-17T20:00:00Z", ids[:5], ids[5:]),
    )
    resp = client.post(f"/api/v1/matches/{body['match_id']}/roulette/unlink")
    assert resp.status_code == 409
    assert "valid" in resp.json()["detail"]


def test_unlink_restores_valid_and_replays_both_universes(client, db):
    ids, session, match_id = _link_setup(client)
    resp = client.post(f"/api/v1/matches/{match_id}/roulette/unlink")
    assert resp.status_code == 200
    body = resp.json()
    # api_contract §4.5 yanıt şekli.
    assert set(body) == {"status", "matches_replayed", "role_matches_replayed"}
    assert body["status"] == "valid"
    assert body["matches_replayed"] == 1
    assert body["role_matches_replayed"] == 1

    assert _match_status(db, match_id) == "valid"
    # Oturum cancelled + match_id NULL (yalnız linked'te dolu — db_schema 0006).
    assert _session_row(db, session["session_id"]) == {
        "status": "cancelled",
        "match_id": None,
    }
    # Maç artık HER İKİ evrende rating'e girdi.
    assert _rating_rows(db) == (10, 10)
    # Maç yanıtındaki roulette alanı artık null.
    match = client.get(f"/api/v1/matches/{match_id}").json()
    assert match["status"] == "valid"
    assert match["roulette"] is None


def test_unlink_then_admin_replay_is_bit_identical(client, db):
    _, _, match_id = _link_setup(client)
    client.post(f"/api/v1/matches/{match_id}/roulette/unlink")

    def dump():
        conn = db()
        try:
            return conn.execute(
                "SELECT player_id, match_id, engine_version, mu_before,"
                " sigma_before, mu_after, sigma_after, perf_score"
                " FROM rating_history ORDER BY player_id, match_id"
            ).fetchall()
        finally:
            conn.close()

    first = [tuple(r) for r in dump()]
    client.post("/api/v1/admin/replay")
    second = [tuple(r) for r in dump()]
    client.post("/api/v1/admin/replay")
    third = [tuple(r) for r in dump()]
    assert first == second == third  # bit-bit determinizm


# ── Maç yanıtındaki `roulette` alanı (api_contract §3) ──────────────────────

def test_matches_roulette_field_null_for_plain_match(client):
    ids = _create_players(client)
    body = _ingest(
        client,
        make_roster_payload("plain-2", "2026-08-17T20:00:00Z", ids[:5], ids[5:]),
    )
    match = client.get(f"/api/v1/matches/{body['match_id']}").json()
    assert match["roulette"] is None


def test_matches_roulette_field_bought_won_and_null_inventory(client, db):
    ids, session, match_id = _link_setup(client)
    assigned = {a["player_id"]: a for a in _assignments(ids)}
    winner_a, winner_b, winner_e = ids[0], ids[1], ids[4]  # team 100 (kazanan)
    loser_c = ids[5]  # team 200

    def items_of(pid):
        return assigned[pid]["item_ids"]

    # A: ikisi de envanterde (ters sıra + fazlalık + yinelenme) → bought True.
    # B: biri eksik → False. C (kaybeden): ikisi de var → True ama won False.
    # E: [] → "bilgi var, boş" → False. Diğerleri: NULL → None.
    a1, a2 = items_of(winner_a)
    b1, _ = items_of(winner_b)
    c1, c2 = items_of(loser_c)
    resp = client.put(
        f"/api/v1/matches/{match_id}/items",
        json={
            "items": {
                str(winner_a): [a2, 9999, a1, a1],
                str(winner_b): [b1, 8888],
                str(loser_c): [c1, c2],
                str(winner_e): [],
            }
        },
    )
    assert resp.status_code == 200

    match = client.get(f"/api/v1/matches/{match_id}").json()
    assert match["status"] == "roulette"
    roulette = match["roulette"]
    assert roulette["session_id"] == session["session_id"]
    assert len(roulette["assignments"]) == 10
    by_pid = {a["player_id"]: a for a in roulette["assignments"]}

    ra = by_pid[winner_a]
    assert ra == {
        "player_id": winner_a,
        "champion": assigned[winner_a]["champion"],
        "position": assigned[winner_a]["position"],
        "item_ids": items_of(winner_a),
        "bought": True,
        "won": True,
    }
    assert (by_pid[winner_b]["bought"], by_pid[winner_b]["won"]) == (False, False)
    assert (by_pid[loser_c]["bought"], by_pid[loser_c]["won"]) == (True, False)
    assert (by_pid[winner_e]["bought"], by_pid[winner_e]["won"]) == (False, False)
    # Envanteri NULL kalanlar: bought null (doğrulanamadı), won False.
    for pid in ids:
        if pid in (winner_a, winner_b, loser_c, winner_e):
            continue
        assert (by_pid[pid]["bought"], by_pid[pid]["won"]) == (None, False)

    # Rulet maçı rating'e girmediği için rating_change tüm katılımcılarda null.
    assert all(p["rating_change"] is None for p in match["participants"])

    # Liste ve detay BİREBİR aynı şekil.
    listed = next(
        m for m in client.get("/api/v1/matches").json() if m["id"] == match_id
    )
    assert listed == match


def test_won_uses_actual_match_team_not_assigned_team(client, db):
    """Rastgele atanan takım ile fiilen oynanan takım farklı olabilir; `won`
    maçtaki takıma bakar."""
    ids = _create_players(client)
    assignments = _assignments(ids)
    # ids[0]'ı atamada 200'e, ids[5]'i 100'e taşı (5/5 ve roller korunur).
    assignments[0]["team"], assignments[5]["team"] = 200, 100
    assignments[0]["position"], assignments[5]["position"] = (
        assignments[5]["position"],
        assignments[0]["position"],
    )
    resp = client.post("/api/v1/roulette", json={"assignments": assignments})
    assert resp.status_code == 201, resp.text
    # Maçta ids[0] YİNE team 100'de (kazanan) oynar.
    body = _ingest(
        client,
        make_roster_payload("rlt-swap", "2026-08-17T20:00:00Z", ids[:5], ids[5:]),
    )
    match_id = body["match_id"]
    assert _match_status(db, match_id) == "roulette"
    item_ids = assignments[0]["item_ids"]
    client.put(
        f"/api/v1/matches/{match_id}/items",
        json={"items": {str(ids[0]): item_ids}},
    )
    by_pid = {
        a["player_id"]: a
        for a in client.get(f"/api/v1/matches/{match_id}").json()["roulette"][
            "assignments"
        ]
    }
    assert (by_pid[ids[0]]["bought"], by_pid[ids[0]]["won"]) == (True, True)


# ── status='valid' süzgeçli sorgular değişmez ───────────────────────────────

def test_roulette_match_excluded_from_valid_statistics(client):
    ids, _, match_id = _link_setup(client)
    # matches_played / stats / leaderboard rulet maçını saymaz.
    players = client.get("/api/v1/players").json()
    me = next(p for p in players if p["id"] == ids[0])
    assert me["matches_played"] == 0
    assert me["rating"]["score"] == 0.0
    stats = client.get(f"/api/v1/players/{ids[0]}/stats").json()
    assert stats["totals"] == {
        "matches": 0, "wins": 0, "losses": 0, "winrate": None,
    }
    history = client.get(f"/api/v1/players/{ids[0]}/rating-history").json()
    assert history["points"] == []
    # Geçmişte GÖRÜNÜR (GET /matches süzgeçsizdir).
    assert any(m["id"] == match_id for m in client.get("/api/v1/matches").json())


def test_void_roulette_match_409(client, db):
    """api_contract §3 (Teoman, 2026-08-19): rulet maçı zaten rating dışıdır,
    void anlamsızdır → 409. Replay TETİKLENMEZ, maç `roulette` kalır, rating
    satırları değişmez (zaten yok). Yanlış eşleşmenin çözümü unlink'tir."""
    ids, session, match_id = _link_setup(client)
    before = _rating_rows(db)
    resp = client.post(f"/api/v1/matches/{match_id}/void")
    assert resp.status_code == 409, resp.text
    assert "rulet" in resp.json()["detail"]
    assert _match_status(db, match_id) == "roulette"
    assert _rating_rows(db) == before == (0, 0)
    # Oturum linked kalır (void reddedildi, hiçbir şeye dokunmadı).
    assert _session_row(db, session["session_id"]) == {
        "status": "linked",
        "match_id": match_id,
    }


# ── Rulet rozetleri (api_contract §2) ───────────────────────────────────────

def _badges(client, player_id):
    body = client.get(f"/api/v1/players/{player_id}/badges").json()
    return {b["key"]: b for b in body["badges"]}, [b["key"] for b in body["badges"]]


def test_roulette_badges_complete_and_winner(client):
    ids, session, match_id = _link_setup(client)
    assigned = {a["player_id"]: a for a in _assignments(ids)}
    winner, loser = ids[0], ids[5]
    client.put(
        f"/api/v1/matches/{match_id}/items",
        json={
            "items": {
                str(winner): assigned[winner]["item_ids"],
                str(loser): assigned[loser]["item_ids"],
                # ids[1]: envanter atanandan farklı → rozet yok.
                str(ids[1]): [1, 2],
            }
        },
    )
    badges, _ = _badges(client, winner)
    # GÖREV 24 alanları: rulet sınıfı ölçülebilir/kademeli DEĞİLDİR
    # (roulette_complete/winner'da progress da yok; yalnız gambler'da var).
    assert badges["roulette_complete"] == {
        "key": "roulette_complete", "count": 1, "last_match_id": match_id,
        "best_match_id": None, "best_value": None,
        "tier": None, "rate": None, "next_tier_rate": None, "progress": None,
    }
    assert badges["roulette_winner"]["count"] == 1
    assert "gambler" not in badges

    badges, _ = _badges(client, loser)  # kaybeden: complete var, winner yok
    assert badges["roulette_complete"]["count"] == 1
    assert "roulette_winner" not in badges

    badges, _ = _badges(client, ids[1])  # yanlış envanter → rozet yok
    assert "roulette_complete" not in badges
    badges, _ = _badges(client, ids[2])  # NULL envanter → doğrulanamaz → yok
    assert "roulette_complete" not in badges


def test_gambler_threshold_catalog_order_and_replay_determinism(client):
    ids = _create_players(client)
    target = ids[0]
    match_ids = []
    for k in range(5):
        session_assignments = _assignments(ids)
        resp = client.post(
            "/api/v1/roulette", json={"assignments": session_assignments}
        )
        assert resp.status_code == 201
        body = _ingest(
            client,
            make_roster_payload(
                f"rlt-g{k}",
                f"2026-08-17T20:{k:02d}:00Z",
                ids[:5],
                ids[5:],
                winner_team=100,
            ),
        )
        match_ids.append(body["match_id"])
        assigned = {a["player_id"]: a for a in session_assignments}
        client.put(
            f"/api/v1/matches/{body['match_id']}/items",
            json={"items": {str(target): assigned[target]["item_ids"]}},
        )

    # Araya normal (valid) bir maç: katalog sırası + valid rozetler etkilenmez.
    _ingest(
        client,
        make_roster_payload("plain-g", "2026-08-18T01:00:00Z", ids[:5], ids[5:]),
    )

    badges, keys = _badges(client, target)
    assert badges["roulette_complete"]["count"] == 5
    assert badges["roulette_winner"]["count"] == 5
    assert badges["gambler"] == {
        "key": "gambler", "count": 1, "last_match_id": match_ids[4],
        "best_match_id": None, "best_value": None,
        "tier": None, "rate": None, "next_tier_rate": None,
        # gambler'ın ilerlemesi roulette_winner sayısıdır (GÖREV 24).
        "progress": {"current": 5, "target": 5},
    }
    # Rulet rozetleri katalog sırasının SONUNDA.
    assert keys[-3:] == ["roulette_complete", "roulette_winner", "gambler"]
    # Valid maçtan gelen rozetler (deathless: deaths=2 → yok; mvp olabilir)
    # rulet öncesinde sıralanır — keys katalog sırasına uyar.
    from app.services.badges import BADGE_KEYS

    assert keys == [k for k in BADGE_KEYS if k in keys]

    # Determinizm: replay sonrası yanıt bit-bit aynı.
    before = client.get(f"/api/v1/players/{target}/badges").json()
    client.post("/api/v1/admin/replay")
    after = client.get(f"/api/v1/players/{target}/badges").json()
    assert before == after


# ── POST /roulette/clear (Teoman 2026-08-19, api_contract §4.5) ────────────

def _session_ids(db):
    conn = db()
    try:
        return [row["id"] for row in conn.execute("SELECT id FROM roulette_sessions")]
    finally:
        conn.close()


def test_clear_empty_returns_zero(client):
    resp = client.post("/api/v1/roulette/clear")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": 0}


def test_clear_deletes_open_and_cancelled_counts_correctly(client, db):
    ids = _create_players(client)
    # open + cancelled: iki oturum aç (ilki cancelled olur), bir tanesi açık kalır.
    first = _post_session(client, ids)
    second = _post_session(client, ids)
    assert _session_row(db, first["session_id"])["status"] == "cancelled"
    assert _session_row(db, second["session_id"])["status"] == "open"

    resp = client.post("/api/v1/roulette/clear")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": 2}
    assert _session_ids(db) == []
    # roulette_assignments de temizlenmiş olmalı (FK RESTRICT'e takılmadan).
    conn = db()
    try:
        assert (
            conn.execute("SELECT COUNT(*) AS n FROM roulette_assignments").fetchone()[
                "n"
            ]
            == 0
        )
    finally:
        conn.close()


def test_clear_preserves_linked_session_and_match_roulette_field(client, db):
    ids, session, match_id = _link_setup(client, game_id="rlt-clear-linked")
    # Ayrıca bağlanmamış bir oturum ekle: silinecek olan bu.
    unlinked = _post_session(client, ids)
    assert _session_row(db, unlinked["session_id"])["status"] == "open"

    resp = client.post("/api/v1/roulette/clear")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": 1}

    # linked oturum ve atamaları AYNEN korunur.
    assert _session_row(db, session["session_id"]) == {
        "status": "linked",
        "match_id": match_id,
    }
    match = client.get(f"/api/v1/matches/{match_id}").json()
    assert match["status"] == "roulette"
    assert match["roulette"]["session_id"] == session["session_id"]
    assert len(match["roulette"]["assignments"]) == 10
    # Rozet türetimi de etkilenmedi (linked oturum verisi bozulmadı).
    _badges(client, ids[0])  # hatasız çağrılabiliyor olması yeterli kanıt


def test_clear_does_not_touch_rating_or_replay(client, db):
    ids, _, match_id = _link_setup(client, game_id="rlt-clear-rating")
    before = _rating_rows(db)
    resp = client.post("/api/v1/roulette/clear")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": 0}  # yalnız linked oturum var, silinecek yok
    assert _rating_rows(db) == before == (0, 0)
    assert _match_status(db, match_id) == "roulette"


def test_clear_then_current_is_null(client):
    ids = _create_players(client)
    _post_session(client, ids)
    assert client.get("/api/v1/roulette/current").json()["session"] is not None

    resp = client.post("/api/v1/roulette/clear")
    assert resp.json() == {"deleted": 1}
    assert client.get("/api/v1/roulette/current").json() == {"session": None}


def test_clear_then_ingest_does_not_auto_link(client, db):
    """Açık oturum kalmadığından, clear sonrası eşleşen bir maç bile
    normal `valid` maç olarak işlenir (oto-eşleşme YOK)."""
    ids = _create_players(client)
    _post_session(client, ids)
    resp = client.post("/api/v1/roulette/clear")
    assert resp.json() == {"deleted": 1}

    body = _ingest(
        client,
        make_roster_payload(
            "rlt-clear-noauto", "2026-08-17T20:00:00Z", ids[:5], ids[5:]
        ),
    )
    assert _match_status(db, body["match_id"]) == "valid"
    assert _rating_rows(db) == (10, 10)
