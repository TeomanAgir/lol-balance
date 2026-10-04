"""ALTIN VEKTÖRLER — engine sayısal çıktısının kütüphane yükseltmesine karşı kilidi.

BU DEĞERLER 2026-10-04'TE, openskill 6.2.0 İLE ÜRETİLDİ (Python 3.12).
DEĞİŞİRSE ENGINE DAVRANIŞI DEĞİŞMİŞ DEMEKTİR: test düzeltilmez, karar alınır
(CLAUDE.md #1/#4 — sayısal çıktı engine_version'a dondurulmuştur; openskill
yükseltmesi = bilinçli karar + gerekçeli altın değer güncellemesi,
bkz. pyproject.toml'daki tam pin).

Karşılaştırmalar `==` iledir (approx DEĞİL): literal'ler `repr` çıktısıdır,
repr float'ı bit-bit geri ürettiği için eşitlik bit düzeyindedir.

Kapsam:
- Default rating'li 10 oyuncu, sabit 5 maçlık dizi (değişen takım
  kompozisyonları, sabit kazananlar; stats'lı / stats'sız / kısmi None /
  süresiz maçlar). Her maç sonrası 10 oyuncunun tamamının (mu, sigma)'sı.
- Aktif `openskill-pl-blend25-v1` ve W/L çekirdeği ortak `openskill-pl-v1`
  aynı altın mu/sigma dizisini üretmelidir.
- Her maçın `perf_scores` çıktısı (10 değer).
- Senaryo sonu her oyuncunun P_avg'ı ve `effective(mu, sigma, p_avg)` →
  (mu_eff, score); ayrıca bilinen sabit üçlüler (maçsız oyuncu tam 0).
"""
import pytest

from rating import Engine, ParticipantStats as PS

ACTIVE_VERSION = "openskill-pl-blend25-v1"
BASE_VERSION = "openskill-pl-v1"

# --- Senaryo (sabit; DEĞİŞTİRİLİRSE altın değerler yeniden üretilmelidir) ---

_FULL_A = [
    PS(kills=8, deaths=2, assists=7, gold=13500, cs=190, damage_to_champs=24000, vision_score=22),
    PS(kills=3, deaths=4, assists=12, gold=10200, cs=40, damage_to_champs=9000, vision_score=55),
    PS(kills=6, deaths=3, assists=5, gold=12100, cs=170, damage_to_champs=19500, vision_score=18),
    PS(kills=11, deaths=5, assists=4, gold=14800, cs=230, damage_to_champs=28700, vision_score=15),
    PS(kills=1, deaths=6, assists=14, gold=8300, cs=25, damage_to_champs=6100, vision_score=71),
]
_FULL_B = [
    PS(kills=4, deaths=7, assists=3, gold=10100, cs=160, damage_to_champs=14000, vision_score=17),
    PS(kills=2, deaths=6, assists=6, gold=8900, cs=35, damage_to_champs=7800, vision_score=40),
    PS(kills=5, deaths=8, assists=2, gold=11000, cs=150, damage_to_champs=16800, vision_score=12),
    PS(kills=6, deaths=5, assists=4, gold=11900, cs=200, damage_to_champs=20100, vision_score=14),
    PS(kills=0, deaths=4, assists=8, gold=7200, cs=20, damage_to_champs=4300, vision_score=48),
]
_PARTIAL_100 = [
    PS(kills=9, deaths=0, assists=6, gold=15000, cs=210, damage_to_champs=31000, vision_score=20),
    None,
    PS(kills=2, deaths=3, assists=9, gold=None, cs=60, damage_to_champs=None, vision_score=33),
    PS(kills=4, deaths=None, assists=4, gold=9800, cs=None, damage_to_champs=12000, vision_score=None),
    PS(kills=0, deaths=0, assists=0, gold=0, cs=0, damage_to_champs=0, vision_score=0),
]
_PARTIAL_200 = [
    PS(kills=3, deaths=5, assists=2, gold=9000, cs=140, damage_to_champs=11000, vision_score=10),
    PS(kills=1, deaths=9, assists=3, gold=7000, cs=90, damage_to_champs=6000, vision_score=8),
    None,
    PS(kills=5, deaths=4, assists=1, gold=10500, cs=170, damage_to_champs=15500, vision_score=9),
    PS(),
]

