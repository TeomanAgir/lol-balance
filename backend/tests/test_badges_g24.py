"""GÖREV 24 — rozet motoru 16 → 27 → 28 (api_contract §2 "Rozetler" + "Kademe" +
"Rozet kataloğu ucu"), + Teoman'ın kademe revizyonları (oran→ardışık-görev,
sonra oran→KÜMÜLATİF SAYAÇ) + `perfect_quad` (ID 28, NADİR ölçek).

Kapsam: 11+1 yeni rozetin kesin tanımı (eşik altı/üstü, NULL, eşitlik, blok
ayrıklığı, min-geçmiş, snapshot'ın İLERİYE BAKMADIĞI), kademe SAYAÇ eşikleri
(STANDART/NADİR ölçek, `matches_played` şartı YOK, kademe hiç düşmez),
`stellar_quest`, `include_locked` iki modu, `GET /badges` (holders/roster_size/
`tier_scale`) ve replay determinizmi.

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
    DURATION_S,
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
# `perfect_quad` katalog SONUNA eklendi (ID 28) — araya girmez.
CONTRACT_ORDER = (
    "mvp", "vision", "damage", "cs_per_min", "gold", "role_duel",
    "role_record", "pr_perf", "pr_damage", "kill_20", "kda_10", "deathless",
    "comeback", "tragic_hero", "marathon_5", "win_streak_3", "lose_streak_3",
    "bench_2", "nemesis_6", "duo_6", "versatile", "veteran_10", "veteran_20",
    "veteran_50", "roulette_complete", "roulette_winner", "gambler",
    "perfect_quad",
)

# Kademeli 7 rozet: 6 STANDART ölçek + perfect_quad (NADİR ölçek, katalog sonunda).
TIERED_ORDER = CONTRACT_ORDER[:6] + ("perfect_quad",)

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
def test_catalog_is_28_frozen_keys_in_contract_order():
    assert BADGE_KEYS == CONTRACT_ORDER
    assert len(CATALOG) == 28
    assert [d.id for d in CATALOG] == list(range(1, 29))
    assert CATALOG[-1].key == "perfect_quad"  # sona eklendi, araya girmedi
    # Kademeli olanlar 01-06 + perfect_quad (28.).
    assert [d.key for d in CATALOG if d.tiered] == list(TIERED_ORDER)
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
# Kademe (api_contract §2 "Kademe — ALTI SEVİYE", Teoman revizyonu 2026-08-19:
# ORAN → KÜMÜLATİF SAYAÇ (`count`); kademe ASLA DÜŞMEZ; `matches_played >= 8`
# şartı KALDIRILDI; `next_tier_rate` → `next_tier_count`; iki eşik ölçeği
# STANDART (6 rozet) / NADİR (`perfect_quad`))
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


def test_tier_matches_played_no_longer_gates_the_tier(client, ids):
    """Eskiden `matches_played < 8` bronza sabitlerdi; artık YOK — 3 maçta silver açılır."""
    _vision_series(client, ids, "mpgate", ["P0"] * 3)
    badge = _by_key(client, ids["P0"])["vision"]
    assert badge["count"] == 3
    assert badge["tier"] == "silver"
    assert badge["next_tier_count"] == 5


def test_tier_rate_is_informational_and_does_not_affect_the_tier(client, wide_ids):
    """Aynı count, FARKLI rate → aynı kademe (`rate` SALT bilgi, hesaba girmez)."""
    ids = wide_ids
    _vision_series(client, ids, "info-a", ["P0"] * 3)  # P0: 3 galibiyet / 3 maç
    _vision_series(client, ids, "info-b", ["P1"] * 3, start=4)  # P1: aynı, şimdilik
    # P1'e P0'ı HİÇ içermeyen 9 ekstra maç (WIDE'daki diğer oyuncularla 5v5) →
    # aynı count (3), çok daha düşük rate.
    filler_t100 = ["P1", "P10", "P11", "P12", "P13"]
    filler_t200 = ["P2", "P3", "P4", "P5", "P6"]
    filler_stats = {
        n: {"vision_score": 99 if n == "P10" else 1}
        for n in filler_t100 + filler_t200
    }
    for i in range(9):
        _ingest(
            client, ids, f"info-filler-{i}", _day(7 + i),
            t100=filler_t100, t200=filler_t200, stats=filler_stats,
        )
    p0 = _by_key(client, ids["P0"])["vision"]
    p1 = _by_key(client, ids["P1"])["vision"]
    assert p0["count"] == 3
    assert p1["count"] == 3
    assert p0["rate"] != p1["rate"]
    assert p0["tier"] == p1["tier"] == "silver"


def test_tier_never_drops_after_a_long_stretch_without_new_wins(client, ids):
    """Eski oran modelinde kademe düşerdi; SAYAÇ modelinde ASLA düşmez."""
    _vision_series(client, ids, "hold-a", ["P0"] * 5)  # count=5 → gold
    gold = _by_key(client, ids["P0"])["vision"]
    assert gold["tier"] == "gold"
    # 20 maç daha, hiçbirinde P0 lider değil (rate ÇÖKER) → kademe SABİT kalır.
    _vision_series(client, ids, "hold-b", ["P1"] * 20, start=6)
    still = _by_key(client, ids["P0"])["vision"]
    assert still["count"] == 5
    assert still["tier"] == "gold"
    assert still["rate"] < gold["rate"]  # oran gerçekten düştü, kademeyi etkilemedi


def test_tier_diamond_without_quest_stays_diamond_via_api(client, ids):
    """12 galibiyet ama HİÇ 3-ardışık yok (WLWLWL...) → diamond kalır, stellar olmaz."""
    pattern = (["P0", "P1"] * 12)[:24]
    _vision_series(client, ids, "dq", pattern)
    badge = _by_key(client, ids["P0"])["vision"]
    assert badge["count"] == 12
    assert badge["tier"] == "diamond"
    assert badge["next_tier_count"] is None  # bir sonraki hedef GÖREVDİR, sayaç değil
    assert badge["stellar_quest"] == {"target": 3, "best": 1, "met": False}


def test_tier_quest_met_early_persists_until_diamond_count_then_yields_stellar(
    client, ids
):
    """Görev (ardışık 3) ERKEN ve KALICI tamamlanır; sayaç SONRADAN elmasa
    ulaşınca stellar HEMEN açılır (kalibrasyon notundaki Konna örneğiyle aynı)."""
    _vision_series(client, ids, "early", ["P0"] * 3 + ["P1"] * 9)  # count=3 (silver)
    silver = _by_key(client, ids["P0"])["vision"]
    assert silver["tier"] == "silver"
    assert silver["stellar_quest"] == {"target": 3, "best": 3, "met": True}
    _vision_series(client, ids, "early2", ["P0"] * 9, start=13)  # count=12 (diamond eşiği)
    stellar = _by_key(client, ids["P0"])["vision"]
    assert stellar["count"] == 12
    assert stellar["tier"] == "stellar"


# --- Doğrudan birim testler: `_tier`/`_next_tier_count`/`_stellar_quest`, iki
# ölçeğin (STANDART/NADİR) sayaç sınırlarında — bkz. `test_badges.
# _cs_per_min_values` ile aynı desen (private fonksiyon doğrudan import).
from app.services.badges import (  # noqa: E402
    STELLAR_QUEST_TARGET,
    STELLAR_TIER,
    TIER_LEVELS_RARE,
    TIER_LEVELS_STANDARD,
    TIER_SCALES,
    _next_tier_count,
    _PlayerState,
    _stellar_quest,
    _tier,
    _tier_levels,
)


def test_tier_levels_are_two_named_ordered_scales_ending_at_diamond():
    """SAYAÇ TABLOSU diamond'da BİTER; `stellar` bu tabloda hiç YOKTUR."""
    assert TIER_LEVELS_STANDARD == (
        ("bronze", 1), ("silver", 3), ("gold", 5), ("platinum", 8), ("diamond", 12),
    )
    assert TIER_LEVELS_RARE == (
        ("bronze", 1), ("silver", 2), ("gold", 3), ("platinum", 4), ("diamond", 6),
    )
    assert STELLAR_QUEST_TARGET == 3
    assert STELLAR_TIER == "stellar"


