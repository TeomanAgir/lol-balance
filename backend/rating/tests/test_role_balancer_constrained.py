"""`balance_roles_constrained` (nemesis maçı, GÖREV 3) testleri.

Kısıt: verilen iki index karşı takımlara ayrılır ve ikisi de verilen role
sabitlenir. Ayrım uzayı 70, atama araması takım başına 24 permütasyondur.
"""
from itertools import permutations

import pytest

from rating import (
    ROLES,
    Engine,
    Rating,
    RoleBalanceSuggestion,
    balance_roles,
    balance_roles_constrained,
)

DEFAULT = Rating(mu=25.0, sigma=25.0 / 3.0)  # score 0 (nötr), hiç oynanmamış rol


def roles_map(**overrides: Rating) -> dict[str, Rating]:
    m = {role: DEFAULT for role in ROLES}
    m.update(overrides)
    return m


def all_default(n: int = 10) -> list[dict[str, Rating]]:
    return [roles_map() for _ in range(n)]


def varied() -> list[dict[str, Rating]]:
    """Rol skorları oyuncudan oyuncuya ayrışan, elle kurgulu senaryo."""
    return [
        roles_map(
            **{
                role: Rating(mu=20.0 + (i * 7 + j * 3) % 15, sigma=6.0 + (i + j) % 4)
                for j, role in enumerate(ROLES)
            }
        )
        for i in range(10)
    ]


def team_of(s: RoleBalanceSuggestion, pid: int) -> tuple[tuple[int, ...], tuple[str, ...]]:
    if pid in s.team100:
        return s.team100, s.positions100
    return s.team200, s.positions200


def position_of(s: RoleBalanceSuggestion, pid: int) -> str:
    team, positions = team_of(s, pid)
    return positions[team.index(pid)]


# --- doğrulama ---------------------------------------------------------------


@pytest.mark.parametrize("n", [0, 1, 9, 11])
def test_requires_exactly_ten_players(n):
    with pytest.raises(ValueError):
        balance_roles_constrained(
            all_default(n), top_n=3, separate=(0, 1), fixed_role="TOP"
        )


@pytest.mark.parametrize("top_n", [0, -1])
def test_rejects_invalid_top_n(top_n):
    with pytest.raises(ValueError):
        balance_roles_constrained(
            all_default(), top_n=top_n, separate=(0, 1), fixed_role="TOP"
        )


def test_rejects_missing_role_key():
    players = all_default()
    del players[4]["UTILITY"]
    with pytest.raises(ValueError):
        balance_roles_constrained(
            players, top_n=3, separate=(0, 1), fixed_role="TOP"
        )


def test_rejects_same_index_twice():
    with pytest.raises(ValueError):
        balance_roles_constrained(
            all_default(), top_n=3, separate=(4, 4), fixed_role="MIDDLE"
        )


@pytest.mark.parametrize("pair", [(0, 10), (-1, 3), (10, 11), (0, 9999)])
def test_rejects_out_of_range_index(pair):
    with pytest.raises(ValueError):
        balance_roles_constrained(
            all_default(), top_n=3, separate=pair, fixed_role="MIDDLE"
        )


def test_rejects_wrong_separate_length():
    with pytest.raises(ValueError):
        balance_roles_constrained(
            all_default(), top_n=3, separate=(1, 2, 3), fixed_role="MIDDLE"
        )


@pytest.mark.parametrize("role", ["SUPPORT", "top", "", "ADC", None])
def test_rejects_invalid_fixed_role(role):
    with pytest.raises(ValueError):
        balance_roles_constrained(
            all_default(), top_n=3, separate=(0, 1), fixed_role=role
        )


# --- kısıtın kendisi ---------------------------------------------------------


