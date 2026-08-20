"""GET /highlights/weekly — haftanın enleri (api_contract §2, GÖREV 2).

Pencere `now` enjeksiyonuyla sabitlenir (`weekly_highlights(..., now=...)`),
böylece senaryolar gerçek saatten bağımsız ve deterministiktir. Endpoint'in
kendisi ayrı bir testte (gerçek UTC şimdiye göreli played_at ile) doğrulanır.

Beklenen değerler HER ZAMAN bağımsız bir kaynaktan üretilir: score'lar
`/api/v1/leaderboard` yanıtından, rising_star delta'sı `rating_history`
satırlarından testin kendi hesabıyla — servis mantığı kopyalanmaz.
"""
from datetime import datetime, timedelta, timezone

from conftest import make_roster_payload

from app.services.weekly import weekly_highlights

ENGINE = "openskill-pl-blend30-s2-v1"

# Sabit "şimdi": pencere = 2026-08-13T12:00:00Z < played_at <= 2026-08-20T12:00:00Z
NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)

TEN = ["Ali", "Burak", "Cem", "Deniz", "Emre",
       "Fatma", "Gizem", "Hakan", "Irmak", "Jale"]
ROLES = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]


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


def _ingest(client, ids, sgid, played_at, team100, team200,
            winner_team=100, duration_s=1874, overrides=None):
    """Kadroyu (isimle) verilen maçı gönderir; rol = kadro sırası
    (TOP, JUNGLE, MIDDLE, BOTTOM, UTILITY — make_roster_payload)."""
    payload = make_roster_payload(
        sgid,
        played_at,
        [ids[n] for n in team100],
        [ids[n] for n in team200],
        winner_team=winner_team,
        duration_s=duration_s,
    )
    name_by_id = {v: k for k, v in ids.items()}
    for p in payload["participants"]:
        override = (overrides or {}).get(name_by_id[p["player_id"]])
        if override is not None:
            p.update(override)
    r = client.post("/api/v1/ingest/match", json=payload)
    assert r.status_code == 201, r.text
    return r.json()["match_id"]


def _highlights(db, now=NOW):
    conn = db()
    try:
        return weekly_highlights(conn, ENGINE, now=now)
    finally:
        conn.close()


def _leaderboard(client):
    r = client.get("/api/v1/leaderboard")
    assert r.status_code == 200, r.text
    return r.json()


def _scores(client):
    """display_name → GÜNCEL score (bağımsız kaynak: leaderboard)."""
    return {p["display_name"]: p["rating"]["score"] for p in _leaderboard(client)}


def _role_scores(client, role):
    """display_name → GÜNCEL rol score'u (bağımsız kaynak: leaderboard)."""
    return {
        p["display_name"]: p["role_ratings"][role]["score"]
        for p in _leaderboard(client)
    }


def _expected_winner(values, matches):
    """Contract eşitlik kırılımı: değer ↓ → pencere maç sayısı ↓ → ad alfabetik."""
    return min(matches, key=lambda n: (-values[n], -matches[n], n))


def _ordinal_delta(db, player_id, first_match_id, last_match_id):
    """İLK pencere maçı ÖNCESİ → SON pencere maçı SONRASI ordinal farkı.

    Servisten bağımsız hesap: satırlar match_id ile açıkça seçilir.
    """
    conn = db()
    try:
        first = conn.execute(
            "SELECT mu_before, sigma_before FROM rating_history "
            "WHERE player_id = ? AND match_id = ? AND engine_version = ?",
            (player_id, first_match_id, ENGINE),
        ).fetchone()
        last = conn.execute(
            "SELECT mu_after, sigma_after FROM rating_history "
            "WHERE player_id = ? AND match_id = ? AND engine_version = ?",
            (player_id, last_match_id, ENGINE),
        ).fetchone()
    finally:
        conn.close()
    return (last["mu_after"] - 3.0 * last["sigma_after"]) - (
        first["mu_before"] - 3.0 * first["sigma_before"]
    )


