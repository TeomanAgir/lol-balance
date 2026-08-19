"""GET /players/{id}/badges (api_contract §2 "Rozetler") — GÖREV 11+12 tabanı.

GÖREV 24'te eklenen 11 rozet, kademe, `include_locked` ve `GET /badges`
testleri `test_badges_g24.py`'dedir; bu dosya ilk 13 rozetin (eşikleri GÖREV
24'te güncellenenler dahil: win_streak_3, bench_2, veteran_20) davranışını
korur.

Rozetler SALT-OKUR türetilmiş veridir: testler hiçbir yeni tablo/kolon
beklemez. Kurgu deseni:

- 10 oyuncu bir kez kurulur (P0..P4 = team100, P5..P9 = team200); her maç
  `_ingest` ile açık stat/rol/süre kontrolüyle gönderilir.
- `BASE_STATS` tüm katılımcılarda AYNIDIR: bu, rekor rozetlerinde bilinçli bir
  "herkes eşit" zemini kurar (eşitlikte herkes alır) ve perf_score'u nötrler —
  senaryolar yalnız ilgilendikleri alanı bozar.
- perf_score bağımlı rozetlerde (mvp, bench_2) değerler `_set_perf` ile
  doğrudan `rating_history`'ye yazılır; böylece kırılım zincirleri ve NULL
  kuralları rating matematiğine bağlı kalmadan, bit-bit test edilir
  (aynı desen test_rating_history'de de kullanılır).
"""
from __future__ import annotations

import pytest

from app.services.badges import BADGE_KEYS, _cs_per_min_values

POSITIONS = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]

NAMES = [f"P{i}" for i in range(10)]
TEAM100 = NAMES[:5]
TEAM200 = NAMES[5:]

# Tüm katılımcılarda aynı: perf nötr, rekorlar eşit, ölüm > 0, gold toplamları eşit.
BASE_STATS = {
    "kills": 5,
    "deaths": 5,
    "assists": 5,
    "gold": 10000,
    "cs": 150,
    "damage_to_champs": 20000,
    "vision_score": 20,
}

DURATION_S = 1800  # 30 dk


# --------------------------------------------------------------------------
# Yardımcılar
# --------------------------------------------------------------------------
def _make_players(client, names=NAMES):
    ids = {}
    for name in names:
        r = client.post(
            "/api/v1/players", json={"display_name": name, "riot_id": f"{name}#TR1"}
        )
        assert r.status_code == 201, r.text
        ids[name] = r.json()["id"]
    return ids


def _payload(
    ids,
    sgid,
    played_at,
    t100=None,
    t200=None,
    winner_team=100,
    duration_s=DURATION_S,
    stats=None,
    positions=None,
):
    """Rol = takım listesindeki indeks; `positions` ile oyuncu bazında ezilir."""
    stats = stats or {}
    positions = positions or {}
    participants = []
    for team, names in ((100, t100 or TEAM100), (200, t200 or TEAM200)):
        for i, name in enumerate(names):
            own = dict(BASE_STATS)
            own.update(stats.get(name, {}))
            participants.append(
                {
                    "player_id": ids[name],
                    "team": team,
                    "position": positions.get(name, POSITIONS[i]),
                    "champion": "Ahri",
                    "stats": own,
                }
            )
    return {
        "source": "lcu_eog",
        "source_game_id": sgid,
        "played_at": played_at,
        "duration_s": duration_s,
        "winner_team": winner_team,
        "participants": participants,
    }


def _ingest(client, ids, sgid, played_at, **kwargs):
    r = client.post(
        "/api/v1/ingest/match", json=_payload(ids, sgid, played_at, **kwargs)
    )
    assert r.status_code == 201, r.text
    return r.json()["match_id"]


def _day(n: int) -> str:
    """n. maçın played_at'i — kronolojik sıra ingest sırasından bağımsız olsun."""
    return f"2026-08-{n:02d}T20:00:00Z"


def _series(client, ids, prefix, count, **kwargs):
    """count adet maç, kronolojik artan; match_id listesi döner."""
    return [
        _ingest(client, ids, f"{prefix}-{n}", _day(n), **kwargs)
        for n in range(1, count + 1)
    ]


def _set_perf(db, match_id, ids, perf_by_name):
    """rating_history.perf_score'u oyuncu bazında sabitler (None = NULL)."""
    conn = db()
    with conn:
        for name, value in perf_by_name.items():
            conn.execute(
                "UPDATE rating_history SET perf_score = ? "
                "WHERE match_id = ? AND player_id = ?",
                (value, match_id, ids[name]),
            )
    conn.close()


