"""GÖREV 14 — Maç sonu envanteri (ingest_contract "items", api_contract §3 + §2).

Kapsam: migration 0005 kolonuna ingest yazımı (+422'ler ve alansız eski
payload), GET yanıtlarındaki üç durum (null / [] / dolu),
`PUT /matches/{id}/items` ve `top_items` sayımı. Envanterin rating'e HİÇBİR
etkisi yoktur — PUT'ta replay koşmadığı ayrıca kanıtlanır.
"""
from __future__ import annotations

import json

import pytest
from conftest import make_payload, make_role_payload

INGEST = "/api/v1/ingest/match"
FULL_ITEMS = [6697, 6676, 3036, 3031, 1055, 2523, 3340]


def _payload_with_items(
    items_by_index: dict[int, object], role_payload: bool = False, **kwargs
):
    """make_payload + belirtilen katılımcılara `items` alanı ekler.

    `role_payload=True` rol evrenine UYGUN kadroyu kullanır (make_payload'ın
    rol dağılımı bilinçli olarak bozuktur).
    """
    payload = (make_role_payload if role_payload else make_payload)(**kwargs)
    for index, items in items_by_index.items():
        payload["participants"][index]["items"] = items
    return payload


def _ingest(client, payload, expected=201):
    r = client.post(INGEST, json=payload)
    assert r.status_code == expected, r.text
    return r


def _items_json(conn) -> list:
    return [
        row["items_json"]
        for row in conn.execute(
            "SELECT items_json FROM match_participants ORDER BY id"
        )
    ]


def _counts(conn) -> tuple[int, int]:
    return (
        conn.execute("SELECT COUNT(*) c FROM matches").fetchone()["c"],
        conn.execute("SELECT COUNT(*) c FROM ingest_events").fetchone()["c"],
    )


def _first_player_id(conn) -> int:
    """Contract örneğindeki katılımcı (participants[0]) — testlerin öznesi."""
    return conn.execute(
        "SELECT id FROM players WHERE riot_id = 'Teoman#TR1'"
    ).fetchone()["id"]


def _match_id(conn, source_game_id: str = "6874231955") -> int:
    return conn.execute(
        "SELECT id FROM matches WHERE source_game_id = ?", (source_game_id,)
    ).fetchone()["id"]


def _top_items(client, player_id: int) -> list[dict]:
    r = client.get(f"/api/v1/players/{player_id}/stats")
    assert r.status_code == 200, r.text
    return r.json()["top_items"]


# ── Ingest (ingest_contract "items") ──────────────────────────────────────


def test_ingest_stores_items_and_keeps_raw_payload(client, db):
    payload = _payload_with_items({0: FULL_ITEMS})
    _ingest(client, payload)

    conn = db()
    stored = _items_json(conn)
    assert json.loads(stored[0]) == FULL_ITEMS
    assert stored[1:] == [None] * 9
    # Ham ingest_events AYNEN saklanır (db_schema ilke 1).
    raw = conn.execute("SELECT payload_json FROM ingest_events").fetchone()[0]
    assert json.loads(raw) == payload


def test_ingest_preserves_raw_item_order(client, db):
    """Ham SIRA korunur (son eleman genelde trinket) — sıralanmaz."""
    reversed_items = list(reversed(FULL_ITEMS))
    _ingest(client, _payload_with_items({0: reversed_items}))
    assert json.loads(_items_json(db())[0]) == reversed_items


def test_ingest_without_items_stays_null(client, db):
    """Eski exe'ler alanı hiç göndermez (geriye uyumluluk) → NULL = bilinmiyor."""
    _ingest(client, make_payload())
    assert _items_json(db()) == [None] * 10


def test_ingest_null_items_stays_null(client, db):
    _ingest(client, _payload_with_items({0: None}))
    assert _items_json(db()) == [None] * 10


