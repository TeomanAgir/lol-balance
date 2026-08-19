"""GÖREV 24 — rozet motoru 16 → 27 (api_contract §2 "Rozetler" + "Kademe" +
"Rozet kataloğu ucu").

Kapsam: 11 yeni rozetin kesin tanımı (eşik altı/üstü, NULL, eşitlik, blok
ayrıklığı, min-geçmiş, snapshot'ın İLERİYE BAKMADIĞI), kademe eşikleri ve
`matches_played >= 8` şartı, `include_locked` iki modu, `GET /badges`
(holders/roster_size) ve replay determinizmi.

Kurgu deseni `test_badges.py` ile aynıdır (yardımcılar oradan gelir):
10 oyuncu (P0..P4 = team100, P5..P9 = team200), tüm katılımcılarda AYNI
`BASE_STATS` — senaryolar yalnız ilgilendikleri alanı bozar. perf_score
`_set_perf` ile `rating_history`'ye doğrudan yazılır (backend perf HESAPLAMAZ,
ham okur).
"""
from __future__ import annotations

import pytest

from app.services.badges import BADGE_KEYS, CATALOG
from test_badges import (
    NAMES,
    POSITIONS,
    TEAM200,
    _badges,
    _by_key,
    _count,
    _day,
    _ingest,
    _make_players,
    _series,
    _set_perf,
)

# api_contract §2: katalog sırası DONDURULMUŞ (görsel dosya adları ID'ye bağlı).
CONTRACT_ORDER = (
    "mvp", "vision", "damage", "cs_per_min", "gold", "role_duel",
    "role_record", "pr_perf", "pr_damage", "kill_20", "kda_10", "deathless",
    "comeback", "tragic_hero", "marathon_5", "win_streak_3", "lose_streak_3",
    "bench_2", "nemesis_6", "duo_6", "versatile", "veteran_10", "veteran_20",
    "veteran_50", "roulette_complete", "roulette_winner", "gambler",
)

FLAT = {n: 1.0 for n in NAMES}  # nötr perf zemini


@pytest.fixture
def ids(client):
    return _make_players(client)


def _badge(client, player_id, key, include_locked=False):
    r = client.get(
        f"/api/v1/players/{player_id}/badges",
        params={"include_locked": str(include_locked).lower()},
    )
    assert r.status_code == 200, r.text
    return {b["key"]: b for b in r.json()["badges"]}.get(key)


# ==========================================================================
# Katalog
# ==========================================================================
def test_catalog_is_27_frozen_keys_in_contract_order():
    assert BADGE_KEYS == CONTRACT_ORDER
    assert len(CATALOG) == 27
    assert [d.id for d in CATALOG] == list(range(1, 28))
    # Kademeli olanlar YALNIZ 01-06.
    assert [d.key for d in CATALOG if d.tiered] == list(CONTRACT_ORDER[:6])
    assert [d.key for d in CATALOG if d.one_time] == [
        "nemesis_6", "duo_6", "versatile",
        "veteran_10", "veteran_20", "veteran_50", "gambler",
    ]
    assert [d.key for d in CATALOG if d.source == "roulette"] == [
        "roulette_complete", "roulette_winner", "gambler",
    ]


# ==========================================================================
# role_duel — "Koridor Hâkimi" (kademeli, tekrarlanabilir)
# ==========================================================================
def test_role_duel_threshold_is_inclusive_and_best_value_is_the_ratio(client, ids, db):
    """Oran >= 1.5 rozet verir; eşiğin ALTI vermez. best_value = oran."""
    match_id = _ingest(client, ids, "d-1", _day(1))
    _set_perf(db, match_id, ids, {**FLAT, "P0": 1.5, "P1": 1.49})
    duel = _by_key(client, ids["P0"])["role_duel"]
    assert duel["count"] == 1
    assert duel["best_match_id"] == match_id
    assert duel["best_value"] == 1.5
    assert _count(client, ids["P1"], "role_duel") == 0
    # Rakip tarafta oran 1/1.5 < 1.5 → rozet yok.
    assert _count(client, ids["P5"], "role_duel") == 0


def test_role_duel_repeats_and_keeps_the_best_ratio(client, ids, db):
    m1 = _ingest(client, ids, "d-r1", _day(1))
    m2 = _ingest(client, ids, "d-r2", _day(2))
    _set_perf(db, m1, ids, {**FLAT, "P0": 4.0})
    _set_perf(db, m2, ids, {**FLAT, "P0": 2.0})
    duel = _by_key(client, ids["P0"])["role_duel"]
    assert duel["count"] == 2
    assert duel["last_match_id"] == m2  # SON kazandıran maç
    assert (duel["best_match_id"], duel["best_value"]) == (m1, 4.0)