def _badges(client, player_id):
    r = client.get(f"/api/v1/players/{player_id}/badges")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["player_id"] == player_id
    return body["badges"]


def _by_key(client, player_id):
    return {b["key"]: b for b in _badges(client, player_id)}


def _count(client, player_id, key):
    return _by_key(client, player_id).get(key, {}).get("count", 0)


@pytest.fixture
def ids(client):
    return _make_players(client)


# --------------------------------------------------------------------------
# Yanıt şekli / sıra / hata durumları
# --------------------------------------------------------------------------
def test_unknown_player_404(client):
    r = client.get("/api/v1/players/999/badges")
    assert r.status_code == 404
    assert "bulunamadı" in r.json()["detail"]


def test_player_without_matches_returns_empty_badges(client):
    created = client.post(
        "/api/v1/players", json={"display_name": "Maçsız", "riot_id": None}
    )
    assert created.status_code == 201
    assert _badges(client, created.json()["id"]) == []


def test_player_with_matches_but_no_qualifying_badge_returns_empty(client, ids):
    """Statsız kaybeden oyuncu hiçbir rozet kazanmaz (rozetsiz oyuncu → [])."""
    nulls = {name: dict.fromkeys(BASE_STATS) for name in NAMES}
    _ingest(client, ids, "b-none", _day(1), stats=nulls)
    assert _badges(client, ids["P5"]) == []


def test_badges_follow_fixed_catalog_order(client, ids, db):
    """Sıra SABİT katalog sırasıdır; count 0 olanlar hiç dönmez."""
    # Rekorlar + deathless + comeback + mvp aynı maçta P0'a gelsin.
    # gold: P0 maçın lideri (8000) ama kazanan takımın TOPLAMI (12000)
    # kaybedenden (25000) küçük → gold rekoru ve comeback birlikte düşer.
    stats = {
        "P0": {
            "deaths": 0, "vision_score": 99, "damage_to_champs": 99000,
            "gold": 8000, "cs": 400,
        },
    }
    stats.update({name: {"gold": 1000} for name in TEAM100[1:]})
    stats.update({name: {"gold": 5000} for name in TEAM200})
    match_id = _ingest(client, ids, "b-order", _day(1), stats=stats)
    _set_perf(db, match_id, ids, {name: 1.0 for name in NAMES} | {"P0": 2.0})

    # GÖREV 24: aynı maç role_duel (perf 2.0 vs rakip TOP 1.0 → oran 2.0) ve
    # kda_10 ((5+5)/max(1,0) = 10) da kazandırır — ikisi de katalog sırasında.
    keys = [b["key"] for b in _badges(client, ids["P0"])]
    # GÖREV 24 revizyonu: P0 aynı maçta mvp+damage+gold+cs_per_min'in DÖRDÜNÜ de
    # topluyor → perfect_quad da (katalog SONUNDA, ID 28) birlikte düşer.
    assert keys == [
        "mvp", "vision", "damage", "cs_per_min", "gold", "role_duel",
        "kda_10", "deathless", "comeback", "perfect_quad",
    ]
    assert [k for k in BADGE_KEYS if k in keys] == keys


# --------------------------------------------------------------------------
# Rekor rozetleri: vision / damage / gold / cs_per_min
# --------------------------------------------------------------------------
def test_record_badges_go_to_match_leader(client, ids):
    match_id = _ingest(
        client, ids, "b-rec", _day(1),
        stats={"P7": {
            "vision_score": 99, "damage_to_champs": 99000,
            "gold": 99000, "cs": 400,
        }},
    )
    leader = _by_key(client, ids["P7"])
    for key in ("vision", "damage", "gold", "cs_per_min"):
        assert leader[key]["count"] == 1
        assert leader[key]["last_match_id"] == match_id
    # Lider varken diğerleri hiçbirini almaz.
    other = _by_key(client, ids["P0"])
    assert not {"vision", "damage", "gold", "cs_per_min"} & set(other)