# (team100 oyuncu indeksleri, team200 oyuncu indeksleri, kazanan, stats100, stats200, süre_s)
MATCHES = [
    ([0, 1, 2, 3, 4], [5, 6, 7, 8, 9], 100, _FULL_A, _FULL_B, 1800),
    ([0, 2, 4, 6, 8], [1, 3, 5, 7, 9], 200, None, None, None),
    ([0, 5, 1, 6, 2], [3, 8, 4, 9, 7], 200, _FULL_B, None, 2100),
    ([3, 4, 5, 6, 7], [8, 9, 0, 1, 2], 100, _PARTIAL_100, _PARTIAL_200, 1500),
    ([9, 8, 7, 6, 5], [4, 3, 2, 1, 0], 100, _FULL_A, _FULL_B, None),
]
N_PLAYERS = 10

# --- ALTIN DEĞERLER (üretilmiş literal'ler; elle düzeltilmez) ---------------
GOLDEN_DEFAULT = (25.0, 8.333333333333334)
# Maç başına, oyuncu indeksi sırasıyla 10 oyuncunun (mu, sigma)'sı.
GOLDEN_AFTER = [
    [
        (26.285928602571605, 8.26500364347017),
        (26.285928602571605, 8.26500364347017),
        (26.285928602571605, 8.26500364347017),
        (26.285928602571605, 8.26500364347017),
        (26.285928602571605, 8.26500364347017),
        (23.714071397428395, 8.26500364347017),
        (23.714071397428395, 8.26500364347017),
        (23.714071397428395, 8.26500364347017),
        (23.714071397428395, 8.26500364347017),
        (23.714071397428395, 8.26500364347017),
    ],
    [
        (24.949907084664954, 8.19747940642658),
        (27.621950120478257, 8.19747940642658),
        (24.949907084664954, 8.19747940642658),
        (27.621950120478257, 8.19747940642658),
        (24.949907084664954, 8.19747940642658),
        (25.050092915335046, 8.19747940642658),
        (22.378049879521743, 8.19747940642658),
        (25.050092915335046, 8.19747940642658),
        (22.378049879521743, 8.19747940642658),
        (25.050092915335046, 8.19747940642658),
    ],
    [
        (23.688326930087506, 8.13043923199477),
        (26.36036996590081, 8.13043923199477),
        (23.688326930087506, 8.13043923199477),
        (28.883530275055705, 8.13043923199477),
        (26.211487239242402, 8.13043923199477),
        (23.788512760757598, 8.13043923199477),
        (21.116469724944295, 8.13043923199477),
        (26.311673069912494, 8.13043923199477),
        (23.63963003409919, 8.13043923199477),
        (26.311673069912494, 8.13043923199477),
    ],
    [
        (22.49747022777576, 8.06420153140943),
        (25.169513263589064, 8.06420153140943),
        (22.49747022777576, 8.06420153140943),
        (30.07438697736745, 8.06420153140943),
        (27.402343941554147, 8.06420153140943),
        (24.979369463069343, 8.06420153140943),
        (22.30732642725604, 8.06420153140943),
        (27.50252977222424, 8.06420153140943),
        (22.448773331787446, 8.06420153140943),
        (25.12081636760075, 8.06420153140943),
    ],
    [
        (21.130130399787205, 7.999100466992427),
        (23.80217343560051, 7.999100466992427),
        (21.130130399787205, 7.999100466992427),
        (28.707047149378894, 7.999100466992427),
        (26.03500411356559, 7.999100466992427),
        (26.3467092910579, 7.999100466992427),
        (23.674666255244595, 7.999100466992427),
        (28.869869600212795, 7.999100466992427),
        (23.816113159776002, 7.999100466992427),
        (26.488156195589305, 7.999100466992427),
    ],
]
# Maç başına (perf100, perf200).
GOLDEN_PERF = [
    ([1.3566171775602287, 1.0003249714044753, 1.0883338049168574, 1.274268526959783, 0.9219122832625279], [0.8991943108216354, 0.7614825093440165, 0.9366008925689737, 1.1340753770553815, 0.7991281989844348]),
    ([1.0, 1.0, 1.0, 1.0, 1.0], [1.0, 1.0, 1.0, 1.0, 1.0]),
    ([0.979610026653862, 0.8953868626500376, 0.9775732621254225, 1.2997193217973009, 0.9905083723409313], [1.0, 1.0, 1.0, 1.0, 1.0]),
    ([1.8761194029850745, 1.0, 1.185102763815882, 1.6855776444111026, 0.5], [1.1788304486276888, 0.8299603578623573, 1.0, 1.335704027034638, 1.0]),
    ([1.3064272096552039, 1.125406214255594, 1.0120566004083669, 1.121524183289893, 1.02739035407816], [0.7961240360680278, 0.8268531366800206, 0.8633740665308893, 1.0077581557454565, 0.8739102487305435]),
]
# Senaryo sonu: oyuncu başına (P_avg, mu_eff, score).
GOLDEN_EFFECTIVE = [
    (1.0420274905889269, 24.662944958780702, 0.6656435578034205),
    (1.0642720832619985, 25.664624607830106, 1.6673232068528243),
    (0.9884432487577357, 23.859181331312836, -0.13812006966444557),
    (1.1954482133249758, 28.858484987219363, 4.861183586242081),
    (0.943607263866111, 24.412859986383065, 0.4155585854057833),
    (1.001414858273143, 25.35790019686162, 1.3605987958843393),
    (1.1736607317684626, 27.27357754033809, 3.2762761393608066),
    (0.8897314985954681, 24.31343987898522, 0.3161384780079395),
    (1.0876624079877328, 26.018964409759988, 2.0216630087827063),
    (0.9871031533003991, 25.178586348403314, 1.1812849474260325),
]

