"""`openskill-pl-perf-v1` için performans skoru ve çarpan hesabı.

Saf modül: DB, dosya ve network erişimi yok; girdi/çıktı yalnızca Python
nesneleridir. Formüller ve sabitler docs/rating_contract.md'de bu version
string'ine DONDURULMUŞTUR; herhangi bir sabit değişikliği = yeni engine
version + insan onayı.

Beş bileşen (her biri [ratio_min, ratio_max] aralığına kırpılır):
1. KDA            (kills+assists)/max(1,deaths)  → maç KDA ortalamasına oran
2. Hasar payı     damage / takım toplam hasarı   → pay / share_baseline
3. Gold payı      gold / takım toplam gold       → pay / share_baseline
4. CS/dk          cs / (duration_s/60)           → maç ortalamasına oran
5. Vizyon         vision_score                   → maç ortalamasına oran

Bir bileşen, ilgili stat null ise veya paydası 0/anlamsız ise HESAPLANMAZ
ve ortalamaya girmez. Hiç bileşen hesaplanamazsa perf = 1.0 (nötr).

    perf   = hesaplanabilen bileşen oranlarının aritmetik ortalaması
    carpan = clamp(1 + alpha * (perf - 1), 1 - cap, 1 + cap)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ParticipantStats:
    """Bir katılımcının maç istatistikleri. Tüm alanlar opsiyoneldir;

    null alan ilgili bileşeni devre dışı bırakır (nötr davranış).
    """

    kills: Optional[int] = None
    deaths: Optional[int] = None
    assists: Optional[int] = None
    gold: Optional[int] = None
    cs: Optional[int] = None
    damage_to_champs: Optional[int] = None
    vision_score: Optional[int] = None


@dataclass(frozen=True)
class PerfParams:
    """Performans katmanı sabitleri (engine version'ına dondurulmuş)."""

    alpha: float
    cap: float
    ratio_min: float
    ratio_max: float
    share_baseline: float


# Perf SKORU tanımı version'dan bağımsızdır (contract "Harman Engine" §2:
# perf-v1'deki beş bileşen ve kurallarla aynı). Bu sabitler skor tanımına
# aittir; perf-v1'in PerfParams kopyaları bunlarla aynı değerdedir.
SCORE_RATIO_MIN = 0.5
SCORE_RATIO_MAX = 2.0
SCORE_SHARE_BASELINE = 0.2


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _kda(s: Optional[ParticipantStats]) -> Optional[float]:
    if s is None or s.kills is None or s.deaths is None or s.assists is None:
        return None
    return (s.kills + s.assists) / max(1, s.deaths)


def _cs_per_min(
    s: Optional[ParticipantStats], duration_s: Optional[int]
) -> Optional[float]:
    if s is None or s.cs is None:
        return None
    if duration_s is None or duration_s <= 0:
        return None
    return s.cs / (duration_s / 60.0)


def _mean(values: list[Optional[float]]) -> Optional[float]:
    present = [v for v in values if v is not None]
    if not present:
        return None
    return sum(present) / len(present)


def _team_total(stats: list[Optional[ParticipantStats]], field: str) -> int:
    return sum(
        getattr(s, field)
        for s in stats
        if s is not None and getattr(s, field) is not None
    )


def compute_perf_scores(
    stats100: list[Optional[ParticipantStats]],
    stats200: list[Optional[ParticipantStats]],
    duration_s: Optional[int],
    ratio_min: float = SCORE_RATIO_MIN,
    ratio_max: float = SCORE_RATIO_MAX,
    share_baseline: float = SCORE_SHARE_BASELINE,
) -> tuple[list[float], list[float]]:
    """Her katılımcı için maç performans skorunu (perf) hesaplar.

    stats100/stats200: 5'er elemanlı liste; eleman ParticipantStats veya None
    (None → o katılımcı için nötr skor 1.0, ortalamalara da girmez).
    Dönüş: (perf100, perf200) — her değer [ratio_min, ratio_max] bandındadır
    (kırpılmış bileşen oranlarının ortalaması; hiç bileşen yoksa 1.0).
    """
    all_stats: list[Optional[ParticipantStats]] = list(stats100) + list(stats200)

    # Maç genelinde ortalamaya oranlanan bileşenler (yalnızca hesaplanabilen
    # katılımcılar ortalamaya girer; ortalama 0 ise bileşen tümden atlanır).
    kdas = [_kda(s) for s in all_stats]
    kda_mean = _mean(kdas)
    cspms = [_cs_per_min(s, duration_s) for s in all_stats]
    cspm_mean = _mean(cspms)
    visions = [None if s is None else s.vision_score for s in all_stats]
    vision_mean = _mean([None if v is None else float(v) for v in visions])

    # Takım içi paya dayanan bileşenler (takım toplamı 0 ise atlanır).
    totals = {
        "damage_to_champs": (
            _team_total(stats100, "damage_to_champs"),
            _team_total(stats200, "damage_to_champs"),
        ),
        "gold": (_team_total(stats100, "gold"), _team_total(stats200, "gold")),
    }

    def perf(i: int) -> float:
        s = all_stats[i]
        team_idx = 0 if i < len(stats100) else 1
        components: list[float] = []

        if kdas[i] is not None and kda_mean:
            components.append(kdas[i] / kda_mean)
        if s is not None and s.damage_to_champs is not None:
            total = totals["damage_to_champs"][team_idx]
            if total > 0:
                components.append((s.damage_to_champs / total) / share_baseline)
        if s is not None and s.gold is not None:
            total = totals["gold"][team_idx]
            if total > 0:
                components.append((s.gold / total) / share_baseline)
        if cspms[i] is not None and cspm_mean:
            components.append(cspms[i] / cspm_mean)
        if visions[i] is not None and vision_mean:
            components.append(visions[i] / vision_mean)

        if not components:
            return 1.0
        clamped = [_clamp(c, ratio_min, ratio_max) for c in components]
        return sum(clamped) / len(clamped)

    scores = [perf(i) for i in range(len(all_stats))]
    return scores[: len(stats100)], scores[len(stats100) :]


def compute_multipliers(
    stats100: list[Optional[ParticipantStats]],
    stats200: list[Optional[ParticipantStats]],
    duration_s: Optional[int],
    params: PerfParams,
) -> tuple[list[float], list[float]]:
    """Her katılımcı için etkin çarpanı hesaplar (`openskill-pl-perf-v1`).

    Skor hesabı compute_perf_scores ile AYNI fonksiyondan gelir (contract:
    blend50 perf_score == perf-v1 çarpanına giren perf, birebir). Nötr skor
    (1.0) çarpanı da tam 1.0 yapar (alpha*(1-1) = 0.0, kırpma değiştirmez).
    Dönüş: (carpan100, carpan200) — her değer [1-cap, 1+cap] bandındadır.
    """
    p100, p200 = compute_perf_scores(
        stats100,
        stats200,
        duration_s,
        ratio_min=params.ratio_min,
        ratio_max=params.ratio_max,
        share_baseline=params.share_baseline,
    )

    def mult(perf: float) -> float:
        return _clamp(
            1.0 + params.alpha * (perf - 1.0), 1.0 - params.cap, 1.0 + params.cap
        )

    return [mult(p) for p in p100], [mult(p) for p in p200]