def test_record_tie_awards_every_tied_player(client, ids):
    """Eşitlikte HERKES alır (rekor rozetlerinde kırılım YOKTUR)."""
    _ingest(
        client, ids, "b-tie", _day(1),
        stats={
            "P0": {"vision_score": 99},
            "P6": {"vision_score": 99},
            **{n: {"vision_score": 1} for n in NAMES if n not in ("P0", "P6")},
        },
    )
    assert _count(client, ids["P0"], "vision") == 1
    assert _count(client, ids["P6"], "vision") == 1
    assert _count(client, ids["P1"], "vision") == 0


def test_record_null_stat_is_not_a_candidate(client, ids):
    """NULL statlı aday değildir; hiç non-null yoksa o maçta rozet yoktur."""
    _ingest(
        client, ids, "b-null-one", _day(1),
        stats={
            "P0": {"vision_score": None},
            "P1": {"vision_score": 50},
            **{n: {"vision_score": 1} for n in NAMES[2:]},
        },
    )
    _ingest(
        client, ids, "b-null-all", _day(2),
        stats={n: {"vision_score": None} for n in NAMES},
    )
    assert _count(client, ids["P0"], "vision") == 0
    # İkinci maçta hiç aday yok → P1'in tek vision rozeti ilk maçtan gelir.
    p1 = _by_key(client, ids["P1"])["vision"]
    assert p1["count"] == 1


def test_cs_per_min_values_scale_with_duration():
    """cs/dk = cs / (duration_s/60); süre yoksa ya da <= 0 ise maç dışıdır."""
    rows = [{"player_id": 1, "cs": 300}, {"player_id": 2, "cs": 150}]
    assert _cs_per_min_values(rows, 1800) == {1: 10.0, 2: 5.0}
    assert _cs_per_min_values(rows, 900) == {1: 20.0, 2: 10.0}
    assert _cs_per_min_values(rows, 0) == {}
    assert _cs_per_min_values(rows, -5) == {}
    assert _cs_per_min_values(rows, None) == {}


def test_cs_per_min_skipped_when_duration_missing_or_zero(client, ids, db):
    """Süresiz maçta cs/dk hesaplanamaz; diğer rekorlar etkilenmez."""
    lead = {"P0": {"cs": 400, "gold": 99000}}
    _ingest(client, ids, "b-cs-null", _day(1), duration_s=None, stats=lead)
    zero = _ingest(client, ids, "b-cs-zero", _day(2), stats=lead)
    conn = db()
    with conn:
        conn.execute("UPDATE matches SET duration_s = 0 WHERE id = ?", (zero,))
    conn.close()

    badges = _by_key(client, ids["P0"])
    assert "cs_per_min" not in badges
    assert badges["gold"]["count"] == 2  # iki maçta da gold lideri


# --------------------------------------------------------------------------
# deathless / comeback
# --------------------------------------------------------------------------
def test_deathless_counts_only_zero_death_matches(client, ids):
    m1 = _ingest(client, ids, "b-dl1", _day(1), stats={"P0": {"deaths": 0}})
    _ingest(client, ids, "b-dl2", _day(2), stats={"P0": {"deaths": 1}})
    m3 = _ingest(client, ids, "b-dl3", _day(3), stats={"P0": {"deaths": 0}})
    _ingest(client, ids, "b-dl4", _day(4), stats={"P0": {"deaths": None}})

    badge = _by_key(client, ids["P0"])["deathless"]
    assert badge["count"] == 2
    assert badge["last_match_id"] == m3
    assert m1 != m3


def test_comeback_requires_winning_side_with_lower_gold(client, ids):
    match_id = _ingest(
        client, ids, "b-cb", _day(1), winner_team=100,
        stats={
            **{n: {"gold": 4000} for n in TEAM100},
            **{n: {"gold": 9000} for n in TEAM200},
        },
    )
    winner = _by_key(client, ids["P0"])["comeback"]
    assert winner["count"] == 1
    assert winner["last_match_id"] == match_id
    # Kaybeden taraf (gold'u fazla olsa da) comeback almaz.
    assert _count(client, ids["P5"], "comeback") == 0


def test_comeback_not_awarded_when_winner_gold_is_higher(client, ids):
    _ingest(
        client, ids, "b-cb-hi", _day(1), winner_team=100,
        stats={
            **{n: {"gold": 9000} for n in TEAM100},
            **{n: {"gold": 4000} for n in TEAM200},
        },
    )
    assert _count(client, ids["P0"], "comeback") == 0


