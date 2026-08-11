import dataclasses
import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from rating import Engine, Rating

TAU = 25.0 / 300.0

rating_st = st.builds(
    Rating,
    mu=st.floats(min_value=0.0, max_value=50.0, allow_nan=False),
    sigma=st.floats(min_value=0.5, max_value=25.0 / 3.0, allow_nan=False),
)
team_st = st.lists(rating_st, min_size=5, max_size=5)


def test_default_rating():
    r = Engine().default_rating()
    assert r.mu == pytest.approx(25.0)
    assert r.sigma == pytest.approx(25.0 / 3.0)


def test_ordinal():
    assert Rating(mu=30.0, sigma=2.0).ordinal == pytest.approx(24.0)
    assert Engine().default_rating().ordinal == pytest.approx(0.0)


def test_rating_is_immutable():
    r = Rating(mu=25.0, sigma=8.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.mu = 30.0


def test_unknown_version_raises():
    with pytest.raises(ValueError):
        Engine(version="openskill-pl-v999")


def test_update_validates_winner():
    e = Engine()
    team = [e.default_rating()] * 5
    with pytest.raises(ValueError):
        e.update(team, team, winner=1)


@pytest.mark.parametrize("n100,n200", [(4, 5), (5, 4), (0, 5), (5, 6)])
def test_update_validates_team_size(n100, n200):
    e = Engine()
    r = e.default_rating()
    with pytest.raises(ValueError):
        e.update([r] * n100, [r] * n200, winner=100)
    with pytest.raises(ValueError):
        e.predict_win([r] * n100, [r] * n200)


@given(team100=team_st, team200=team_st, winner=st.sampled_from([100, 200]))
@settings(max_examples=200, deadline=None)
def test_determinism(team100, team200, winner):
    """Aynı girdi → aynı çıktı; ayrı Engine örnekleri de aynı sonucu verir."""
    a = Engine().update(team100, team200, winner)
    b = Engine().update(team100, team200, winner)
    assert a == b
    pa = Engine().predict_win(team100, team200)
    pb = Engine().predict_win(team100, team200)
    assert pa == pb


@given(team100=team_st, team200=team_st, winner=st.sampled_from([100, 200]))
@settings(max_examples=200, deadline=None)
def test_winner_mu_up_loser_mu_down(team100, team200, winner):
    new100, new200 = Engine().update(team100, team200, winner)
    winners, new_winners = (
        (team100, new100) if winner == 100 else (team200, new200)
    )
    losers, new_losers = (
        (team200, new200) if winner == 100 else (team100, new100)
    )
    for old, new in zip(winners, new_winners):
        assert new.mu > old.mu
    for old, new in zip(losers, new_losers):
        assert new.mu < old.mu


@given(team100=team_st, team200=team_st, winner=st.sampled_from([100, 200]))
@settings(max_examples=200, deadline=None)
def test_sigma_never_exceeds_tau_bound(team100, team200, winner):
    """Sigma, tau ile şişirilmiş üst sınırın (sqrt(sigma² + tau²)) üzerine çıkamaz.

    Not: tau > 0 olduğu için sigma her güncellemede mutlak olarak azalmak
    zorunda değildir — tau, sigma'nın sıfıra çökmesini önlemek için her maçta
    küçük bir belirsizlik enjekte eder. Kütüphanenin garantisi, dinamiğe izin
    verilen bu tavanın asla aşılmamasıdır. Default sigma'dan başlarken mutlak
    azalma ayrıca test edilir (test_sigma_decreases_from_default).
    """
    new100, new200 = Engine().update(team100, team200, winner)
    for old, new in zip(team100 + team200, new100 + new200):
        assert new.sigma <= math.sqrt(old.sigma**2 + TAU**2) + 1e-9


def test_sigma_decreases_from_default():
    """İlk maçta (default rating'lerle) herkesin sigma'sı kesin azalır."""
    e = Engine()
    team = [e.default_rating() for _ in range(5)]
    new100, new200 = e.update(team, team, winner=100)
    for old, new in zip(team + team, new100 + new200):
        assert new.sigma < old.sigma


@given(team100=team_st, team200=team_st)
@settings(max_examples=200, deadline=None)
def test_predict_win_symmetry(team100, team200):
    e = Engine()
    p_ab = e.predict_win(team100, team200)
    p_ba = e.predict_win(team200, team100)
    assert abs(p_ab + p_ba - 1.0) < 1e-9
    assert 0.0 <= p_ab <= 1.0


def test_predict_win_favors_stronger_team():
    e = Engine()
    strong = [Rating(mu=30.0, sigma=5.0)] * 5
    weak = [Rating(mu=20.0, sigma=5.0)] * 5
    assert e.predict_win(strong, weak) > 0.5
    assert e.predict_win(weak, strong) < 0.5
    even = [e.default_rating()] * 5
    assert e.predict_win(even, even) == pytest.approx(0.5)
