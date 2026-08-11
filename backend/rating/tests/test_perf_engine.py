"""`openskill-pl-perf-v1` performans katmanı testleri.

Contract (docs/rating_contract.md) test yükümlülükleri:
- Nötr durum: tüm statlar null → taban modelle birebir aynı.
- Yön garantisi: kazanan üye asla kaybetmez, kaybeden üye asla kazanmaz.
- Bant garantisi: etkin çarpan hiçbir koşulda [0.7, 1.3] dışına çıkmaz.
- Determinizm: aynı girdiyle iki çağrı aynı sonucu verir.
- Bileşen bazlı: tek bileşenli senaryolar doğru ortalanır.
- Sınır: deaths=0, takım toplamı 0, duration_s null/0.
Ek: iyi performanslı kazanan daha çok kazanır; iyi performanslı kaybeden
daha az kaybeder.
"""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from rating import Engine, ParticipantStats, Rating
from rating.performance import PerfParams, compute_multipliers

PERF_VERSION = "openskill-pl-perf-v1"
BASE_VERSION = "openskill-pl-v1"

# Contract'ta bu version'a dondurulmuş sabitler (testte bağımsız kopya).
PERF = PerfParams(alpha=0.5, cap=0.3, ratio_min=0.5, ratio_max=2.0, share_baseline=0.2)

rating_st = st.builds(
    Rating,
    mu=st.floats(min_value=0.0, max_value=50.0, allow_nan=False),
    sigma=st.floats(min_value=0.5, max_value=25.0 / 3.0, allow_nan=False),
)
team_st = st.lists(rating_st, min_size=5, max_size=5)

opt_small = st.one_of(st.none(), st.integers(min_value=0, max_value=50))
opt_big = st.one_of(st.none(), st.integers(min_value=0, max_value=100_000))
participant_st = st.one_of(
    st.none(),
    st.builds(
        ParticipantStats,
        kills=opt_small,
        deaths=opt_small,
        assists=opt_small,
        gold=opt_big,
        cs=opt_big,
        damage_to_champs=opt_big,
        vision_score=opt_small,
    ),
)
stats_team_st = st.lists(participant_st, min_size=5, max_size=5)
duration_st = st.one_of(st.none(), st.integers(min_value=0, max_value=7200))


def _default_teams():
    e = Engine(PERF_VERSION)
    return [e.default_rating() for _ in range(5)], [
        e.default_rating() for _ in range(5)
    ]


# --- Nötr durum -------------------------------------------------------------


def test_no_stats_identical_to_base():
    team100, team200 = _default_teams()
    perf = Engine(PERF_VERSION).update(team100, team200, winner=100)
    base = Engine(BASE_VERSION).update(team100, team200, winner=100)
    assert perf == base


@pytest.mark.parametrize(
    "s100,s200",
    [
        ([None] * 5, [None] * 5),
        ([ParticipantStats()] * 5, [ParticipantStats()] * 5),
        ([None] * 5, None),
        (None, [ParticipantStats()] * 5),
    ],
)
def test_all_null_stats_identical_to_base(s100, s200):
    team100, team200 = _default_teams()
    perf = Engine(PERF_VERSION).update(
        team100, team200, winner=200, stats100=s100, stats200=s200, duration_s=1800
    )
    base = Engine(BASE_VERSION).update(team100, team200, winner=200)
    assert perf == base


def test_v1_ignores_stats():
    """Taban version'a stats geçilse bile davranış bugünküyle birebir aynı."""
    team100, team200 = _default_teams()
    s = [ParticipantStats(kills=10, deaths=0, assists=5, gold=15000)] * 5
    with_stats = Engine(BASE_VERSION).update(
        team100, team200, winner=100, stats100=s, stats200=s, duration_s=1800
    )
    without = Engine(BASE_VERSION).update(team100, team200, winner=100)
    assert with_stats == without


