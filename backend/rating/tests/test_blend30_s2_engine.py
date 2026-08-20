"""`openskill-pl-blend30-s2-v1` harman engine testleri (AKTİF version).

Contract (docs/rating_contract.md, "Test yükümlülükleri (blend30-s2)"):
- mu/sigma güncellemeleri `openskill-pl-v1` (ve blend20/blend50) ile bit-bit aynı.
- perf_score fonksiyonu öncekilerle birebir aynı değerleri üretir.
- Efektif skor bilinen üçlülerde: mu=25, sigma=25/3, P_avg=1 → mu_eff=25,
  score ≈ 8.33; P_avg=1.25 → mu_eff = 0.3*mu + 0.7*30.
- Maçsız oyuncu nötr (score ≈ 8.33); score monotonluğu (P_avg arttıkça artar).
- Önceki version testleri değişmeden geçer (test_blend20_engine.py,
  test_blend_engine.py, test_perf_engine.py, test_engine.py).
- `ordinal` tanımı DEĞİŞMEZ (mu - 3σ); S=2 yalnız harman score'a girer.
"""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from rating import EffectiveRating, Engine, ParticipantStats, Rating

S2_VERSION = "openskill-pl-blend30-s2-v1"
BLEND20_VERSION = "openskill-pl-blend20-v1"
BLEND50_VERSION = "openskill-pl-blend50-v1"
BASE_VERSION = "openskill-pl-v1"

# Contract'ta blend30-s2'ye dondurulmuş sabitler (testte bağımsız kopya).
MU_0, K, W, S = 25.0, 20.0, 0.70, 2.0

# Nötr noktanın beklenen score'u: 25 - 2*(25/3).
NEUTRAL_SCORE = 25.0 - S * (25.0 / 3.0)

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
# test_blend20_engine.py / test_blend_engine.py ile aynı kurgu).
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


# --- 1) update: v1, blend20 ve blend50 ile bit-bit aynı (çekirdek özdeşliği) --


@given(
    team100=team_st,
    team200=team_st,
    winner=st.sampled_from([100, 200]),
    s100=stats_team_st,
    s200=stats_team_st,
    duration_s=duration_st,
)
@settings(max_examples=150, deadline=None)
def test_s2_update_bitwise_equal_to_v1_blend20_blend50(
    team100, team200, winner, s100, s200, duration_s
):
    kwargs = dict(stats100=s100, stats200=s200, duration_s=duration_s)
    s2 = Engine(S2_VERSION).update(team100, team200, winner, **kwargs)
    base = Engine(BASE_VERSION).update(team100, team200, winner)
    blend20 = Engine(BLEND20_VERSION).update(team100, team200, winner, **kwargs)
    blend50 = Engine(BLEND50_VERSION).update(team100, team200, winner, **kwargs)
    # Rating frozen dataclass'ında == alan bazlı float eşitliğidir → bit-bit.
    assert s2 == base
    assert s2 == blend20
    assert s2 == blend50


def test_s2_update_with_extreme_stats_equal_to_v1():
    """Nötr OLMAYAN statlarla dahi blend30-s2 update'i v1 ile birebir aynıdır
    (çarpanın gerçekten devre dışı olduğunun pozitif kanıtı)."""
    e = Engine(S2_VERSION)
    team100 = [e.default_rating() for _ in range(5)]
    team200 = [e.default_rating() for _ in range(5)]
    s2 = e.update(
        team100, team200, winner=100,
        stats100=STATS_100, stats200=STATS_200, duration_s=1800,
    )
    base = Engine(BASE_VERSION).update(team100, team200, winner=100)
    assert s2 == base


def test_s2_multi_match_history_bitwise_equal_to_blend20():
    """Ardışık maç zincirinde (state taşınarak) mu/sigma geçmişi blend20 ile
    bit-bit aynı kalır — tek maç değil, GEÇMİŞ özdeşliği."""
    s2, b20 = Engine(S2_VERSION), Engine(BLEND20_VERSION)
    t100_a = [s2.default_rating() for _ in range(5)]
    t200_a = [s2.default_rating() for _ in range(5)]
    t100_b, t200_b = list(t100_a), list(t200_a)
    history_a, history_b = [], []
    for i, winner in enumerate([100, 200, 100, 100, 200]):
        kwargs = dict(
            stats100=STATS_100, stats200=STATS_200, duration_s=1500 + 60 * i
        )
        t100_a, t200_a = s2.update(t100_a, t200_a, winner, **kwargs)
        t100_b, t200_b = b20.update(t100_b, t200_b, winner, **kwargs)
        history_a.append((t100_a, t200_a))
        history_b.append((t100_b, t200_b))
    assert history_a == history_b


# --- 2) perf_scores: önceki version'larla birebir aynılık --------------------


