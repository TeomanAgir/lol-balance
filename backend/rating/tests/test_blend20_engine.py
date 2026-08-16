"""`openskill-pl-blend20-v1` harman engine testleri.

Contract (docs/rating_contract.md, "Test yükümlülükleri (blend20)"):
- mu/sigma güncellemeleri `openskill-pl-v1` (ve blend50) ile bit-bit aynı.
- perf_score fonksiyonu blend50'ninkiyle birebir aynı değerleri üretir.
- Efektif skor bilinen üçlülerde: mu=25, P_avg=1 → mu_eff=25;
  P_avg=1.25 → mu_eff = 0.2*mu + 0.8*30.
- Maçsız oyuncu nötr; score monotonluğu (P_avg arttıkça score artar).
- blend50 testleri değişmeden geçmeye devam eder (test_blend_engine.py).
"""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from rating import EffectiveRating, Engine, ParticipantStats, Rating

BLEND20_VERSION = "openskill-pl-blend20-v1"
BLEND50_VERSION = "openskill-pl-blend50-v1"
BASE_VERSION = "openskill-pl-v1"

# Contract'ta blend20'ye dondurulmuş sabitler (testte bağımsız kopya).
MU_0, K, W = 25.0, 20.0, 0.8

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

# Belirgin biçimde nötr OLMAYAN bir stats seti (çarpan-yokluğu kanıtı için;
# test_blend_engine.py ile aynı kurgu).
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


# --- 1) update: v1 ve blend50 ile bit-bit aynı (çekirdek özdeşliği) ----------


@given(
    team100=team_st,
    team200=team_st,
    winner=st.sampled_from([100, 200]),
    s100=stats_team_st,
    s200=stats_team_st,
    duration_s=duration_st,
)
@settings(max_examples=150, deadline=None)
def test_blend20_update_bitwise_equal_to_v1_and_blend50(
    team100, team200, winner, s100, s200, duration_s
):
    kwargs = dict(stats100=s100, stats200=s200, duration_s=duration_s)
    blend20 = Engine(BLEND20_VERSION).update(team100, team200, winner, **kwargs)
    base = Engine(BASE_VERSION).update(team100, team200, winner)
    blend50 = Engine(BLEND50_VERSION).update(team100, team200, winner, **kwargs)
    # Rating frozen dataclass'ında == alan bazlı float eşitliğidir → bit-bit.
    assert blend20 == base
    assert blend20 == blend50


def test_blend20_update_with_extreme_stats_equal_to_v1():
    """Nötr OLMAYAN statlarla dahi blend20 update'i v1 ile birebir aynıdır
    (çarpanın gerçekten devre dışı olduğunun pozitif kanıtı)."""
    e = Engine(BLEND20_VERSION)
    team100 = [e.default_rating() for _ in range(5)]
    team200 = [e.default_rating() for _ in range(5)]
    blend20 = e.update(
        team100, team200, winner=100,
        stats100=STATS_100, stats200=STATS_200, duration_s=1800,
    )
    base = Engine(BASE_VERSION).update(team100, team200, winner=100)
    assert blend20 == base


# --- 2) perf_scores: blend50 fonksiyonuyla birebir aynılık -------------------


@given(s100=stats_team_st, s200=stats_team_st, duration_s=duration_st)
@settings(max_examples=150, deadline=None)
def test_perf_scores_identical_to_blend50(s100, s200, duration_s):
    a = Engine(BLEND20_VERSION).perf_scores(s100, s200, duration_s)
    b = Engine(BLEND50_VERSION).perf_scores(s100, s200, duration_s)
    assert a == b  # bit-bit
    # Determinizm: aynı girdiyle ikinci çağrı aynı sonucu verir.
    assert a == Engine(BLEND20_VERSION).perf_scores(s100, s200, duration_s)


def test_perf_scores_neutral_and_none_team():
    p100, p200 = Engine(BLEND20_VERSION).perf_scores([None] * 5, None, None)
    assert p100 == [1.0] * 5
    assert p200 == [1.0] * 5


# --- 3) Efektif skor: bilinen üçlüler ----------------------------------------