def test_single_computable_participant_is_neutral():
    """Tek katılımcı hesaplanabilirse ortalama kendisidir → oran 1 → nötr."""
    team100, team200 = _default_teams()
    s100 = [ParticipantStats(vision_score=30)] + [None] * 4
    perf = Engine(PERF_VERSION).update(
        team100, team200, winner=100, stats100=s100, stats200=None
    )
    base = Engine(BASE_VERSION).update(team100, team200, winner=100)
    assert perf == base


# --- Yön ve sigma garantileri ----------------------------------------------


@given(
    team100=team_st,
    team200=team_st,
    winner=st.sampled_from([100, 200]),
    s100=stats_team_st,
    s200=stats_team_st,
    duration_s=duration_st,
)
@settings(max_examples=200, deadline=None)
def test_winner_always_gains_loser_always_loses(
    team100, team200, winner, s100, s200, duration_s
):
    new100, new200 = Engine(PERF_VERSION).update(
        team100, team200, winner, stats100=s100, stats200=s200, duration_s=duration_s
    )
    winners, new_winners = (team100, new100) if winner == 100 else (team200, new200)
    losers, new_losers = (team200, new200) if winner == 100 else (team100, new100)
    for old, new in zip(winners, new_winners):
        assert new.mu > old.mu
    for old, new in zip(losers, new_losers):
        assert new.mu < old.mu


@given(
    team100=team_st,
    team200=team_st,
    winner=st.sampled_from([100, 200]),
    s100=stats_team_st,
    s200=stats_team_st,
    duration_s=duration_st,
)
@settings(max_examples=100, deadline=None)
def test_sigma_taken_from_base_model(team100, team200, winner, s100, s200, duration_s):
    perf100, perf200 = Engine(PERF_VERSION).update(
        team100, team200, winner, stats100=s100, stats200=s200, duration_s=duration_s
    )
    base100, base200 = Engine(BASE_VERSION).update(team100, team200, winner)
    for p, b in zip(perf100 + perf200, base100 + base200):
        assert p.sigma == b.sigma


# --- Bant garantisi ---------------------------------------------------------


@given(s100=stats_team_st, s200=stats_team_st, duration_s=duration_st)
@settings(max_examples=300, deadline=None)
def test_multiplier_band(s100, s200, duration_s):
    m100, m200 = compute_multipliers(s100, s200, duration_s, PERF)
    for m in m100 + m200:
        assert 0.7 <= m <= 1.3


def test_multiplier_band_extreme_stats():
    """Uç statlarla dahi çarpan tam sınırda kırpılır."""
    hero = ParticipantStats(
        kills=50, deaths=0, assists=50, gold=99999, cs=99999,
        damage_to_champs=99999, vision_score=50,
    )
    feeder = ParticipantStats(
        kills=0, deaths=50, assists=0, gold=1, cs=0,
        damage_to_champs=1, vision_score=0,
    )
    s100 = [hero, feeder, feeder, feeder, feeder]
    m100, _ = compute_multipliers(s100, [None] * 5, 1800, PERF)
    # Üst uç: perf=2.0 → ham 1.5 → 1.3'e kırpılır.
    assert m100[0] == pytest.approx(1.3)
    # Alt uç: perf=0.5 → ham 1 + 0.5*(0.5-1) = 0.75 (RATIO_MIN=0.5 ile
    # ulaşılabilen minimum; 0.7 alt bandı yalnızca güvenlik kırpmasıdır).
    assert m100[1] == pytest.approx(0.75)


# --- Determinizm ------------------------------------------------------------


@given(
    team100=team_st,
    team200=team_st,
    winner=st.sampled_from([100, 200]),
    s100=stats_team_st,
    s200=stats_team_st,
    duration_s=duration_st,
)
@settings(max_examples=100, deadline=None)
def test_determinism(team100, team200, winner, s100, s200, duration_s):
    a = Engine(PERF_VERSION).update(
        team100, team200, winner, stats100=s100, stats200=s200, duration_s=duration_s
    )
    b = Engine(PERF_VERSION).update(
        team100, team200, winner, stats100=s100, stats200=s200, duration_s=duration_s
    )
    assert a == b


# --- Tek bileşenli senaryolar ----------------------------------------------