def test_ingest_empty_items_is_stored_not_null(client, db):
    """`[]` = "bilgi var, envanter boş" — NULL'dan AYRI bir durumdur."""
    _ingest(client, _payload_with_items({0: []}))
    assert _items_json(db())[0] == "[]"


def test_ingest_items_max_seven_accepted(client, db):
    _ingest(client, _payload_with_items({0: FULL_ITEMS}))
    assert len(json.loads(_items_json(db())[0])) == 7


def test_ingest_too_many_items_rejected(client, db):
    r = client.post(INGEST, json=_payload_with_items({0: FULL_ITEMS + [1001]}))
    assert r.status_code == 422
    assert "7" in r.json()["detail"]
    # Reddedilen istek hiçbir şey yazmamalı (client_id 422 deseni).
    assert _counts(db()) == (0, 0)


@pytest.mark.parametrize(
    "items",
    [
        ["3031"],                 # metin
        [3031.5],                 # float
        [None],                   # null eleman
        [True],                   # bool int SAYILMAZ (eşya id'si değil)
        [3031, {"id": 3036}],     # nesne
        [3031, [3036]],           # iç içe dizi
    ],
)
def test_ingest_non_integer_item_rejected(client, db, items):
    r = client.post(INGEST, json=_payload_with_items({0: items}))
    assert r.status_code == 422
    assert "items" in r.json()["detail"]
    assert _counts(db()) == (0, 0)


@pytest.mark.parametrize("items", ["3031", 3031, {"0": 3031}])
def test_ingest_items_must_be_a_list(client, db, items):
    r = client.post(INGEST, json=_payload_with_items({0: items}))
    assert r.status_code == 422
    assert _counts(db()) == (0, 0)


def test_ingest_invalid_items_on_later_participant_writes_nothing(client, db):
    """Geçerli katılımcılar da yazılmaz: doğrulama DB'ye dokunmadan önce biter."""
    r = client.post(
        INGEST, json=_payload_with_items({0: FULL_ITEMS, 7: [3031, "x"]})
    )
    assert r.status_code == 422
    assert "participants[7]" in r.json()["detail"]
    assert _counts(db()) == (0, 0)


def test_duplicate_ingest_does_not_change_items(client, db):
    """Idempotency "işlem yok" demektir: ilk gönderimin envanteri korunur."""
    _ingest(client, _payload_with_items({0: FULL_ITEMS}))
    r = client.post(INGEST, json=_payload_with_items({0: [1001, 1002]}))
    assert r.status_code == 200
    assert r.json()["duplicate"] is True

    conn = db()
    assert json.loads(_items_json(conn)[0]) == FULL_ITEMS
    assert _counts(conn) == (1, 1)


# ── GET /matches + GET /matches/{id} (api_contract §3) ────────────────────


def test_match_participants_expose_three_item_states(client, db):
    """null = bilinmiyor · [] = bilgi var, boş · dolu dizi."""
    _ingest(client, _payload_with_items({0: FULL_ITEMS, 1: []}))
    match = client.get("/api/v1/matches").json()[0]
    by_player = {p["player_id"]: p["items"] for p in match["participants"]}

    conn = db()
    first = _first_player_id(conn)
    second = conn.execute(
        "SELECT id FROM players WHERE riot_id = 'Player1#TR1'"
    ).fetchone()["id"]
    third = conn.execute(
        "SELECT id FROM players WHERE riot_id = 'Player2#TR1'"
    ).fetchone()["id"]

    assert by_player[first] == FULL_ITEMS
    assert by_player[second] == []
    assert by_player[third] is None


def test_get_match_items_identical_to_list_element(client, db):
    """Tekil maç liste elemanıyla BİREBİR aynı şekil (paylaşımlı serializasyon)."""
    _ingest(client, _payload_with_items({0: FULL_ITEMS, 1: []}))
    match_id = _match_id(db())

    detail = client.get(f"/api/v1/matches/{match_id}").json()
    listed = client.get("/api/v1/matches").json()[0]
    assert detail == listed
    assert [p["items"] for p in detail["participants"]].count(FULL_ITEMS) == 1