def test_role_duel_requires_exactly_two_opposing_slots(client, ids, db):
    """O rolde tam 2 non-NULL slot ve KARŞI takımlarda olmalı.

    TOP'ta tek slot kalır (P5 JUNGLE'a kaydı) → P0 rozet almaz; JUNGLE'da 3 slot
    olur → o rol de dışıdır; MIDDLE etkilenmez (diğer roller bağımsız).
    """
    match_id = _ingest(client, ids, "d-slots", _day(1), positions={"P5": "JUNGLE"})
    _set_perf(db, match_id, ids, {**FLAT, "P0": 9.0, "P1": 9.0, "P2": 9.0})
    assert _count(client, ids["P0"], "role_duel") == 0  # TOP: 1 slot
    assert _count(client, ids["P1"], "role_duel") == 0  # JUNGLE: 3 slot
    assert _count(client, ids["P2"], "role_duel") == 1  # MIDDLE: sağlam çift


def test_role_duel_ignores_same_team_pairs(client, ids, db):
    """Aynı rolde 2 slot AMA aynı takımda → düello değildir."""
    match_id = _ingest(
        client, ids, "d-same", _day(1),
        positions={"P0": "TOP", "P1": "TOP", "P5": "JUNGLE", "P6": "JUNGLE"},
    )
    _set_perf(db, match_id, ids, {**FLAT, "P0": 9.0, "P5": 9.0})
    assert _count(client, ids["P0"], "role_duel") == 0
    assert _count(client, ids["P5"], "role_duel") == 0


def test_role_duel_null_perf_or_non_positive_opponent(client, ids, db):
    """NULL perf aday değil; rakip perf'i <= 0 ise oran TANIMSIZ → rozet yok."""
    m1 = _ingest(client, ids, "d-null", _day(1))
    _set_perf(db, m1, ids, {**FLAT, "P0": 9.0, "P5": None})
    m2 = _ingest(client, ids, "d-zero", _day(2))
    _set_perf(db, m2, ids, {**FLAT, "P0": 9.0, "P5": 0.0})
    m3 = _ingest(client, ids, "d-neg", _day(3))
    _set_perf(db, m3, ids, {**FLAT, "P0": 9.0, "P5": -2.0})
    assert _count(client, ids["P0"], "role_duel") == 0


# ==========================================================================
# role_record — "Rolün Rekoru" (maç-öncesi grup snapshot'ı)
# ==========================================================================
def _flat_series(client, ids, db, prefix, count, perf=None, **kwargs):
    """count maç, hepsinde perf nötr (ya da verilen harita) — zemin kurulumu."""
    matches = _series(client, ids, prefix, count, **kwargs)
    for match_id in matches:
        _set_perf(db, match_id, ids, perf or FLAT)
    return matches


def test_role_record_needs_ten_prior_slots_in_that_role(client, ids, db):
    """Maç başına rol başına 2 slot → 5 maç = 10 slot; 6. maçta rekor sayılır."""
    _flat_series(client, ids, db, "rr-a", 4)  # 8 slot → yetersiz
    m5 = _ingest(client, ids, "rr-a-5", _day(5))
    _set_perf(db, m5, ids, {**FLAT, "P0": 5.0})
    assert _count(client, ids["P0"], "role_record") == 0  # 8 önceki slot

    m6 = _ingest(client, ids, "rr-a-6", _day(6))
    _set_perf(db, m6, ids, {**FLAT, "P0": 9.0})
    record = _by_key(client, ids["P0"])["role_record"]
    assert record["count"] == 1
    assert record["last_match_id"] == m6
    assert (record["best_match_id"], record["best_value"]) == (m6, 9.0)


def test_role_record_snapshot_does_not_look_ahead(client, ids, db):
    """Rekor MAÇ-ÖNCESİ snapshot'tır; aynı maçta iki slot da onunla ölçülür.

    6. maçta P0 (2.0) ve rakibi P5 (3.0) ikisi de maç-öncesi rekoru (1.0) aşar →
    ikisi de rozet alır (P0, P5'in 3.0'ını GÖRMEZ). 7. maçta P0'ın 2.5'i artık
    3.0'ın altındadır → rozet YOK (snapshot maçtan SONRA güncellendi).
    """
    _flat_series(client, ids, db, "rr-b", 5)
    m6 = _ingest(client, ids, "rr-b-6", _day(6))
    _set_perf(db, m6, ids, {**FLAT, "P0": 2.0, "P5": 3.0})
    m7 = _ingest(client, ids, "rr-b-7", _day(7))
    _set_perf(db, m7, ids, {**FLAT, "P0": 2.5})

    p0 = _by_key(client, ids["P0"])["role_record"]
    assert (p0["count"], p0["last_match_id"], p0["best_value"]) == (1, m6, 2.0)
    assert _count(client, ids["P5"], "role_record") == 1


