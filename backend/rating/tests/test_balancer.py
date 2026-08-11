import pytest

from rating import BalanceSuggestion, Engine, Rating, balance, enumerate_splits


def test_enumerate_splits_count_and_disjoint():
    splits = list(enumerate_splits(10))
    assert len(splits) == 126
    for team_a, team_b in splits:
        assert len(team_a) == 5
        assert len(team_b) == 5
        assert set(team_a) & set(team_b) == set()
        assert set(team_a) | set(team_b) == set(range(10))


def test_enumerate_splits_mirrors_deduplicated():
    splits = list(enumerate_splits(10))
    seen = {frozenset({frozenset(a), frozenset(b)}) for a, b in splits}
    assert len(seen) == 126  # ayna ayrım olsaydı küme küçülürdü


@pytest.mark.parametrize("n", [0, -2, 3, 7])
def test_enumerate_splits_rejects_invalid_n(n):
    with pytest.raises(ValueError):
        list(enumerate_splits(n))


def test_balance_requires_ten_ratings():
    r = Engine().default_rating()
    with pytest.raises(ValueError):
        balance([r] * 8, top_n=3)
    with pytest.raises(ValueError):
        balance([r] * 10, top_n=0)


def test_balance_sorted_and_consistent_with_predict_win():
    ratings = [Rating(mu=20.0 + i, sigma=6.0) for i in range(10)]
    top = balance(ratings, top_n=10)
    assert len(top) == 10
    assert all(isinstance(s, BalanceSuggestion) for s in top)
    # imbalance artan sıralı
    assert all(
        top[i].imbalance <= top[i + 1].imbalance for i in range(len(top) - 1)
    )
    engine = Engine()
    for s in top:
        p = engine.predict_win(
            [ratings[i] for i in s.team100], [ratings[i] for i in s.team200]
        )
        assert s.p_team100 == pytest.approx(p)
        assert s.imbalance == pytest.approx(abs(p - 0.5))


def test_balance_top_n_caps_at_126():
    ratings = [Engine().default_rating() for _ in range(10)]
    assert len(balance(ratings, top_n=500)) == 126


def test_balance_identical_players_perfectly_even():
    ratings = [Engine().default_rating() for _ in range(10)]
    for s in balance(ratings, top_n=5):
        assert s.p_team100 == pytest.approx(0.5)
        assert s.imbalance == pytest.approx(0.0)


def test_balance_deterministic():
    ratings = [Rating(mu=15.0 + 2 * i, sigma=5.0) for i in range(10)]
    assert balance(ratings, top_n=5) == balance(ratings, top_n=5)