def test_single_component_kda():
    """Yalnız KDA hesaplanabilir: oran maç ortalamasına göre, formül birebir."""
    s100 = [ParticipantStats(kills=8, deaths=1, assists=0)] + [
        ParticipantStats(kills=2, deaths=1, assists=0)
    ] * 4
    s200 = [ParticipantStats(kills=2, deaths=1, assists=0)] * 5
    # KDA: [8, 2x9] → ortalama 2.6; 8/2.6=3.08 → kırp 2.0 → çarpan 1.5 → kırp 1.3
    # 2/2.6=0.76923 → çarpan 1 + 0.5*(0.76923-1) = 0.884615
    m100, m200 = compute_multipliers(s100, s200, None, PERF)
    assert m100[0] == pytest.approx(1.3)
    for m in m100[1:] + m200:
        assert m == pytest.approx(1.0 + 0.5 * (2.0 / 2.6 - 1.0))


def test_single_component_gold_share():
    """Yalnız gold payı hesaplanabilir: pay / SHARE_BASELINE, takım içi."""
    s100 = [
        ParticipantStats(gold=10000),
        ParticipantStats(gold=2500),
        ParticipantStats(gold=2500),
        ParticipantStats(gold=2500),
        ParticipantStats(gold=2500),
    ]
    m100, m200 = compute_multipliers(s100, [None] * 5, None, PERF)
    # p0: pay 0.5 → 0.5/0.2=2.5 → kırp 2.0 → çarpan 1.5 → kırp 1.3
    assert m100[0] == pytest.approx(1.3)
    # diğerleri: pay 0.125 → 0.625 → çarpan 1 + 0.5*(0.625-1) = 0.8125
    for m in m100[1:]:
        assert m == pytest.approx(0.8125)
    # Statsız takım nötr kalır.
    for m in m200:
        assert m == pytest.approx(1.0)


def test_single_component_cs_per_min():
    """Yalnız CS/dk hesaplanabilir; duration_s zorunlu."""
    s100 = [ParticipantStats(cs=300)] + [ParticipantStats(cs=100)] * 4
    s200 = [ParticipantStats(cs=100)] * 5
    # CS/dk (1800s=30dk): [10, 3.33x9] → ort 4.0; 10/4=2.5 → kırp 2.0 → 1.3
    m100, m200 = compute_multipliers(s100, s200, 1800, PERF)
    assert m100[0] == pytest.approx(1.3)
    ratio_rest = (100 / 30.0) / 4.0
    for m in m100[1:] + m200:
        assert m == pytest.approx(1.0 + 0.5 * (ratio_rest - 1.0))


def test_update_applies_multiplier_to_mu_delta():
    """Uçtan uca: mu deltası kazananlarda carpan, kaybedenlerde (2-carpan)."""
    team100, team200 = _default_teams()
    s100 = [ParticipantStats(kills=8, deaths=1, assists=0)] + [
        ParticipantStats(kills=2, deaths=1, assists=0)
    ] * 4
    s200 = [ParticipantStats(kills=8, deaths=1, assists=0)] + [
        ParticipantStats(kills=2, deaths=1, assists=0)
    ] * 4
    m100, m200 = compute_multipliers(s100, s200, None, PERF)
    base100, base200 = Engine(BASE_VERSION).update(team100, team200, winner=100)
    perf100, perf200 = Engine(PERF_VERSION).update(
        team100, team200, winner=100, stats100=s100, stats200=s200
    )
    for old, base, perf, m in zip(team100, base100, perf100, m100):
        assert perf.mu - old.mu == pytest.approx((base.mu - old.mu) * m)
        assert perf.sigma == base.sigma
    for old, base, perf, m in zip(team200, base200, perf200, m200):
        assert perf.mu - old.mu == pytest.approx((base.mu - old.mu) * (2.0 - m))
        assert perf.sigma == base.sigma


# --- Sınır durumlar ---------------------------------------------------------


