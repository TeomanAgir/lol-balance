"""`openskill-pl-blend50-v1` harman engine testleri.

Contract (docs/rating_contract.md, "Test yükümlülükleri (blend50)"):
- mu/sigma güncellemeleri `openskill-pl-v1` ile bit-bit aynı (çarpan yok kanıtı).
- perf_scores determinizmi ve perf-v1 skor fonksiyonuyla birebir aynılık.
- Maçsız oyuncu: P_avg=1 → default rating'de mu_eff=25, score=0.
- score monotonluğu: aynı mu/sigma'da P_avg arttıkça score artar;
  P_avg uçlarında mu_eff sapması ±10 bandında.
- effective() harman olmayan version'da ValueError.
"""
import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from rating import EffectiveRating, Engine, ParticipantStats, Rating
from rating.performance import PerfParams, compute_multipliers

BLEND_VERSION = "openskill-pl-blend50-v1"
PERF_VERSION = "openskill-pl-perf-v1"
BASE_VERSION = "openskill-pl-v1"

# Contract'ta blend50'ye dondurulmuş sabitler (testte bağımsız kopya).
MU_0, K, W = 25.0, 20.0, 0.5
# perf-v1 sabitleri (çarpan karşılaştırması için bağımsız kopya).
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

# Belirgin biçimde nötr OLMAYAN bir stats seti (çarpan-yokluğu kanıtı için).
HERO = ParticipantStats(
    kills=15, deaths=1, assists=10, gold=18000, cs=250,
    damage_to_champs=40000, vision_score=45,
)
FILLER = ParticipantStats(
    kills=2, deaths=6, assists=3, gold=8000, cs=110,
    damage_to_champs=9000, vision_score=12,
)
STATS_100 = [HERO, FILLER, FILLER, FILLER, FILLER]
STATS_200 = [FILLER] * 5


def _default_teams():
    e = Engine(BLEND_VERSION)
    return [e.default_rating() for _ in range(5)], [
        e.default_rating() for _ in range(5)
    ]


# --- 1) update: v1 ile bit-bit aynı (çarpan yok kanıtı) ----------------------


@given(
    team100=team_st,
    team200=team_st,
    winner=st.sampled_from([100, 200]),
    s100=stats_team_st,
    s200=stats_team_st,
    duration_s=duration_st,
)
@settings(max_examples=150, deadline=None)
def test_blend_update_bitwise_equal_to_v1(
    team100, team200, winner, s100, s200, duration_s
):
    blend = Engine(BLEND_VERSION).update(
        team100, team200, winner, stats100=s100, stats200=s200, duration_s=duration_s
    )
    base = Engine(BASE_VERSION).update(team100, team200, winner)
    # Rating frozen dataclass'ında == alan bazlı float eşitliğidir → bit-bit.
    assert blend == base


def test_blend_update_with_extreme_stats_equal_to_v1():
    """Nötr OLMAYAN statlarla dahi blend50 update'i v1 ile birebir aynıdır;

    aynı statlar perf-v1'de sonucu DEĞİŞTİRİR (çarpanın gerçekten devre dışı
    olduğunun pozitif kanıtı).
    """
    team100, team200 = _default_teams()
    kwargs = dict(stats100=STATS_100, stats200=STATS_200, duration_s=1800)
    blend = Engine(BLEND_VERSION).update(team100, team200, winner=100, **kwargs)
    base = Engine(BASE_VERSION).update(team100, team200, winner=100)
    perf = Engine(PERF_VERSION).update(team100, team200, winner=100, **kwargs)
    assert blend == base
    assert blend != perf  # aynı statlar perf-v1'de fark yaratıyor


def test_blend_update_without_stats_equal_to_v1():
    team100, team200 = _default_teams()
    blend = Engine(BLEND_VERSION).update(team100, team200, winner=200)
    base = Engine(BASE_VERSION).update(team100, team200, winner=200)
    assert blend == base


# --- 2) perf_scores: determinizm + perf-v1 skoruyla birebir aynılık ----------


@given(s100=stats_team_st, s200=stats_team_st, duration_s=duration_st)
@settings(max_examples=150, deadline=None)
def test_perf_scores_deterministic_and_version_independent(s100, s200, duration_s):
    a = Engine(BLEND_VERSION).perf_scores(s100, s200, duration_s)
    b = Engine(BLEND_VERSION).perf_scores(s100, s200, duration_s)
    assert a == b
    # Skor tanımı versiyondan bağımsız: her version aynı değeri verir.
    assert a == Engine(BASE_VERSION).perf_scores(s100, s200, duration_s)
    assert a == Engine(PERF_VERSION).perf_scores(s100, s200, duration_s)


@given(s100=stats_team_st, s200=stats_team_st, duration_s=duration_st)
@settings(max_examples=150, deadline=None)
def test_perf_scores_match_perf_v1_multiplier_input(s100, s200, duration_s):
    """perf_scores, perf-v1 çarpanına multiplier'dan ÖNCE giren perf ile

    birebir aynıdır: carpan == clamp(1 + ALPHA*(perf-1), 0.7, 1.3) tam eşitlik.
    """
    p100, p200 = Engine(BLEND_VERSION).perf_scores(s100, s200, duration_s)
    m100, m200 = compute_multipliers(s100, s200, duration_s, PERF)
    for p, m in zip(p100 + p200, m100 + m200):
        assert 0.5 <= p <= 2.0
        expected = max(0.7, min(1.3, 1.0 + PERF.alpha * (p - 1.0)))
        assert m == expected  # bit-bit