def test_tier_scale_lookup_maps_the_seven_tiered_badges():
    assert TIER_SCALES == {
        "mvp": "standard", "vision": "standard", "damage": "standard",
        "cs_per_min": "standard", "gold": "standard", "role_duel": "standard",
        "perfect_quad": "rare",
    }
    assert _tier_levels("vision") == TIER_LEVELS_STANDARD
    assert _tier_levels("perfect_quad") == TIER_LEVELS_RARE
    assert _tier_levels("kill_20") == TIER_LEVELS_STANDARD  # kademesiz → varsayılan


@pytest.mark.parametrize(
    "count, expected_tier, expected_next",
    [
        (1, "bronze", 3),
        (2, "bronze", 3),
        (3, "silver", 5),
        (4, "silver", 5),
        (5, "gold", 8),
        (7, "gold", 8),
        (8, "platinum", 12),
        (11, "platinum", 12),
        (12, "diamond", None),
        (99, "diamond", None),
    ],
)
def test_tier_standard_scale_counter_boundaries(count, expected_tier, expected_next):
    tier = _tier(count, TIER_LEVELS_STANDARD, best_streak=0)
    assert tier == expected_tier
    assert _next_tier_count(tier, TIER_LEVELS_STANDARD) == expected_next


@pytest.mark.parametrize(
    "count, expected_tier, expected_next",
    [
        (1, "bronze", 2),
        (2, "silver", 3),
        (3, "gold", 4),
        (4, "platinum", 6),
        (6, "diamond", None),
        (20, "diamond", None),
    ],
)
def test_tier_rare_scale_counter_boundaries(count, expected_tier, expected_next):
    tier = _tier(count, TIER_LEVELS_RARE, best_streak=0)
    assert tier == expected_tier
    assert _next_tier_count(tier, TIER_LEVELS_RARE) == expected_next