def test_comeback_excluded_when_any_gold_is_null(client, ids):
    """İKİ takımın da 5 gold'u non-null olmalı; tek NULL rozeti düşürür."""
    stats = {
        **{n: {"gold": 4000} for n in TEAM100},
        **{n: {"gold": 9000} for n in TEAM200},
    }
    stats["P9"] = {"gold": None}  # kaybeden takımda tek NULL
    _ingest(client, ids, "b-cb-null", _day(1), winner_team=100, stats=stats)
    assert _count(client, ids["P0"], "comeback") == 0


# --------------------------------------------------------------------------
# mvp (GÖREV 12)
# --------------------------------------------------------------------------
def test_mvp_goes_to_highest_perf_on_winning_team(client, ids, db):
    """Perf, statlardan ÖNCE gelir: en az kill'li oyuncu bile MVP olabilir."""
    match_id = _ingest(
        client, ids, "b-mvp", _day(1), winner_team=100,
        stats={"P3": {"kills": 0}, "P0": {"kills": 20}},
    )
    _set_perf(
        db, match_id, ids,
        {**{n: 1.0 for n in NAMES}, "P3": 1.9, "P0": 1.5},
    )
    badge = _by_key(client, ids["P3"])["mvp"]
    assert badge["count"] == 1
    assert badge["last_match_id"] == match_id
    assert _count(client, ids["P0"], "mvp") == 0


def test_mvp_ignores_losing_team_even_with_best_perf(client, ids, db):
    match_id = _ingest(client, ids, "b-mvp-lose", _day(1), winner_team=100)
    _set_perf(db, match_id, ids, {**{n: 1.0 for n in NAMES}, "P8": 5.0, "P2": 1.4})
    assert _count(client, ids["P8"], "mvp") == 0
    assert _count(client, ids["P2"], "mvp") == 1


def test_mvp_null_perf_row_is_not_a_candidate(client, ids, db):
    """NULL perf aday değil; kazanan takımda hiç perf yoksa MVP yoktur."""
    m1 = _ingest(client, ids, "b-mvp-n1", _day(1), winner_team=100)
    _set_perf(db, m1, ids, {**{n: 1.0 for n in NAMES}, "P1": None, "P2": 1.3})
    m2 = _ingest(client, ids, "b-mvp-n2", _day(2), winner_team=100)
    _set_perf(db, m2, ids, {n: None for n in TEAM100})

    assert _count(client, ids["P1"], "mvp") == 0
    badge = _by_key(client, ids["P2"])["mvp"]
    assert badge["count"] == 1
    assert badge["last_match_id"] == m1  # 2. maçta MVP yok
    assert all(_count(client, ids[n], "mvp") == 0 for n in TEAM100 if n != "P2")


def test_mvp_tiebreak_chain_kills_then_assists_then_deaths(client, ids, db):
    """Eşit perf'te kırılım: kills ↓ → assists ↓ → deaths ↑.

    P2/P4 kills'te, P3 assists'te elenir; P0 ile P1 deaths'te ayrışır.
    """
    match_id = _ingest(
        client, ids, "b-mvp-tie", _day(1), winner_team=100,
        stats={
            "P0": {"kills": 9, "assists": 3, "deaths": 2},
            "P1": {"kills": 9, "assists": 3, "deaths": 1},
            "P2": {"kills": 8, "assists": 9, "deaths": 0},
            "P3": {"kills": 9, "assists": 2, "deaths": 0},
            "P4": {"kills": 7, "assists": 9, "deaths": 0},
        },
    )
    _set_perf(db, match_id, ids, {n: 1.0 for n in NAMES})
    assert _count(client, ids["P1"], "mvp") == 1
    assert all(_count(client, ids[n], "mvp") == 0 for n in ("P0", "P2", "P3", "P4"))


def test_mvp_tiebreak_falls_back_to_smallest_player_id(client, ids, db):
    """Perf ve k/d/a tamamen eşitse en küçük player_id kazanır."""
    match_id = _ingest(client, ids, "b-mvp-pid", _day(1), winner_team=100)
    _set_perf(db, match_id, ids, {n: 1.0 for n in NAMES})
    smallest = min(TEAM100, key=lambda n: ids[n])
    assert smallest == "P0"
    assert _count(client, ids["P0"], "mvp") == 1
    assert all(_count(client, ids[n], "mvp") == 0 for n in TEAM100[1:])


