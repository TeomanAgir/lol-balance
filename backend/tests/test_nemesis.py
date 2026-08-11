"""GET /nemesis + POST /balance/nemesis (api_contract §2/§4, GÖREV 3).

Haftalık pencere `now` enjeksiyonuyla sabitlenir (`nemesis_pairs(..., now=...)`),
böylece senaryolar gerçek saatten bağımsız ve deterministiktir. Endpoint'ler
ayrıca gerçek UTC şimdiye göreli played_at ile doğrulanır.

Kadro kurgusu: `make_roster_payload` rolü takım listesindeki İNDEKSTEN üretir
(0=TOP, 1=JUNGLE, 2=MIDDLE, 3=BOTTOM, 4=UTILITY), yani i. indeksteki iki
oyuncu o maçta aynı koridorda karşılaşır. Odaklanılan çift her maçta aynı
slotta durur; kalan 8 oyuncu `_lineup` ile döndürülür, böylece onların hiçbir
(çift, rol) üçlüsü 3 karşılaşma eşiğine ULAŞMAZ — testler tek adayı izler.
"""
from datetime import datetime, timedelta, timezone

from conftest import ROLES_SET, make_roster_payload

from app.services.nemesis import encounter_candidates, nemesis_pairs

# Sabit "şimdi": pencere = 2026-08-13T12:00:00Z < played_at <= 2026-08-20T12:00:00Z
NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)

A, B = "Ada", "Bora"
R1_100 = ["C1", "C2", "C3", "C4"]
R1_200 = ["D1", "D2", "D3", "D4"]
GROUP1 = [A, B] + R1_100 + R1_200

C, D = "Ceyda", "Doruk"
R2_100 = ["E1", "E2", "E3", "E4"]
R2_200 = ["F1", "F2", "F3", "F4"]
GROUP2 = [C, D] + R2_100 + R2_200

TOP, MIDDLE = 0, 2  # `slot` = takım listesindeki indeks = rol


# --------------------------------------------------------------------------
# Yardımcılar
# --------------------------------------------------------------------------
def _make_players(client, names):
    ids = {}
    for name in names:
        r = client.post(
            "/api/v1/players", json={"display_name": name, "riot_id": f"{name}#TR1"}
        )
        assert r.status_code == 201, r.text
        ids[name] = r.json()["id"]
    return ids


def _ingest(client, ids, sgid, played_at, t100, t200,
            winner_team=100, null_positions=()):
    payload = make_roster_payload(
        sgid,
        played_at,
        [ids[n] for n in t100],
        [ids[n] for n in t200],
        winner_team=winner_team,
    )
    null_ids = {ids[n] for n in null_positions}
    for p in payload["participants"]:
        if p["player_id"] in null_ids:
            p["position"] = None
    r = client.post("/api/v1/ingest/match", json=payload)
    assert r.status_code == 201, r.text
    return r.json()["match_id"]


def _lineup(anchor, rest, slot, k):
    """`anchor` sabit `slot`'ta; kalan 4 oyuncu k kadar döndürülmüş sırada."""
    rot = [rest[(j + k) % 4] for j in range(4)]
    return rot[:slot] + [anchor] + rot[slot:]


def _faceoff(client, ids, prefix, anchor100, anchor200, rest100, rest200,
             slot, winners, days, null_positions=()):
    """anchor100 vs anchor200'ü `slot` rolünde len(winners) kez karşılaştırır."""
    return [
        _ingest(
            client, ids, f"{prefix}-{k}", day,
            _lineup(anchor100, rest100, slot, k),
            _lineup(anchor200, rest200, slot, 0),
            winner_team=winner,
            null_positions=null_positions,
        )
        for k, (winner, day) in enumerate(zip(winners, days))
    ]


def _days(n, start_day=1, month=8):
    return [f"2026-{month:02d}-{start_day + i:02d}T20:00:00Z" for i in range(n)]