def test_role_record_requires_strictly_exceeding_and_ignores_other_roles(
    client, ids, db
):
    """Eşitlik rekor DEĞİLDİR; rekor rol bazlıdır (JUNGLE'daki tavan TOP'u bağlamaz)."""
    _flat_series(client, ids, db, "rr-c", 5, perf={**FLAT, "P1": 8.0})
    tie = _ingest(client, ids, "rr-c-6", _day(6))
    _set_perf(db, tie, ids, {**FLAT, "P0": 1.0})  # TOP rekoru zaten 1.0
    assert _count(client, ids["P0"], "role_record") == 0
    # JUNGLE'ın rekoru 8.0'dır; TOP'ta 2.0 yine de rekordur.
    beat = _ingest(client, ids, "rr-c-7", _day(7))
    _set_perf(db, beat, ids, {**FLAT, "P0": 2.0})
    assert _count(client, ids["P0"], "role_record") == 1


def test_role_record_null_perf_slots_do_not_count_as_history(client, ids, db):
    """NULL perf slotu ne rekor adayıdır ne de 10'luk slot sayacına girer."""
    # 5 maçın hepsinde TOP slotlarının perf'i NULL → karşılaştırılabilir slot yok.
    _flat_series(client, ids, db, "rr-d", 5, perf={**FLAT, "P0": None, "P5": None})
    m6 = _ingest(client, ids, "rr-d-6", _day(6))
    _set_perf(db, m6, ids, {**FLAT, "P0": 9.0})
    assert _count(client, ids["P0"], "role_record") == 0


def test_role_record_null_position_cannot_break_any_record(client, ids, db):
    _flat_series(client, ids, db, "rr-e", 5)
    m6 = _ingest(client, ids, "rr-e-6", _day(6), positions={"P0": None})
    _set_perf(db, m6, ids, {**FLAT, "P0": 99.0})
    assert _count(client, ids["P0"], "role_record") == 0


# ==========================================================================
# pr_perf / pr_damage — kişisel rekor (min 5 önceki karşılaştırılabilir maç)
# ==========================================================================
def test_pr_perf_needs_five_prior_matches_then_strict_exceed(client, ids, db):
    _flat_series(client, ids, db, "pr-a", 4)
    m5 = _ingest(client, ids, "pr-a-5", _day(5))
    _set_perf(db, m5, ids, {**FLAT, "P0": 5.0})
    assert _count(client, ids["P0"], "pr_perf") == 0  # yalnız 4 önceki maç

    m6 = _ingest(client, ids, "pr-a-6", _day(6))
    _set_perf(db, m6, ids, {**FLAT, "P0": 5.0})  # eşitlik → rekor değil
    assert _count(client, ids["P0"], "pr_perf") == 0

    m7 = _ingest(client, ids, "pr-a-7", _day(7))
    _set_perf(db, m7, ids, {**FLAT, "P0": 5.01})
    record = _by_key(client, ids["P0"])["pr_perf"]
    assert record["count"] == 1
    assert (record["best_match_id"], record["best_value"]) == (m7, 5.01)
    assert record["progress"] is None  # kişisel rekorda ilerleme YOKTUR


def test_pr_perf_null_match_neither_counts_nor_qualifies(client, ids, db):
    """Metriği hesaplanamayan maç ne rekor adayıdır ne de 5'lik sayaca girer."""
    matches = _series(client, ids, "pr-b", 6)
    for i, match_id in enumerate(matches):
        _set_perf(db, match_id, ids, {**FLAT, "P0": None if i == 2 else 1.0})
    m7 = _ingest(client, ids, "pr-b-7", _day(7))
    _set_perf(db, m7, ids, {**FLAT, "P0": 9.0})
    # 7. maçtan önce yalnız 5 hesaplanabilir maç var (biri NULL) → rekor sayılır;
    # 6. maçta sayaç 4'tü, o yüzden orada rozet düşmedi.
    record = _by_key(client, ids["P0"])["pr_perf"]
    assert record["count"] == 1
    assert record["last_match_id"] == m7


