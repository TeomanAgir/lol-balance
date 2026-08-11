"""5v5 takım dengeleme yardımcıları.

Matematik burada durur; backend yalnızca çağırır. Ayrımlar index bazlıdır:
çağıran, kendi oyuncu listesinin sırasını korumaktan sorumludur.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Iterator

from .engine import Engine, Rating


@dataclass(frozen=True)
class BalanceSuggestion:
    team100: tuple[int, ...]
    team200: tuple[int, ...]
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
