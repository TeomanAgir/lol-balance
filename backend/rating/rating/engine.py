"""OpenSkill (Plackett-Luce) tabanlı rating motoru.

Saf kütüphane: DB, dosya ve network erişimi yok. Girdi/çıktı yalnızca
Python nesneleridir. openskill'in kendi rating tipi bu modülün dışına sızmaz.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from openskill.models import PlackettLuce

from .performance import (
    ParticipantStats,
    PerfParams,
    compute_multipliers,
    compute_perf_scores,
)

TEAM_SIZE = 5

# Taban model parametreleri (OpenSkill PlackettLuce default'ları).
_BASE_PARAMS = {
    "mu": 25.0,
    "sigma": 25.0 / 3.0,
    "beta": 25.0 / 6.0,
    "tau": 25.0 / 300.0,
}


@dataclass(frozen=True)
class BlendParams:
    """Harman (efektif rating) sabitleri — engine version'ına dondurulmuş.

    mu_eff = (1-w) * mu + w * (mu_0 + k * (p_avg - 1))
    """

    mu_0: float
    k: float
    w: float


# Bilinen version string'leri ve bağlı parametreler.
# Parametre değişikliği = YENİ version string (replay uyumluluğu için);
# mevcut bir version'ın parametreleri asla değiştirilmez.
# "perf" None ise performans ÇARPANI yoktur (mu/sigma güncellemesi saf W/L).
# "blend" None ise efektif rating harmanı yoktur (effective() ValueError).
# blend version'larında perf bilinçli olarak None'dır: performans hem çarpanda
# hem harman teriminde sayılırsa çift sayım olur (contract "Model" §1).
# blend20/blend25/blend50 arasındaki TEK fark harman ağırlığıdır (w): version
# adındaki sayı W/L (mu) payını söyler (blend20 → mu %20, performans %80;
# blend25 → mu %25, performans %75). Sigma katsayısı 3.0 sabittir (Engine.effective
# içinde donmuştur) — bu bilinçlidir, version'lar arası değişmez.
_VERSIONS = {
    "openskill-pl-v1": {
        "model": dict(_BASE_PARAMS),
        "perf": None,
        "blend": None,
    },
    "openskill-pl-perf-v1": {
        "model": dict(_BASE_PARAMS),
        "perf": PerfParams(
            alpha=0.5,
            cap=0.3,
            ratio_min=0.5,
            ratio_max=2.0,
            share_baseline=0.2,
        ),
        "blend": None,
    },
    "openskill-pl-blend50-v1": {
        "model": dict(_BASE_PARAMS),
        "perf": None,
        "blend": BlendParams(mu_0=25.0, k=20.0, w=0.5),
    },
    "openskill-pl-blend20-v1": {
        "model": dict(_BASE_PARAMS),
        "perf": None,
        "blend": BlendParams(mu_0=25.0, k=20.0, w=0.8),
    },
    "openskill-pl-blend25-v1": {
        "model": dict(_BASE_PARAMS),
        "perf": None,
        "blend": BlendParams(mu_0=25.0, k=20.0, w=0.75),
    },
}


@dataclass(frozen=True)
class Rating:
    mu: float
    sigma: float

    @property
    def ordinal(self) -> float:
        return self.mu - 3.0 * self.sigma


@dataclass(frozen=True)
class EffectiveRating:
    """Harman version'larında efektif rating: sıralama/gösterim score iledir."""

    mu_eff: float
    sigma: float
    score: float  # mu_eff - 3*sigma


