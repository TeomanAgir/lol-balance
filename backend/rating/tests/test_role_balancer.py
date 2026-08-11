import pytest

from rating import (
    ROLES,
    Engine,
    Rating,
    RoleBalanceSuggestion,
    balance_roles,
)

DEFAULT = Rating(mu=25.0, sigma=25.0 / 3.0)  # score 0 (nötr), hiç oynanmamış rol


def roles_map(**overrides: Rating) -> dict[str, Rating]:
    """5 rolün tamamı default; overrides ile tek tek güçlendirilir."""
    m = {role: DEFAULT for role in ROLES}
    m.update(overrides)
    return m


def all_default(n: int = 10) -> list[dict[str, Rating]]:
    return [roles_map() for _ in range(n)]


# --- doğrulama ---------------------------------------------------------------


@pytest.mark.parametrize("n", [0, 1, 9, 11])
def test_requires_exactly_ten_players(n):
    with pytest.raises(ValueError):
        balance_roles(all_default(n), top_n=3)


@pytest.mark.parametrize("top_n", [0, -1])
def test_rejects_invalid_top_n(top_n):
    with pytest.raises(ValueError):
        balance_roles(all_default(), top_n=top_n)


def test_rejects_missing_role_key():
    players = all_default()
    del players[4]["UTILITY"]
    with pytest.raises(ValueError):
        balance_roles(players, top_n=3)


def test_rejects_extra_role_key():
    players = all_default()
    players[0]["SUPPORT"] = DEFAULT  # LCU'daki eski ad; kabul edilmez
    with pytest.raises(ValueError):
        balance_roles(players, top_n=3)


def test_rejects_empty_role_map():
    players = all_default()
    players[7] = {}
    with pytest.raises(ValueError):
        balance_roles(players, top_n=3)


# --- şekil / hizalama --------------------------------------------------------


def test_suggestion_shape_and_alignment():
    players = [
        roles_map(**{ROLES[i % 5]: Rating(mu=20.0 + i, sigma=6.0)}) for i in range(10)
    ]
    top = balance_roles(players, top_n=10)
    assert len(top) == 10
    for s in top:
        assert isinstance(s, RoleBalanceSuggestion)
        assert len(s.team100) == len(s.positions100) == 5
        assert len(s.team200) == len(s.positions200) == 5
        assert set(s.positions100) == set(ROLES)
        assert set(s.positions200) == set(ROLES)
        assert set(s.team100) & set(s.team200) == set()
        assert set(s.team100) | set(s.team200) == set(range(10))


def test_sorted_by_imbalance_and_consistent_with_predict_win():
    players = [roles_map(**{ROLES[i % 5]: Rating(mu=20.0 + i, sigma=6.0)}) for i in range(10)]
    top = balance_roles(players, top_n=126)
    assert len(top) == 126
    assert all(top[i].imbalance <= top[i + 1].imbalance for i in range(len(top) - 1))
    engine = Engine()
    for s in top:
        p = engine.predict_win(
            [players[i][role] for i, role in zip(s.team100, s.positions100)],
            [players[i][role] for i, role in zip(s.team200, s.positions200)],
        )
        assert s.p_team100 == pytest.approx(p)
        assert s.imbalance == pytest.approx(abs(p - 0.5))


def test_top_n_caps_at_126():
    assert len(balance_roles(all_default(), top_n=500)) == 126


def test_identical_players_perfectly_even():
    for s in balance_roles(all_default(), top_n=5):
        assert s.p_team100 == pytest.approx(0.5)
        assert s.imbalance == pytest.approx(0.0)


# --- determinizm -------------------------------------------------------------


def test_deterministic():
    players = [roles_map(**{ROLES[i % 5]: Rating(mu=15.0 + 2 * i, sigma=5.0)}) for i in range(10)]
    assert balance_roles(players, top_n=5) == balance_roles(players, top_n=5)


def test_tie_break_keeps_first_permutation():
    """Tüm roller eşitken ilk bulunan maksimum korunur → ROLES sırası."""
    for s in balance_roles(all_default(), top_n=126):
        assert s.positions100 == ROLES
        assert s.positions200 == ROLES


# --- optimal atama -----------------------------------------------------------


