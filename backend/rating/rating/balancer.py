"""5v5 takım dengeleme yardımcıları.

Matematik burada durur; backend yalnızca çağırır. Ayrımlar index bazlıdır:
çağıran, kendi oyuncu listesinin sırasını korumaktan sorumludur.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, permutations
from typing import Iterator

from .engine import Engine, Rating

# Deterministik rol sırası. Eşitlik kırılımı bu sırayla gezmeye bağlıdır
# (contract: TOP < JUNGLE < MIDDLE < BOTTOM < UTILITY).
ROLES: tuple[str, ...] = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")


@dataclass(frozen=True)
class BalanceSuggestion:
    team100: tuple[int, ...]
    team200: tuple[int, ...]
    p_team100: float  # Engine.predict_win: P(team100 kazanır)
    imbalance: float  # |p_team100 - 0.5|; 0 = mükemmel denge


@dataclass(frozen=True)
class RoleBalanceSuggestion:
    """Rol atamalı 5v5 öneri; positions* alanları team* ile hizalıdır."""

    team100: tuple[int, ...]
    team200: tuple[int, ...]
    positions100: tuple[str, ...]
    positions200: tuple[str, ...]
    p_team100: float  # Engine.predict_win: P(team100 kazanır)
    imbalance: float  # |p_team100 - 0.5|; 0 = mükemmel denge


def enumerate_splits(
    n: int = 10,
) -> Iterator[tuple[tuple[int, ...], tuple[int, ...]]]:
    """0..n-1 indekslerinin iki eşit takıma benzersiz ayrımları.

    Ayna ayrımlar tekilleştirilir: 0 indeksi her zaman ilk takımdadır.
    n=10 için tam 126 ayrım (C(9,4)) üretir.
    """
    if n < 2 or n % 2 != 0:
        raise ValueError(f"n pozitif ve çift olmalı, geldi: {n!r}")
    half = n // 2
    rest = range(1, n)
    for combo in combinations(rest, half - 1):
        chosen = set(combo)
        team_a = (0, *combo)
        team_b = tuple(i for i in rest if i not in chosen)
        yield team_a, team_b


def balance(ratings: list[Rating], top_n: int) -> list[BalanceSuggestion]:
    """10 oyuncuyu en dengeli 5v5 ayrımlarına böler.

    Tüm 126 ayrımı değerlendirir, imbalance'a göre artan sıralar ve
    ilk top_n öneriyi döner.
    """
    if len(ratings) != 10:
        raise ValueError(f"balance tam 10 rating bekler (5v5), geldi: {len(ratings)}")
    if top_n < 1:
        raise ValueError(f"top_n en az 1 olmalı, geldi: {top_n!r}")
    engine = Engine()
    suggestions = []
    for team_a, team_b in enumerate_splits(10):
        p = engine.predict_win(
            [ratings[i] for i in team_a], [ratings[i] for i in team_b]
        )
        suggestions.append(
            BalanceSuggestion(
                team100=team_a,
                team200=team_b,
                p_team100=p,
                imbalance=abs(p - 0.5),
            )
        )
    suggestions.sort(key=lambda s: (s.imbalance, s.team100))
    return suggestions[:top_n]


def _best_assignment(
    team: tuple[int, ...],
    ratings_by_role: list[dict[str, Rating]],
    roles: tuple[str, ...] = ROLES,
) -> tuple[str, ...]:
    """Takımın toplam ordinal'ini maksimize eden rol ataması.

    `roles` permütasyonları verilen sırayla gezilir (tam evrende 120,
    kısıtlı varyantta kalan 4 rol için 24); strict-greater karşılaştırma
    sayesinde eşitlikte İLK bulunan atama korunur (deterministik kırılım).
    """
    best_perm: tuple[str, ...] = ()
    best_total = float("-inf")
    for perm in permutations(roles):
        total = 0.0
        for idx, role in zip(team, perm):
            total += ratings_by_role[idx][role].ordinal
        if total > best_total:
            best_total = total
            best_perm = perm
    return best_perm


def _validate_role_inputs(
    ratings_by_role: list[dict[str, Rating]], top_n: int, caller: str
) -> None:
    """`balance_roles` ailesinin ortak girdi doğrulaması (mesajlar Türkçe)."""
    if len(ratings_by_role) != 10:
        raise ValueError(
            f"{caller} tam 10 oyuncu bekler (5v5), "
            f"geldi: {len(ratings_by_role)}"
        )
    if top_n < 1:
        raise ValueError(f"top_n en az 1 olmalı, geldi: {top_n!r}")
    for i, by_role in enumerate(ratings_by_role):
        if set(by_role) != set(ROLES):
            raise ValueError(
                f"ratings_by_role[{i}] tam 5 rol anahtarı içermeli "
                f"{list(ROLES)}, geldi: {sorted(by_role)}"
            )


def balance_roles(
    ratings_by_role: list[dict[str, Rating]], top_n: int
) -> list[RoleBalanceSuggestion]:
    """10 oyuncuyu rol atamalı en dengeli 5v5 ayrımlarına böler.

    `ratings_by_role[i]`, i. oyuncunun `{rol: Rating}` haritasıdır ve 5 rolün
    TAMAMINI içermelidir. Geçilen `Rating.mu` çağıran tarafından zaten
    harmanlanmış `mu_eff_role` kabul edilir: bu fonksiyon harmanı bilmez
    (engine-agnostik, `balance()` ile aynı desen).

    Her ayrımda her takım için, atanan Rating'lerin ordinal TOPLAMINI
    maksimize eden rol ataması seçilir; `p_team100` seçilen atamanın
    Rating'leriyle hesaplanır. Sıralama `balance()` ile aynıdır.
    """
    _validate_role_inputs(ratings_by_role, top_n, "balance_roles")

    engine = Engine()
    # Aynı 5'li alt küme farklı ayrımlarda tekrar geçer (252 alt küme, 126*2
    # kullanım); atama başına 120 permütasyon olduğu için memoize edilir.
    memo: dict[tuple[int, ...], tuple[str, ...]] = {}

    def assignment(team: tuple[int, ...]) -> tuple[str, ...]:
        cached = memo.get(team)
        if cached is None:
            cached = _best_assignment(team, ratings_by_role)
            memo[team] = cached
        return cached

    suggestions = []
    for team_a, team_b in enumerate_splits(10):
        pos_a = assignment(team_a)
        pos_b = assignment(team_b)
        p = engine.predict_win(
            [ratings_by_role[i][role] for i, role in zip(team_a, pos_a)],
            [ratings_by_role[i][role] for i, role in zip(team_b, pos_b)],
        )
        suggestions.append(
            RoleBalanceSuggestion(
                team100=team_a,
                team200=team_b,
                positions100=pos_a,
                positions200=pos_b,
                p_team100=p,
                imbalance=abs(p - 0.5),
            )
        )
    suggestions.sort(key=lambda s: (s.imbalance, s.team100))
    return suggestions[:top_n]


def balance_roles_constrained(
    ratings_by_role: list[dict[str, Rating]],
    top_n: int,
    *,
    separate: tuple[int, int],
    fixed_role: str,
) -> list[RoleBalanceSuggestion]:
    """`balance_roles`'un kısıtlı kardeşi (nemesis maçı, GÖREV 3).

    `separate` iki oyuncu index'i KARŞI takımlara düşer ve İKİSİ DE
    `fixed_role`'e sabitlenir; kalan 4'er oyuncuya kalan 4 rol normal aramayla
    dağıtılır. Ayrım uzayı 126'dan çifti ayıran 70 ayrıma daralır, atama
    araması takım başına 24 permütasyondur.

    Girdi anlamı, `p_team100`/`imbalance` tanımı, sıralama ve eşitlik kırılımı
    `balance_roles` ile birebir aynıdır (rating_contract §6).
    """
    _validate_role_inputs(ratings_by_role, top_n, "balance_roles_constrained")
    if len(separate) != 2:
        raise ValueError(f"separate tam 2 index içermeli, geldi: {separate!r}")
    first, second = separate
    for idx in (first, second):
        if not isinstance(idx, int) or isinstance(idx, bool) or not 0 <= idx < 10:
            raise ValueError(
                f"separate index'leri 0..9 aralığında olmalı, geldi: {separate!r}"
            )
    if first == second:
        raise ValueError(f"separate iki FARKLI index olmalı, geldi: {separate!r}")
    if fixed_role not in ROLES:
        raise ValueError(
            f"fixed_role {list(ROLES)} içinden olmalı, geldi: {fixed_role!r}"
        )

    engine = Engine()
    remaining_roles = tuple(role for role in ROLES if role != fixed_role)
    # Takım, `separate`'ten hangi oyuncuyu içerdiğini tek başına belirler
    # (ayrımlar çifti ayırdığı için tam 1 tanesini); memo anahtarı takımdır.
    memo: dict[tuple[int, ...], tuple[str, ...]] = {}

    def assignment(team: tuple[int, ...]) -> tuple[str, ...]:
        cached = memo.get(team)
        if cached is None:
            pinned = first if first in team else second
            rest = tuple(i for i in team if i != pinned)
            perm = _best_assignment(rest, ratings_by_role, remaining_roles)
            by_index = dict(zip(rest, perm))
            cached = tuple(
                fixed_role if i == pinned else by_index[i] for i in team
            )
            memo[team] = cached
        return cached

    suggestions = []
    for team_a, team_b in enumerate_splits(10):
        if (first in team_a) == (second in team_a):
            continue  # çifti ayırmayan ayrım: kısıt gereği elenir
        pos_a = assignment(team_a)
        pos_b = assignment(team_b)
        p = engine.predict_win(
            [ratings_by_role[i][role] for i, role in zip(team_a, pos_a)],
            [ratings_by_role[i][role] for i, role in zip(team_b, pos_b)],
        )
        suggestions.append(
            RoleBalanceSuggestion(
                team100=team_a,
                team200=team_b,
                positions100=pos_a,
                positions200=pos_b,
                p_team100=p,
                imbalance=abs(p - 0.5),
            )
        )
    suggestions.sort(key=lambda s: (s.imbalance, s.team100))
    return suggestions[:top_n]
