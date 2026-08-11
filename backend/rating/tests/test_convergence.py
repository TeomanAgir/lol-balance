"""Yakınsama smoke testi: sabit 'gerçek güç' ile 200 simüle maç sonrası
ordinal sıralaması gerçek güç sıralamasıyla uyumlu olmalı (Spearman > 0.9).
"""
import random

from rating import Engine, enumerate_splits


def _ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0] * len(xs)
    for r, i in enumerate(order):
        ranks[i] = r
    return ranks


def spearman(xs, ys):
    rx, ry = _ranks(xs), _ranks(ys)
    n = len(xs)
    d2 = sum((a - b) ** 2 for a, b in zip(rx, ry))
    return 1.0 - 6.0 * d2 / (n * (n * n - 1))


def test_convergence_smoke():
    rng = random.Random(1234)
    true_skill = [10.0 + 3.0 * i for i in range(10)]  # 10..37, iyi ayrışmış
    engine = Engine()
    ratings = [engine.default_rating() for _ in range(10)]
    splits = list(enumerate_splits(10))

    for _ in range(200):
        team_a, team_b = rng.choice(splits)
        sum_a = sum(true_skill[i] for i in team_a)
        sum_b = sum(true_skill[i] for i in team_b)
        # Elo benzeri Bradley-Terry: takım güç farkı kazanma olasılığını belirler
        p_a = 1.0 / (1.0 + 10.0 ** (-(sum_a - sum_b) / 20.0))
        winner = 100 if rng.random() < p_a else 200
        new_a, new_b = engine.update(
            [ratings[i] for i in team_a], [ratings[i] for i in team_b], winner
        )
        for i, r in zip(team_a, new_a):
            ratings[i] = r
        for i, r in zip(team_b, new_b):
            ratings[i] = r

    rho = spearman([r.ordinal for r in ratings], true_skill)
    assert rho > 0.9, f"Spearman {rho:.3f} <= 0.9"