def test_specialist_always_gets_his_role():
    """Tek rolde çok yüksek ordinal'i olan oyuncu her ayrımda o role atanır."""
    players = all_default()
    players[3] = roles_map(JUNGLE=Rating(mu=60.0, sigma=25.0 / 3.0))
    for s in balance_roles(players, top_n=126):
        if 3 in s.team100:
            assert s.positions100[s.team100.index(3)] == "JUNGLE"
        else:
            assert s.positions200[s.team200.index(3)] == "JUNGLE"


def test_two_specialists_same_team_only_one_gets_the_role():
    """İki TOP uzmanı aynı takımdayken rolü yalnız biri alır (diğeri default)."""
    players = all_default()
    strong_top = Rating(mu=45.0, sigma=25.0 / 3.0)
    players[0] = roles_map(TOP=strong_top)
    players[1] = roles_map(TOP=strong_top)
    same_team = [
        s
        for s in balance_roles(players, top_n=126)
        if (0 in s.team100) == (1 in s.team100)
    ]
    assert same_team  # 0 ve 1'in aynı takımda olduğu ayrımlar mevcut
    for s in same_team:
        team, positions = (
            (s.team100, s.positions100) if 0 in s.team100 else (s.team200, s.positions200)
        )
        assigned = {team[i]: positions[i] for i in range(5)}
        assert sorted([assigned[0], assigned[1]]).count("TOP") == 1


def test_only_top_specialists_land_on_opposite_teams():
    """'Sadece TOP oynamış' iki güçlü oyuncu en iyi öneride ayrı takımlarda."""
    players = all_default()
    strong_top = Rating(mu=45.0, sigma=25.0 / 3.0)
    players[0] = roles_map(TOP=strong_top)
    players[1] = roles_map(TOP=strong_top)
    top = balance_roles(players, top_n=3)
    best = top[0]
    assert (0 in best.team100) != (1 in best.team100)
    assert best.imbalance == pytest.approx(0.0)
    # Her ikisi de kendi takımında TOP'a atanmalı (uzmanlık kullanılıyor).
    for s in top:
        if s.imbalance != pytest.approx(0.0):
            continue
        for pid in (0, 1):
            if pid in s.team100:
                assert s.positions100[s.team100.index(pid)] == "TOP"
            else:
                assert s.positions200[s.team200.index(pid)] == "TOP"
    # Aynı takıma düşen ayrımlar dengesizdir (uzmanlığın biri boşa gider).
    for s in balance_roles(players, top_n=126):
        if (0 in s.team100) == (1 in s.team100):
            assert s.imbalance > 0.0


def test_assignment_maximizes_team_ordinal_sum():
    """Seçilen atamanın toplamı, o takımın 120 permütasyonunun maksimumu."""
    from itertools import permutations

    players = [
        roles_map(
            **{
                role: Rating(mu=20.0 + (i * 7 + j * 3) % 15, sigma=6.0)
                for j, role in enumerate(ROLES)
            }
        )
        for i in range(10)
    ]
    for s in balance_roles(players, top_n=20):
        for team, positions in (
            (s.team100, s.positions100),
            (s.team200, s.positions200),
        ):
            chosen = sum(players[i][r].ordinal for i, r in zip(team, positions))
            best = max(
                sum(players[i][r].ordinal for i, r in zip(team, perm))
                for perm in permutations(ROLES)
            )
            assert chosen == pytest.approx(best)


def test_blended_mu_is_caller_responsibility():
    """Fonksiyon harman bilmez: mu_eff geçirmek sonucu doğrudan belirler."""
    engine = Engine("openskill-pl-blend50-v1")
    eff = engine.effective(mu=25.0, sigma=25.0 / 3.0, p_avg=1.5)
    blended = Rating(mu=eff.mu_eff, sigma=eff.sigma)
    assert blended.ordinal == pytest.approx(eff.score)
    players = all_default()
    players[0] = roles_map(MIDDLE=blended)
    for s in balance_roles(players, top_n=126):
        if 0 in s.team100:
            assert s.positions100[s.team100.index(0)] == "MIDDLE"
        else:
            assert s.positions200[s.team200.index(0)] == "MIDDLE"