# --------------------------------------------------------------------------
# Ana senaryo
# --------------------------------------------------------------------------
# Pencere DIŞI (2026-08-01..06), her maçı team100 kazanır:
#   100 = [Zirve, Ali, Burak, Cem, Deniz]  200 = [Emre, Fatma, Gizem, Hakan, Irmak]
#   → Zirve 6G/0M ile en yüksek güncel score'u alır ve pencerede HİÇ oynamaz.
#   (aktif blend30-s2'de mu payı %30 olduğundan 3 galibiyet yetmez: az maç =
#   yüksek sigma cezası (S=2) mu avantajını yer; 6 galibiyet Zirve'yi rahat
#   marjla zirvede tutar.)
# Pencere İÇİ (08-14, 08-16, 08-19), her maçı team100 kazanır:
#   100 = [Emre, Fatma, Gizem, Hakan, Irmak]  200 = [Ali, Burak, Cem, Deniz, Jale]
#   → Emre grubu 6 mağlubiyetin ardından 3 galibiyet: pencere içi yükseliş onlarda.
# Statlar tüm katılımcılarda aynı (perf = 1.0 nötr) → aynı takımdaki oyuncuların
# rating yörüngesi BİREBİR aynıdır; bu, eşitlik kırılımlarını test edilebilir kılar.
OLD_100 = ["Zirve", "Ali", "Burak", "Cem", "Deniz"]
OLD_200 = ["Emre", "Fatma", "Gizem", "Hakan", "Irmak"]
WIN_100 = ["Emre", "Fatma", "Gizem", "Hakan", "Irmak"]
WIN_200 = ["Ali", "Burak", "Cem", "Deniz", "Jale"]


def _scenario(client):
    """(ids, pencere içi maç id'leri kronolojik) döner."""
    ids = _make_players(client, TEN + ["Zirve"])
    for i, day in enumerate(("01", "02", "03", "04", "05", "06")):
        _ingest(client, ids, f"old{i}", f"2026-08-{day}T20:00:00Z",
                OLD_100, OLD_200, winner_team=100)
    window_ids = [
        _ingest(client, ids, f"win{i}", f"2026-08-{day}T20:00:00Z",
                WIN_100, WIN_200, winner_team=100)
        for i, day in enumerate(("14", "16", "19"))
    ]
    return ids, window_ids


def test_window_bounds_and_no_fallback(client, db):
    _scenario(client)
    window = _highlights(db)["window"]
    assert window == {
        "start": "2026-08-13T12:00:00Z",
        "end": "2026-08-20T12:00:00Z",
        "fallback": False,
    }


def test_best_player_must_have_played_in_window(client, db):
    _scenario(client)
    hl = _highlights(db)
    scores = _scores(client)

    # Kurulumun ön koşulu: en yüksek güncel score pencerede oynamayan Zirve'de.
    assert max(scores, key=lambda n: scores[n]) == "Zirve"

    best = hl["best_player"]
    assert best["display_name"] != "Zirve"
    # Pencerede 10 oyuncunun her biri 3 maç oynadı.
    in_window = {n: 3 for n in TEN}
    expected = _expected_winner(scores, in_window)
    assert best["display_name"] == expected
    assert best["player_id"] is not None
    assert best["matches_in_window"] == 3
    # Score GÜNCEL değerdir (leaderboard ile birebir), 2 ondalığa yuvarlanır.
    assert best["score"] == round(scores[expected], 2)


def test_matches_in_window_excludes_older_matches(client, db):
    _scenario(client)
    best = _highlights(db)["best_player"]
    played = {
        p["display_name"]: p["matches_played"] for p in _leaderboard(client)
    }
    # Kazanan pencere dışında da oynamış olabilir; sayaç yalnız pencereyi sayar.
    assert best["matches_in_window"] == 3
    assert played[best["display_name"]] in (3, 9)