def test_tier_locked_badge_next_tier_count_is_bronze_threshold():
    """Kilitli kademeli rozette (`tier is None`) hedef bronz eşiğidir (`1`)."""
    assert _next_tier_count(None, TIER_LEVELS_STANDARD) == 1
    assert _next_tier_count(None, TIER_LEVELS_RARE) == 1


def test_tier_stellar_needs_diamond_count_and_the_quest_together():
    assert _tier(12, TIER_LEVELS_STANDARD, best_streak=2) == "diamond"  # görev eksik
    assert _tier(12, TIER_LEVELS_STANDARD, best_streak=3) == "stellar"
    assert _tier(6, TIER_LEVELS_RARE, best_streak=1) == "diamond"
    assert _tier(6, TIER_LEVELS_RARE, best_streak=3) == "stellar"


def test_tier_quest_alone_never_promotes_below_diamond_count():
    """Görev VAR (ardışık 3+) ama sayaç elmas eşiğinin altındaysa stellar olmaz."""
    assert _tier(5, TIER_LEVELS_STANDARD, best_streak=10) == "gold"
    assert _tier(3, TIER_LEVELS_RARE, best_streak=10) == "gold"


def test_tier_next_count_is_null_for_diamond_and_stellar():
    assert _next_tier_count("diamond", TIER_LEVELS_STANDARD) is None
    assert _next_tier_count("stellar", TIER_LEVELS_STANDARD) is None
    assert _next_tier_count("diamond", TIER_LEVELS_RARE) is None
    assert _next_tier_count("stellar", TIER_LEVELS_RARE) is None


def test_tier_never_decreases_as_count_increases():
    """Kademe hiç düşmez: `count` tek yönlü arttıkça `_tier` de asla düşmez."""
    order = {
        None: -1, "bronze": 0, "silver": 1, "gold": 2,
        "platinum": 3, "diamond": 4, "stellar": 5,
    }
    prev = -1
    for count in range(0, 15):
        rank = order[_tier(count, TIER_LEVELS_STANDARD, best_streak=0)]
        assert rank >= prev
        prev = rank


def test_tier_unearned_badge_defaults_to_none():
    assert _tier(0, TIER_LEVELS_STANDARD, best_streak=0) is None
    assert _tier(0, TIER_LEVELS_RARE, best_streak=5) is None  # count=0 tavan


def test_stellar_quest_helper_reads_tier_best():
    st = _PlayerState()
    assert _stellar_quest(st, "vision") == {"target": 3, "best": 0, "met": False}
    st.tier_best["vision"] = 3
    assert _stellar_quest(st, "vision") == {"target": 3, "best": 3, "met": True}