def test_effective_known_triple_neutral():
    """mu=25, P_avg=1 → mu_eff = 0.2*25 + 0.8*25 = 25 (nötr)."""
    e = Engine(BLEND20_VERSION)
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
def test_effective_known_triple_p_avg_125(mu, sigma):
    """P_avg=1.25 → perf terimi 25 + 20*0.25 = 30: mu_eff = 0.2*mu + 0.8*30."""
    eff = Engine(BLEND20_VERSION).effective(mu, sigma, p_avg=1.25)
    assert eff.mu_eff == pytest.approx(0.2 * mu + 0.8 * 30.0)
    assert eff.score == pytest.approx(eff.mu_eff - 3.0 * sigma)


@given(
    mu=st.floats(min_value=0.0, max_value=50.0, allow_nan=False),
    sigma=st.floats(min_value=0.5, max_value=25.0 / 3.0, allow_nan=False),
    p_avg=st.floats(min_value=0.5, max_value=2.0, allow_nan=False),
)
@settings(max_examples=100, deadline=None)
def test_effective_formula_general(mu, sigma, p_avg):
    """Genel formül: mu_eff = (1-W)*mu + W*(MU_0 + K*(p_avg-1)), W=0.8."""
    eff = Engine(BLEND20_VERSION).effective(mu, sigma, p_avg)
    assert eff.mu_eff == pytest.approx((1 - W) * mu + W * (MU_0 + K * (p_avg - 1.0)))
    assert eff.score == pytest.approx(eff.mu_eff - 3.0 * sigma)


# --- 4) Maçsız oyuncu nötr + score monotonluğu -------------------------------


def test_matchless_player_neutral():
    """Maçsız oyuncu: default rating + P_avg=1 → mu_eff=25, score=0 (nötr;
    blend50 ile aynı nötr nokta)."""
    e20 = Engine(BLEND20_VERSION)
    e50 = Engine(BLEND50_VERSION)
    r = e20.default_rating()
    eff20 = e20.effective(r.mu, r.sigma, p_avg=1.0)
    eff50 = e50.effective(r.mu, r.sigma, p_avg=1.0)
    assert eff20.mu_eff == 25.0
    assert eff20.score == pytest.approx(0.0, abs=1e-12)
    assert eff20 == eff50  # nötr noktada iki version özdeş


@given(
    mu=st.floats(min_value=0.0, max_value=50.0, allow_nan=False),
    sigma=st.floats(min_value=0.5, max_value=25.0 / 3.0, allow_nan=False),
)
@settings(max_examples=100, deadline=None)
def test_score_monotonic_in_p_avg(mu, sigma):
    e = Engine(BLEND20_VERSION)
    p_avgs = [0.5, 0.8, 1.0, 1.2, 1.5, 2.0]
    scores = [e.effective(mu, sigma, p).score for p in p_avgs]
    for lo, hi in zip(scores, scores[1:]):
        assert lo < hi


# --- Ek: version kaydı + blend50'den fark yalnız ağırlıkta -------------------


def test_blend20_version_registered_and_common_behavior():
    base, blend = Engine(BASE_VERSION), Engine(BLEND20_VERSION)
    assert blend.version == BLEND20_VERSION
    assert base.default_rating() == blend.default_rating()
    strong = [Rating(mu=30.0, sigma=5.0)] * 5
    weak = [Rating(mu=20.0, sigma=5.0)] * 5
    assert base.predict_win(strong, weak) == blend.predict_win(strong, weak)


def test_blend20_weight_differs_from_blend50_off_neutral():
    """Aynı (mu, sigma, p_avg) girdisinde (nötr dışında) blend20 performansa
    daha çok ağırlık verir: p_avg>1'de mu_eff daha yüksek, p_avg<1'de daha
    düşük olmalıdır (mu=25 sabitken perf terimi baskındır)."""
    e20, e50 = Engine(BLEND20_VERSION), Engine(BLEND50_VERSION)
    sigma = 25.0 / 3.0
    assert e20.effective(25.0, sigma, 1.5).mu_eff > e50.effective(25.0, sigma, 1.5).mu_eff
    assert e20.effective(25.0, sigma, 0.7).mu_eff < e50.effective(25.0, sigma, 0.7).mu_eff
