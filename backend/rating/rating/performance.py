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


def compute_multipliers(
    stats100: list[Optional[ParticipantStats]],
    stats200: list[Optional[ParticipantStats]],
    duration_s: Optional[int],
    params: PerfParams,
) -> tuple[list[float], list[float]]:
    """Her katılımcı için etkin çarpanı hesaplar.

    stats100/stats200: 5'er elemanlı liste; eleman ParticipantStats veya None
    (None → o katılımcı için nötr çarpan 1.0, ortalamalara da girmez).
    Dönüş: (carpan100, carpan200) — her değer [1-cap, 1+cap] bandındadır.
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

    def multiplier(i: int) -> float:
        s = all_stats[i]
        team_idx = 0 if i < len(stats100) else 1
        components: list[float] = []

        if kdas[i] is not None and kda_mean:
            components.append(kdas[i] / kda_mean)
        if s is not None and s.damage_to_champs is not None:
            total = totals["damage_to_champs"][team_idx]
            if total > 0:
                components.append((s.damage_to_champs / total) / params.share_baseline)
        if s is not None and s.gold is not None:
            total = totals["gold"][team_idx]
            if total > 0:
                components.append((s.gold / total) / params.share_baseline)
        if cspms[i] is not None and cspm_mean:
            components.append(cspms[i] / cspm_mean)
        if visions[i] is not None and vision_mean:
            components.append(visions[i] / vision_mean)

        if not components:
            return 1.0
        clamped = [_clamp(c, params.ratio_min, params.ratio_max) for c in components]
        perf = sum(clamped) / len(clamped)
        return _clamp(1.0 + params.alpha * (perf - 1.0), 1.0 - params.cap, 1.0 + params.cap)

    mults = [multiplier(i) for i in range(len(all_stats))]
    return mults[: len(stats100)], mults[len(stats100) :]