def test_old_match_without_items_returns_null(client):
    _ingest(client, make_payload())
    match = client.get("/api/v1/matches").json()[0]
    assert all(p["items"] is None for p in match["participants"])


# ── PUT /matches/{id}/items (api_contract §3) ─────────────────────────────


def _put_items(client, match_id: int, items: dict):
    return client.put(f"/api/v1/matches/{match_id}/items", json={"items": items})


def _snapshot(conn) -> tuple[list, list]:
    """Her iki rating evreninin ham satırları (replay koşmadığının kanıtı)."""
    return (
        [
            tuple(row)
            for row in conn.execute(
                "SELECT id, player_id, match_id, mu_after, sigma_after, perf_score"
                " FROM rating_history ORDER BY id"
            )
        ],
        [
            tuple(row)
            for row in conn.execute(
                "SELECT id, player_id, match_id, role, mu_after, sigma_after"
                " FROM role_rating_history ORDER BY id"
            )
        ],
    )


def test_put_items_writes_partially(client, db):
    _ingest(client, make_payload())
    conn = db()
    match_id = _match_id(conn)
    pid = _first_player_id(conn)

    r = _put_items(client, match_id, {str(pid): FULL_ITEMS})
    assert r.status_code == 200
    assert r.json() == {"updated": 1}

    conn = db()
    stored = _items_json(conn)
    assert json.loads(stored[0]) == FULL_ITEMS
    assert stored[1:] == [None] * 9  # dokunulmayanlar NULL kalır


def test_put_items_overwrites_existing(client, db):
    """Ham arşiv OTORİTEDİR: mevcut değerin üzerine yazılır."""
    _ingest(client, _payload_with_items({0: [1001, 1002]}))
    conn = db()
    match_id = _match_id(conn)
    pid = _first_player_id(conn)

    assert _put_items(client, match_id, {str(pid): FULL_ITEMS}).json() == {
        "updated": 1
    }
    assert json.loads(_items_json(db())[0]) == FULL_ITEMS


def test_put_items_empty_list_allowed(client, db):
    _ingest(client, _payload_with_items({0: FULL_ITEMS}))
    conn = db()
    match_id = _match_id(conn)
    pid = _first_player_id(conn)

    assert _put_items(client, match_id, {str(pid): []}).json() == {"updated": 1}
    assert _items_json(db())[0] == "[]"


def test_put_items_multiple_players(client, db):
    _ingest(client, make_payload())
    conn = db()
    match_id = _match_id(conn)
    pids = [
        row["player_id"]
        for row in conn.execute(
            "SELECT player_id FROM match_participants WHERE match_id = ? ORDER BY id",
            (match_id,),
        )
    ]
    r = _put_items(
        client, match_id, {str(pids[0]): FULL_ITEMS, str(pids[3]): [1055]}
    )
    assert r.json() == {"updated": 2}

    match = client.get(f"/api/v1/matches/{match_id}").json()
    by_player = {p["player_id"]: p["items"] for p in match["participants"]}
    assert by_player[pids[0]] == FULL_ITEMS
    assert by_player[pids[3]] == [1055]
    assert by_player[pids[1]] is None


def test_put_items_unknown_match_404(client):
    r = _put_items(client, 999, {})
    assert r.status_code == 404
    assert "999" in r.json()["detail"]


def test_put_items_player_not_in_match_422(client, db):
    _ingest(client, make_payload())
    r = _put_items(client, _match_id(db()), {"9999": FULL_ITEMS})
    assert r.status_code == 422
    assert "9999" in r.json()["detail"]


def test_put_items_non_integer_key_422(client, db):
    _ingest(client, make_payload())
    r = _put_items(client, _match_id(db()), {"abc": FULL_ITEMS})
    assert r.status_code == 422


