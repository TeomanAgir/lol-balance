import json

from conftest import make_payload


def test_happy_path_creates_match_and_ratings(client, db):
    payload = make_payload()
    r = client.post("/api/v1/ingest/match", json=payload)
    assert r.status_code == 201
    body = r.json()
    assert body["duplicate"] is False
    match_id = body["match_id"]

    conn = db()
    m = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    assert m["status"] == "valid"
    assert m["source_game_id"] == payload["source_game_id"]

    # Ham gövde ingest_events'e aynen yazıldı.
    ev = conn.execute(
        "SELECT payload_json FROM ingest_events WHERE source_game_id=?",
        (payload["source_game_id"],),
    ).fetchone()
    assert json.loads(ev["payload_json"]) == payload

    n_participants = conn.execute(
        "SELECT COUNT(*) c FROM match_participants WHERE match_id=?", (match_id,)
    ).fetchone()["c"]
    assert n_participants == 10

    # Incremental rating: 10 oyuncu için before/after satırları.
    rows = conn.execute(
        "SELECT * FROM rating_history WHERE match_id=?", (match_id,)
    ).fetchall()
    assert len(rows) == 10
    for row in rows:
        assert row["mu_before"] != row["mu_after"]


def test_idempotency_same_payload_twice(client, db):
    payload = make_payload()
    r1 = client.post("/api/v1/ingest/match", json=payload)
    r2 = client.post("/api/v1/ingest/match", json=payload)
    assert r1.status_code == 201
    assert r2.status_code == 200
    assert r2.json() == {"match_id": r1.json()["match_id"], "duplicate": True}

    conn = db()
    assert conn.execute("SELECT COUNT(*) c FROM matches").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM ingest_events").fetchone()["c"] == 1


def test_not_ten_participants_rejected(client):
    payload = make_payload()
    payload["participants"] = payload["participants"][:9]
    r = client.post("/api/v1/ingest/match", json=payload)
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str)


def test_unbalanced_teams_rejected(client):
    payload = make_payload()
    payload["participants"][9]["team"] = 100  # 6 vs 4
    r = client.post("/api/v1/ingest/match", json=payload)
    assert r.status_code == 422


def test_participant_without_identity_rejected(client):
    payload = make_payload()
    p = payload["participants"][3]
    p.pop("puuid")
    p.pop("player_id", None)
    r = client.post("/api/v1/ingest/match", json=payload)
    assert r.status_code == 422


def test_short_match_voided_no_rating(client, db):
    payload = make_payload(duration_s=200)
    r = client.post("/api/v1/ingest/match", json=payload)
    assert r.status_code == 201

    conn = db()
    m = conn.execute("SELECT status FROM matches").fetchone()
    assert m["status"] == "void"
    assert conn.execute("SELECT COUNT(*) c FROM rating_history").fetchone()["c"] == 0


def test_precreated_player_bound_by_riot_id(client, db):
    # Önce puuid'siz roster kaydı (api_contract §2 / db_schema "Yeni oyuncu").
    r = client.post(
        "/api/v1/players", json={"display_name": "Teo", "riot_id": "teoman#tr1"}
    )
    assert r.status_code == 201
    pre_id = r.json()["id"]

    # Aynı riot_id ile ingest (case-insensitive eşleşme) → aynı player, yeni satır yok.
    r = client.post("/api/v1/ingest/match", json=make_payload())
    assert r.status_code == 201

    conn = db()
    row = conn.execute(
        "SELECT id, puuid FROM players WHERE lower(riot_id)=lower('Teoman#TR1')"
    ).fetchall()
    assert len(row) == 1
    assert row[0]["id"] == pre_id
    assert row[0]["puuid"] == "abc-123-..."
    # Toplam: 1 önceden + 9 otomatik oluşturulan.
    assert conn.execute("SELECT COUNT(*) c FROM players").fetchone()["c"] == 10


def test_unknown_puuid_autocreates_with_gamename(client, db):
    client.post("/api/v1/ingest/match", json=make_payload())
    conn = db()
    row = conn.execute(
        "SELECT display_name FROM players WHERE puuid='abc-123-...'"
    ).fetchone()
    assert row["display_name"] == "Teoman"


def test_manual_ingest_with_player_id(client, db):
    ids = [
        client.post("/api/v1/players", json={"display_name": f"P{i}"}).json()["id"]
        for i in range(10)
    ]
    payload = {
        "source": "manual",
        "source_game_id": "manual:3f1b6c1e-0000-0000-0000-000000000000",
        "played_at": "2026-08-11T21:00:00Z",
        "duration_s": 1800,
        "winner_team": 200,
        "participants": [
            {"player_id": pid, "team": 100 if i < 5 else 200}
            for i, pid in enumerate(ids)
        ],
    }
    r = client.post("/api/v1/ingest/match", json=payload)
    assert r.status_code == 201

    conn = db()
    assert conn.execute("SELECT COUNT(*) c FROM players").fetchone()["c"] == 10
    assert (
        conn.execute("SELECT COUNT(*) c FROM rating_history").fetchone()["c"] == 10
    )


def test_manual_ingest_unknown_player_id_rejected(client):
    payload = make_payload(source_game_id="manual:x")
    payload["source"] = "manual"
    payload["participants"][0] = {"player_id": 999, "team": 100}
    r = client.post("/api/v1/ingest/match", json=payload)
    assert r.status_code == 422
    assert "999" in r.json()["detail"]


# --- İsim tazeleme (ingest_contract "İsim tazeleme", fix-2) ---------------