# --------------------------------------------------------------------------
# win_streak_3 (GÖREV 24: eşik 5 → 3) — ayrık bloklar
# --------------------------------------------------------------------------
def test_win_streak_blocks_are_disjoint(client, ids):
    """6 galibiyet = 2 rozet; last_match_id ikinci bloğun SON maçıdır."""
    matches = _series(client, ids, "b-ws", 6, winner_team=100)
    badge = _by_key(client, ids["P0"])["win_streak_3"]
    assert badge["count"] == 2
    assert badge["last_match_id"] == matches[5]
    # Kaybeden taraf hiç blok tamamlamaz (ama lose_streak_3 alır).
    assert _count(client, ids["P5"], "win_streak_3") == 0


def test_win_streak_reset_by_a_loss(client, ids):
    """2 galibiyet + 1 mağlubiyet + 2 galibiyet → tamamlanan blok yok."""
    for n in range(1, 6):
        _ingest(
            client, ids, f"b-wsr-{n}", _day(n),
            winner_team=200 if n == 3 else 100,
        )
    assert _count(client, ids["P0"], "win_streak_3") == 0


def test_win_streak_last_match_id_is_block_end(client, ids):
    matches = _series(client, ids, "b-wsl", 3, winner_team=100)
    badge = _by_key(client, ids["P0"])["win_streak_3"]
    assert badge["count"] == 1
    assert badge["last_match_id"] == matches[2]


# --------------------------------------------------------------------------
# bench_2 (GÖREV 24: blok 3 → 2) — ayrık bloklar, karşılaştırılabilirlik
# --------------------------------------------------------------------------
def _bench_perf(low="P0"):
    """Kendi takımında (team100) `low` tek başına en düşük."""
    return {**{n: 1.0 for n in NAMES}, low: 0.5}


def test_bench_two_consecutive_matches_earn_one_badge(client, ids, db):
    matches = _series(client, ids, "b-bench", 2)
    for match_id in matches:
        _set_perf(db, match_id, ids, _bench_perf())
    badge = _by_key(client, ids["P0"])["bench_2"]
    assert badge["count"] == 1
    assert badge["last_match_id"] == matches[1]


def test_bench_blocks_are_disjoint(client, ids, db):
    matches = _series(client, ids, "b-bench4", 4)
    for match_id in matches:
        _set_perf(db, match_id, ids, _bench_perf())
    badge = _by_key(client, ids["P0"])["bench_2"]
    assert badge["count"] == 2
    assert badge["last_match_id"] == matches[3]


def test_bench_tie_at_lowest_breaks_the_streak(client, ids, db):
    """En düşükte eşitlik: o maç bench SAYILMAZ ve seriyi kırar."""
    matches = _series(client, ids, "b-bench-tie", 3)
    for i, match_id in enumerate(matches):
        if i == 1:
            _set_perf(
                db, match_id, ids,
                {**{n: 1.0 for n in NAMES}, "P0": 0.5, "P1": 0.5},
            )
        else:
            _set_perf(db, match_id, ids, _bench_perf())
    # 1 + 1 maçlık iki parça kaldı → tamamlanan 2'lik blok yok.
    assert _count(client, ids["P0"], "bench_2") == 0


def test_bench_null_perf_in_own_team_breaks_the_streak(client, ids, db):
    """Kendi takımında tek NULL perf → maç karşılaştırılamaz, seri kırılır."""
    matches = _series(client, ids, "b-bench-null", 3)
    for i, match_id in enumerate(matches):
        perf = _bench_perf()
        if i == 1:
            perf["P3"] = None
        _set_perf(db, match_id, ids, perf)
    assert _count(client, ids["P0"], "bench_2") == 0


def test_bench_ignores_opposing_team_perf(client, ids, db):
    """Karşılaştırma yalnız KENDİ takımı içindedir."""
    matches = _series(client, ids, "b-bench-opp", 2)
    for match_id in matches:
        perf = _bench_perf()
        perf["P7"] = 0.1  # rakip takımda daha düşük perf; P0'ı etkilemez
        perf["P8"] = None  # rakip takımda NULL; karşılaştırılabilirliği bozmaz
        _set_perf(db, match_id, ids, perf)
    assert _count(client, ids["P0"], "bench_2") == 1


def test_bench_not_awarded_when_not_the_lowest(client, ids, db):
    matches = _series(client, ids, "b-bench-no", 2)
    for match_id in matches:
        _set_perf(db, match_id, ids, _bench_perf(low="P1"))
    assert _count(client, ids["P0"], "bench_2") == 0
    assert _count(client, ids["P1"], "bench_2") == 1