def test_pr_damage_uses_damage_per_minute_and_skips_durationless_matches(
    client, ids, db
):
    """pr_damage = damage_to_champs / (duration_s/60); süresiz maç sayaca girmez."""
    base = {"damage_to_champs": 20000}
    for n in range(1, 6):
        _ingest(
            client, ids, f"pd-{n}", _day(n),
            duration_s=None if n == 3 else 1800,
            stats={name: dict(base) for name in NAMES},
        )
    # 6. maç: 5 hesaplanabilir maç GEREKİR ama süresiz maç sayılmadı → 4 var.
    _ingest(
        client, ids, "pd-6", _day(6), duration_s=1800,
        stats={"P0": {"damage_to_champs": 90000}},
    )
    assert _count(client, ids["P0"], "pr_damage") == 0

    m7 = _ingest(
        client, ids, "pd-7", _day(7), duration_s=1800,
        stats={"P0": {"damage_to_champs": 120000}},
    )
    record = _by_key(client, ids["P0"])["pr_damage"]
    assert record["count"] == 1
    assert record["best_match_id"] == m7
    assert record["best_value"] == round(120000 / 30, 2)


def test_pr_damage_shorter_match_can_beat_a_bigger_absolute_number(client, ids, db):
    """Metrik dakika başınadır: 60000/15dk, 90000/30dk'yı geçer."""
    for n in range(1, 7):
        _ingest(
            client, ids, f"pdb-{n}", _day(n), duration_s=1800,
            stats={"P0": {"damage_to_champs": 90000}},
        )
    m7 = _ingest(
        client, ids, "pdb-7", _day(7), duration_s=900,
        stats={"P0": {"damage_to_champs": 60000}},
    )
    record = _by_key(client, ids["P0"])["pr_damage"]
    assert record["count"] == 1
    assert record["best_match_id"] == m7
    assert record["best_value"] == 4000.0


# ==========================================================================
# kill_20 / kda_10
# ==========================================================================
def test_kill_20_threshold_null_and_repeat(client, ids):
    _ingest(client, ids, "k-19", _day(1), stats={"P0": {"kills": 19}})
    m2 = _ingest(client, ids, "k-20", _day(2), stats={"P0": {"kills": 20}})
    m3 = _ingest(client, ids, "k-25", _day(3), stats={"P0": {"kills": 25}})
    _ingest(client, ids, "k-null", _day(4), stats={"P0": {"kills": None}})
    badge = _by_key(client, ids["P0"])["kill_20"]
    assert badge["count"] == 2
    assert badge["last_match_id"] == m3
    assert m2 != m3
    # Anlatısal sınıf: ölçülebilir değeri YOKTUR.
    assert (badge["best_match_id"], badge["best_value"]) == (None, None)


def test_kda_10_threshold_zero_deaths_and_nulls(client, ids):
    """(k+a)/max(1,deaths) >= 10; k/d/a üçü de non-NULL olmalı."""
    _ingest(
        client, ids, "kda-9", _day(1),
        stats={"P0": {"kills": 9, "assists": 0, "deaths": 1}},
    )
    m2 = _ingest(
        client, ids, "kda-10", _day(2),
        stats={"P0": {"kills": 10, "assists": 0, "deaths": 1}},
    )
    m3 = _ingest(
        client, ids, "kda-inf", _day(3),
        stats={"P0": {"kills": 6, "assists": 4, "deaths": 0}},
    )
    _ingest(
        client, ids, "kda-null", _day(4),
        stats={"P0": {"kills": 40, "assists": 40, "deaths": None}},
    )
    badge = _by_key(client, ids["P0"])["kda_10"]
    assert badge["count"] == 2
    assert badge["last_match_id"] == m3
    assert m2 != m3


# ==========================================================================
# tragic_hero — kaybeden takımın TEK BAŞINA en iyisi (bench_2'nin aynası)
# ==========================================================================
def test_tragic_hero_goes_to_sole_best_of_losing_team(client, ids, db):
    match_id = _ingest(client, ids, "th-1", _day(1), winner_team=100)
    _set_perf(db, match_id, ids, {**FLAT, "P7": 3.0, "P2": 5.0})
    badge = _by_key(client, ids["P7"])["tragic_hero"]
    assert badge["count"] == 1
    assert badge["last_match_id"] == match_id
    # Kazanan takımın en iyisi tragic_hero DEĞİL (o mvp'dir).
    assert _count(client, ids["P2"], "tragic_hero") == 0
    assert _count(client, ids["P2"], "mvp") == 1