def _recent_days(n):
    """Gerçek UTC şimdiye göre son n gün (hepsi 7 günlük pencerenin İÇİNDE)."""
    base = datetime.now(timezone.utc) - timedelta(days=n)
    return [
        (base + timedelta(days=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for i in range(n)
    ]


def _with_conn(db, fn):
    conn = db()
    try:
        return fn(conn)
    finally:
        conn.close()


def _nemesis(db, now=NOW):
    return _with_conn(db, lambda conn: nemesis_pairs(conn, now=now))


def _candidates(db, match_ids=None):
    """(low_id, high_id, role) → (encounters, low_wins) — eşiği geçen adaylar."""
    rows = _with_conn(db, lambda conn: encounter_candidates(conn, match_ids))
    return {
        (r["low_id"], r["high_id"], r["role"]): (r["encounters"], r["low_wins"])
        for r in rows
    }


# --------------------------------------------------------------------------
# Karşılaşma sayımı
# --------------------------------------------------------------------------
def test_encounter_counts_pair_role_and_wins(client, db):
    ids = _make_players(client, GROUP1)
    # Ada (team100) vs Bora (team200), MIDDLE, 3 maç; Ada 2 galibiyet.
    _faceoff(client, ids, "m", A, B, R1_100, R1_200, MIDDLE,
             winners=[100, 200, 100], days=_days(3))

    assert _candidates(db) == {(ids[A], ids[B], "MIDDLE"): (3, 2)}

    pair = _nemesis(db)["all_time"]
    assert pair["role"] == "MIDDLE"
    # players: küçük player_id önce (Ada önce oluşturuldu → küçük id).
    assert ids[A] < ids[B]
    assert pair["players"] == [
        {"player_id": ids[A], "display_name": A, "wins": 2},
        {"player_id": ids[B], "display_name": B, "wins": 1},
    ]
    assert pair["encounters"] == 3
    # 1 - 2*|2/3 - 0.5| = 0.6666... → 2 ondalık
    assert pair["closeness"] == 0.67


def test_null_position_is_not_an_encounter(client, db):
    ids = _make_players(client, GROUP1)
    # Aynı kurgu, ama Ada'nın position'ı her maçta null → karşılaşma sayılmaz.
    _faceoff(client, ids, "m", A, B, R1_100, R1_200, MIDDLE,
             winners=[100, 200, 100], days=_days(3), null_positions=(A,))

    assert _candidates(db) == {}
    assert _nemesis(db)["all_time"] is None


def test_same_team_is_not_an_encounter(client, db):
    ids = _make_players(client, GROUP1)
    # Ada ve Bora AYNI takımda, aynı rol imkânsız olduğundan Bora 200'ün
    # yerine geçmez: karşılaşma tanımı KARŞI takım şartı içerir.
    for k, day in enumerate(_days(4)):
        _ingest(client, ids, f"same-{k}", day,
                [A, *R1_100[:4]], [B, *R1_200[:4]], winner_team=100)
    # Kurgu doğru: Ada-Bora TOP'ta karşı takımlarda → aday.
    assert (ids[A], ids[B], "TOP") in _candidates(db)

    # Şimdi ikisini de team100'e koyalım (aynı takım) — yeni karşılaşma yok.
    before = _candidates(db)[(ids[A], ids[B], "TOP")]
    for k, day in enumerate(_days(3, start_day=10)):
        _ingest(client, ids, f"ally-{k}", day,
                [A, B, *R1_100[:3]], [R1_100[3], *R1_200], winner_team=100)
    assert _candidates(db)[(ids[A], ids[B], "TOP")] == before


def test_different_roles_are_separate_candidates(client, db):
    ids = _make_players(client, GROUP1 + GROUP2)
    # Aynı çift (Ada-Bora) iki farklı rolde 3'er kez karşılaşır.
    # Dolgu kadroları ayrı tutulur ki başka aday doğmasın.
    _faceoff(client, ids, "top", A, B, R1_100, R1_200, TOP,
             winners=[100, 200, 100], days=_days(3))
    _faceoff(client, ids, "mid", A, B, R2_100, R2_200, MIDDLE,
             winners=[200, 200, 100], days=_days(3, start_day=10))

    cands = _candidates(db)
    assert cands == {
        (ids[A], ids[B], "TOP"): (3, 2),
        (ids[A], ids[B], "MIDDLE"): (3, 1),
    }
    # 6 karşılaşmalık TEK aday YOKTUR — birim (çift, rol) üçlüsüdür.
    assert all(enc == 3 for enc, _ in cands.values())


def test_void_match_is_excluded(client, db):
    ids = _make_players(client, GROUP1)
    match_ids = _faceoff(client, ids, "m", A, B, R1_100, R1_200, TOP,
                         winners=[100, 200, 100], days=_days(3))
    assert _nemesis(db)["all_time"] is not None

    assert client.post(f"/api/v1/matches/{match_ids[1]}/void").status_code == 200

    assert _candidates(db) == {}  # 3 → 2, eşiğin altına düştü
    assert _nemesis(db)["all_time"] is None


# --------------------------------------------------------------------------
# Uygunluk eşiği
# --------------------------------------------------------------------------
def test_two_encounters_is_not_a_candidate_three_is(client, db):
    ids = _make_players(client, GROUP1)
    days = _days(3)
    _faceoff(client, ids, "m", A, B, R1_100, R1_200, TOP,
             winners=[100, 200], days=days[:2])
    assert _candidates(db) == {}
    assert _nemesis(db)["all_time"] is None

    _ingest(client, ids, "m-2", days[2],
            _lineup(A, R1_100, TOP, 2), _lineup(B, R1_200, TOP, 0),
            winner_team=100)
    pair = _nemesis(db)["all_time"]
    assert pair is not None
    assert pair["encounters"] == 3


# --------------------------------------------------------------------------
# Sıralama
# --------------------------------------------------------------------------
def _two_groups(client, winners1, winners2, slot1=TOP, slot2=TOP):
    ids = _make_players(client, GROUP1 + GROUP2)
    _faceoff(client, ids, "g1", A, B, R1_100, R1_200, slot1,
             winners=winners1, days=_days(len(winners1), month=8))
    _faceoff(client, ids, "g2", C, D, R2_100, R2_200, slot2,
             winners=winners2, days=_days(len(winners2), month=7))
    return ids


def _pair_ids(pair):
    return [p["player_id"] for p in pair["players"]]


def test_closeness_beats_encounters(client, db):
    # Ada-Bora: 4 karşılaşma, 2-2 → closeness 1.0
    # Ceyda-Doruk: 6 karşılaşma, 4-2 → closeness 0.67
    ids = _two_groups(
        client,
        winners1=[100, 200, 100, 200],
        winners2=[100, 100, 100, 100, 200, 200],
    )
    cands = _candidates(db)
    assert cands[(ids[A], ids[B], "TOP")] == (4, 2)
    assert cands[(ids[C], ids[D], "TOP")] == (6, 4)

    pair = _nemesis(db)["all_time"]
    # Daha AZ karşılaşan ama daha başa baş çift kazanır.
    assert _pair_ids(pair) == [ids[A], ids[B]]
    assert pair["closeness"] == 1.0
    assert pair["encounters"] == 4


def test_encounters_break_closeness_tie(client, db):
    # İkisi de tam başa baş (closeness 1.0); çok karşılaşan kazanır.
    ids = _two_groups(
        client,
        winners1=[100, 200, 100, 200],
        winners2=[100, 200, 100, 200, 100, 200],
    )
    pair = _nemesis(db)["all_time"]
    assert _pair_ids(pair) == [ids[C], ids[D]]
    assert pair["encounters"] == 6
    assert pair["closeness"] == 1.0


def test_canonical_role_breaks_encounter_tie(client, db):
    # closeness ve encounters eşit; roller MIDDLE vs TOP → TOP kazanır
    # (kanonik sıra), player_id'leri BÜYÜK olan çift olmasına rağmen.
    ids = _two_groups(
        client,
        winners1=[100, 200, 100, 200],
        winners2=[100, 200, 100, 200],
        slot1=MIDDLE,
        slot2=TOP,
    )
    assert ids[A] < ids[C]  # id kırılımı olsaydı Ada-Bora kazanırdı
    pair = _nemesis(db)["all_time"]
    assert pair["role"] == "TOP"
    assert _pair_ids(pair) == [ids[C], ids[D]]


def test_player_ids_break_role_tie(client, db):
    # Her şey eşit (closeness 1.0, 4 karşılaşma, TOP) → (küçük id, büyük id) artan.
    ids = _two_groups(
        client,
        winners1=[100, 200, 100, 200],
        winners2=[100, 200, 100, 200],
    )
    pair = _nemesis(db)["all_time"]
    assert _pair_ids(pair) == [ids[A], ids[B]]


# --------------------------------------------------------------------------
# Haftalık pencere + active
# --------------------------------------------------------------------------
def test_weekly_counts_only_window_encounters(client, db):
    ids = _make_players(client, GROUP1)
    # 3 maç pencere DIŞI (08-01..03), 3 maç pencere İÇİ (08-14/16/19).
    days = _days(3) + ["2026-08-14T20:00:00Z", "2026-08-16T20:00:00Z",
                       "2026-08-19T20:00:00Z"]
    _faceoff(client, ids, "m", A, B, R1_100, R1_200, TOP,
             winners=[100, 100, 100, 100, 200, 200], days=days)

    body = _nemesis(db)
    assert body["all_time"]["encounters"] == 6
    assert body["weekly"]["encounters"] == 3
    # Pencere içi 3 maçın 1'ini Ada kazandı (100, 200, 200).
    assert _pair_ids(body["weekly"]) == [ids[A], ids[B]]
    assert body["weekly"]["players"][0]["wins"] == 1
    assert body["weekly"]["players"][1]["wins"] == 2
    assert body["all_time"]["players"][0]["wins"] == 4
    assert body["active"] == "weekly"


def test_now_injection_moves_the_window(client, db):
    ids = _make_players(client, GROUP1)
    days = _days(3) + ["2026-08-14T20:00:00Z", "2026-08-16T20:00:00Z",
                       "2026-08-19T20:00:00Z"]
    _faceoff(client, ids, "m", A, B, R1_100, R1_200, TOP,
             winners=[100, 100, 100, 100, 200, 200], days=days)

    # 08-05'te pencere (07-29, 08-05] → yalnız eski 3 maç: Ada 3-0 → closeness 0.0
    earlier = _nemesis(db, now=datetime(2026, 8, 5, tzinfo=timezone.utc))
    assert earlier["weekly"]["encounters"] == 3
    assert earlier["weekly"]["closeness"] == 0.0
    assert earlier["weekly"]["players"][0]["wins"] == 3
    # NOW'da aynı veri farklı bir haftalık çift üretir.
    assert _nemesis(db)["weekly"]["closeness"] != 0.0
    assert ids[A] in _pair_ids(earlier["weekly"])


def test_weekly_falls_back_to_last_match_anchor(client, db):
    ids = _make_players(client, GROUP1)
    # Tüm maçlar rolling pencerenin dışında → çapa son valid maça kayar
    # ([07-27, 08-03]) ve üç maç da pencereye girer.
    _faceoff(client, ids, "m", A, B, R1_100, R1_200, TOP,
             winners=[100, 200, 100], days=_days(3))

    body = _nemesis(db)
    assert body["weekly"] is not None
    assert body["weekly"]["encounters"] == 3
    assert body["active"] == "weekly"


def test_active_falls_back_to_all_time(client, db):
    ids = _make_players(client, GROUP1)
    # Karşılaşmalar 14 gün arayla: hiçbir 7 günlük pencere 3'ünü birden
    # kapsamaz (çapalanmış pencere yalnız son maçı alır).
    _faceoff(client, ids, "m", A, B, R1_100, R1_200, TOP,
             winners=[100, 200, 100],
             days=["2026-07-01T20:00:00Z", "2026-07-15T20:00:00Z",
                   "2026-07-29T20:00:00Z"])

    body = _nemesis(db)
    assert body["all_time"] is not None
    assert body["all_time"]["encounters"] == 3
    assert body["weekly"] is None
    assert body["active"] == "all_time"
    assert _pair_ids(body["all_time"]) == [ids[A], ids[B]]


def test_active_null_without_data(client, db):
    _make_players(client, GROUP1)
    assert _nemesis(db) == {"all_time": None, "weekly": None, "active": None}


# --------------------------------------------------------------------------
# GET /nemesis
# --------------------------------------------------------------------------
def test_endpoint_returns_contract_shape(client):
    ids = _make_players(client, GROUP1)
    _faceoff(client, ids, "m", A, B, R1_100, R1_200, MIDDLE,
             winners=[100, 200, 100], days=_recent_days(3))

    r = client.get("/api/v1/nemesis")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"all_time", "weekly", "active"}
    assert body["active"] == "weekly"
    pair = body["weekly"]
    assert set(pair) == {"role", "players", "encounters", "closeness"}
    assert pair["role"] == "MIDDLE"
    assert pair["encounters"] == 3
    assert [set(p) for p in pair["players"]] == [
        {"player_id", "display_name", "wins"}
    ] * 2
    assert _pair_ids(pair) == [ids[A], ids[B]]
    assert body["all_time"] == pair


def test_endpoint_nulls_without_data(client):
    _make_players(client, GROUP1)
    assert client.get("/api/v1/nemesis").json() == {
        "all_time": None, "weekly": None, "active": None
    }


def test_endpoint_requires_api_key(client):
    r = client.get("/api/v1/nemesis", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


# --------------------------------------------------------------------------
# POST /balance/nemesis
# --------------------------------------------------------------------------
def _nemesis_scenario(client, extra_names=()):
    """Ada-Bora TOP'ta 4 kez (2-2) karşılaşır; hepsi haftalık pencerede."""
    ids = _make_players(client, GROUP1 + list(extra_names))
    _faceoff(client, ids, "m", A, B, R1_100, R1_200, TOP,
             winners=[100, 200, 100, 200], days=_recent_days(4))
    return ids


def test_balance_nemesis_conflict_without_active_pair(client):
    ids = _make_players(client, GROUP1)
    r = client.post(
        "/api/v1/balance/nemesis",
        json={"player_ids": [ids[n] for n in GROUP1]},
    )
    assert r.status_code == 409
    assert "nemesis" in r.json()["detail"].lower()


def test_balance_nemesis_422_when_pair_member_not_selected(client):
    extra = ["X1", "X2"]
    ids = _nemesis_scenario(client, extra)
    # Ada HARİÇ 10 oyuncu (Bora dahil).
    pool = [B] + R1_100 + R1_200 + ["X1"]
    assert len(pool) == 10 and A not in pool
    r = client.post(
        "/api/v1/balance/nemesis", json={"player_ids": [ids[n] for n in pool]}
    )
    assert r.status_code == 422
    assert str(ids[A]) in r.json()["detail"]


def test_balance_nemesis_pins_pair_to_opposite_teams(client):
    ids = _nemesis_scenario(client)
    pool = [ids[n] for n in GROUP1]

    active = client.get("/api/v1/nemesis").json()
    assert active["active"] == "weekly"
    role = active["weekly"]["role"]

    r = client.post(
        "/api/v1/balance/nemesis", json={"player_ids": pool, "top_n": 3}
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["engine_version"] == "openskill-pl-blend50-v1"
    assert body["nemesis"] == {
        "source": "weekly", "role": role, "player_ids": [ids[A], ids[B]]
    }
    assert len(body["suggestions"]) == 3

    for s in body["suggestions"]:
        t100 = {slot["player_id"]: slot["position"] for slot in s["team_100"]}
        t200 = {slot["player_id"]: slot["position"] for slot in s["team_200"]}
        assert sorted(list(t100) + list(t200)) == sorted(pool)
        assert set(t100.values()) == ROLES_SET
        assert set(t200.values()) == ROLES_SET
        # Çift KARŞI takımlarda ve İKİSİ DE nemesis rolünde.
        assert (ids[A] in t100) != (ids[B] in t100)
        assert (ids[A] in t200) != (ids[B] in t200)
        assigned = {**t100, **t200}
        assert assigned[ids[A]] == role
        assert assigned[ids[B]] == role
        assert 0.0 <= s["p_win_team_100"] <= 1.0

    qualities = [s["quality"] for s in body["suggestions"]]
    assert qualities == sorted(qualities, reverse=True)


def test_balance_nemesis_is_deterministic(client):
    ids = _nemesis_scenario(client)
    pool = [ids[n] for n in GROUP1]
    first = client.post("/api/v1/balance/nemesis", json={"player_ids": pool})
    second = client.post("/api/v1/balance/nemesis", json={"player_ids": pool})
    assert first.json() == second.json()
    assert len(first.json()["suggestions"]) == 3  # default top_n


def test_balance_nemesis_shares_base_validation(client):
    ids = _nemesis_scenario(client)
    pool = [ids[n] for n in GROUP1]

    assert client.post(
        "/api/v1/balance/nemesis", json={"player_ids": pool[:9]}
    ).status_code == 422
    dupes = list(pool)
    dupes[9] = dupes[0]
    assert client.post(
        "/api/v1/balance/nemesis", json={"player_ids": dupes}
    ).status_code == 422
    unknown = list(pool)
    unknown[9] = 9999
    r = client.post("/api/v1/balance/nemesis", json={"player_ids": unknown})
    assert r.status_code == 422
    assert "9999" in r.json()["detail"]


def test_balance_nemesis_requires_api_key(client):
    r = client.post(
        "/api/v1/balance/nemesis",
        json={"player_ids": list(range(1, 11))},
        headers={"X-API-Key": "wrong"},
    )
    assert r.status_code == 401