def test_perf_scores_neutral_and_none_team():
    p100, p200 = Engine(BLEND_VERSION).perf_scores([None] * 5, None, None)
    assert p100 == [1.0] * 5
    assert p200 == [1.0] * 5


def test_perf_scores_length_validated():
    e = Engine(BLEND_VERSION)
    with pytest.raises(ValueError):
        e.perf_scores([None] * 4, [None] * 5, None)
    with pytest.raises(ValueError):
        e.perf_scores([None] * 5, [None] * 6, None)


# --- 3) Maçsız oyuncu: P_avg=1 → nötr --------------------------------------


def test_effective_neutral_p_avg_default_rating():
    e = Engine(BLEND_VERSION)
    r = e.default_rating()  # mu=25, sigma=25/3
    eff = e.effective(r.mu, r.sigma, p_avg=1.0)
    assert isinstance(eff, EffectiveRating)
    assert eff.mu_eff == 25.0
    assert eff.sigma == r.sigma
    assert eff.score == pytest.approx(0.0, abs=1e-12)


@given(
    mu=st.floats(min_value=0.0, max_value=50.0, allow_nan=False),
    sigma=st.floats(min_value=0.5, max_value=25.0 / 3.0, allow_nan=False),
)
@settings(max_examples=100, deadline=None)
def test_effective_neutral_p_avg_is_w_weighted_blend(mu, sigma):
    """p_avg=1'de perf terimi W*MU_0'a düşer: mu_eff = (1-W)*mu + W*MU_0."""
    eff = Engine(BLEND_VERSION).effective(mu, sigma, p_avg=1.0)
    assert eff.mu_eff == pytest.approx((1 - W) * mu + W * MU_0)
    assert eff.score == pytest.approx(eff.mu_eff - 3.0 * sigma)


# --- 4) Monotonluk + uç sapma bandı -----------------------------------------


@given(
    mu=st.floats(min_value=0.0, max_value=50.0, allow_nan=False),
    sigma=st.floats(min_value=0.5, max_value=25.0 / 3.0, allow_nan=False),
)
@settings(max_examples=100, deadline=None)
def test_score_monotonic_in_p_avg(mu, sigma):
    e = Engine(BLEND_VERSION)
    p_avgs = [0.5, 0.8, 1.0, 1.2, 1.5, 2.0]
    scores = [e.effective(mu, sigma, p).score for p in p_avgs]
    for lo, hi in zip(scores, scores[1:]):
        assert lo < hi


def test_mu_eff_deviation_bounded_at_p_avg_extremes():
    """Contract: perf terimi mu_eff'e en fazla ±10 katar.

    Sapma (p_avg=1 nötrüne göre) = W*K*(p_avg-1):
    p_avg=2.0 → +10 (tavan), p_avg=0.5 → -5 (RATIO_MIN=0.5 nedeniyle taban).
    """
    e = Engine(BLEND_VERSION)
    for mu, sigma in [(25.0, 25.0 / 3.0), (32.5, 4.0), (18.0, 6.0)]:
        neutral = e.effective(mu, sigma, 1.0).mu_eff
        hi = e.effective(mu, sigma, 2.0).mu_eff
        lo = e.effective(mu, sigma, 0.5).mu_eff
        assert hi - neutral == pytest.approx(10.0)
        assert lo - neutral == pytest.approx(-5.0)
        # [0.5, 2.0] aralığının tamamında sapma ±10 bandında kalır.
        for p in [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]:
            assert abs(e.effective(mu, sigma, p).mu_eff - neutral) <= 10.0 + 1e-9


# --- 5) effective() yalnız harman version'ında ------------------------------


@pytest.mark.parametrize("version", [BASE_VERSION, PERF_VERSION])
def test_effective_raises_on_non_blend_version(version):
    e = Engine(version)
    with pytest.raises(ValueError):
        e.effective(25.0, 25.0 / 3.0, 1.0)


# --- Ek: version'lar arası ortak davranış ------------------------------------


def test_blend_version_registered_and_common_behavior():
    base, blend = Engine(BASE_VERSION), Engine(BLEND_VERSION)
    assert blend.version == BLEND_VERSION
    assert base.default_rating() == blend.default_rating()
    strong = [Rating(mu=30.0, sigma=5.0)] * 5
    weak = [Rating(mu=20.0, sigma=5.0)] * 5
    assert base.predict_win(strong, weak) == blend.predict_win(strong, weak)


def test_effective_usable_for_predict_win_direction():
    """P_avg farkı, (mu_eff, sigma) ile çağrılan predict_win'i beklenen yönde

    değiştirir (contract §5: dengeleme mu_eff üzerinden çalışır).
    """
    e = Engine(BLEND_VERSION)
    sigma = 25.0 / 3.0
    highs = [e.effective(25.0, sigma, 1.5) for _ in range(5)]
    lows = [e.effective(25.0, sigma, 0.7) for _ in range(5)]
    team_hi = [Rating(mu=x.mu_eff, sigma=x.sigma) for x in highs]
    team_lo = [Rating(mu=x.mu_eff, sigma=x.sigma) for x in lows]
    assert e.predict_win(team_hi, team_lo) > 0.5
    assert not math.isclose(e.predict_win(team_hi, team_lo), 0.5)