def test_tragic_hero_tie_or_null_in_losing_team_awards_nobody(client, ids, db):
    m1 = _ingest(client, ids, "th-tie", _day(1), winner_team=100)
    _set_perf(db, m1, ids, {**FLAT, "P7": 3.0, "P8": 3.0})
    m2 = _ingest(client, ids, "th-null", _day(2), winner_team=100)
    _set_perf(db, m2, ids, {**FLAT, "P7": 3.0, "P8": None})
    assert all(_count(client, ids[n], "tragic_hero") == 0 for n in TEAM200)


# ==========================================================================
# marathon_5 — gece = played_at (UTC) − 6 saat
# ==========================================================================
def _night_match(client, ids, sgid, when):
    return _ingest(client, ids, sgid, when)


def test_marathon_counts_a_session_running_past_midnight_as_one_night(client, ids):
    """22:00–03:00 arası tek gecedir (UTC − 6 saat kuralı)."""
    times = [
        "2026-08-10T21:00:00Z", "2026-08-10T22:00:00Z", "2026-08-10T23:30:00Z",
        "2026-08-11T01:00:00Z", "2026-08-11T03:00:00Z",
    ]
    matches = [
        _night_match(client, ids, f"mr-{i}", t) for i, t in enumerate(times)
    ]
    badge = _by_key(client, ids["P0"])["marathon_5"]
    assert badge["count"] == 1
    assert badge["last_match_id"] == matches[-1]  # gecenin SON maçı


def test_marathon_not_awarded_when_the_fifth_match_is_the_next_night(client, ids):
    """07:00 artık yeni gecedir (06:00 sınırı) → 4 + 1 → rozet yok."""
    times = [
        "2026-08-10T21:00:00Z", "2026-08-10T22:00:00Z", "2026-08-10T23:30:00Z",
        "2026-08-11T01:00:00Z", "2026-08-11T07:00:00Z",
    ]
    for i, t in enumerate(times):
        _night_match(client, ids, f"mn-{i}", t)
    assert _count(client, ids["P0"], "marathon_5") == 0


def test_marathon_repeats_per_qualifying_night(client, ids):
    first = [f"2026-08-10T2{i}:00:00Z" for i in range(3)] + [
        "2026-08-11T00:00:00Z", "2026-08-11T01:00:00Z",
    ]
    second = [f"2026-08-12T2{i}:00:00Z" for i in range(3)] + [
        "2026-08-13T00:00:00Z", "2026-08-13T01:00:00Z", "2026-08-13T02:00:00Z",
    ]
    matches = [
        _night_match(client, ids, f"mp-{i}", t)
        for i, t in enumerate(first + second)
    ]
    badge = _by_key(client, ids["P0"])["marathon_5"]
    assert badge["count"] == 2
    assert badge["last_match_id"] == matches[-1]


# ==========================================================================
# lose_streak_3 — win_streak_3'ün aynası
# ==========================================================================
def test_lose_streak_blocks_are_disjoint_and_reset_by_a_win(client, ids):
    matches = _series(client, ids, "ls", 6, winner_team=100)
    badge = _by_key(client, ids["P5"])["lose_streak_3"]
    assert badge["count"] == 2
    assert badge["last_match_id"] == matches[5]
    assert _count(client, ids["P0"], "lose_streak_3") == 0


def test_lose_streak_reset_by_a_win(client, ids):
    for n in range(1, 6):
        _ingest(
            client, ids, f"lsr-{n}", _day(n),
            winner_team=200 if n == 3 else 100,
        )
    assert _count(client, ids["P5"], "lose_streak_3") == 0


def test_streak_progress_is_the_open_run_length(client, ids):
    """progress.current = AÇIK serinin uzunluğu (blok tamamlanınca sıfırlanır)."""
    _series(client, ids, "sp", 4, winner_team=100)
    p0 = _badge(client, ids["P0"], "win_streak_3")
    assert p0["count"] == 1 and p0["progress"] == {"current": 1, "target": 3}
    p5 = _badge(client, ids["P5"], "lose_streak_3")
    assert p5["progress"] == {"current": 1, "target": 3}


# ==========================================================================
# nemesis_6 / duo_6 — tek seferlik ilişkisel rozetler
# ==========================================================================
WIDE = [f"P{i}" for i in range(15)]


@pytest.fixture
def wide_ids(client):
    return _make_players(client, WIDE)