def test_deaths_zero_uses_max_one():
    """deaths=0 → payda max(1, deaths) = 1; sıfıra bölme yok."""
    s100 = [
        ParticipantStats(kills=3, deaths=0, assists=0),  # KDA = 3/1 = 3
        ParticipantStats(kills=1, deaths=1, assists=0),  # KDA = 1
        None,
        None,
        None,
    ]
    m100, _ = compute_multipliers(s100, [None] * 5, None, PERF)
    # Ortalama (3+1)/2 = 2 → oranlar 1.5 ve 0.5 → çarpanlar 1.25 ve 0.75
    assert m100[0] == pytest.approx(1.25)
    assert m100[1] == pytest.approx(0.75)
    for m in m100[2:]:
        assert m == pytest.approx(1.0)


def test_team_total_zero_skips_share_components():
    """Takım toplamı 0 (gold/hasar) → bileşen atlanır → nötr."""
    s100 = [ParticipantStats(gold=0, damage_to_champs=0)] * 5
    m100, m200 = compute_multipliers(s100, [None] * 5, None, PERF)
    for m in m100 + m200:
        assert m == pytest.approx(1.0)
    # Uçtan uca da taban modelle birebir aynı olmalı.
    team100, team200 = _default_teams()
    perf = Engine(PERF_VERSION).update(
        team100, team200, winner=100, stats100=s100, stats200=None
    )
    base = Engine(BASE_VERSION).update(team100, team200, winner=100)
    assert perf == base


@pytest.mark.parametrize("duration_s", [None, 0])
def test_duration_null_or_zero_skips_cs(duration_s):
    """duration_s null/0 → CS/dk hesaplanamaz → nötr."""
    s100 = [ParticipantStats(cs=250)] * 5
    m100, _ = compute_multipliers(s100, [None] * 5, duration_s, PERF)
    for m in m100:
        assert m == pytest.approx(1.0)
    team100, team200 = _default_teams()
    perf = Engine(PERF_VERSION).update(
        team100, team200, winner=100, stats100=s100, duration_s=duration_s
    )
    base = Engine(BASE_VERSION).update(team100, team200, winner=100)
    assert perf == base


def test_match_mean_zero_skips_component():
    """Maç ortalaması 0 (herkesin vizyonu 0) → bileşen atlanır → nötr."""
    s100 = [ParticipantStats(vision_score=0)] * 5
    s200 = [ParticipantStats(vision_score=0)] * 5
    m100, m200 = compute_multipliers(s100, s200, None, PERF)
    for m in m100 + m200:
        assert m == pytest.approx(1.0)


def test_stats_length_validated():
    team100, team200 = _default_teams()
    e = Engine(PERF_VERSION)
    with pytest.raises(ValueError):
        e.update(team100, team200, winner=100, stats100=[None] * 4)
    with pytest.raises(ValueError):
        e.update(team100, team200, winner=100, stats200=[None] * 6)


# --- Göreli kazanç/kayıp ----------------------------------------------------


def test_better_winner_gains_more_and_better_loser_loses_less():
    team100, team200 = _default_teams()
    good = ParticipantStats(kills=8, deaths=1, assists=0)
    bad = ParticipantStats(kills=2, deaths=1, assists=0)
    s100 = [good, bad, bad, bad, bad]
    s200 = [good, bad, bad, bad, bad]
    new100, new200 = Engine(PERF_VERSION).update(
        team100, team200, winner=100, stats100=s100, stats200=s200
    )
    # Kazananlar: iyi performans daha çok kazanır (eşit başlangıçtan).
    assert new100[0].mu > new100[1].mu > 25.0
    # Kaybedenler: iyi performans daha az kaybeder; ama yine de kaybeder.
    assert 25.0 > new200[0].mu > new200[1].mu


# --- Version'lar arası ortak davranış ---------------------------------------


def test_default_rating_and_predict_win_same_across_versions():
    base, perf = Engine(BASE_VERSION), Engine(PERF_VERSION)
    assert base.default_rating() == perf.default_rating()
    strong = [Rating(mu=30.0, sigma=5.0)] * 5
    weak = [Rating(mu=20.0, sigma=5.0)] * 5
    assert base.predict_win(strong, weak) == perf.predict_win(strong, weak)
