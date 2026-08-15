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


def test_synergy_order_and_min_matches(client):
    ids = _known_scenario(client)
    synergy = _stats(client, ids["Ali"])["synergy"]
    # Burak 3/2 (0.67), Deniz 3/2 (0.67), Hakan 2/1 (0.5), Cem 3/1, Fatma 3/1;
    # Emre & Gizem 1'er maç → elenir. Sıra: winrate ↓, ortak maç ↓, ad ↑.
    assert synergy == [
        {"player_id": ids["Burak"], "display_name": "Burak",
         "matches_together": 3, "wins_together": 2, "winrate": 0.67},
        {"player_id": ids["Deniz"], "display_name": "Deniz",
         "matches_together": 3, "wins_together": 2, "winrate": 0.67},
        {"player_id": ids["Hakan"], "display_name": "Hakan",
         "matches_together": 2, "wins_together": 1, "winrate": 0.5},
    ]
    # En fazla 3 kayıt; rakip olarak kalan Irmak/Jale hiç görünmez.
    assert len(synergy) == 3


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


def test_synergy_equal_winrate_prefers_more_matches(client):
    names = ["Ali", "Burak", "Cem", "Deniz", "Emre", "Fatma", "Gizem", "Hakan",
             "Irmak", "Zeynep"]
    ids = _make_players(client, names)
    # Zeynep 3 ortak maç (3G), Burak/Cem/Deniz 2'şer (2G) → hepsi winrate 1.0.
    for i, sgid in enumerate(("g1", "g2")):
        _ingest(
            client, ids, sgid, f"2026-08-0{i + 1}T20:00:00Z",
            ["Ali", "Burak", "Cem", "Deniz", "Zeynep"],
            ["Emre", "Fatma", "Gizem", "Hakan", "Irmak"],
            winner_team=100,
        )
    _ingest(
        client, ids, "g3", "2026-08-03T20:00:00Z",
        ["Ali", "Emre", "Fatma", "Gizem", "Zeynep"],
        ["Burak", "Cem", "Deniz", "Hakan", "Irmak"],
        winner_team=100,
    )
    synergy = _stats(client, ids["Ali"])["synergy"]
    # Winrate eşit → ortak maç fazla olan (Zeynep) önce; kalanlar alfabetik.
    assert [s["display_name"] for s in synergy] == ["Zeynep", "Burak", "Cem"]
    assert synergy[0]["matches_together"] == 3
    assert all(s["winrate"] == 1.0 for s in synergy)


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
    assert before["synergy"][0]["matches_together"] == 2

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
    # Ortak maç 2'den 1'e düştü → sinerji eşiğinin (≥2) altına indi.
    assert after["synergy"] == []


def test_unknown_player_404(client):
    r = client.get("/api/v1/players/98765/stats")
    assert r.status_code == 404
    assert "98765" in r.json()["detail"]