def test_nemesis_and_duo_awarded_on_sixth_win_and_never_again(client, ids):
    matches = _series(client, ids, "nm", 8, winner_team=100)
    badges = _by_key(client, ids["P0"])
    for key in ("nemesis_6", "duo_6"):
        assert badges[key]["count"] == 1  # TEK SEFERLİK
        assert badges[key]["last_match_id"] == matches[5]  # eşiği İLK dolduran
        assert badges[key]["progress"] == {"current": 8, "target": 6}
    # Kaybeden taraf hiçbirini almaz (yalnız GALİBİYET sayılır).
    assert _count(client, ids["P5"], "nemesis_6") == 0
    assert _count(client, ids["P5"], "duo_6") == 0


def test_nemesis_requires_the_same_opponent(client, wide_ids):
    """Rakip havuzu dönüşümlüyse kimseye karşı 6 galibiyet olmaz; duo düşer."""
    for n in range(1, 7):
        _ingest(
            client, wide_ids, f"nr-{n}", _day(n),
            t100=WIDE[:5],
            t200=WIDE[5:10] if n % 2 else WIDE[10:],
            winner_team=100,
        )
    p0 = wide_ids["P0"]
    assert _count(client, p0, "nemesis_6") == 0
    assert _badge(client, p0, "nemesis_6", include_locked=True)["progress"] == {
        "current": 3, "target": 6,
    }
    assert _count(client, p0, "duo_6") == 1  # takım arkadaşları sabit


def test_relational_progress_below_threshold(client, ids):
    _series(client, ids, "np", 4, winner_team=100)
    badge = _badge(client, ids["P0"], "nemesis_6", include_locked=True)
    assert badge["count"] == 0
    assert badge["last_match_id"] is None
    assert badge["progress"] == {"current": 4, "target": 6}


# ==========================================================================
# Kademe (api_contract §2 "Kademe")
# ==========================================================================
def _vision_stats(leader):
    return {n: {"vision_score": 99 if n == leader else 1} for n in NAMES}


def _vision_series(client, ids, prefix, leaders, start=1):
    """leaders[i] = i. maçın vizyon lideri; `start` kronolojik gün ofsetidir."""
    return [
        _ingest(
            client, ids, f"{prefix}-{i}", _day(start + i),
            stats=_vision_stats(leader),
        )
        for i, leader in enumerate(leaders)
    ]


def test_tier_gold_uses_raw_rate_not_the_rounded_one(client, ids):
    """8 maçta 3 rozet → ham oran 0.375 (>= 0.32) → altın; `rate` 0.38 gösterir."""
    _vision_series(client, ids, "tg", ["P0"] * 3 + ["P1"] * 5)
    badge = _by_key(client, ids["P0"])["vision"]
    assert badge["count"] == 3
    assert badge["tier"] == "gold"
    assert badge["rate"] == 0.38
    assert badge["next_tier_rate"] is None


def test_tier_silver_and_bronze_thresholds(client, ids):
    _vision_series(client, ids, "ts", ["P0"] * 2 + ["P1"] * 8)  # 2/10 = 0.20
    silver = _by_key(client, ids["P0"])["vision"]
    assert (silver["tier"], silver["rate"], silver["next_tier_rate"]) == (
        "silver", 0.2, 0.32,
    )
    bronze = _by_key(client, ids["P1"])["vision"]  # 8/10 = 0.80 → altın
    assert bronze["tier"] == "gold"


def test_tier_requires_eight_matches_for_silver_and_gold(client, ids):
    """3 maçta 3 rozet (oran 1.0) bile matches_played < 8 iken BRONZ kalır."""
    _vision_series(client, ids, "tm", ["P0"] * 3)
    badge = _by_key(client, ids["P0"])["vision"]
    assert badge["count"] == 3
    assert (badge["tier"], badge["rate"], badge["next_tier_rate"]) == (
        "bronze", 1.0, 0.2,
    )
    # 8. maçta oran hâlâ >= 0.32 → altın açılır.
    _vision_series(client, ids, "tm2", ["P0"] * 5, start=4)
    assert _by_key(client, ids["P0"])["vision"]["tier"] == "gold"


def test_tier_bronze_when_rate_below_silver(client, ids):
    _vision_series(client, ids, "tb", ["P0"] + ["P1"] * 9)  # 1/10 = 0.10
    badge = _by_key(client, ids["P0"])["vision"]
    assert (badge["tier"], badge["rate"], badge["next_tier_rate"]) == (
        "bronze", 0.1, 0.2,
    )


