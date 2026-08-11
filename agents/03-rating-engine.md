# Agent 3 — Rating Engine

## Rol
OpenSkill tabanlı, I/O'suz, saf Python rating kütüphanesi. DB bilmez, HTTP bilmez; girdi/çıktı sadece Python nesneleridir. Backend (Agent 2) bunu import eder.

## Ortam
- **Çalışma dizini: `backend/rating/`** — başka hiçbir dizine dokunma.
- Python 3.11+, tek bağımlılık: `openskill` (PyPI, Weng-Lin modelleri). Test: pytest + hypothesis (property-based testler için).

## Public API (Agent 2 ile mutabık — imzaları DEĞİŞTİRME)
```python
@dataclass(frozen=True)
class Rating:
    mu: float
    sigma: float
    @property
    def ordinal(self) -> float: ...   # mu - 3*sigma

class Engine:
    def __init__(self, version: str = "openskill-pl-v1"): ...
    def default_rating(self) -> Rating: ...                       # mu=25, sigma=25/3
    def update(self, team100: list[Rating], team200: list[Rating],
               winner: int) -> tuple[list[Rating], list[Rating]]  # winner ∈ {100, 200}
    def predict_win(self, team100: list[Rating],
                    team200: list[Rating]) -> float               # P(team100 kazanır)
```

## Model kararları (gerekçeleriyle, uygulamada sorgulamadan uygula)
- Model: OpenSkill **PlackettLuce**, default parametreler (mu=25, sigma=25/3, beta=25/6, tau=25/300). Bunlar `version` string'ine bağlanır; parametre değişikliği = yeni version string (replay uyumluluğu için).
- Rating güncellemesine giren tek bilgi maç sonucudur (W/L). KDA/gold gibi metrikler bilinçli olarak kapsam dışı — role göre yapısal olarak kıyaslanamazlar ve stat kasmayı teşvik ederler.
- 5'ten farklı takım boyutu → `ValueError` (bu sistem yalnızca 5v5).

## Görevler
1. `Rating`, `Engine` implementasyonu (openskill'in kendi Rating tipiyle dönüşüm içeride kalır, dışarı sızmaz).
2. Balancer yardımcıları (backend kullanacak ama matematik burada dursun):
   ```python
   def enumerate_splits(n: int = 10) -> Iterator[tuple[tuple[int,...], tuple[int,...]]]
   # index bazlı 126 benzersiz ayrım (ayna ayrımlar tekilleştirilmiş)
   def balance(ratings: list[Rating], top_n: int) -> list[BalanceSuggestion]
   ```
3. Testler:
   - Deterministiklik: aynı girdi → aynı çıktı.
   - Kazanan takımın her üyesinin mu'su artar, kaybedenin azalır; sigma her güncellemede azalır veya sabit kalır.
   - `predict_win` simetrisi: `predict_win(A,B) + predict_win(B,A) == 1` (tolerans 1e-9).
   - Yakınsama smoke testi: sabit "gerçek güç" ile simüle 200 maç sonrası ordinal sıralaması gerçek sıralamayla uyumlu (Spearman > 0.9).
   - `enumerate_splits(10)` tam 126 eleman ve her ayrımda kesişim boş.

## Definition of done
- Yukarıdaki testler geçiyor; paket `pip install -e .` ile kurulabiliyor (`pyproject.toml`).
- `backend/rating/README.md`: model seçimi gerekçesi + version'lama kuralı.

## Yasaklar
- Public API imzalarını değiştirmek yasak; ihtiyaç varsa `docs/CHANGE_REQUESTS.md`.
- DB, dosya, network erişimi yasak — saf kütüphane.