@pytest.mark.parametrize("pair", [(0, 1), (2, 5), (3, 9), (1, 8)])
@pytest.mark.parametrize("role", list(ROLES))
def test_pair_is_split_and_pinned_to_fixed_role(pair, role):
    players = varied()
    top = balance_roles_constrained(players, top_n=70, separate=pair, fixed_role=role)
    assert top
    a, b = pair
    for s in top:
        assert (a in s.team100) != (b in s.team100), "çift aynı takımda"
        assert (a in s.team100) != (a in s.team200)
        assert position_of(s, a) == role
        assert position_of(s, b) == role


@pytest.mark.parametrize("pair", [(0, 1), (2, 5), (3, 9), (4, 6), (7, 8)])
def test_exactly_seventy_splits_evaluated(pair):
    players = varied()
    top = balance_roles_constrained(
        players, top_n=500, separate=pair, fixed_role="MIDDLE"
    )
    assert len(top) == 70
    # ayrımlar benzersiz ve kısıtsız evrenin (126) gerçek alt kümesi
    splits = {s.team100 for s in top}
    assert len(splits) == 70
    all_splits = {s.team100 for s in balance_roles(players, top_n=126)}
    assert splits < all_splits


def test_shape_and_alignment():
    players = varied()
    for s in balance_roles_constrained(
        players, top_n=70, separate=(2, 7), fixed_role="BOTTOM"
    ):
        assert isinstance(s, RoleBalanceSuggestion)
        assert len(s.team100) == len(s.positions100) == 5
        assert len(s.team200) == len(s.positions200) == 5
        assert set(s.positions100) == set(ROLES)
        assert set(s.positions200) == set(ROLES)
        assert set(s.team100) & set(s.team200) == set()
        assert set(s.team100) | set(s.team200) == set(range(10))


def test_sorted_by_imbalance_and_consistent_with_predict_win():
    players = varied()
    top = balance_roles_constrained(
        players, top_n=70, separate=(1, 6), fixed_role="JUNGLE"
    )
    assert all(top[i].imbalance <= top[i + 1].imbalance for i in range(len(top) - 1))
    engine = Engine()
    for s in top:
        p = engine.predict_win(
            [players[i][role] for i, role in zip(s.team100, s.positions100)],
            [players[i][role] for i, role in zip(s.team200, s.positions200)],
        )
        assert s.p_team100 == pytest.approx(p)
        assert s.imbalance == pytest.approx(abs(p - 0.5))


def test_top_n_truncates():
    players = varied()
    full = balance_roles_constrained(
        players, top_n=70, separate=(0, 5), fixed_role="UTILITY"
    )
    assert balance_roles_constrained(
        players, top_n=3, separate=(0, 5), fixed_role="UTILITY"
    ) == full[:3]


# --- kalan rollerin optimal atanması ----------------------------------------


@pytest.mark.parametrize("pair", [(0, 3), (2, 8)])
@pytest.mark.parametrize("role", ["TOP", "MIDDLE", "UTILITY"])
def test_remaining_roles_are_brute_force_optimal(pair, role):
    """Kalan 4 oyuncunun atanan toplamı, 24 permütasyonun gerçek maksimumu."""
    players = varied()
    a, b = pair
    remaining = tuple(r for r in ROLES if r != role)
    for s in balance_roles_constrained(players, top_n=70, separate=pair, fixed_role=role):
        for team, positions in (
            (s.team100, s.positions100),
            (s.team200, s.positions200),
        ):
            pinned = a if a in team else b
            rest = [i for i in team if i != pinned]
            chosen = sum(
                players[i][r].ordinal
                for i, r in zip(team, positions)
                if i != pinned
            )
            best = max(
                sum(players[i][r].ordinal for i, r in zip(rest, perm))
                for perm in permutations(remaining)
            )
            assert chosen == pytest.approx(best)


def test_tie_break_keeps_first_permutation():
    """Her şey eşitken kalan roller ROLES sırasıyla, sabit rol yerinde kalır."""
    for s in balance_roles_constrained(
        all_default(), top_n=70, separate=(0, 1), fixed_role="MIDDLE"
    ):
        for team, positions in (
            (s.team100, s.positions100),
            (s.team200, s.positions200),
        ):
            pinned = 0 if 0 in team else 1
            rest_positions = [r for i, r in zip(team, positions) if i != pinned]
            assert positions[team.index(pinned)] == "MIDDLE"
            assert tuple(rest_positions) == ("TOP", "JUNGLE", "BOTTOM", "UTILITY")


