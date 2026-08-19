"""GET /players/{id}/stats — oyuncu profil istatistikleri (api_contract §2).

Beklenen değerler testlerde ELLE hesaplanmıştır (senaryolar dosyanın içinde
yorumla gösterilir); yalnız GÖSTERİM metriğidir, rating'e etkisi yoktur.
"""
from conftest import make_roster_payload

TEN = ["Ali", "Burak", "Cem", "Deniz", "Emre", "Fatma", "Gizem", "Hakan", "Irmak", "Jale"]


def _make_players(client, names):
    """İsim → player_id. riot_id de dolar (player bloğu doğrulanabilsin)."""
    ids = {}
    for name in names:
        r = client.post(
            "/api/v1/players", json={"display_name": name, "riot_id": f"{name}#TR1"}
        )
        assert r.status_code == 201
        ids[name] = r.json()["id"]
    return ids


def _ingest(
    client,
    ids,
    source_game_id,
    played_at,
    team100,
    team200,
    winner_team=100,
    duration_s=1874,
    overrides=None,
):
    """Verilen kadroyla maç gönderir; overrides isim → participant alan sözlüğü.

    Örn. overrides={"Ali": {"champion": None, "stats": None}}.
    """
    payload = make_roster_payload(
        source_game_id,
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


def _stats(client, player_id):
    r = client.get(f"/api/v1/players/{player_id}/stats")
    assert r.status_code == 200, r.text
    return r.json()


def _kda(kills, deaths, assists):
    return {"stats": {"kills": kills, "deaths": deaths, "assists": assists}}


# --------------------------------------------------------------------------
# Bilinen senaryo (tüm alanlar tek kurulumdan)
# --------------------------------------------------------------------------
#  M1 kazanç: Ali + Burak Cem Deniz Emre   | Ahri  / MIDDLE / 10-2-5
#  M2 kayıp : Ali + Burak Cem Fatma Gizem  | Ahri  / MIDDLE /  4-6-8
#  M3 kazanç: Ali + Burak Deniz Fatma Hakan| Zed   / TOP    / stat yok
#  M4 kayıp : Ali + Cem Deniz Fatma Hakan  | Zed   / null   /  1-4-2
def _known_scenario(client):
    ids = _make_players(client, TEN)
    _ingest(
        client, ids, "g1", "2026-08-01T20:00:00Z",
        ["Ali", "Burak", "Cem", "Deniz", "Emre"],
        ["Fatma", "Gizem", "Hakan", "Irmak", "Jale"],
        winner_team=100,
        overrides={"Ali": {"champion": "Ahri", "position": "MIDDLE", **_kda(10, 2, 5)}},
    )
    _ingest(
        client, ids, "g2", "2026-08-02T20:00:00Z",
        ["Ali", "Burak", "Cem", "Fatma", "Gizem"],
        ["Deniz", "Emre", "Hakan", "Irmak", "Jale"],
        winner_team=200,
        overrides={"Ali": {"champion": "Ahri", "position": "MIDDLE", **_kda(4, 6, 8)}},
    )
    _ingest(
        client, ids, "g3", "2026-08-03T20:00:00Z",
        ["Ali", "Burak", "Deniz", "Fatma", "Hakan"],
        ["Cem", "Emre", "Gizem", "Irmak", "Jale"],
        winner_team=100,
        overrides={"Ali": {"champion": "Zed", "position": "TOP", "stats": None}},
    )
    _ingest(
        client, ids, "g4", "2026-08-04T20:00:00Z",
        ["Ali", "Cem", "Deniz", "Fatma", "Hakan"],
        ["Burak", "Emre", "Gizem", "Irmak", "Jale"],
        winner_team=200,
        overrides={"Ali": {"champion": "Zed", "position": None, **_kda(1, 4, 2)}},
    )
    return ids


def test_player_block_and_totals(client):
    ids = _known_scenario(client)
    body = _stats(client, ids["Ali"])
    assert body["player"] == {
        "id": ids["Ali"], "display_name": "Ali", "riot_id": "Ali#TR1"
    }
    # 4 maç: M1, M3 kazanıldı; M2, M4 kaybedildi.
    assert body["totals"] == {"matches": 4, "wins": 2, "losses": 2, "winrate": 0.5}


def test_kda_ignores_statless_match(client):
    ids = _known_scenario(client)
    kda = _stats(client, ids["Ali"])["kda"]
    # Statlı 3 maç (M3 statsız): ΣK=15, ΣD=12, ΣA=15 → ratio = 30/12 = 2.5
    assert kda == {
        "kills_avg": 5.0, "deaths_avg": 4.0, "assists_avg": 5.0, "ratio": 2.5
    }


def test_favorite_champion_tie_breaks_alphabetically(client):
    ids = _known_scenario(client)
    # Ahri 2 maç (1G/1M), Zed 2 maç (1G/1M) → galibiyet ve maç sayısı eşit;
    # son kırılım alfabetik küçük: Ahri.
    assert _stats(client, ids["Ali"])["favorite_champion"] == {
        "champion": "Ahri", "matches": 2, "wins": 1, "winrate": 0.5
    }


def _play(client, ids, seq, champion, won):
    """Ali'yi verilen şampiyonla tek maça sokar (kadro sabit, sonuç parametrik)."""
    return _ingest(
        client, ids, f"g{seq}", f"2026-08-{seq:02d}T20:00:00Z",
        TEN[:5], TEN[5:], winner_team=100 if won else 200,
        overrides={"Ali": {"champion": champion}},
    )


def test_favorite_champion_prefers_most_wins_not_most_played(client):
    # api_contract §2 [REVİZE 2026-08-15]: ölçüt galibiyet SAYISI.
    # Ahri 4 maç / 1 galibiyet, Zed 2 maç / 2 galibiyet → Zed kazanır;
    # ne maç sayısı ne de alfabetik sıra (Ahri < Zed) bunu geçemez.
    ids = _make_players(client, TEN)
    for seq, won in ((1, True), (2, False), (3, False), (4, False)):
        _play(client, ids, seq, "Ahri", won)
    for seq in (5, 6):
        _play(client, ids, seq, "Zed", True)
    assert _stats(client, ids["Ali"])["favorite_champion"] == {
        "champion": "Zed", "matches": 2, "wins": 2, "winrate": 1.0
    }


def test_favorite_champion_win_tie_breaks_by_match_count(client):
    # Galibiyet eşit (2-2) → maç sayısı çok olan: Zed (3 maç) Ahri'yi (2 maç)
    # geçer; alfabetik kırılım ancak bu da eşitse devreye girer.
    ids = _make_players(client, TEN)
    for seq in (1, 2):
        _play(client, ids, seq, "Ahri", True)
    for seq, won in ((3, True), (4, True), (5, False)):
        _play(client, ids, seq, "Zed", won)
    assert _stats(client, ids["Ali"])["favorite_champion"] == {
        "champion": "Zed", "matches": 3, "wins": 2, "winrate": 0.67
    }


def test_favorite_champion_without_any_win_uses_match_count(client):
    # Hiç galibiyet yoksa (hepsi 0) aynı kırılım en çok oynanana düşer.
    ids = _make_players(client, TEN)
    _play(client, ids, 1, "Ahri", False)
    for seq in (2, 3):
        _play(client, ids, seq, "Zed", False)
    assert _stats(client, ids["Ali"])["favorite_champion"] == {
        "champion": "Zed", "matches": 2, "wins": 0, "winrate": 0.0
    }


def test_favorite_champion_exposes_wins_field(client):
    # `wins` yanıtın alanıdır: winrate + matches'tan türetmeye gerek kalmaz.
    ids = _make_players(client, TEN)
    for seq, won in ((1, True), (2, True), (3, False)):
        _play(client, ids, seq, "Ahri", won)
    fc = _stats(client, ids["Ali"])["favorite_champion"]
    assert fc["wins"] == 2
    assert set(fc) == {"champion", "matches", "wins", "winrate"}


def test_favorite_role_ignores_null_position(client):
    ids = _known_scenario(client)
    # MIDDLE 2 (M1, M2), TOP 1 (M3); M4'ün null pozisyonu sayılmaz.
    assert _stats(client, ids["Ali"])["favorite_role"] == {
        "role": "MIDDLE", "matches": 2
    }


def test_synergy_threshold_drops_three_shared_matches(client):
    # GÖREV 22: eşik n>=4. Bu senaryoda Ali'nin en sık takım arkadaşları
    # 3'er ortak maçta kalıyor (Burak/Cem/Deniz/Fatma), Hakan 2, Emre/Gizem 1
    # → hiçbiri aday değil. Eski tanımda (eşik 2) burada 3 kayıt dönüyordu.
    ids = _known_scenario(client)
    assert _stats(client, ids["Ali"])["synergy"] == []


# --------------------------------------------------------------------------
# Kenar durumlar
# --------------------------------------------------------------------------
def test_player_without_matches(client):
    pid = _make_players(client, ["Yalnız"])["Yalnız"]
    body = _stats(client, pid)
    assert body["totals"] == {
        "matches": 0, "wins": 0, "losses": 0, "winrate": None
    }
    assert body["kda"] is None
    assert body["favorite_champion"] is None
    assert body["favorite_role"] is None
    assert body["synergy"] == []


def test_partial_stats_do_not_enter_kda(client):
    ids = _make_players(client, TEN)
    # M1: tam stat; M2: deaths null → kda'ya GİRMEZ (üçü de dolu olmalı).
    _ingest(
        client, ids, "g1", "2026-08-01T20:00:00Z",
        TEN[:5], TEN[5:], winner_team=100,
        overrides={"Ali": _kda(6, 3, 9)},
    )
    _ingest(
        client, ids, "g2", "2026-08-02T20:00:00Z",
        TEN[:5], TEN[5:], winner_team=100,
        overrides={"Ali": {"stats": {"kills": 99, "deaths": None, "assists": 99}}},
    )
    body = _stats(client, ids["Ali"])
    assert body["totals"]["matches"] == 2  # totals eksik statı umursamaz
    assert body["kda"] == {
        "kills_avg": 6.0, "deaths_avg": 3.0, "assists_avg": 9.0, "ratio": 5.0
    }


def test_kda_null_when_no_stats_at_all(client):
    ids = _make_players(client, TEN)
    _ingest(
        client, ids, "g1", "2026-08-01T20:00:00Z",
        TEN[:5], TEN[5:], winner_team=100,
        overrides={"Ali": {"stats": None}},
    )
    body = _stats(client, ids["Ali"])
    assert body["totals"]["matches"] == 1
    assert body["kda"] is None


def test_null_champion_and_position_excluded_from_favorites(client):
    ids = _make_players(client, TEN)
    # M1: champion/position null → favorilere girmez.
    _ingest(
        client, ids, "g1", "2026-08-01T20:00:00Z",
        TEN[:5], TEN[5:], winner_team=100,
        overrides={"Ali": {"champion": None, "position": None}},
    )
    body = _stats(client, ids["Ali"])
    assert body["favorite_champion"] is None
    assert body["favorite_role"] is None
    # M2: dolu champion/position → tek aday odur (M1 sayıya katılmaz).
    _ingest(
        client, ids, "g2", "2026-08-02T20:00:00Z",
        TEN[:5], TEN[5:], winner_team=200,
        overrides={"Ali": {"champion": "Yasuo", "position": "UTILITY"}},
    )
    body = _stats(client, ids["Ali"])
    assert body["favorite_champion"] == {
        "champion": "Yasuo", "matches": 1, "wins": 0, "winrate": 0.0
    }
    assert body["favorite_role"] == {"role": "UTILITY", "matches": 1}


def test_favorite_role_tie_uses_canonical_order(client):
    ids = _make_players(client, TEN)
    # BOTTOM 1 maç, JUNGLE 1 maç → eşitlik; kanonik sırada JUNGLE önce gelir.
    _ingest(
        client, ids, "g1", "2026-08-01T20:00:00Z",
        TEN[:5], TEN[5:], winner_team=100,
        overrides={"Ali": {"position": "BOTTOM"}},
    )
    _ingest(
        client, ids, "g2", "2026-08-02T20:00:00Z",
        TEN[:5], TEN[5:], winner_team=100,
        overrides={"Ali": {"position": "JUNGLE"}},
    )
    assert _stats(client, ids["Ali"])["favorite_role"] == {
        "role": "JUNGLE", "matches": 1
    }


def test_void_match_excluded_from_all_metrics(client):
    ids = _make_players(client, TEN)
    _ingest(
        client, ids, "g1", "2026-08-01T20:00:00Z",
        TEN[:5], TEN[5:], winner_team=100,
        overrides={"Ali": {"champion": "Ahri", "position": "MIDDLE", **_kda(10, 2, 5)}},
    )
    m2 = _ingest(
        client, ids, "g2", "2026-08-02T20:00:00Z",
        TEN[:5], TEN[5:], winner_team=200,
        overrides={"Ali": {"champion": "Zed", "position": "TOP", **_kda(0, 10, 0)}},
    )
    before = _stats(client, ids["Ali"])
    assert before["totals"] == {"matches": 2, "wins": 1, "losses": 1, "winrate": 0.5}
    # 2 ortak maç eşiğin (n>=4) altında → sinerji zaten boş; void'in sinerjiye
    # etkisi ayrıca test_synergy_void_drops_candidate_below_threshold'ta.
    assert before["synergy"] == []

    assert client.post(f"/api/v1/matches/{m2}/void").status_code == 200

    after = _stats(client, ids["Ali"])
    assert after["totals"] == {"matches": 1, "wins": 1, "losses": 0, "winrate": 1.0}
    assert after["kda"] == {
        "kills_avg": 10.0, "deaths_avg": 2.0, "assists_avg": 5.0, "ratio": 7.5
    }
    assert after["favorite_champion"] == {
        "champion": "Ahri", "matches": 1, "wins": 1, "winrate": 1.0
    }
    assert after["favorite_role"] == {"role": "MIDDLE", "matches": 1}
    assert after["synergy"] == []


def test_unknown_player_404(client):
    r = client.get("/api/v1/players/98765/stats")
    assert r.status_code == 404
    assert "98765" in r.json()["detail"]


# --------------------------------------------------------------------------
# Sinerji — GÖREV 22 lift ölçütü (api_contract §2 `synergy`)
# --------------------------------------------------------------------------
# Kurulum deseni: her maçın kadrosu ADLANDIRILMIŞ oyuncular + O MAÇA ÖZEL
# dolgu oyuncularıyla tamamlanır. Dolgu tek maç oynadığı için hiçbiri n>=4
# eşiğini geçemez → aday havuzu yalnız adlandırılmış oyunculardır ve beklenen
# değerler elle hesaplanabilir. Ali HER ZAMAN team100'dedir; `ali_wins`
# maçın kazananını belirler.
#
# Katsayılar (api_contract §2): MIN_TOGETHER=4, M=4, W_WR=W_PERF=0.5,
# PERF_SCALE=3.4 → score = n/(n+4) * (0.5*wr_lift + 1.7*perf_delta).

SHRINK4 = 4 / (4 + 4)  # n=4'te shrinkage katsayısı


def _syn_ingest(client, ids, seq, team100, team200=(), ali_wins=True, overrides=None):
    """Adlandırılmış kadroyu maça özel dolgularla 5+5'e tamamlayıp ingest eder."""
    fill100 = [f"F{seq:02d}A{k}" for k in range(5 - len(team100))]
    fill200 = [f"F{seq:02d}B{k}" for k in range(5 - len(team200))]
    ids.update(_make_players(client, fill100 + fill200))
    return _ingest(
        client, ids, f"s{seq}", f"2026-08-{seq:02d}T20:00:00Z",
        list(team100) + fill100, list(team200) + fill200,
        winner_team=100 if ali_wins else 200,
        overrides=overrides,
    )


def _set_perf(db, match_id, ids, perf_by_name):
    """rating_history.perf_score'u oyuncu bazında sabitler (None = NULL).

    test_badges.py'deki desenin aynısı: perf'i rating motoru yazar, test yalnız
    okunacak değeri sabitler (backend perf'i KENDİ hesaplamaz).
    """
    conn = db()
    with conn:
        for name, value in perf_by_name.items():
            conn.execute(
                "UPDATE rating_history SET perf_score = ? "
                "WHERE match_id = ? AND player_id = ?",
                (value, match_id, ids[name]),
            )
    conn.close()


def _pair_scenario(client, together_wins, solo_ali_wins, mate="Burak"):
    """4 ortak + 4 ayrı maç; ortak maçların `together_wins` tanesi kazanılır.

    Ayrı maçlarda `mate` team200'dedir (yani Ali'nin kaybettiğini kazanır).
    Dönen: (ids, ortak match_id'leri, ayrı match_id'leri).
    """
    ids = _make_players(client, ["Ali", mate])
    together = [
        _syn_ingest(client, ids, seq, ["Ali", mate], ali_wins=seq <= together_wins)
        for seq in range(1, 5)
    ]
    solo = [
        _syn_ingest(
            client, ids, seq, ["Ali"], [mate], ali_wins=seq - 4 <= solo_ali_wins
        )
        for seq in range(5, 9)
    ]
    return ids, together, solo


def _only_synergy(client, ids):
    """Ali'nin sinerji listesi tek kayıtlık olmalı; o kaydı döner."""
    synergy = _stats(client, ids["Ali"])["synergy"]
    assert len(synergy) == 1, synergy
    return synergy[0]


def test_synergy_empty_solo_uses_neutral_winrate(client):
    # Ali ve Burak YALNIZ birlikte oynadı (4 maç, hepsi galibiyet) → solo küme
    # boş, wr_solo ikisinde de nötr 0.5. Statlar eşit olduğu için perf 1.0'dır;
    # solo tarafında hiç perf yok → her iki lift 0 (yokluk "kötü" değildir).
    # wr_lift = 4/4 - (0.5+0.5)/2 = 0.5 → score = 0.5 * (0.5*0.5) = 0.125
    ids = _make_players(client, ["Ali", "Burak"])
    for seq in range(1, 5):
        _syn_ingest(client, ids, seq, ["Ali", "Burak"])
    assert _only_synergy(client, ids) == {
        "player_id": ids["Burak"],
        "display_name": "Burak",
        "matches_together": 4,
        "wins_together": 4,
        "winrate": 1.0,
        "score": 0.125,
        "perf_delta": 0.0,
    }


def test_synergy_requires_four_matches_together(client):
    # 3 ortak maç → aday değil; 4'üncü maç geldiğinde kayıt belirir.
    ids = _make_players(client, ["Ali", "Burak"])
    for seq in range(1, 4):
        _syn_ingest(client, ids, seq, ["Ali", "Burak"])
    assert _stats(client, ids["Ali"])["synergy"] == []
    _syn_ingest(client, ids, 4, ["Ali", "Burak"])
    assert _only_synergy(client, ids)["matches_together"] == 4


def test_synergy_combines_winrate_and_perf_lift(client, db):
    # Ortak 4 maçın 3'ü galibiyet (wr 0.75); ayrı 4 maçın 2'sini Ali, 2'sini
    # Burak kazanıyor (wr_solo 0.5 / 0.5) → wr_lift = 0.25.
    # perf: Ali 1.5 → 1.25, Burak 1.25 → 1.0 (ikisinde de lift 0.25)
    # → perf_delta = 0.25. score = 0.5 * (0.5*0.25 + 0.5*3.4*0.25) ≈ 0.275.
    ids, together, solo = _pair_scenario(client, together_wins=3, solo_ali_wins=2)
    for mid in together:
        _set_perf(db, mid, ids, {"Ali": 1.5, "Burak": 1.25})
    for mid in solo:
        _set_perf(db, mid, ids, {"Ali": 1.25, "Burak": 1.0})
    entry = _only_synergy(client, ids)
    assert entry["matches_together"] == 4
    assert entry["wins_together"] == 3
    assert entry["winrate"] == 0.75
    assert entry["perf_delta"] == 0.25
    assert entry["score"] == round(SHRINK4 * (0.5 * 0.25 + 0.5 * 3.4 * 0.25), 3)


def test_synergy_ignores_matches_without_perf_score(client, db):
    # Ali'nin bir ortak maçında perf_score NULL → o maç ORTALAMAYA GİRMEZ
    # (0 ya da 1.0 sayılmaz): ort(1.5, 1.5, 1.5) = 1.5, lift = 0.25.
    # NULL 0 sayılsaydı ortalama 1.125'e, lift eksiye düşerdi.
    ids, together, solo = _pair_scenario(client, together_wins=3, solo_ali_wins=2)
    for i, mid in enumerate(together):
        _set_perf(db, mid, ids, {"Ali": None if i == 2 else 1.5, "Burak": 1.25})
    for mid in solo:
        _set_perf(db, mid, ids, {"Ali": 1.25, "Burak": 1.0})
    entry = _only_synergy(client, ids)
    assert entry["perf_delta"] == 0.25
    assert entry["score"] == round(SHRINK4 * (0.5 * 0.25 + 0.5 * 3.4 * 0.25), 3)


def test_synergy_lift_is_zero_when_one_side_has_no_perf(client, db):
    # Burak'ın HİÇBİR maçında perf yok → lift(Burak) = 0 (contract kuralı),
    # perf_delta yalnız Ali'nin lift'inin yarısıdır: (0.5 + 0)/2 = 0.25.
    # W/L tarafı nötrlendi (ortak 2/4, ayrı 2/4) → skor tamamen perf'ten gelir.
    ids, together, solo = _pair_scenario(client, together_wins=2, solo_ali_wins=2)
    for mid in together:
        _set_perf(db, mid, ids, {"Ali": 1.75, "Burak": None})
    for mid in solo:
        _set_perf(db, mid, ids, {"Ali": 1.25, "Burak": None})
    entry = _only_synergy(client, ids)
    assert entry["winrate"] == 0.5
    assert entry["perf_delta"] == 0.25
    assert entry["score"] == round(SHRINK4 * (0.5 * 0.0 + 0.5 * 3.4 * 0.25), 3)


def test_synergy_excludes_negative_score(client):
    # Ortak 4 maçın hepsi mağlubiyet, ayrı 4 maçın hepsi Ali'nin galibiyeti
    # → wr_lift = 0 - (1.0 + 0.0)/2 = -0.5, perf nötr → score < 0 → listelenmez
    # ("sahte birinci" gösterilmez; UI "kayda değer sinerji yok" der).
    ids, _, _ = _pair_scenario(client, together_wins=0, solo_ali_wins=4)
    assert _stats(client, ids["Ali"])["synergy"] == []


def test_synergy_excludes_zero_score(client):
    # Tam nötr çift: wr_lift = 0, perf lift = 0 → score = 0. Eşik `score > 0`
    # olduğu için sıfır da listeye GİRMEZ.
    ids, _, _ = _pair_scenario(client, together_wins=2, solo_ali_wins=2)
    assert _stats(client, ids["Ali"])["synergy"] == []


def test_synergy_score_formula_matches_contract():
    # Saf formül (api_contract §2): n=4, 3 galibiyet, wr_solo 0.5/0.5,
    # lift 0.25/0.25 → wr_lift 0.25, perf_delta 0.25.
    from app.services.player_stats import synergy_score

    score, perf_delta = synergy_score(4, 3, 0.5, 0.5, 0.25, 0.25)
    assert perf_delta == 0.25
    assert score == SHRINK4 * (0.5 * 0.25 + 0.5 * 3.4 * 0.25)


def test_synergy_sort_key_breaks_ties_by_matches_then_name():
    # Eşit skorda ortak maç çok olan önce; o da eşitse ad alfabetik.
    from app.services.player_stats import synergy_sort_key

    def entry(name, n):
        return {"display_name": name, "matches_together": n}

    items = [
        (0.1, entry("Ali", 5)),
        (0.2, entry("Zeynep", 4)),
        (0.2, entry("Burak", 9)),
        (0.2, entry("Ahmet", 9)),
    ]
    assert [e["display_name"] for _, e in sorted(items, key=synergy_sort_key)] == [
        "Ahmet", "Burak", "Zeynep", "Ali",
    ]


def test_synergy_shrinkage_suppresses_small_samples():
    # Aynı lift'ler, farklı örneklem: n=4 → 4/8, n=12 → 12/16. Skor oranı tam
    # olarak shrinkage oranıdır (0.5 / 0.75) — küçük örneklem 0'a çekilir.
    from app.services.player_stats import synergy_score

    small, _ = synergy_score(4, 4, 0.5, 0.5, 0.2, 0.2)
    big, _ = synergy_score(12, 12, 0.5, 0.5, 0.2, 0.2)
    assert 0 < small < big
    assert small / big == (4 / 8) / (12 / 16)


def test_synergy_orders_by_score_not_by_match_count(client):
    # Burak: 4 ortak maç, hepsi galibiyet; ayrı 4 maçta rakip ve hepsini kazanıyor
    #   → wr_lift = 1.0 - (0.0 + 1.0)/2 = 0.5 → score = 0.5*0.5*0.5 = 0.125
    # Cem: 6 ortak maç (4 galibiyet), ayrı 2 maçta rakip ve ikisini de kazanıyor
    #   → wr_lift = 4/6 - (0.0 + 1.0)/2 ≈ 0.167 → score = 0.6*0.5*0.167 ≈ 0.05
    # Cem'in ortak maçı DAHA ÇOK ama skoru düşük → sıralamayı skor belirler.
    ids = _make_players(client, ["Ali", "Burak", "Cem"])
    for seq in range(1, 5):
        _syn_ingest(client, ids, seq, ["Ali", "Burak", "Cem"])
    for seq in (5, 6):
        _syn_ingest(client, ids, seq, ["Ali", "Cem"], ["Burak"], ali_wins=False)
    for seq in (7, 8):
        _syn_ingest(client, ids, seq, ["Ali"], ["Burak", "Cem"], ali_wins=False)
    synergy = _stats(client, ids["Ali"])["synergy"]
    assert [s["display_name"] for s in synergy] == ["Burak", "Cem"]
    assert [s["matches_together"] for s in synergy] == [4, 6]
    assert synergy[0]["score"] > synergy[1]["score"] > 0


def test_synergy_limit_and_alphabetical_tie_break(client):
    # Dört arkadaş da Ali'yle aynı 4 maçı aynı sonuçlarla oynadı → score, n ve
    # winrate birebir eşit. Son kırılım ad alfabetik; yanıt en fazla 3 kayıt.
    ids = _make_players(client, ["Ali", "Emre", "Cem", "Burak", "Deniz"])
    for seq in range(1, 5):
        _syn_ingest(client, ids, seq, ["Ali", "Burak", "Cem", "Deniz", "Emre"])
    synergy = _stats(client, ids["Ali"])["synergy"]
    assert [s["display_name"] for s in synergy] == ["Burak", "Cem", "Deniz"]
    assert {s["score"] for s in synergy} == {0.125}


def test_synergy_response_fields_and_rounding(client, db):
    # Ham değerler bilinçli olarak uzun ondalıklı:
    #   perf_delta = ((1.1+1.2+1.4)/3 - 1.0 + (1.2 - 1.0)) / 2 = 0.21666... → 0.22
    #   score = 0.5 * (0.5*0.25 + 1.7*0.21666...) = 0.24666... → 0.247
    # Yuvarlama YALNIZ yanıttadır (score 3, perf_delta 2 ondalık).
    ids, together, solo = _pair_scenario(client, together_wins=3, solo_ali_wins=2)
    ali_perfs = [1.1, 1.2, None, 1.4]
    for perf, mid in zip(ali_perfs, together):
        _set_perf(db, mid, ids, {"Ali": perf, "Burak": 1.2})
    for mid in solo:
        _set_perf(db, mid, ids, {"Ali": 1.0, "Burak": 1.0})
    entry = _only_synergy(client, ids)
    assert set(entry) == {
        "player_id", "display_name", "matches_together", "wins_together",
        "winrate", "score", "perf_delta",
    }
    assert entry["perf_delta"] == 0.22
    assert entry["score"] == 0.247


def test_synergy_perf_delta_never_negative_zero(client, db):
    # Çok küçük negatif perf farkı 2 ondalığa yuvarlanınca IEEE -0.0 olur ve
    # JSON'a "-0.0" diye düşerdi. Değer 0.0'dır; işareti yanıta sızmamalı.
    import math

    ids, together, solo = _pair_scenario(client, together_wins=3, solo_ali_wins=2)
    for mid in together:
        _set_perf(db, mid, ids, {"Ali": 1.0, "Burak": 1.0})
    for mid in solo:
        _set_perf(db, mid, ids, {"Ali": 1.001, "Burak": 1.0})
    entry = _only_synergy(client, ids)  # wr_lift pozitif olduğu için listede
    assert entry["perf_delta"] == 0.0
    assert math.copysign(1.0, entry["perf_delta"]) == 1.0


def test_synergy_void_drops_candidate_below_threshold(client):
    # 4 ortak maçın biri void edilince n=3'e düşer → aday listeden çıkar.
    ids = _make_players(client, ["Ali", "Burak"])
    matches = [_syn_ingest(client, ids, seq, ["Ali", "Burak"]) for seq in range(1, 5)]
    assert _only_synergy(client, ids)["matches_together"] == 4
    assert client.post(f"/api/v1/matches/{matches[-1]}/void").status_code == 200
    assert _stats(client, ids["Ali"])["synergy"] == []


def test_synergy_identical_after_replay(client):
    # Determinizm: perf_score'lar replay'de bit-bit yeniden üretilir, sinerji
    # de yalnız onları okuduğu için yanıt DEĞİŞMEZ (toplama sırası match_id'ye
    # bağlıdır, satır sırasına değil).
    ids = _make_players(client, ["Ali", "Burak"])
    strong = {"stats": {"kills": 14, "deaths": 1, "assists": 12, "gold": 19000,
                        "cs": 280, "damage_to_champs": 41000, "vision_score": 34}}
    weak = {"stats": {"kills": 1, "deaths": 9, "assists": 2, "gold": 8000,
                      "cs": 90, "damage_to_champs": 9000, "vision_score": 8}}
    for seq in range(1, 5):
        _syn_ingest(
            client, ids, seq, ["Ali", "Burak"],
            overrides={"Ali": dict(strong), "Burak": dict(strong)},
        )
    for seq in range(5, 9):
        _syn_ingest(
            client, ids, seq, ["Ali"], ["Burak"], ali_wins=False,
            overrides={"Ali": dict(weak), "Burak": dict(weak)},
        )
    before = _stats(client, ids["Ali"])["synergy"]
    assert before and before[0]["perf_delta"] > 0  # perf gerçekten oynuyor
    assert client.post("/api/v1/admin/replay").status_code == 200
    assert _stats(client, ids["Ali"])["synergy"] == before
