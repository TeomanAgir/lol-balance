"""OpenSkill (Plackett-Luce) tabanlı rating motoru.

Saf kütüphane: DB, dosya ve network erişimi yok. Girdi/çıktı yalnızca
Python nesneleridir. openskill'in kendi rating tipi bu modülün dışına sızmaz.
"""
from __future__ import annotations

from dataclasses import dataclass

from openskill.models import PlackettLuce

TEAM_SIZE = 5

# Bilinen version string'leri ve bağlı model parametreleri.
# Parametre değişikliği = YENİ version string (replay uyumluluğu için);
# mevcut bir version'ın parametreleri asla değiştirilmez.
_VERSIONS = {
    "openskill-pl-v1": {
        "mu": 25.0,
        "sigma": 25.0 / 3.0,
        "beta": 25.0 / 6.0,
        "tau": 25.0 / 300.0,
    },
}


@dataclass(frozen=True)
class Rating:
    mu: float
    sigma: float

    @property
    def ordinal(self) -> float:
        return self.mu - 3.0 * self.sigma


class Engine:
    def __init__(self, version: str = "openskill-pl-v1"):
        params = _VERSIONS.get(version)
        if params is None:
            raise ValueError(
                f"Bilinmeyen rating version: {version!r}. "
                f"Geçerli: {sorted(_VERSIONS)}"
            )
        self.version = version
        self._model = PlackettLuce(**params)

    def default_rating(self) -> Rating:
        r = self._model.rating()
        return Rating(mu=r.mu, sigma=r.sigma)

    def update(
        self,
        team100: list[Rating],
        team200: list[Rating],
        winner: int,
    ) -> tuple[list[Rating], list[Rating]]:
        if winner not in (100, 200):
            raise ValueError(f"winner 100 veya 200 olmalı, geldi: {winner!r}")
        self._check_team(team100, "team100")
        self._check_team(team200, "team200")
        ranks = [1, 2] if winner == 100 else [2, 1]
        new100, new200 = self._model.rate(
            [self._to_model(team100), self._to_model(team200)], ranks=ranks
        )
        return (
            [Rating(mu=r.mu, sigma=r.sigma) for r in new100],
            [Rating(mu=r.mu, sigma=r.sigma) for r in new200],
        )

    def predict_win(self, team100: list[Rating], team200: list[Rating]) -> float:
        self._check_team(team100, "team100")
        self._check_team(team200, "team200")
        p100, _ = self._model.predict_win(
            [self._to_model(team100), self._to_model(team200)]
        )
        return p100

    def _check_team(self, team: list[Rating], name: str) -> None:
        if len(team) != TEAM_SIZE:
            raise ValueError(
                f"{name} tam {TEAM_SIZE} oyuncu olmalı (5v5), geldi: {len(team)}"
            )

    def _to_model(self, team: list[Rating]):
        return [self._model.rating(mu=r.mu, sigma=r.sigma) for r in team]
