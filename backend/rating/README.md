# rating — OpenSkill tabanlı rating & 5v5 dengeleme kütüphanesi

Saf Python kütüphanesi: DB, dosya ve network erişimi **yoktur**. Girdi/çıktı
yalnızca Python nesneleridir; backend (Agent 2) bu paketi import eder.

## Kurulum

```bash
pip install -e .          # runtime (tek bağımlılık: openskill)
pip install -e ".[dev]"   # + pytest, hypothesis
pytest
```

## Public API

```python
from rating import Engine, Rating, BalanceSuggestion, balance, enumerate_splits

engine = Engine()                      # version="openskill-pl-v1"
r = engine.default_rating()            # Rating(mu=25, sigma=25/3)
r.ordinal                              # mu - 3*sigma (muhafazakâr tek sayı)

new100, new200 = engine.update(team100, team200, winner=100)  # winner ∈ {100, 200}
p = engine.predict_win(team100, team200)                      # P(team100 kazanır)

suggestions = balance(ratings_10, top_n=3)  # en dengeli 5v5 ayrımları (index bazlı)
```

Takımlar tam 5 kişi olmalıdır; aksi halde `ValueError` (sistem yalnızca 5v5).

## Model seçimi gerekçesi

- **OpenSkill PlackettLuce** (Weng-Lin), default parametrelerle:
  `mu=25`, `sigma=25/3`, `beta=25/6`, `tau=25/300`.
- TrueSkill yerine OpenSkill: patent yükü yok, saf Python, çok oyunculu takım
  desteği yerleşik ve Plackett-Luce modeli takım bazlı sonuçlarla iyi çalışır.
- Rating güncellemesine giren **tek** bilgi maç sonucudur (W/L). KDA, gold vb.
  metrikler bilinçli olarak kapsam dışıdır: role göre yapısal olarak
  kıyaslanamazlar (support ile ADC'nin KDA'sı aynı ölçek değildir) ve rating'e
  girerlerse stat kasmayı teşvik ederler.
- `Rating.ordinal = mu - 3*sigma`: sıralama/gösterim için muhafazakâr tek sayı;
  yeni oyuncu (sigma yüksek) listenin tepesine sıçramaz.

### tau ve sigma davranışı

`tau > 0` olduğu için sigma her güncellemede mutlak olarak azalmak zorunda
değildir: tau, her maçta küçük bir belirsizlik enjekte ederek sigma'nın sıfıra
çöküp rating'in donmasını önler. Garanti edilen invariant şudur:

```
sigma_yeni <= sqrt(sigma_eski² + tau²)
```

Default sigma'dan başlayan güncellemelerde azalma her zaman gözlenir; sigma
tau dengesine yaklaştıkça salınım tau mertebesinde kalır. Testler bu doğru
invariant'ı doğrular (`tests/test_engine.py`).

## Version'lama kuralı

- Model parametreleri `version` string'ine bağlıdır (`openskill-pl-v1`).
- **Parametre değişikliği = yeni version string** (örn. `openskill-pl-v2`).
  Mevcut bir version'ın parametreleri asla değiştirilmez; böylece geçmiş
  maçların replay'i her zaman aynı rating'leri üretir.
- Bilinmeyen version → `ValueError` (sessizce farklı parametrelerle
  çalışmaktansa erken patlama).

## Dengeleme

- `enumerate_splits(10)`: 0..9 indekslerinin 126 benzersiz 5v5 ayrımı
  (ayna ayrımlar tekilleştirilmiş: 0 indeksi hep ilk takımda).
- `balance(ratings, top_n)`: 126 ayrımın hepsi için `predict_win` hesaplar,
  `imbalance = |p - 0.5|` değerine göre artan sıralar, ilk `top_n` öneriyi
  döner. Ayrımlar index bazlıdır; oyuncu listesinin sırasını çağıran korur.
