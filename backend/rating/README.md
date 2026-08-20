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
- `openskill-pl-v1`'de rating güncellemesine giren **tek** bilgi maç sonucudur
  (W/L). `openskill-pl-perf-v1` bunun üzerine sınırlı bir performans
  modülasyonu ekler (aşağıya bakın); W/L her iki version'da da birincil
  sinyaldir ve sonucun yönünü yalnızca o belirler.
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

## `openskill-pl-perf-v1` — performans ağırlıklı version

Taban PlackettLuce güncellemesi `openskill-pl-v1` ile birebir aynı parametrelerle
hesaplanır; ardından her katılımcının mu deltası bir performans çarpanıyla
ölçeklenir (kazanan: `delta*carpan`, kaybeden: `delta*(2-carpan)`; sigma taban
modelden aynen alınır). Çarpan, beş bileşenin (KDA, hasar payı, gold payı,
CS/dk, vizyon — her biri [0.5, 2.0] aralığına kırpılmış oran) ortalamasından
`clamp(1 + 0.5*(perf-1), 0.7, 1.3)` ile türetilir; formüller ve sabitler
`docs/rating_contract.md`'de bu version'a dondurulmuştur. Null stat'lı bileşen
atlanır; hiç bileşen yoksa çarpan 1.0'dır ve sonuç taban modelle birebir
aynıdır — bu yüzden maç sonucunun yönü asla değişmez. Statlar
`update(..., stats100=, stats200=, duration_s=)` ile `ParticipantStats`
listeleri olarak geçirilir (`from rating import ParticipantStats`).

## Harman version'ları — blend50 / blend20 / **blend30-s2 (aktif)**

Her harman version'ında mu/sigma güncellemeleri `openskill-pl-v1` ile
**bit-bit aynıdır** (çarpan yok: performans hem güncellemede hem harmanda
sayılırsa çift sayım olur). Performansın tüm etkisi efektif rating
harmanındadır; sabitler version string'ine dondurulmuştur:

| Version | MU_0 | K | W (perf ağırlığı) | mu payı | S (sigma katsayısı) |
|---|---|---|---|---|---|
| `openskill-pl-blend50-v1` | 25 | 20 | 0.5 | %50 | 3 |
| `openskill-pl-blend20-v1` | 25 | 20 | 0.8 | %20 | 3 |
| `openskill-pl-blend30-s2-v1` (aktif) | 25 | 20 | 0.70 | %30 | **2** |

Version adındaki sayı W/L (mu) payını, `s2` eki sigma katsayısını söyler.
blend50 ↔ blend20 arasındaki TEK fark harman ağırlığıdır; blend30-s2'de İKİ
sabit değişir (W ve S). W/L çekirdeği, perf_score hesabı ve null/nötr kuralları
üç version'da da özdeştir.

```python
engine = Engine("openskill-pl-blend30-s2-v1")   # veya blend20 / blend50

# Maç başına perf skorları ([0.5, 2.0]; hesaplanamayan katılımcı 1.0).
# Skor tanımı versiyondan bağımsızdır ve perf-v1 çarpanına giren perf ile
# birebir aynıdır; her version'da çağrılabilir.
p100, p200 = engine.perf_scores(stats100, stats200, duration_s)

# Efektif rating (p_avg: kariyer perf ortalaması; maçsız oyuncuda 1.0):
# mu_eff = (1-W)*mu + W*(MU_0 + K*(p_avg-1)),  score = mu_eff - S*sigma
eff = engine.effective(mu, sigma, p_avg)   # EffectiveRating(mu_eff, sigma, score)
```

`Rating.ordinal` (= `mu - 3*sigma`) W/L çekirdeğinin muhafazakâr tahminidir ve
**S'ten etkilenmez**; S yalnızca harman `score`'a girer (`BlendParams.s`).

Leaderboard/dengeleme `score` (ve `mu_eff`, `sigma`) üzerinden çalışır;
`effective()` harman olmayan version'da `ValueError` verir. p_avg=1'de default
rating için mu_eff=25; score S=3'te 0, S=2'de ≈8.33 (nötr nokta aynı, yalnız
gösterim ölçeği kayar). Perf teriminin mu_eff sapması `W*K*(p_avg-1)` ile
sınırlıdır: blend50'de en fazla +10 / en az −5, blend20'de +16 / −8,
blend30-s2'de +14 / −7 (taban 0.5 olduğu için negatif uca ulaşılamaz).

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

### Rol atamalı dengeleme (`balance_roles`)

```python
from rating import ROLES, balance_roles   # ROLES = TOP, JUNGLE, MIDDLE, BOTTOM, UTILITY

# ratings_by_role[i] = i. oyuncunun {rol: Rating} haritası; 5 rolün TAMAMI zorunlu.
suggestions = balance_roles(ratings_by_role, top_n=3)
s = suggestions[0]
s.team100, s.positions100   # hizalı: team100[k] oyuncusu positions100[k] rolünde
s.p_team100, s.imbalance
```

- Her ayrımda, her takım için 120 rol atamasından atanan `Rating.ordinal`
  TOPLAMINI maksimize eden atama seçilir. Permütasyonlar `ROLES` sırasıyla
  gezilir ve strict-greater karşılaştırma kullanılır → eşitlikte ilk bulunan
  atama korunur (deterministik). Alt küme başına atama memoize edilir.
- `p_team100`, seçilen atamanın Rating'leriyle `predict_win`'dir; sıralama
  `balance()` ile aynıdır (`(imbalance, team100)` artan).
- Geçilen `Rating.mu`, çağıran tarafından ZATEN harmanlanmış `mu_eff_role`
  kabul edilir — fonksiyon harmanı bilmez (engine-agnostik, `balance()` deseni).
  Backend `Engine.effective(...)` ile harmanlayıp buraya geçirir.
- Doğrulama: tam 10 oyuncu, her oyuncuda tam 5 rol anahtarı, `top_n >= 1`;
  aksi `ValueError`. Spec: `docs/rating_contract.md` "Rol Rating Evreni → Dengeleme".