def test_non_tiered_badges_never_carry_tier_fields(client, ids):
    _ingest(client, ids, "nt", _day(1), stats={"P0": {"deaths": 0}})
    badge = _by_key(client, ids["P0"])["deathless"]
    assert (badge["tier"], badge["rate"], badge["next_tier_rate"]) == (
        None, None, None,
    )


def test_locked_tiered_badge_has_no_tier_but_reports_rate(client, ids):
    """Kazanılmamış kademeli rozet: tier NULL, rate 0.0, next_tier_rate 0.20."""
    _ingest(client, ids, "lt", _day(1), stats=_vision_stats("P1"))
    badge = _badge(client, ids["P0"], "vision", include_locked=True)
    assert badge["count"] == 0
    assert (badge["tier"], badge["rate"], badge["next_tier_rate"]) == (
        None, 0.0, 0.2,
    )


# ==========================================================================
# include_locked + matches_played
# ==========================================================================
def test_default_response_only_returns_earned_badges(client, ids):
    _ingest(client, ids, "il-1", _day(1), stats={"P0": {"deaths": 0}})
    body = client.get(f"/api/v1/players/{ids['P0']}/badges").json()
    assert body["matches_played"] == 1
    assert all(b["count"] > 0 for b in body["badges"])
    assert len(body["badges"]) < len(BADGE_KEYS)


def test_include_locked_returns_the_whole_catalog_in_order(client, ids):
    _ingest(client, ids, "il-2", _day(1), stats={"P0": {"deaths": 0}})
    body = client.get(
        f"/api/v1/players/{ids['P0']}/badges", params={"include_locked": "true"}
    ).json()
    keys = [b["key"] for b in body["badges"]]
    assert keys == list(BADGE_KEYS)
    locked = {b["key"]: b for b in body["badges"]}["veteran_50"]
    assert locked["count"] == 0
    assert locked["last_match_id"] is None
    assert locked["progress"] == {"current": 1, "target": 50}
    assert (locked["best_match_id"], locked["best_value"]) == (None, None)


def test_include_locked_for_a_player_without_matches(client):
    created = client.post("/api/v1/players", json={"display_name": "Maçsız"})
    player_id = created.json()["id"]
    body = client.get(
        f"/api/v1/players/{player_id}/badges", params={"include_locked": "true"}
    ).json()
    assert body["matches_played"] == 0
    assert [b["key"] for b in body["badges"]] == list(BADGE_KEYS)
    assert all(b["count"] == 0 for b in body["badges"])
    # Payda 0 → oran tanımsız.
    mvp = {b["key"]: b for b in body["badges"]}["mvp"]
    assert (mvp["rate"], mvp["tier"]) == (None, None)
    # Varsayılan mod hâlâ boş liste döner.
    assert client.get(f"/api/v1/players/{player_id}/badges").json()["badges"] == []


def test_include_locked_unknown_player_still_404(client):
    r = client.get("/api/v1/players/999/badges", params={"include_locked": "true"})
    assert r.status_code == 404


def test_matches_played_counts_only_valid_matches(client, ids):
    m1 = _ingest(client, ids, "mp-1", _day(1))
    _ingest(client, ids, "mp-2", _day(2))
    assert client.get(f"/api/v1/players/{ids['P0']}/badges").json()[
        "matches_played"
    ] == 2
    assert client.post(f"/api/v1/matches/{m1}/void").status_code == 200
    assert client.get(f"/api/v1/players/{ids['P0']}/badges").json()[
        "matches_played"
    ] == 1


# ==========================================================================
# GET /badges — katalog + nadirlik
# ==========================================================================
def test_badge_catalog_shape_and_order(client):
    body = client.get("/api/v1/badges").json()
    assert body["roster_size"] == 0
    assert [b["id"] for b in body["badges"]] == list(range(1, 28))
    assert [b["key"] for b in body["badges"]] == list(BADGE_KEYS)
    first = body["badges"][0]
    assert first == {
        "id": 1, "key": "mvp", "class": "record", "source": "valid",
        "tiered": True, "one_time": False, "holders": 0, "holders_pct": None,
    }
    classes = {b["class"] for b in body["badges"]}
    assert classes <= {
        "record", "role", "personal", "narrative", "streak", "relational",
        "identity", "milestone", "roulette",
    }
    assert {b["source"] for b in body["badges"]} == {"valid", "roulette"}