# --------------------------------------------------------------------------
# versatile / veteran_*
# --------------------------------------------------------------------------
def test_versatile_awarded_once_when_fifth_role_is_played(client, ids):
    matches = []
    for n, role in enumerate(POSITIONS, start=1):
        matches.append(
            _ingest(client, ids, f"b-vers-{n}", _day(n), positions={"P0": role})
        )
    badge = _by_key(client, ids["P0"])["versatile"]
    assert badge["count"] == 1
    assert badge["last_match_id"] == matches[4]

    # 6. maç yeni rozet üretmez (tek seferlik).
    _ingest(client, ids, "b-vers-6", _day(6), positions={"P0": "TOP"})
    assert _by_key(client, ids["P0"])["versatile"] == badge


def test_versatile_ignores_null_positions(client, ids):
    """NULL position rol saymaz; rozet 5. GERÇEK rolün maçında düşer."""
    for n, role in enumerate(POSITIONS[:4], start=1):
        _ingest(client, ids, f"b-vn-{n}", _day(n), positions={"P0": role})
    _ingest(client, ids, "b-vn-5", _day(5), positions={"P0": None})
    assert _count(client, ids["P0"], "versatile") == 0

    fifth = _ingest(client, ids, "b-vn-6", _day(6), positions={"P0": POSITIONS[4]})
    badge = _by_key(client, ids["P0"])["versatile"]
    assert badge["count"] == 1
    assert badge["last_match_id"] == fifth


def test_veteran_thresholds_are_independent_with_own_last_match_id(client, ids):
    """GÖREV 24: eşik 25 → 20; veteran_50 KORUNDU (kilitli hedef).

    Yanıt kaydı GÖREV 24 alanlarını da taşır: kilometre sınıfında `progress`
    doludur, `best_*` ve kademe alanları NULL'dur.
    """
    matches = _series(client, ids, "b-vet", 20)
    badges = _by_key(client, ids["P0"])
    assert badges["veteran_10"] == {
        "key": "veteran_10", "count": 1, "last_match_id": matches[9],
        "best_match_id": None, "best_value": None,
        "tier": None, "rate": None, "next_tier_count": None,
        "progress": {"current": 20, "target": 10},
        "stellar_quest": None,
    }
    assert badges["veteran_20"] == {
        "key": "veteran_20", "count": 1, "last_match_id": matches[19],
        "best_match_id": None, "best_value": None,
        "tier": None, "rate": None, "next_tier_count": None,
        "progress": {"current": 20, "target": 20},
        "stellar_quest": None,
    }
    assert "veteran_25" not in badges
    assert "veteran_50" not in badges


def test_veteran_not_awarded_below_threshold(client, ids):
    _series(client, ids, "b-vet9", 9)
    assert "veteran_10" not in _by_key(client, ids["P0"])


# --------------------------------------------------------------------------
# Valid maç kapsamı + determinizm
# --------------------------------------------------------------------------
def test_void_match_does_not_count(client, ids):
    _ingest(client, ids, "b-void-1", _day(1), stats={"P0": {"deaths": 0}})
    m2 = _ingest(client, ids, "b-void-2", _day(2), stats={"P0": {"deaths": 0}})
    assert _count(client, ids["P0"], "deathless") == 2

    assert client.post(f"/api/v1/matches/{m2}/void").status_code == 200
    badge = _by_key(client, ids["P0"])["deathless"]
    assert badge["count"] == 1
    assert badge["last_match_id"] != m2


def test_badges_identical_after_replay(client, ids):
    """Determinizm: POST /admin/replay sonrası yanıt bit-bit aynı kalır."""
    for n in range(1, 7):
        _ingest(
            client, ids, f"b-det-{n}", _day(n),
            winner_team=100 if n % 3 else 200,
            stats={
                "P0": {"deaths": 0, "kills": 10 + n, "vision_score": 30 + n},
                "P6": {"gold": 20000, "damage_to_champs": 50000, "cs": 300},
                "P2": {"kills": 0, "deaths": 12, "damage_to_champs": 1000},
            },
        )
    before = {ids[n]: _badges(client, ids[n]) for n in NAMES}

    r = client.post("/api/v1/admin/replay")
    assert r.status_code == 200
    assert r.json()["matches_replayed"] == 6

    assert {ids[n]: _badges(client, ids[n]) for n in NAMES} == before
    # Senaryo boş bir determinizm iddiası olmasın:
    assert any(badges for badges in before.values())