def test_rising_star_uses_window_endpoints(client, db):
    ids, window_ids = _scenario(client)
    star = _highlights(db)["rising_star"]

    # Emre grubu pencerede 3 galibiyet aldı (öncesinde 3 mağlubiyetle düşük
    # başladılar) → yükseliş onlarda; beşinin yörüngesi BİREBİR aynı olduğu
    # için delta eşit, eşitliği ad alfabetiği kırar → Emre.
    assert star["display_name"] == "Emre"

    expected = _ordinal_delta(db, ids["Emre"], window_ids[0], window_ids[-1])
    assert star["delta"] == round(expected, 2)
    assert star["delta"] > 0
    assert star["matches_in_window"] == 3

    # Pencere ÇAPALIDIR: tüm kariyer farkı (ilk maçtan bugüne) bambaşkadır.
    conn = db()
    try:
        first_ever = conn.execute(
            "SELECT id FROM matches ORDER BY played_at, id LIMIT 1"
        ).fetchone()["id"]
    finally:
        conn.close()
    career = _ordinal_delta(db, ids["Emre"], first_ever, window_ids[-1])
    assert round(career, 2) != star["delta"]

    # Pencerede kaybedenlerin delta'sı daha düşük olmalı (seçim argmax'tır).
    loser = _ordinal_delta(db, ids["Ali"], window_ids[0], window_ids[-1])
    assert loser < expected


def test_best_by_role_winner_and_window_filter(client, db):
    _scenario(client)
    best_by_role = _highlights(db)["best_by_role"]
    assert sorted(best_by_role) == sorted(ROLES)

    # Kadro sırası rolü belirler: pencerede TOP'ta yalnız Emre (100) ve Ali (200)
    # oynadı; Zirve TOP'ta 3 galibiyetle daha yüksek rol score'una sahip ama
    # PENCEREDE OYNAMADI → aday değildir.
    top_scores = _role_scores(client, "TOP")
    assert top_scores["Zirve"] > top_scores["Emre"]

    top = best_by_role["TOP"]
    assert top["display_name"] == "Emre"
    assert top["matches_in_window"] == 3
    assert top["score"] == round(top_scores["Emre"], 2)

    # Her rolde pencerenin kazanan takımından biri önde olmalı (o rolde
    # pencere içi 3 galibiyet vs 3 mağlubiyet).
    for role, winner_name in zip(ROLES, WIN_100):
        card = best_by_role[role]
        assert card is not None
        assert card["display_name"] == winner_name
        role_scores = _role_scores(client, role)
        assert card["score"] == round(role_scores[winner_name], 2)


def test_best_by_role_null_when_nobody_played_role(client, db):
    ids = _make_players(client, TEN)
    # Tek pencere maçı; bir katılımcının rolü null → maç rol evrenine UYGUN
    # DEĞİL (role_rating_history satırı üretmez) → 5 rol de null.
    _ingest(client, ids, "g1", "2026-08-14T20:00:00Z", TEN[:5], TEN[5:],
            overrides={"Ali": {"position": None}})
    hl = _highlights(db)
    assert hl["best_by_role"] == {role: None for role in ROLES}
    # Ana evren etkilenmez: best_player ve rising_star yine dolu.
    assert hl["best_player"] is not None
    assert hl["rising_star"] is not None


# --------------------------------------------------------------------------
# Pencere kenar durumları
# --------------------------------------------------------------------------
def test_window_boundaries_are_exclusive_start_inclusive_end(client, db):
    ids = _make_players(client, TEN)
    # start'ın TAM üstünde → HARİÇ (start < played_at); end'in tam üstünde → DAHİL.
    _ingest(client, ids, "at-start", "2026-08-13T12:00:00Z", TEN[:5], TEN[5:])
    _ingest(client, ids, "at-end", "2026-08-20T12:00:00Z", TEN[:5], TEN[5:])
    hl = _highlights(db)
    assert hl["window"]["fallback"] is False
    assert hl["best_player"]["matches_in_window"] == 1