@given(s100=stats_team_st, s200=stats_team_st, duration_s=duration_st)
@settings(max_examples=150, deadline=None)
def test_perf_scores_identical_to_blend20_and_blend50(s100, s200, duration_s):
    a = Engine(S2_VERSION).perf_scores(s100, s200, duration_s)
    assert a == Engine(BLEND20_VERSION).perf_scores(s100, s200, duration_s)
    assert a == Engine(BLEND50_VERSION).perf_scores(s100, s200, duration_s)
    # Determinizm: aynı girdiyle ikinci çağrı aynı sonucu verir.
    assert a == Engine(S2_VERSION).perf_scores(s100, s200, duration_s)


def test_perf_scores_neutral_and_none_team():
    p100, p200 = Engine(S2_VERSION).perf_scores([None] * 5, None, None)
    assert p100 == [1.0] * 5
    assert p200 == [1.0] * 5


# --- 3) Efektif skor: bilinen üçlüler ---------------------------------------


def test_effective_known_triple_neutral():
    """mu=25, sigma=25/3, P_avg=1 → mu_eff = 0.3*25 + 0.7*25 = 25,
    score = 25 - 2*(25/3) ≈ 8.33."""
    e = Engine(S2_VERSION)
    r = e.default_rating()  # mu=25, sigma=25/3
    eff = e.effective(r.mu, r.sigma, p_avg=1.0)
    assert isinstance(eff, EffectiveRating)
    assert eff.mu_eff == pytest.approx(25.0)
    assert eff.sigma == r.sigma
    assert eff.score == pytest.approx(8.333333333333334, abs=1e-9)
    assert eff.score == pytest.approx(NEUTRAL_SCORE)


@given(
    mu=st.floats(min_value=0.0, max_value=50.0, allow_nan=False),
    sigma=st.floats(min_value=0.5, max_value=25.0 / 3.0, allow_nan=False),
)
@settings(max_examples=100, deadline=None)
def test_effective_known_triple_p_avg_125(mu, sigma):
    """P_avg=1.25 → perf terimi 25 + 20*0.25 = 30: mu_eff = 0.3*mu + 0.7*30."""
    eff = Engine(S2_VERSION).effective(mu, sigma, p_avg=1.25)
    assert eff.mu_eff == pytest.approx(0.3 * mu + 0.7 * 30.0)
    assert eff.score == pytest.approx(eff.mu_eff - 2.0 * sigma)


@given(
    mu=st.floats(min_value=0.0, max_value=50.0, allow_nan=False),
    sigma=st.floats(min_value=0.5, max_value=25.0 / 3.0, allow_nan=False),
    p_avg=st.floats(min_value=0.5, max_value=2.0, allow_nan=False),
)
@settings(max_examples=100, deadline=None)
def test_effective_formula_general(mu, sigma, p_avg):
    """Genel formül: mu_eff = (1-W)*mu + W*(MU_0 + K*(p_avg-1)), W=0.70;
    score = mu_eff - S*sigma, S=2."""
    eff = Engine(S2_VERSION).effective(mu, sigma, p_avg)
    assert eff.mu_eff == pytest.approx((1 - W) * mu + W * (MU_0 + K * (p_avg - 1.0)))
    assert eff.score == pytest.approx(eff.mu_eff - S * sigma)


# --- 4) Maçsız oyuncu nötr + score monotonluğu ------------------------------


def test_matchless_player_neutral():
    """Maçsız oyuncu: default rating + P_avg=1 → mu_eff=25, score ≈ 8.33.
    Nötr NOKTA (mu_eff) blend20/blend50 ile aynıdır; yalnız gösterim ölçeği
    (S) kaydığı için score farklıdır."""
    e_s2 = Engine(S2_VERSION)
    r = e_s2.default_rating()
    eff = e_s2.effective(r.mu, r.sigma, p_avg=1.0)
    assert eff.mu_eff == pytest.approx(25.0)
    assert eff.score == pytest.approx(NEUTRAL_SCORE)
    eff20 = Engine(BLEND20_VERSION).effective(r.mu, r.sigma, p_avg=1.0)
    assert eff20.mu_eff == pytest.approx(eff.mu_eff)
    assert eff20.score == pytest.approx(0.0, abs=1e-12)


@given(
    mu=st.floats(min_value=0.0, max_value=50.0, allow_nan=False),
    sigma=st.floats(min_value=0.5, max_value=25.0 / 3.0, allow_nan=False),
)
@settings(max_examples=100, deadline=None)
def test_score_monotonic_in_p_avg(mu, sigma):
    e = Engine(S2_VERSION)
    p_avgs = [0.5, 0.8, 1.0, 1.2, 1.5, 2.0]
    scores = [e.effective(mu, sigma, p).score for p in p_avgs]
    for lo, hi in zip(scores, scores[1:]):
        assert lo < hi


# --- 5) S yeni bir eksendir: ordinal DEĞİŞMEZ, score kayar ------------------