@pytest.mark.parametrize(
    "items", [FULL_ITEMS + [1001], ["3031"], [3031, None], 3031, "3031", None]
)
def test_put_items_invalid_value_422(client, db, items):
    _ingest(client, make_payload())
    conn = db()
    match_id = _match_id(conn)
    pid = _first_player_id(conn)
    r = _put_items(client, match_id, {str(pid): items})
    assert r.status_code == 422


def test_put_items_invalid_input_does_not_touch_db(client, db):
    """İlk anahtar geçerli, ikincisi değil → hiçbiri uygulanmaz."""
    _ingest(client, _payload_with_items({0: [1001]}))
    conn = db()
    match_id = _match_id(conn)
    pids = [
        row["player_id"]
        for row in conn.execute(
            "SELECT player_id FROM match_participants WHERE match_id = ? ORDER BY id",
            (match_id,),
        )
    ]
    before = _items_json(conn)

    r = _put_items(
        client,
        match_id,
        {str(pids[0]): FULL_ITEMS, str(pids[1]): [3031, "yanlış"]},
    )
    assert r.status_code == 422
    assert _items_json(db()) == before


def test_put_items_does_not_run_replay(client, db, monkeypatch):
    """Rating'e etkisi YOKTUR: hiçbir replay tetiklenmez (api_contract §3)."""
    from app.routers import matches as matches_router

    _ingest(
        client,
        _payload_with_items({0: [1001]}, role_payload=True, source_game_id="g1"),
    )
    _ingest(
        client,
        make_role_payload(source_game_id="g2", played_at="2026-08-12T20:00:00Z"),
    )
    conn = db()
    match_id = _match_id(conn, "g1")
    pid = _first_player_id(conn)
    before = _snapshot(conn)
    assert before[0] and before[1]  # her iki evrende de satır var

    def _boom(*args, **kwargs):  # pragma: no cover - çağrılırsa test kırılır
        raise AssertionError("PUT /items replay tetiklememeli")

    monkeypatch.setattr(matches_router, "replay", _boom)
    monkeypatch.setattr(matches_router, "replay_roles", _boom)

    r = _put_items(client, match_id, {str(pid): FULL_ITEMS})
    assert r.status_code == 200
    assert r.json() == {"updated": 1}
    assert _snapshot(db()) == before


def test_put_items_does_not_change_raw_ingest_events(client, db):
    """`items_json` küratörlü alandır: ham `ingest_events` DEĞİŞMEZ."""
    payload = _payload_with_items({0: [1001]})
    _ingest(client, payload)
    conn = db()
    match_id = _match_id(conn)
    pid = _first_player_id(conn)

    _put_items(client, match_id, {str(pid): FULL_ITEMS})

    raw = db().execute("SELECT payload_json FROM ingest_events").fetchone()[0]
    assert json.loads(raw) == payload


def test_put_items_requires_api_key(client, db):
    _ingest(client, make_payload())
    r = client.put(
        f"/api/v1/matches/{_match_id(db())}/items",
        json={"items": {}},
        headers={"X-API-Key": "wrong"},
    )
    assert r.status_code == 401


# ── top_items (api_contract §2 "Oyuncu profili") ──────────────────────────


def test_top_items_empty_without_item_data(client, db):
    _ingest(client, make_payload())
    assert _top_items(client, _first_player_id(db())) == []


def test_top_items_counts_and_orders(client, db):
    """Sıralama: sayım azalan → item_id artan."""
    # 3031: 3 maç · 6676: 2 maç · 1055: 1 maç
    _ingest(client, _payload_with_items({0: [3031, 6676]}, source_game_id="g1"))
    _ingest(
        client,
        _payload_with_items(
            {0: [3031, 6676, 1055]},
            source_game_id="g2",
            played_at="2026-08-12T20:00:00Z",
        ),
    )
    _ingest(
        client,
        _payload_with_items(
            {0: [3031]}, source_game_id="g3", played_at="2026-08-13T20:00:00Z"
        ),
    )
    assert _top_items(client, _first_player_id(db())) == [
        {"item_id": 3031, "matches": 3},
        {"item_id": 6676, "matches": 2},
        {"item_id": 1055, "matches": 1},
    ]