def test_fallback_anchors_to_last_valid_match(client, db):
    ids = _make_players(client, TEN)
    for i, day in enumerate(("01", "02", "03")):
        _ingest(client, ids, f"g{i}", f"2026-08-{day}T20:00:00Z", TEN[:5], TEN[5:])
    hl = _highlights(db)  # NOW = 08-20 → rolling pencere boş
    assert hl["window"] == {
        "start": "2026-07-27T20:00:00Z",
        "end": "2026-08-03T20:00:00Z",
        "fallback": True,
    }
    # Çapalanmış pencerede üç maç da var → ekran boş kalmaz.
    assert hl["best_player"]["matches_in_window"] == 3
    assert hl["rising_star"]["matches_in_window"] == 3
    assert hl["best_by_role"]["TOP"] is not None


def test_no_valid_match_returns_nulls(client, db):
    _make_players(client, TEN)
    hl = _highlights(db)
    assert hl["window"] == {
        "start": "2026-08-13T12:00:00Z",
        "end": "2026-08-20T12:00:00Z",
        "fallback": False,
    }
    assert hl["best_player"] is None
    assert hl["rising_star"] is None
    assert hl["best_by_role"] == {role: None for role in ROLES}


def test_void_match_leaves_window(client, db):
    ids = _make_players(client, TEN)
    _ingest(client, ids, "g1", "2026-08-14T20:00:00Z", TEN[:5], TEN[5:])
    m2 = _ingest(client, ids, "g2", "2026-08-16T20:00:00Z", TEN[:5], TEN[5:])
    before = _highlights(db)
    assert before["best_player"]["matches_in_window"] == 2

    assert client.post(f"/api/v1/matches/{m2}/void").status_code == 200

    after = _highlights(db)
    assert after["best_player"]["matches_in_window"] == 1
    assert after["rising_star"]["matches_in_window"] == 1
    assert after["best_by_role"]["TOP"]["matches_in_window"] == 1
    assert after["window"]["fallback"] is False


def test_void_only_match_falls_back_to_older_valid_match(client, db):
    ids = _make_players(client, TEN)
    _ingest(client, ids, "old", "2026-08-01T20:00:00Z", TEN[:5], TEN[5:])
    m2 = _ingest(client, ids, "g2", "2026-08-16T20:00:00Z", TEN[:5], TEN[5:])
    assert client.post(f"/api/v1/matches/{m2}/void").status_code == 200

    hl = _highlights(db)
    # Penceredeki tek maç void oldu → çapa en son VALID maça kayar.
    assert hl["window"]["end"] == "2026-08-01T20:00:00Z"
    assert hl["window"]["fallback"] is True
    assert hl["best_player"]["matches_in_window"] == 1


# --------------------------------------------------------------------------
# Endpoint (gerçek UTC şimdi)
# --------------------------------------------------------------------------
def test_endpoint_returns_contract_shape(client):
    ids = _make_players(client, TEN)
    recent = datetime.now(timezone.utc) - timedelta(days=1)
    _ingest(client, ids, "g1", recent.strftime("%Y-%m-%dT%H:%M:%SZ"),
            TEN[:5], TEN[5:])

    r = client.get("/api/v1/highlights/weekly")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"window", "best_player", "rising_star", "best_by_role"}
    assert body["window"]["fallback"] is False
    assert set(body["window"]) == {"start", "end", "fallback"}
    assert sorted(body["best_by_role"]) == sorted(ROLES)
    assert set(body["best_player"]) == {
        "player_id", "display_name", "score", "matches_in_window"
    }
    assert set(body["rising_star"]) == {
        "player_id", "display_name", "delta", "matches_in_window"
    }
    assert body["best_player"]["matches_in_window"] == 1
    assert body["best_by_role"]["TOP"]["matches_in_window"] == 1


def test_endpoint_requires_api_key(client):
    r = client.get("/api/v1/highlights/weekly", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401