def test_non_tiered_badges_never_carry_tier_fields(client, ids):
    _ingest(client, ids, "nt", _day(1), stats={"P0": {"deaths": 0}})
    badge = _by_key(client, ids["P0"])["deathless"]
    assert (badge["tier"], badge["rate"], badge["next_tier_count"]) == (
        None, None, None,
    )
    assert badge["stellar_quest"] is None  # kademesiz sınıf → görev yok


def test_locked_tiered_badge_has_no_tier_but_reports_rate(client, ids):
    """Kazanılmamış kademeli rozet: tier NULL, rate 0.0, next_tier_count 1
    (bronz eşiği), stellar_quest yine de {best:0, met:false} döner."""
    _ingest(client, ids, "lt", _day(1), stats=_vision_stats("P1"))
    badge = _badge(client, ids["P0"], "vision", include_locked=True)
    assert badge["count"] == 0
    assert (badge["tier"], badge["rate"], badge["next_tier_count"]) == (
        None, 0.0, 1,
    )
    assert badge["stellar_quest"] == {"target": 3, "best": 0, "met": False}


def test_locked_tiered_badge_without_any_matches_still_reports_next_tier_count(
    client,
):
    """Hiç valid maçı olmayan oyuncuda bile kilitli kademeli rozet next_tier_count
    (bronz eşiği) verir; `rate` yalnız bu durumda `null`dır (payda 0)."""
    created = client.post("/api/v1/players", json={"display_name": "Maçsız"})
    player_id = created.json()["id"]
    badge = _badge(client, player_id, "vision", include_locked=True)
    assert badge["count"] == 0
    assert (badge["tier"], badge["rate"], badge["next_tier_count"]) == (
        None, None, 1,
    )


# ==========================================================================
# stellar_quest — ardışık-3 GÖREVİ, kademeli 7 rozetin HEPSİNDE (bench_2
# deseniyle: kapsam dışı / kazanılmayan maç seriyi 0'a döndürür; GERİ ALINMAZ)
# ==========================================================================
def _mvp_scenario(client, ids, db, sgid, day, win, out_of_scope=False):
    """MVP: takım100 hep kazanır; win=True → P0 en yüksek perf (MVP)."""
    match_id = _ingest(client, ids, sgid, day, winner_team=100)
    if win:
        _set_perf(db, match_id, ids, {**FLAT, "P0": 9.0})
    else:
        _set_perf(db, match_id, ids, {**FLAT, "P0": 1.0, "P1": 9.0})
    return match_id


def _record_scenario(stat):
    def scenario(client, ids, db, sgid, day, win, out_of_scope=False):
        leader = "P0" if win else "P1"
        stats = {n: {stat: 99 if n == leader else 1} for n in NAMES}
        return _ingest(client, ids, sgid, day, stats=stats)

    return scenario


def _cs_per_min_scenario(client, ids, db, sgid, day, win, out_of_scope=False):
    """out_of_scope=True → duration_s NULL: o maçta KİMSE cs_per_min alamaz."""
    if out_of_scope:
        return _ingest(client, ids, sgid, day, duration_s=None)
    leader = "P0" if win else "P1"
    stats = {n: {"cs": 300 if n == leader else 1} for n in NAMES}
    return _ingest(client, ids, sgid, day, duration_s=DURATION_S, stats=stats)


def _role_duel_scenario(client, ids, db, sgid, day, win, out_of_scope=False):
    """out_of_scope=True → TOP'ta P5'i JUNGLE'a kaydırıp P0'ın rolünü 1 slota düşürür."""
    if out_of_scope:
        match_id = _ingest(client, ids, sgid, day, positions={"P5": "JUNGLE"})
        _set_perf(db, match_id, ids, FLAT)
        return match_id
    match_id = _ingest(client, ids, sgid, day)
    if win:
        _set_perf(db, match_id, ids, {**FLAT, "P0": 9.0, "P5": 1.0})
    else:
        _set_perf(db, match_id, ids, {**FLAT, "P0": 1.0, "P5": 9.0})
    return match_id