def test_identical_players_perfectly_even():
    for s in balance_roles_constrained(
        all_default(), top_n=5, separate=(3, 4), fixed_role="TOP"
    ):
        assert s.p_team100 == pytest.approx(0.5)
        assert s.imbalance == pytest.approx(0.0)


# --- determinizm -------------------------------------------------------------


def test_deterministic():
    players = varied()
    first = balance_roles_constrained(
        players, top_n=10, separate=(2, 9), fixed_role="BOTTOM"
    )
    second = balance_roles_constrained(
        players, top_n=10, separate=(2, 9), fixed_role="BOTTOM"
    )
    assert first == second


def test_separate_order_does_not_matter():
    players = varied()
    assert balance_roles_constrained(
        players, top_n=70, separate=(2, 9), fixed_role="BOTTOM"
    ) == balance_roles_constrained(
        players, top_n=70, separate=(9, 2), fixed_role="BOTTOM"
    )


# --- kısıtsız aramayla tutarlılık -------------------------------------------


def test_matches_unconstrained_when_constraint_is_already_optimal():
    """Çift zaten o rolün uzmanıysa kısıt bağlayıcı değildir → aynı p."""
    players = all_default()
    strong_top = Rating(mu=45.0, sigma=25.0 / 3.0)
    players[0] = roles_map(TOP=strong_top)
    players[1] = roles_map(TOP=strong_top)

    unconstrained = {
        s.team100: s for s in balance_roles(players, top_n=126)
    }
    constrained = balance_roles_constrained(
        players, top_n=70, separate=(0, 1), fixed_role="TOP"
    )
    assert len(constrained) == 70
    for s in constrained:
        ref = unconstrained[s.team100]
        assert ref.team200 == s.team200
        assert ref.positions100 == s.positions100
        assert ref.positions200 == s.positions200
        assert ref.p_team100 == pytest.approx(s.p_team100)
    # En iyi kısıtlı öneri kısıtsız evrende de mükemmel dengeli.
    best = constrained[0]
    assert best.imbalance == pytest.approx(0.0)
    assert unconstrained[best.team100].imbalance == pytest.approx(0.0)


def test_constraint_can_be_binding():
    """Kısıt gerçekten daraltır: kısıtsız en iyi öneri kısıtı ihlal edebilir."""
    players = all_default()
    # 0 ve 1 UTILITY'de güçlü; kısıtsız optimizasyon onları ayırır ama ikisini
    # de MIDDLE'a sabitlemek zorunda değildir.
    players[0] = roles_map(UTILITY=Rating(mu=45.0, sigma=25.0 / 3.0))
    players[1] = roles_map(UTILITY=Rating(mu=45.0, sigma=25.0 / 3.0))
    unconstrained_best = balance_roles(players, top_n=1)[0]
    assert position_of(unconstrained_best, 0) == "UTILITY"
    constrained_best = balance_roles_constrained(
        players, top_n=1, separate=(0, 1), fixed_role="MIDDLE"
    )[0]
    assert position_of(constrained_best, 0) == "MIDDLE"
    assert position_of(constrained_best, 1) == "MIDDLE"
    # Kısıtlı arama uzayı kısıtsızın alt kümesi olduğundan daha iyi olamaz.
    assert constrained_best.imbalance >= unconstrained_best.imbalance - 1e-12


def test_no_better_than_unconstrained_optimum():
    players = varied()
    unconstrained_best = balance_roles(players, top_n=1)[0]
    constrained_best = balance_roles_constrained(
        players, top_n=1, separate=(3, 4), fixed_role="JUNGLE"
    )[0]
    assert constrained_best.imbalance >= unconstrained_best.imbalance - 1e-12