class Engine:
    def __init__(self, version: str = "openskill-pl-v1"):
        spec = _VERSIONS.get(version)
        if spec is None:
            raise ValueError(
                f"Bilinmeyen rating version: {version!r}. "
                f"Geçerli: {sorted(_VERSIONS)}"
            )
        self.version = version
        self._model = PlackettLuce(**spec["model"])
        self._perf: Optional[PerfParams] = spec["perf"]
        self._blend: Optional[BlendParams] = spec["blend"]

    def default_rating(self) -> Rating:
        r = self._model.rating()
        return Rating(mu=r.mu, sigma=r.sigma)

    def update(
        self,
        team100: list[Rating],
        team200: list[Rating],
        winner: int,
        stats100: Optional[list[Optional[ParticipantStats]]] = None,
        stats200: Optional[list[Optional[ParticipantStats]]] = None,
        duration_s: Optional[int] = None,
    ) -> tuple[list[Rating], list[Rating]]:
        if winner not in (100, 200):
            raise ValueError(f"winner 100 veya 200 olmalı, geldi: {winner!r}")
        self._check_team(team100, "team100")
        self._check_team(team200, "team200")
        self._check_stats(stats100, "stats100")
        self._check_stats(stats200, "stats200")
        ranks = [1, 2] if winner == 100 else [2, 1]
        new100, new200 = self._model.rate(
            [self._to_model(team100), self._to_model(team200)], ranks=ranks
        )
        base100 = [Rating(mu=r.mu, sigma=r.sigma) for r in new100]
        base200 = [Rating(mu=r.mu, sigma=r.sigma) for r in new200]

        # Performans katmanı yalnızca perf'li version'da ve stats verildiyse
        # devreye girer; aksi halde taban modelle birebir aynı sonuç döner.
        if self._perf is None or (stats100 is None and stats200 is None):
            return base100, base200

        s100 = stats100 if stats100 is not None else [None] * TEAM_SIZE
        s200 = stats200 if stats200 is not None else [None] * TEAM_SIZE
        m100, m200 = compute_multipliers(s100, s200, duration_s, self._perf)
        return (
            self._modulate(team100, base100, m100, won=(winner == 100)),
            self._modulate(team200, base200, m200, won=(winner == 200)),
        )

    def perf_scores(
        self,
        stats100: Optional[list[Optional[ParticipantStats]]],
        stats200: Optional[list[Optional[ParticipantStats]]],
        duration_s: Optional[int] = None,
    ) -> tuple[list[float], list[float]]:
        """Her katılımcının maç performans skoru (perf), [0.5, 2.0] bandında.

        Skor tanımı version'dan bağımsızdır (her version'da çağrılabilir) ve
        perf-v1 çarpanına giren perf değeriyle birebir aynıdır; hesaplanamayan
        katılımcı 1.0 (nötr) alır. Takım listesi None ise [None]*5 sayılır.
        """
        self._check_stats(stats100, "stats100")
        self._check_stats(stats200, "stats200")
        s100 = stats100 if stats100 is not None else [None] * TEAM_SIZE
        s200 = stats200 if stats200 is not None else [None] * TEAM_SIZE
        return compute_perf_scores(s100, s200, duration_s)

    def effective(self, mu: float, sigma: float, p_avg: float) -> EffectiveRating:
        """Efektif rating: mu_eff = (1-W)*mu + W*(MU_0 + K*(p_avg-1)).

        Yalnızca harman version'larında (`openskill-pl-blend50-v1`,
        `openskill-pl-blend20-v1`, `openskill-pl-blend25-v1`) geçerlidir;
        diğerlerinde ValueError (yanlış version'la sıralama üretmek sessiz veri
        bozulması olur, erken patlasın).
        p_avg: oyuncunun kariyer perf ortalaması; maçı olmayan oyuncu için
        1.0 geçilir.
        """
        if self._blend is None:
            blend_versions = sorted(
                v for v, spec in _VERSIONS.items() if spec["blend"] is not None
            )
            raise ValueError(
                f"effective() harman sabiti olmayan version'da çağrılamaz: "
                f"{self.version!r} (harman version'ları: {blend_versions})"
            )
        b = self._blend
        mu_eff = (1.0 - b.w) * mu + b.w * (b.mu_0 + b.k * (p_avg - 1.0))
        return EffectiveRating(mu_eff=mu_eff, sigma=sigma, score=mu_eff - 3.0 * sigma)

    def predict_win(self, team100: list[Rating], team200: list[Rating]) -> float:
        self._check_team(team100, "team100")
        self._check_team(team200, "team200")
        p100, _ = self._model.predict_win(
            [self._to_model(team100), self._to_model(team200)]
        )
        return p100

    @staticmethod
    def _modulate(
        old_team: list[Rating],
        base_team: list[Rating],
        mults: list[float],
        won: bool,
    ) -> list[Rating]:
        """mu deltasını çarpanla ölçekler; sigma taban modelden aynen alınır.

        Kazanan: mu_after = mu_before + delta_mu * carpan
        Kaybeden: mu_after = mu_before + delta_mu * (2 - carpan)
        Çarpan (1-cap, 1+cap) bandında pozitif kaldığı için delta'nın işareti
        asla değişmez: kazanan her zaman kazanır, kaybeden her zaman kaybeder.
        """
        out: list[Rating] = []
        for old, base, m in zip(old_team, base_team, mults):
            factor = m if won else 2.0 - m
            if factor == 1.0:
                # Nötr çarpanda taban sonuç BİREBİR (bit-bit) korunur.
                out.append(base)
            else:
                out.append(
                    Rating(mu=old.mu + (base.mu - old.mu) * factor, sigma=base.sigma)
                )
        return out

    def _check_team(self, team: list[Rating], name: str) -> None:
        if len(team) != TEAM_SIZE:
            raise ValueError(
                f"{name} tam {TEAM_SIZE} oyuncu olmalı (5v5), geldi: {len(team)}"
            )

    def _check_stats(
        self, stats: Optional[list[Optional[ParticipantStats]]], name: str
    ) -> None:
        if stats is not None and len(stats) != TEAM_SIZE:
            raise ValueError(
                f"{name} verilirse tam {TEAM_SIZE} eleman olmalı "
                f"(eksik katılımcı için None kullanın), geldi: {len(stats)}"
            )

    def _to_model(self, team: list[Rating]):
        return [self._model.rating(mu=r.mu, sigma=r.sigma) for r in team]