# Sabit üçlüler: (mu, sigma, p_avg, mu_eff, score). İlk satır maçsız oyuncu:
# score TAM 0 (S=3 denkliği).
GOLDEN_EFFECTIVE_FIXED = [
    (25.0, 8.333333333333334, 1.0, 25.0, 0.0),
    (25.0, 8.333333333333334, 1.25, 28.75, 3.75),
    (31.7, 4.2, 0.5, 19.175, 6.574999999999999),
    (18.3, 6.05, 2.0, 38.325, 20.175000000000004),
    (40.0, 1.5, 1.37, 34.300000000000004, 29.800000000000004),
]


# --- Testler ------------------------------------------------------------------


def _as_tuples(ratings):
    return [(r.mu, r.sigma) for r in ratings]


def _run(version):
    """Senaryoyu koşar: (maç sonrası durumlar, maç perf'leri, oyuncu perf geçmişi, son durum)."""
    eng = Engine(version)
    ratings = [eng.default_rating() for _ in range(N_PLAYERS)]
    perf_hist = [[] for _ in range(N_PLAYERS)]
    after, perfs = [], []
    for t100, t200, winner, s100, s200, dur in MATCHES:
        new100, new200 = eng.update(
            [ratings[i] for i in t100], [ratings[i] for i in t200], winner, s100, s200, dur
        )
        for i, r in zip(t100, new100):
            ratings[i] = r
        for i, r in zip(t200, new200):
            ratings[i] = r
        after.append(_as_tuples(ratings))
        p100, p200 = eng.perf_scores(s100, s200, dur)
        perfs.append((list(p100), list(p200)))
        for i, p in zip(t100, p100):
            perf_hist[i].append(p)
        for i, p in zip(t200, p200):
            perf_hist[i].append(p)
    return eng, after, perfs, perf_hist, ratings


@pytest.mark.parametrize("version", [ACTIVE_VERSION, BASE_VERSION])
def test_default_rating_golden(version):
    r = Engine(version).default_rating()
    assert (r.mu, r.sigma) == GOLDEN_DEFAULT


@pytest.mark.parametrize("version", [ACTIVE_VERSION, BASE_VERSION])
def test_mu_sigma_golden_after_each_match(version):
    _, after, _, _, _ = _run(version)
    assert len(after) == len(GOLDEN_AFTER) == len(MATCHES)
    for m, (got, want) in enumerate(zip(after, GOLDEN_AFTER), start=1):
        assert got == want, f"{version}: maç {m} sonrası mu/sigma altın değerden saptı"


@pytest.mark.parametrize("version", [ACTIVE_VERSION, BASE_VERSION])
def test_perf_scores_golden(version):
    _, _, perfs, _, _ = _run(version)
    assert len(perfs) == len(GOLDEN_PERF)
    for m, (got, want) in enumerate(zip(perfs, GOLDEN_PERF), start=1):
        assert got == (list(want[0]), list(want[1])), f"{version}: maç {m} perf saptı"


def test_effective_golden_end_of_scenario():
    eng, _, _, perf_hist, ratings = _run(ACTIVE_VERSION)
    assert len(GOLDEN_EFFECTIVE) == N_PLAYERS
    for i, (r, hist, want) in enumerate(zip(ratings, perf_hist, GOLDEN_EFFECTIVE)):
        p_avg = sum(hist) / len(hist)
        e = eng.effective(r.mu, r.sigma, p_avg)
        assert (p_avg, e.mu_eff, e.score) == want, f"oyuncu {i} efektif skoru saptı"
        assert e.sigma == r.sigma


@pytest.mark.parametrize("mu,sigma,p_avg,mu_eff,score", GOLDEN_EFFECTIVE_FIXED)
def test_effective_golden_fixed_triples(mu, sigma, p_avg, mu_eff, score):
    e = Engine(ACTIVE_VERSION).effective(mu, sigma, p_avg)
    assert (e.mu_eff, e.sigma, e.score) == (mu_eff, sigma, score)