def _quad_stats(has_damage, has_gold, has_cs):
    """P0 üç metrikte de (damage/gold/cs) TEK BAŞINA lider olsun isteniyorsa 99,
    değilse P8 lider olsun diye 99 alır (P0 kesin dışarıda kalır, eşitlik değil)."""
    def field(has):
        return {
            n: 99 if (has and n == "P0") or (not has and n == "P8") else 1
            for n in NAMES
        }

    damage_vals, gold_vals, cs_vals = (
        field(has_damage), field(has_gold), field(has_cs)
    )
    return {
        n: {
            "damage_to_champs": damage_vals[n],
            "gold": gold_vals[n],
            "cs": cs_vals[n],
        }
        for n in NAMES
    }


def _quad_match(
    client, ids, db, sgid, day, *,
    has_mvp=True, has_damage=True, has_gold=True, has_cs=True,
    duration_s=DURATION_S,
):
    """perfect_quad senaryosu: dört bileşen bağımsız açılıp kapatılabilir."""
    match_id = _ingest(
        client, ids, sgid, day, winner_team=100, duration_s=duration_s,
        stats=_quad_stats(has_damage, has_gold, has_cs),
    )
    if has_mvp:
        _set_perf(db, match_id, ids, {**FLAT, "P0": 9.0})
    else:
        _set_perf(db, match_id, ids, {**FLAT, "P0": 1.0, "P1": 9.0})
    return match_id


def _perfect_quad_scenario(client, ids, db, sgid, day, win, out_of_scope=False):
    """TIER_SCENARIOS ile uyumlu imza: win yalnız MVP bileşenini değiştirir
    (diğer üçü hep P0'da), out_of_scope duration_s'i NULL yapar."""
    if out_of_scope:
        return _quad_match(client, ids, db, sgid, day, duration_s=None)
    return _quad_match(client, ids, db, sgid, day, has_mvp=win)


TIER_SCENARIOS = {
    "mvp": _mvp_scenario,
    "vision": _record_scenario("vision_score"),
    "damage": _record_scenario("damage_to_champs"),
    "gold": _record_scenario("gold"),
    "cs_per_min": _cs_per_min_scenario,
    "role_duel": _role_duel_scenario,
    "perfect_quad": _perfect_quad_scenario,
}


@pytest.mark.parametrize("key", list(TIER_SCENARIOS))
def test_stellar_quest_best_tracks_the_longest_consecutive_run(client, ids, db, key):
    """Kazan/kazan/KAYIP/kazan/kazan/kazan → en uzun ardışık seri 3 (son üçü)."""
    scenario = TIER_SCENARIOS[key]
    pattern = [True, True, False, True, True, True]
    for i, win in enumerate(pattern):
        scenario(client, ids, db, f"sq-{key}-{i}", _day(i + 1), win)
    badge = _by_key(client, ids["P0"])[key]
    assert badge["stellar_quest"] == {"target": 3, "best": 3, "met": True}


@pytest.mark.parametrize("key", list(TIER_SCENARIOS))
def test_stellar_quest_not_met_when_no_run_reaches_three(client, ids, db, key):
    """Hiçbir ardışık seri 3'e ulaşmıyor (en uzunu 2) → met False."""
    scenario = TIER_SCENARIOS[key]
    pattern = [True, True, False, True, True, False]
    for i, win in enumerate(pattern):
        scenario(client, ids, db, f"sn-{key}-{i}", _day(i + 1), win)
    badge = _by_key(client, ids["P0"])[key]
    assert badge["stellar_quest"]["best"] == 2
    assert badge["stellar_quest"]["met"] is False


def test_stellar_quest_broken_by_out_of_scope_match_cs_per_min(client, ids):
    """cs_per_min: duration_s NULL o maçta KİMSEYİ ödüllendirmez → seriyi kırar."""
    _cs_per_min_scenario(client, ids, None, "cs-a-0", _day(1), True)
    _cs_per_min_scenario(client, ids, None, "cs-a-1", _day(2), True)
    _cs_per_min_scenario(client, ids, None, "cs-a-oos", _day(3), True, out_of_scope=True)
    _cs_per_min_scenario(client, ids, None, "cs-a-3", _day(4), True)
    badge = _by_key(client, ids["P0"])["cs_per_min"]
    assert badge["stellar_quest"] == {"target": 3, "best": 2, "met": False}