def test_badge_catalog_holders_and_roster_size(client, ids):
    """roster_size = en az 1 VALID maçı olan oyuncu; holders = taşıyan oyuncu sayısı."""
    client.post("/api/v1/players", json={"display_name": "Maçsız"})  # roster'a girmez
    _ingest(client, ids, "cat-1", _day(1), stats={"P0": {"deaths": 0}})
    body = client.get("/api/v1/badges").json()
    assert body["roster_size"] == 10
    by_key = {b["key"]: b for b in body["badges"]}
    assert by_key["deathless"]["holders"] == 1
    assert by_key["deathless"]["holders_pct"] == 10.0
    assert by_key["veteran_50"]["holders"] == 0
    # Tüm katılımcıların statları eşit → damage rekoru 10 kişide (eşitlikte herkes).
    assert by_key["damage"]["holders"] == 10
    assert by_key["damage"]["holders_pct"] == 100.0


def test_badge_catalog_holders_match_the_per_player_endpoint(client, ids, db):
    """Katalog per-player hesapların SAF TOPLAMIDIR (ortak çekirdek kanıtı)."""
    matches = _series(client, ids, "cs", 6, winner_team=100)
    for i, match_id in enumerate(matches):
        _set_perf(db, match_id, ids, {**FLAT, "P0": 2.0 + i, "P7": 0.2})
    catalog = {b["key"]: b["holders"] for b in client.get("/api/v1/badges").json()["badges"]}
    expected = dict.fromkeys(BADGE_KEYS, 0)
    for name in NAMES:
        for badge in _badges(client, ids[name]):
            expected[badge["key"]] += 1
    assert catalog == expected
    assert sum(catalog.values()) > 0  # boş bir iddia olmasın


def test_badge_catalog_requires_api_key(client):
    client.headers.pop("X-API-Key")
    assert client.get("/api/v1/badges").status_code == 401


def test_badge_catalog_does_not_write_to_the_db(client, ids, db):
    _series(client, ids, "cw", 3, winner_team=100)

    def _snapshot():
        conn = db()
        try:
            return [
                conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
                for table in (
                    "matches", "match_participants", "rating_history",
                    "role_rating_history", "ingest_events", "players",
                )
            ]
        finally:
            conn.close()

    before = _snapshot()
    assert client.get("/api/v1/badges").status_code == 200
    assert client.get(f"/api/v1/players/{ids['P0']}/badges").status_code == 200
    assert _snapshot() == before


# ==========================================================================
# Determinizm — replay sonrası bit-bit aynı yanıt
# ==========================================================================
def test_all_new_badges_are_replay_deterministic(client, ids):
    """Zengin senaryo: yeni rozetlerin çoğu düşer, replay yanıtı değiştirmez.

    perf_score BURADA elle yazılmaz: replay rating_history'yi yeniden üretir, o
    yüzden iddia "aynı ham girdiden aynı rozet yanıtı" olmalıdır (motorun
    yazdığı perf'lerle).
    """
    times = [
        "2026-08-10T20:00:00Z", "2026-08-10T21:00:00Z", "2026-08-10T22:00:00Z",
        "2026-08-10T23:00:00Z", "2026-08-11T01:00:00Z", "2026-08-11T20:00:00Z",
        "2026-08-12T20:00:00Z", "2026-08-13T20:00:00Z",
    ]
    matches = []
    for i, when in enumerate(times):
        matches.append(
            _ingest(
                client, ids, f"det-{i}", when,
                winner_team=100 if i % 4 else 200,
                stats={
                    "P0": {
                        "kills": 20 + i, "deaths": 0, "assists": 5,
                        "damage_to_champs": 30000 + 1000 * i,
                        "vision_score": 50 + i, "cs": 300,
                    },
                    "P7": {"kills": 1, "deaths": 9, "damage_to_champs": 1000},
                },
                positions={"P0": POSITIONS[i % 5]},
            )
        )

    def _snapshot():
        return {
            "catalog": client.get("/api/v1/badges").json(),
            "players": {
                name: client.get(
                    f"/api/v1/players/{ids[name]}/badges",
                    params={"include_locked": "true"},
                ).json()
                for name in NAMES
            },
        }

    before = _snapshot()
    r = client.post("/api/v1/admin/replay")
    assert r.status_code == 200
    assert r.json()["matches_replayed"] == len(times)
    assert _snapshot() == before

    # Senaryo boş bir iddia olmasın: yeni rozetlerin çoğu fiilen düştü.
    earned = {
        b["key"]
        for body in before["players"].values()
        for b in body["badges"]
        if b["count"] > 0
    }
    assert {
        "kill_20", "kda_10", "marathon_5", "lose_streak_3", "win_streak_3",
        "versatile", "pr_perf",
    } <= earned