def _player_by_puuid(conn, puuid="abc-123-..."):
    return conn.execute(
        "SELECT id, riot_id, display_name FROM players WHERE puuid=?", (puuid,)
    ).fetchone()


def _renamed_payload(source_game_id, new_riot_id="Teoman2#EUW", **kwargs):
    """participants[0]'ın riot_id'si değişmiş payload (aynı puuid)."""
    payload = make_payload(source_game_id=source_game_id, **kwargs)
    payload["participants"][0]["riot_id"] = new_riot_id
    return payload


def test_rename_in_new_match_updates_riot_id_and_display_name(client, db):
    client.post("/api/v1/ingest/match", json=make_payload())
    conn = db()
    assert _player_by_puuid(conn)["display_name"] == "Teoman"

    r = client.post(
        "/api/v1/ingest/match",
        json=_renamed_payload("6874231956", played_at="2026-08-12T20:41:03Z"),
    )
    assert r.status_code == 201

    row = _player_by_puuid(db())
    assert row["riot_id"] == "Teoman2#EUW"
    assert row["display_name"] == "Teoman2"


def test_rename_on_duplicate_refreshes_names_without_touching_match(client, db):
    payload = make_payload()
    r1 = client.post("/api/v1/ingest/match", json=payload)
    assert r1.status_code == 201

    conn = db()
    before_events = conn.execute(
        "SELECT COUNT(*) c FROM ingest_events"
    ).fetchone()["c"]
    before_ratings = conn.execute(
        "SELECT COUNT(*) c FROM rating_history"
    ).fetchone()["c"]
    before_match = dict(
        conn.execute("SELECT * FROM matches WHERE id=?", (r1.json()["match_id"],))
        .fetchone()
    )

    # Aynı source_game_id, yeni riot_id → duplicate ama isimler tazelenir.
    r2 = client.post(
        "/api/v1/ingest/match", json=_renamed_payload(payload["source_game_id"])
    )
    assert r2.status_code == 200
    assert r2.json() == {"match_id": r1.json()["match_id"], "duplicate": True}

    conn = db()
    assert conn.execute("SELECT COUNT(*) c FROM matches").fetchone()["c"] == 1
    assert (
        conn.execute("SELECT COUNT(*) c FROM ingest_events").fetchone()["c"]
        == before_events
    )
    assert (
        conn.execute("SELECT COUNT(*) c FROM rating_history").fetchone()["c"]
        == before_ratings
    )
    # Ham payload ve maç satırı DEĞİŞMEDİ (ingest_events immutable).
    ev = conn.execute(
        "SELECT payload_json FROM ingest_events WHERE source_game_id=?",
        (payload["source_game_id"],),
    ).fetchone()
    assert json.loads(ev["payload_json"]) == payload
    assert (
        dict(
            conn.execute(
                "SELECT * FROM matches WHERE id=?", (r1.json()["match_id"],)
            ).fetchone()
        )
        == before_match
    )

    row = _player_by_puuid(conn)
    assert row["riot_id"] == "Teoman2#EUW"
    assert row["display_name"] == "Teoman2"


def test_custom_display_name_preserved_riot_id_still_refreshed(client, db):
    client.post("/api/v1/ingest/match", json=make_payload())
    pid = _player_by_puuid(db())["id"]
    r = client.patch(f"/api/v1/players/{pid}", json={"display_name": "Patron"})
    assert r.status_code == 200

    r = client.post(
        "/api/v1/ingest/match",
        json=_renamed_payload("6874231957", played_at="2026-08-12T20:41:03Z"),
    )
    assert r.status_code == 201

    row = _player_by_puuid(db())
    assert row["riot_id"] == "Teoman2#EUW"
    assert row["display_name"] == "Patron"  # elle verilen ad korunur


def test_participant_without_riot_id_left_untouched(client, db):
    client.post("/api/v1/ingest/match", json=make_payload())
    before = dict(_player_by_puuid(db()))

    payload = make_payload(
        source_game_id="6874231958", played_at="2026-08-12T20:41:03Z"
    )
    payload["participants"][0]["riot_id"] = None
    assert client.post("/api/v1/ingest/match", json=payload).status_code == 201

    assert dict(_player_by_puuid(db())) == before

    # Boş string de tazelemeyi tetiklemez.
    payload = make_payload(
        source_game_id="6874231959", played_at="2026-08-13T20:41:03Z"
    )
    payload["participants"][0]["riot_id"] = ""
    assert client.post("/api/v1/ingest/match", json=payload).status_code == 201

    assert dict(_player_by_puuid(db())) == before


def test_same_riot_id_resubmission_changes_nothing(client, db):
    client.post("/api/v1/ingest/match", json=make_payload())
    before = dict(_player_by_puuid(db()))

    r = client.post("/api/v1/ingest/match", json=make_payload())
    assert r.status_code == 200

    assert dict(_player_by_puuid(db())) == before


def test_rename_does_not_affect_rating(client, db):
    client.post("/api/v1/ingest/match", json=make_payload())
    conn = db()
    before = [
        dict(row)
        for row in conn.execute("SELECT * FROM rating_history ORDER BY id")
    ]

    r = client.post(
        "/api/v1/ingest/match", json=_renamed_payload(make_payload()["source_game_id"])
    )
    assert r.json()["duplicate"] is True

    after = [
        dict(row)
        for row in db().execute("SELECT * FROM rating_history ORDER BY id")
    ]
    assert after == before