def test_stellar_quest_broken_by_out_of_scope_match_role_duel(client, ids, db):
    """role_duel: rolde tam 2 slot yoksa o maç DEĞERLENDİRİLMEZ → seriyi kırar."""
    _role_duel_scenario(client, ids, db, "rd-a-0", _day(1), True)
    _role_duel_scenario(client, ids, db, "rd-a-1", _day(2), True)
    _role_duel_scenario(client, ids, db, "rd-a-oos", _day(3), True, out_of_scope=True)
    _role_duel_scenario(client, ids, db, "rd-a-3", _day(4), True)
    badge = _by_key(client, ids["P0"])["role_duel"]
    assert badge["stellar_quest"] == {"target": 3, "best": 2, "met": False}


def test_stellar_quest_broken_by_out_of_scope_match_perfect_quad(client, ids, db):
    """perfect_quad: dört bileşenden biri (cs_per_min→duration_s) hesaplanamazsa
    o maç bu rozetin dışındadır ve seriyi kırar (mvp/role_duel'le aynı desen)."""
    _quad_match(client, ids, db, "pq-b0", _day(1))
    _quad_match(client, ids, db, "pq-b1", _day(2))
    _quad_match(client, ids, db, "pq-boos", _day(3), duration_s=None)
    _quad_match(client, ids, db, "pq-b3", _day(4))
    badge = _by_key(client, ids["P0"])["perfect_quad"]
    assert badge["stellar_quest"] == {"target": 3, "best": 2, "met": False}


def test_stellar_requires_diamond_count_without_quest_stays_diamond_via_api(
    client, ids
):
    """12 galibiyet ama HİÇ ardışık 3 yok → `diamond` kalır (üstteki API testinin
    stellar_quest'e odaklı hâli — `_tier` birim testleriyle çapraz doğrulanır)."""
    pattern = (["P0", "P1"] * 12)[:24]
    _vision_series(client, ids, "dqs", pattern)
    badge = _by_key(client, ids["P0"])["vision"]
    assert badge["count"] == 12
    assert badge["tier"] == "diamond"
    assert badge["stellar_quest"] == {"target": 3, "best": 1, "met": False}


# ==========================================================================
# perfect_quad — "Kusursuz Dörtlük" (ID 28, NADİR ölçek, Teoman 2026-08-19)
# ==========================================================================
def test_perfect_quad_requires_all_four_components(client, ids, db):
    """Dört bileşenden BİRİ eksikse rozet yok; hepsi varsa 1 rozet."""
    _quad_match(client, ids, db, "pq-nomvp", _day(1), has_mvp=False)
    _quad_match(client, ids, db, "pq-nodmg", _day(2), has_damage=False)
    _quad_match(client, ids, db, "pq-nogold", _day(3), has_gold=False)
    _quad_match(client, ids, db, "pq-nocs", _day(4), has_cs=False)
    assert _count(client, ids["P0"], "perfect_quad") == 0

    m5 = _quad_match(client, ids, db, "pq-all", _day(5))
    badge = _by_key(client, ids["P0"])["perfect_quad"]
    assert badge["count"] == 1
    assert badge["last_match_id"] == m5


def test_perfect_quad_is_repeatable_and_has_no_best_value(client, ids, db):
    """Tekrarlanabilir; kendi başına ölçülebilir bir değeri YOKTUR (narrative sınıfı)."""
    m1 = _quad_match(client, ids, db, "pq-r1", _day(1))
    m2 = _quad_match(client, ids, db, "pq-r2", _day(2))
    badge = _by_key(client, ids["P0"])["perfect_quad"]
    assert badge["count"] == 2
    assert badge["last_match_id"] == m2
    assert (badge["best_match_id"], badge["best_value"]) == (None, None)


def test_perfect_quad_excluded_when_cs_per_min_out_of_scope(client, ids, db):
    """cs_per_min'in duration_s şartı birebir geçerli: duration NULL → quad da yok."""
    _quad_match(client, ids, db, "pq-oos", _day(1), duration_s=None)
    assert _count(client, ids["P0"], "perfect_quad") == 0