@given(
    mu=st.floats(min_value=0.0, max_value=50.0, allow_nan=False),
    sigma=st.floats(min_value=0.5, max_value=25.0 / 3.0, allow_nan=False),
)
@settings(max_examples=100, deadline=None)
def test_ordinal_definition_unchanged(mu, sigma):
    """`Rating.ordinal` W/L çekirdeğinin muhafazakâr tahmini olarak
    mu - 3σ kalır; aktif version'ın S=2'si onu ETKİLEMEZ."""
    r = Rating(mu=mu, sigma=sigma)
    assert r.ordinal == mu - 3.0 * sigma


@given(
    mu=st.floats(min_value=0.0, max_value=50.0, allow_nan=False),
    sigma=st.floats(min_value=0.5, max_value=25.0 / 3.0, allow_nan=False),
    p_avg=st.floats(min_value=0.5, max_value=2.0, allow_nan=False),
)
@settings(max_examples=100, deadline=None)
def test_score_shift_is_exactly_one_sigma_vs_same_weight(mu, sigma, p_avg):
    """S farkının etkisi tam olarak +1σ'dır: aynı mu_eff'te S=2 score'u
    S=3'ünkünden sigma kadar yüksektir (blend20 sabit W ile karşılaştırma
    yerine formül üzerinden, W farkından arındırılmış hâli)."""
    eff = Engine(S2_VERSION).effective(mu, sigma, p_avg)
    assert eff.score - (eff.mu_eff - 3.0 * sigma) == pytest.approx(sigma)


def test_low_sigma_discount_ranking_example():
    """S=2'de sigma iskontosu azaldığı için az maçlı (yüksek sigma) oyuncu
    görece kayrılır — kabul edilen ödünleşim (contract "Kabul edilen
    ödünleşimler" (b)). Somut örnek: aynı mu_eff'te sigma farkı S ile ölçekli."""
    e_s2, e20 = Engine(S2_VERSION), Engine(BLEND20_VERSION)
    rookie = (25.0, 25.0 / 3.0)   # çok maçsız: yüksek sigma
    veteran = (25.0, 3.0)         # oturmuş sigma
    gap_s2 = (
        e_s2.effective(*veteran, 1.0).score - e_s2.effective(*rookie, 1.0).score
    )
    gap_20 = (
        e20.effective(*veteran, 1.0).score - e20.effective(*rookie, 1.0).score
    )
    assert 0 < gap_s2 < gap_20


# --- Ek: version kaydı + önceki version'lardan farkın kapsamı ---------------


def test_s2_version_registered_and_common_behavior():
    base, s2 = Engine(BASE_VERSION), Engine(S2_VERSION)
    assert s2.version == S2_VERSION
    assert base.default_rating() == s2.default_rating()
    strong = [Rating(mu=30.0, sigma=5.0)] * 5
    weak = [Rating(mu=20.0, sigma=5.0)] * 5
    assert base.predict_win(strong, weak) == s2.predict_win(strong, weak)


def test_s2_weight_between_blend50_and_blend20():
    """W=0.70: perf ağırlığı blend50 (0.5) ile blend20 (0.8) ARASINDA.
    Karşılaştırma mu_eff üzerinden yapılır (score'da S farkı vardır)."""
    e_s2, e20, e50 = (
        Engine(S2_VERSION), Engine(BLEND20_VERSION), Engine(BLEND50_VERSION)
    )
    sigma = 25.0 / 3.0
    for p in (1.5, 1.2):
        assert (
            e50.effective(25.0, sigma, p).mu_eff
            < e_s2.effective(25.0, sigma, p).mu_eff
            < e20.effective(25.0, sigma, p).mu_eff
        )
    for p in (0.7, 0.9):
        assert (
            e50.effective(25.0, sigma, p).mu_eff
            > e_s2.effective(25.0, sigma, p).mu_eff
            > e20.effective(25.0, sigma, p).mu_eff
        )


def test_previous_versions_effective_unchanged():
    """Regresyon kilidi: eski harman version'larının efektif skoru S=3 ile
    hesaplanmaya DEVAM eder (yeni eksen onları etkilemedi)."""
    sigma = 25.0 / 3.0
    for version, w in (
        (BLEND50_VERSION, 0.5),
        (BLEND20_VERSION, 0.8),
    ):
        eff = Engine(version).effective(30.0, sigma, 1.4)
        expected_mu_eff = (1 - w) * 30.0 + w * (25.0 + 20.0 * 0.4)
        assert eff.mu_eff == pytest.approx(expected_mu_eff)
        assert eff.score == pytest.approx(expected_mu_eff - 3.0 * sigma)


def test_effective_still_raises_for_non_blend_versions():
    for version in (BASE_VERSION, "openskill-pl-perf-v1"):
        with pytest.raises(ValueError) as exc:
            Engine(version).effective(25.0, 25.0 / 3.0, 1.0)
        # Hata mesajı harman version'larını listeler; yenisi de görünmelidir.
        assert S2_VERSION in str(exc.value)