def test_top_items_tie_breaks_by_item_id_ascending(client, db):
    _ingest(client, _payload_with_items({0: [6676, 3031, 1055]}))
    assert [row["item_id"] for row in _top_items(client, _first_player_id(db()))] == [
        1055,
        3031,
        6676,
    ]


def test_top_items_counts_duplicate_item_once_per_match(client, db):
    """Aynı maçta aynı eşya (ör. iki iksir slotu) BİR kez sayılır."""
    _ingest(client, _payload_with_items({0: [2003, 2003, 2003, 3031]}))
    assert _top_items(client, _first_player_id(db())) == [
        {"item_id": 2003, "matches": 1},
        {"item_id": 3031, "matches": 1},
    ]


def test_top_items_ignores_matches_without_item_data(client, db):
    """items NULL olan maç sayıma girmez; `[]` girer ama katkısı yoktur."""
    _ingest(client, make_payload(source_game_id="g1"))
    _ingest(
        client,
        _payload_with_items(
            {0: []}, source_game_id="g2", played_at="2026-08-12T20:00:00Z"
        ),
    )
    _ingest(
        client,
        _payload_with_items(
            {0: [3031]}, source_game_id="g3", played_at="2026-08-13T20:00:00Z"
        ),
    )
    assert _top_items(client, _first_player_id(db())) == [
        {"item_id": 3031, "matches": 1}
    ]


def test_top_items_excludes_void_matches(client, db):
    """Tüm profil metrikleri gibi yalnız valid maçlardan (duration < 300 → void)."""
    _ingest(
        client,
        _payload_with_items({0: [3031]}, source_game_id="g1", duration_s=120),
    )
    conn = db()
    assert conn.execute("SELECT status FROM matches").fetchone()[0] == "void"
    assert _top_items(client, _first_player_id(conn)) == []


def test_top_items_limited_to_ten(client, db):
    """14 farklı eşya, hepsi 1 maç → item_id artan ilk 10 kayıt."""
    first_seven = [1001, 1002, 1003, 1004, 1005, 1006, 1007]
    second_seven = [1008, 1009, 1010, 1011, 1012, 1013, 1014]
    _ingest(client, _payload_with_items({0: first_seven}, source_game_id="g1"))
    _ingest(
        client,
        _payload_with_items(
            {0: second_seven},
            source_game_id="g2",
            played_at="2026-08-12T20:00:00Z",
        ),
    )
    top = _top_items(client, _first_player_id(db()))
    assert len(top) == 10
    assert [row["item_id"] for row in top] == list(range(1001, 1011))
    assert all(row["matches"] == 1 for row in top)


def test_top_items_after_put_backfill(client, db):
    """Backfill edilen envanter profilde görünür (uçtan uca)."""
    _ingest(client, make_payload())
    conn = db()
    match_id = _match_id(conn)
    pid = _first_player_id(conn)
    assert _top_items(client, pid) == []

    _put_items(client, match_id, {str(pid): [3031, 6676]})
    assert _top_items(client, pid) == [
        {"item_id": 3031, "matches": 1},
        {"item_id": 6676, "matches": 1},
    ]


def test_top_items_is_per_player(client, db):
    """Sayım yalnız o oyuncunun kendi envanterinden gelir."""
    _ingest(client, _payload_with_items({0: [3031], 5: [6676]}))
    conn = db()
    other = conn.execute(
        "SELECT id FROM players WHERE riot_id = 'Player5#TR1'"
    ).fetchone()["id"]
    assert _top_items(client, _first_player_id(conn)) == [
        {"item_id": 3031, "matches": 1}
    ]
    assert _top_items(client, other) == [{"item_id": 6676, "matches": 1}]