def test_perfect_quad_mvp_component_follows_the_mvp_tiebreak_not_raw_perf(
    client, ids, db
):
    """MVP tekliği: perf EŞİT olsa da mvp'nin KENDİ kırılımı (kills) devreye
    girer ve TEK bir kazanan belirler; quad da aynı kazananı izler."""
    stats = _quad_stats(True, True, True)
    stats["P0"]["kills"] = 10
    stats["P1"]["kills"] = 1
    match_id = _ingest(client, ids, "pq-tie", _day(1), winner_team=100, stats=stats)
    _set_perf(db, match_id, ids, {**FLAT, "P0": 9.0, "P1": 9.0})  # perf eşit
    assert _count(client, ids["P0"], "mvp") == 1
    assert _count(client, ids["P0"], "perfect_quad") == 1
    assert _count(client, ids["P1"], "mvp") == 0
    assert _count(client, ids["P1"], "perfect_quad") == 0


def test_perfect_quad_uses_the_rare_tier_scale(client, ids, db):
    """NADİR ölçek: 4 ardışık Kusursuz Dörtlük → platinum (4), görev de dolu."""
    matches = [
        _quad_match(client, ids, db, f"pq-t{i}", _day(i + 1)) for i in range(4)
    ]
    badge = _by_key(client, ids["P0"])["perfect_quad"]
    assert badge["count"] == 4
    assert badge["tier"] == "platinum"
    assert badge["next_tier_count"] == 6
    assert badge["stellar_quest"] == {"target": 3, "best": 4, "met": True}
    assert badge["last_match_id"] == matches[-1]


def test_perfect_quad_diamond_without_quest_via_api(client, ids, db):
    """6 Kusursuz Dörtlük ama HİÇ 3-ardışık yok (araya MVP'siz maç girer) →
    NADİR ölçekte diamond kalır, stellar olmaz.

    Aradaki maç düz `_ingest` DEĞİLDİR: tüm katılımcılar BASE_STATS'ta EŞİT
    olduğundan mvp'nin kendi kırılımı (kills eşit → ... → player_id küçük) P0'ı
    yine MVP yapardı (quad'ı YANLIŞLIKLA tekrar tetikler) — bu yüzden araya
    `has_mvp=False` konur (yalnız MVP bileşenini kırar, `_perfect_quad_scenario`
    ile aynı desen).
    """
    for i in range(6):
        _quad_match(client, ids, db, f"pq-alt-quad-{i}", _day(2 * i + 1))
        _quad_match(
            client, ids, db, f"pq-alt-filler-{i}", _day(2 * i + 2), has_mvp=False
        )
    badge = _by_key(client, ids["P0"])["perfect_quad"]
    assert badge["count"] == 6
    assert badge["tier"] == "diamond"
    assert badge["stellar_quest"]["met"] is False


def test_perfect_quad_diamond_and_quest_together_yields_stellar(client, ids, db):
    """6 ardışık Kusursuz Dörtlük (ara YOK) → sayaç elmasta VE görev dolu → stellar."""
    for i in range(6):
        _quad_match(client, ids, db, f"pq-stellar-{i}", _day(i + 1))
    badge = _by_key(client, ids["P0"])["perfect_quad"]
    assert badge["count"] == 6
    assert badge["tier"] == "stellar"
    assert badge["stellar_quest"] == {"target": 3, "best": 6, "met": True}


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
    assert [b["id"] for b in body["badges"]] == list(range(1, 29))
    assert [b["key"] for b in body["badges"]] == list(BADGE_KEYS)
    first = body["badges"][0]
    assert first == {
        "id": 1, "key": "mvp", "class": "record", "source": "valid",
        "tiered": True, "tier_scale": "standard", "one_time": False,
        "holders": 0, "holders_pct": None,
    }
    last = body["badges"][-1]
    assert last == {
        "id": 28, "key": "perfect_quad", "class": "narrative", "source": "valid",
        "tiered": True, "tier_scale": "rare", "one_time": False,
        "holders": 0, "holders_pct": None,
    }
    classes = {b["class"] for b in body["badges"]}
    assert classes <= {
        "record", "role", "personal", "narrative", "streak", "relational",
        "identity", "milestone", "roulette",
    }
    assert {b["source"] for b in body["badges"]} == {"valid", "roulette"}
    # tier_scale yalnız kademeli rozetlerde dolu.
    for b in body["badges"]:
        if b["tiered"]:
            assert b["tier_scale"] in ("standard", "rare")
        else:
            assert b["tier_scale"] is None


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
