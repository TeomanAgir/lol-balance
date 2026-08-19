# Rating Contract — Performans Ağırlıklı Engine — v3

**Karar dayanağı:** Teoman, 2026-08-11 — "KDA, hasar payı gibi metrikler rating'e de girsin"
(CHANGE_REQUESTS kaydı). Bu, önceki "rating'e giren tek sinyal W/L'dir" kararının insan
tarafından revize edilmiş hâlidir.

**v2 eki (Teoman, 2026-08-11, ikinci karar):** W/L %50 + performans %50 doğrudan katkı —
`openskill-pl-blend50-v1` (bkz. "Harman engine" bölümü).
`openskill-pl-perf-v1` (çarpan yaklaşımı) tanımlı ve geçerli kalır ama aktif değildir.

**v3 eki (Teoman, 2026-08-16, üçüncü karar):** W/L etkisi %20'ye düşürüldü, performans %80 —
`openskill-pl-blend30-s2-v1` (bkz. "Harman Engine — blend30-s2" bölümü). AKTİF version budur;
rol evreni de aynı version'la işler. Karar, canlı 19 maçlık veriyle koşulan %50/%25/%20
simülasyonuna dayanır (CHANGE_REQUESTS kaydı). `openskill-pl-blend50-v1` tanımlı ve
geçerli kalır ama aktif değildir.

## Tasarım ilkeleri

1. **W/L birincil sinyal kalır.** Performans metrikleri maç sonucunun yönünü ASLA değiştirmez;
   yalnızca güncellemenin BÜYÜKLÜĞÜNÜ sınırlı bir bantta modüle eder. Kazanan takımın her üyesi
   her zaman puan kazanır, kaybedenin her üyesi her zaman kaybeder.
2. **Determinizm ve replay korunur.** Performans, yalnızca `match_participants`'ta saklanan
   statlardan hesaplanır; aynı veriyle replay her zaman aynı sonucu üretir.
3. **Null güvenliği.** Statı olmayan katılımcı (manuel giriş, eksik alan) nötr çarpan (1.0) alır.
4. **Rol normalizasyonu sınırlıdır.** Custom maçlarda `position` null geldiği için rol bazlı
   normalizasyon YAPILMAZ; bunun yerine beş farklı metrik harmanlanarak tek rolün lehine/aleyhine
   sistematik sapma azaltılır (hasar+gold carry'yi, vizyon support'u, KDA herkesi yakalar).
   Bu bilinçli bir ödünleşimdir (bkz. karar kaydı).

## Engine version

`openskill-pl-perf-v1`

- Taban model: OpenSkill PlackettLuce, `openskill-pl-v1` ile AYNI default parametreler
  (mu=25, sigma=25/3, beta=25/6, tau=25/300). Taban parametre "tuning" yasağı sürüyor.
- `openskill-pl-v1` değişmeden yaşamaya devam eder (rating_history'de yan yana).
- Performans katmanı parametreleri bu version string'ine DONDURULMUŞTUR; herhangi bir değişiklik
  yeni version string'i + insan onayı gerektirir:
  - `ALPHA = 0.5` (performansın çarpana etkisi)
  - `CAP = 0.3` (çarpan bandı: [0.7, 1.3])
  - `RATIO_MIN = 0.5`, `RATIO_MAX = 2.0` (bileşen oran sınırları)
  - `SHARE_BASELINE = 0.2` (takım içi eşit pay tabanı)

## Performans skoru (maç başına, katılımcı başına)

Girdi: katılımcının `stats` alanları (kills, deaths, assists, gold, cs, damage_to_champs,
vision_score) + maç `duration_s` + aynı maçtaki diğer 9 katılımcının statları.

### Bileşenler (her biri [RATIO_MIN, RATIO_MAX] aralığına kırpılır)

| # | Bileşen | Formül | Normalizasyon |
|---|---------|--------|---------------|
| 1 | KDA | `(kills + assists) / max(1, deaths)` | maçtaki 10 katılımcının KDA ortalamasına oran |
| 2 | Hasar payı | `damage_to_champs / kendi_takım_toplam_hasar` | `pay / SHARE_BASELINE` |
| 3 | Gold payı | `gold / kendi_takım_toplam_gold` | `pay / SHARE_BASELINE` |
| 4 | CS/dk | `cs / (duration_s / 60)` | maç ortalamasına oran |
| 5 | Vizyon | `vision_score` | maç ortalamasına oran |

Kurallar:
- Bir bileşen, katılımcıda ilgili stat null ise veya paydası 0/anlamsız ise (ör. maç
  ortalaması 0, takım toplamı 0, duration_s null/0) HESAPLANMAZ ve ortalamaya girmez.
- Ortalamalar yalnızca ilgili statı null olmayan katılımcılar üzerinden alınır.
- KDA bileşeni kills, deaths ve assists'in ÜÇÜNÜN DE null olmamasını gerektirir.
- Kırpma sırası: her bileşen oranı ÖNCE tek tek [RATIO_MIN, RATIO_MAX]'a kırpılır,
  `perf` ortalaması kırpılmış değerler üzerinden alınır.
- Not: RATIO_MIN=0.5 nedeniyle ham çarpan minimumu 0.75'tir; [0.7, 1.3] bandının alt
  sınırı yalnızca güvenlik kırpmasıdır (üst sınır 1.3 ise fiilen devreye girer). Bu
  asimetri bilinçlidir: kötü performans cezası, iyi performans ödülünden hafif tutulur.

### Skor ve çarpan

```
perf   = hesaplanabilen bileşen oranlarının aritmetik ortalaması   (hiçbiri yoksa 1.0)
carpan = clamp(1 + ALPHA * (perf - 1), 1 - CAP, 1 + CAP)           # [0.7, 1.3]
```

## Rating güncellemesi

1. Taban OpenSkill güncellemesi `openskill-pl-v1` ile birebir aynı şekilde hesaplanır:
   `delta_mu_i = mu_after_base_i - mu_before_i`.
2. Performans modülasyonu yalnızca mu'ya uygulanır:
   - Kazanan takım üyesi: `mu_after = mu_before + delta_mu * carpan`
     (iyi performans → daha çok kazanç)
   - Kaybeden takım üyesi: `mu_after = mu_before + delta_mu * (2 - carpan)`
     (iyi performans → daha az kayıp; `delta_mu` negatiftir)
3. `sigma_after` taban modelden AYNEN alınır (belirsizlik daralması performanstan bağımsız).
4. Statların tamamı null ise (ör. manuel maç) carpan=1.0 → sonuç `openskill-pl-v1`
   güncellemesiyle birebir aynıdır.

## API etkisi

- `rating` paketi: `Engine.update(team100, team200, winner, stats100=None, stats200=None)` —
  stats parametreleri opsiyonel; verilmezse davranış taban modelle aynı. Stats tipi rating
  paketinde tanımlanan saf bir dataclass'tır (`ParticipantStats`); DB/pydantic sızmaz.
  Maç süresi de geçirilir (CS/dk için).
- Backend: `apply_match_incremental` ve `replay`, match_participants + matches.duration_s'ten
  statları okuyup engine'e geçirir. Aktif version `ENGINE_VERSION` env ile seçilir
  (`openskill-pl-perf-v1` yapılınca replay şarttır).
- `POST /balance` ve leaderboard değişmez: mu/sigma üzerinden çalışırlar; hangi version'ın
  mu/sigma'sı kullanılacağını mevcut `engine_version` config'i belirler.
- Web UI/gösterim: bu contract gösterimi TANIMLAMAZ (api_contract'ın işi); rating_change
  şekli değişmez.

## Test yükümlülükleri (rating paketi)

- Nötr durum: tüm statlar null → `openskill-pl-perf-v1` sonucu, taban modelle birebir aynı.
- Yön garantisi: kazanan üye asla kaybetmez, kaybeden üye asla kazanmaz (uç statlarla dahi).
- Bant garantisi: etkin çarpan hiçbir koşulda [0.7, 1.3] dışına çıkmaz.
- Determinizm: aynı girdiyle iki çağrı aynı sonucu verir.
- Bileşen bazlı: tek bileşenli senaryolar (yalnız KDA hesaplanabilir vb.) doğru ortalanır.
- Sınır: deaths=0 (max(1,d) yolu), takım toplamı 0, duration_s null/0.

---

# Harman Engine — `openskill-pl-blend50-v1` (tanımlı, aktif değil — bkz. blend20)

**Amaç:** İyi oyuncunun bireysel gücü, takım şansından bağımsız olarak rating'in yarısını
belirlesin (Teoman: "W/L %50 + diğer işlevseller %50").

## Model

1. **W/L çekirdeği:** mu/sigma güncellemeleri `openskill-pl-v1` ile BİREBİR aynıdır
   (saf PlackettLuce, çarpan YOK). Gerekçe: performans hem güncelleme çarpanında hem
   harman teriminde sayılırsa çift sayım olur; blend50'de performansın tüm etkisi
   harman terimindedir.
2. **Maç performans skoru:** perf-v1'deki beş bileşen ve kurallarla aynı `perf` değeri
   (kırpılmış bileşen oranlarının ortalaması, [0.5, 2.0]; hesaplanamıyorsa 1.0).
   Bu değer her katılımcı-maç için `rating_history.perf_score` kolonuna yazılır.
3. **Kariyer performansı:** `P_avg(oyuncu) = AVG(perf_score)` — yalnız valid maçlar,
   yalnız bu engine_version satırları.
4. **Efektif rating (leaderboard + dengeleme bunu kullanır):**
   ```
   MU_0 = 25, K = 20, W = 0.5           # bu version'a dondurulmuş sabitler
   mu_eff  = (1-W) * mu + W * (MU_0 + K * (P_avg - 1))
   score   = mu_eff - 3 * sigma          # görünen/sıralanan değer
   ```
   - Hiç maçı olmayan oyuncu: P_avg = 1.0 kabul edilir → default'ta mu_eff = 25 (nötr).
   - `P_avg` aralığı [0.5, 2.0] olduğundan perf teriminin mu_eff katkısı en fazla +10,
     en az −5'tir (taban 0.5 olduğu için −10'a ulaşılamaz). Bu asimetri perf-v1'deki
     bilinçli asimetriyle tutarlıdır: kötü performans cezası ödülden hafiftir.
5. **Dengeleme:** `predict_win`, (mu_eff, sigma) çiftleriyle çağrılır. Sıralama ve
   quality tanımı değişmez.

## API etkisi (api_contract §2/§4/§5 ile birlikte okunur)

- `GET /players` ve `GET /leaderboard` rating nesnesi genişler:
  `rating: {mu, sigma, ordinal, perf_avg, score}` — `mu/sigma/ordinal` W/L çekirdeğinin
  ham değerleri (eski anlamları korunur), `perf_avg` = P_avg (maçsız oyuncuda 1.0),
  `score` = efektif rating. Leaderboard `score`'a göre sıralanır. Harman olmayan
  version'larda `perf_avg = null`, `score = ordinal` döner (alanlar her zaman mevcut).
- `POST /balance` yanıtındaki `engine_version` aktif version'ı söyler; öneriler
  score/mu_eff üzerinden hesaplanır.
- `rating_history` yeni kolon: `perf_score REAL` (nullable; migration 0002). Eski
  version satırlarında NULL kalır.
- Rating paketi API'si: `Engine.perf_scores(stats100, stats200, duration_s)` (per-maç
  skorlar) ve `Engine.effective(mu, sigma, p_avg)` (mu_eff + score) fonksiyonları;
  sabitler version'a bağlı.

## Kabul edilen ödünleşimler (insan kararı, 2026-08-11)

- Çok iyi performansla KAYBEDEN bir oyuncunun score'u, kötü performansla KAZANAN
  birininkini geçebilir (W/L çekirdeği yine de mu üzerinden farkı işler).
- Stat kasma teşviki teoride var; grup ölçeğinde kabul edildi. Bant/K/W "tuning"
  önerileri yine reddedilir — değişiklik = yeni version + insan onayı.

## Test yükümlülükleri (blend50)

- mu/sigma geçmişi `openskill-pl-v1` replay'iyle bit-bit aynı (çarpan yok kanıtı).
- perf_score determinizmi ve perf-v1 skor fonksiyonuyla birebir aynılık.
- Maçsız oyuncu: P_avg=1, default score = 0 civarı (25 - 3*25/3 = 0) — nötr.
- score monotonluğu: aynı mu/sigma'da P_avg arttıkça score artar.
- Efektif dengeleme: P_avg farkı predict_win'i beklenen yönde değiştirir.

---

# Harman Engine — `openskill-pl-blend20-v1` (tanımlı, aktif değil — bkz. blend30-s2)

**Karar dayanağı:** Teoman, 2026-08-16 — "sıralamada çok kötü oyuncular sadece W/L sayesinde
çok yukarıdalar"; W/L etkisi %20'ye düşürüldü, performans %80'e çıkarıldı. Karar öncesi
%50/%25/%20 senaryoları canlı verinin (19 maç, 18 oyuncu) tam replay simülasyonuyla
karşılaştırıldı; %50 kolonunun canlı leaderboard'la 18/18 birebir eşleşmesi doğrulama
ön koşuluydu (CHANGE_REQUESTS kaydı).

## Model

blend50 ile TEK fark harman ağırlığıdır; diğer her şey (W/L çekirdeği, perf_score
hesabı, P_avg tanımı, null/nötr kuralları, dengeleme mekaniği) blend50 bölümündeki
tanımlarla BİREBİR aynıdır:

1. **W/L çekirdeği:** mu/sigma güncellemeleri `openskill-pl-v1` ile birebir aynı
   (saf PlackettLuce, çarpan yok). blend50'nin mu/sigma geçmişiyle de bit-bit aynıdır —
   yalnız efektif skor katmanı değişir.
2. **Efektif rating:**
   ```
   MU_0 = 25, K = 20, W = 0.8           # bu version'a dondurulmuş sabitler
   mu_eff  = (1-W) * mu + W * (MU_0 + K * (P_avg - 1))
   score   = mu_eff - 3 * sigma          # görünen/sıralanan değer
   ```
   Version adındaki "20", W/L (mu) payını söyler: mu katkısı %20, performans katkısı %80.
   `W` konvansiyonu blend50 ile aynıdır (W = performans ağırlığı).
3. **perf_score / P_avg:** fonksiyonlar blend50 ile özdeş olduğundan değerler de özdeştir;
   `rating_history.perf_score` bu version satırlarına da aynı şekilde yazılır. P_avg
   yalnız AKTİF version'ın valid satırları üzerinden hesaplanır (mevcut kural).
4. **Maçsız oyuncu:** P_avg = 1.0 → mu_eff = 25, score = 0 civarı (nötr; blend50 ile aynı).
5. **Sabit dondurma kuralı sürer:** W/K/MU_0 "tuning"i bu version içinde yasaktır;
   herhangi bir oran değişikliği = yeni version string'i + insan onayı.

## API etkisi

blend50'nin "API etkisi" bölümü aynen geçerlidir (alan şekilleri değişmez):
`rating: {mu, sigma, ordinal, perf_avg, score}` yapısı, leaderboard'un `score` sıralaması,
`perf_score` kolonu, `Engine.perf_scores` / `Engine.effective` API'si — hepsi aynı; yalnız
`Engine.effective` bu version sabitleriyle hesaplar. Aktif version yine `ENGINE_VERSION`
config'iyle seçilir; `openskill-pl-blend20-v1`'e geçiş REPLAY GEREKTİRİR (iki evren).

## Test yükümlülükleri (blend20)

- mu/sigma geçmişi `openskill-pl-v1` (ve blend50) replay'iyle bit-bit aynı.
- perf_score fonksiyonu blend50'ninkiyle birebir aynı değerleri üretir.
- Efektif skor: bilinen (mu, sigma, P_avg) üçlülerinde beklenen mu_eff/score
  (ör. mu=25, P_avg=1 → mu_eff=25; P_avg=1.25 → mu_eff = 0.2*mu + 0.8*30).
- Maçsız oyuncu nötr; score monotonluğu (P_avg arttıkça score artar) korunur.
- blend50 testleri değişmeden geçmeye devam eder (version tanımlı kalır).

---

# Harman Engine — `openskill-pl-blend30-s2-v1` (AKTİF)

**Karar dayanağı:** Teoman, 2026-08-20 (GÖREV 27, modules/module-27-rework) — "kaybettiğinde
cezası çok azıcık daha fazla olmalı; maç kazanmanın rolünü %25 ya da %30'a çekebiliriz…
puanlar biraz daha aşağı yukarı oynamalı". Şikâyetin somut örneği maç #31: kaybeden takım
~0.1 kaybetti, kötü oynayan (perf 0.80) oyuncu **−0.02** aldı.

Karar öncesi canlı verinin (32 valid maç, 20 oyuncu) tam replay simülasyonu koşuldu;
doğrulama ön koşulu sağlandı (mevcut W ile yeniden üretilen leaderboard canlıyla **20/20
birebir**). Ölçülen kök neden İKİ parçalıdır: (a) W/L payı %20 olduğu için kaybetme cezası
küçük (−0.20), (b) `−3σ` teriminden gelen **oynama primi** maç başına ortalama **+0.18**
vererek cezanın ~%95'ini geri veriyor. Bu yüzden İKİ sabit birden değişti.

## Model

blend20 ile İKİ fark vardır; diğer her şey (W/L çekirdeği, perf_score hesabı, P_avg tanımı,
null/nötr kuralları, dengeleme mekaniği) blend50/blend20 bölümlerindeki tanımlarla BİREBİR
aynıdır:

1. **W/L çekirdeği:** mu/sigma güncellemeleri `openskill-pl-v1` ile birebir aynı (saf
   PlackettLuce). blend20/blend50'nin mu/sigma geçmişiyle de bit-bit aynıdır — yalnız
   efektif skor katmanı değişir.
2. **Efektif rating:**
   ```
   MU_0 = 25, K = 20, W = 0.70, S = 2      # bu version'a dondurulmuş sabitler
   mu_eff  = (1-W) * mu + W * (MU_0 + K * (P_avg - 1))
   score   = mu_eff - S * sigma            # görünen/sıralanan değer
   ```
   Version adındaki "30" W/L (mu) payını (%30), "s2" ise sigma katsayısını (S=2) söyler.
   `W` konvansiyonu öncekilerle aynıdır (W = performans ağırlığı, %70).
3. **perf_score / P_avg:** fonksiyonlar öncekilerle özdeştir; `rating_history.perf_score`
   bu version satırlarına da aynı şekilde yazılır. P_avg yalnız AKTİF version'ın valid
   satırları üzerinden hesaplanır.
4. **Maçsız oyuncu:** P_avg = 1.0 → mu_eff = 25, `score = 25 − 2*(25/3) ≈ 8.33`
   (blend20'de ≈ 0 idi). **Gösterim ölçeği kayar:** S=3 → S=2 geçişinde tüm puanlar
   yaklaşık **+7** yukarı kayar. Bu bilinçli kabul edilmiştir (Teoman, 2026-08-20);
   sıralama anlamı değişmez, yalnız mutlak sayılar büyür.
5. **Sabit dondurma kuralı sürer:** W/K/MU_0/S "tuning"i bu version içinde yasaktır;
   herhangi bir oran değişikliği = yeni version string'i + insan onayı.

## Beklenen etki (simülasyonla ölçüldü, canlı 32 maç)

| ölçüt | blend20 (eski) | blend30-s2 (yeni) |
|---|---|---|
| kaybedenin ortalama skor değişimi | −0.247 | **−0.407** |
| kaybeden takımda POZİTİF skor alan oranı | %30.6 | **%13.1** |
| maç #31'de perf 0.80 oyuncunun değişimi | −0.02 | **−0.18** |
| 1 galibiyetin nötrlediği mağlubiyet sayısı | 2.31 | **1.51** |
| sonuçtan bağımsız "oynama primi" (maç başına) | +0.18 | **+0.10** |

**Kabul edilen ödünleşimler:** (a) tüm puanlar ~+7 yukarı kayar; (b) düşük sigma
iskontosu azaldığı için az maçlı oyuncular biraz kayrılır; (c) 2026-08-16'da şikâyet edilen
"düşük perf + yüksek W/L" etkisi kısmen geri gelir ama kontrollüdür (%40'ta en yüksek
P_avg'lı oyuncu birinciliği kaybediyordu — %30 sınırında kalındı, bu yüzden %40 REDDEDİLDİ).
**Çözülmediği açıkça bilinen sorun:** "kronik kötü oynayan ceza almıyor" — perf cezası
oyuncunun KENDİ P_avg'ına göre işlediği için W ile çözülmez (ölçüldü: %40'ta hafifçe
kötüleşiyor). Çözümü perf'in mutlak tabana çekilmesi ya da P_avg'ın pencereli olmasıdır;
AYRI karar, bu version'ın kapsamı dışında.

## API etkisi

Alan şekilleri DEĞİŞMEZ: `rating: {mu, sigma, ordinal, perf_avg, score}`, leaderboard'un
`score` sıralaması, `perf_score` kolonu, `Engine.perf_scores` / `Engine.effective` API'si.
`ordinal` tanımı (`mu − 3*sigma`, W/L çekirdeğinin muhafazakâr tahmini) DEĞİŞMEZ — yalnız
harman `score` S=2 kullanır. Aktif version `ENGINE_VERSION` config'iyle seçilir;
`openskill-pl-blend30-s2-v1`'e geçiş **REPLAY GEREKTİRİR (iki evren)**.

## Test yükümlülükleri (blend30-s2)

- mu/sigma geçmişi `openskill-pl-v1` (ve blend20/blend50) replay'iyle bit-bit aynı.
- perf_score fonksiyonu öncekilerle birebir aynı değerleri üretir.
- Efektif skor: bilinen üçlülerde beklenen mu_eff/score
  (ör. mu=25, sigma=25/3, P_avg=1 → mu_eff=25, score≈8.33; P_avg=1.25 → mu_eff = 0.3*mu + 0.7*30).
- Maçsız oyuncu nötr (score ≈ 8.33); score monotonluğu (P_avg arttıkça score artar) korunur.
- **Önceki version testleri değişmeden geçmeye devam eder** (blend20/blend50/perf/pl
  tanımlı kalır).

---

# Rol Rating Evreni — aktif blend rol bazlı (GÖREV 0)

**Karar dayanağı:** Teoman, 2026-08-11 — `new_modules.md` GÖREV 0 + sohbet kararları
(CHANGE_REQUESTS kaydı). Rol verisi hibrittir: collector tahmini + manuel düzeltme.

## Model

1. **Ana rating DEĞİŞMEZ.** Rol evreni ayrı bir state uzayıdır: (player, role) başına
   mu/sigma. `role ∈ {TOP, JUNGLE, MIDDLE, BOTTOM, UTILITY}`. İki evren ayrı hesaplanır,
   birbirini asla etkilemez.
2. **Formül ana AKTİF engine ile BİREBİR aynı:** aktif harman version'ının sabitleri
   (bugün `openskill-pl-blend30-s2-v1`: MU_0=25, K=20, W=0.70, S=2), saf W/L PlackettLuce
   çekirdeği (çarpan yok), aynı default parametreler. `engine_version` string'i ana
   evrenin AKTİF version'ıyla AYNIDIR; evren ayrımı tabloyla yapılır
   (`role_rating_history`, bkz. db_schema migration 0003). Aktif version değişince
   rol evreni de aynı version'la REPLAY edilir.
3. **Uygunluk kuralı (deterministik):** valid bir maç rol evrenine yalnızca şu koşulda
   girer: 10 katılımcının 10'unda da `position` dolu VE her takımda 5 farklı rolün her
   birinden tam 1 tane. Aksi halde maç rol evrenine GİRMEZ (ana evren yine işler).
4. **Güncelleme:** uygun maçta her katılımcının O ROLDEKİ güncel rating'i (yoksa default
   prior mu=25, sigma=25/3) `Engine.update`'e girer — 5v5 yapısı, winner ve stats ana
   evrendekiyle aynı şekilde geçilir. Sonuç `role_rating_history`'ye yazılır;
   `perf_score` ana evrendeki maç perf değeriyle aynıdır (aynı stats, aynı fonksiyon).
5. **P_avg rol bazındadır:** `P_avg(player, role) = AVG(role_rating_history.perf_score)`
   — yalnız valid maçlar, yalnız bu engine_version, yalnız o rolün satırları.
   `mu_eff_role = (1-W)*mu_role + W*(25 + 20*(P_avg_role - 1))` (W = aktif version'ın
   perf ağırlığı; blend20'de 0.8), `score_role = mu_eff_role - 3*sigma_role`.
6. **Hiç oynanmamış rol:** default prior + P_avg=1.0 → score 0 (nötr).
7. **Position düzeltmesi** (`PUT /matches/{id}/positions`) rol evreninde replay tetikler;
   ana evren bit-bit değişmeden kalır. Rol replay'i her zaman `match_participants.position`'ın
   GÜNCEL değerinden okur (ham ingest payload'ından değil).

## Dengeleme — HER ZAMAN rol bazlı (eski salt-rating modu kaldırıldı)

1. Girdi: 10 oyuncu; her oyuncu için 5 rolün `(mu_eff_role, sigma_role)` çiftleri
   (backend harmanı uygular, rating paketine harmanlanmış Rating geçer — mevcut desenle
   tutarlı).
2. 126 ayrımın her birinde, HER TAKIM için 120 rol atamasından takım toplam
   `score_role`'ünü (= geçilen Rating'in ordinal'i) maksimize eden atama seçilir.
   Eşitlikte deterministik kırılım: roller `TOP < JUNGLE < MIDDLE < BOTTOM < UTILITY`
   sırasıyla gezilir, ilk bulunan maksimum korunur (strict-greater karşılaştırma).
3. `p_win`: seçilen atamadaki `(mu_eff_role, sigma_role)` çiftleriyle `predict_win`.
   `quality = 1 - 2*|p - 0.5|` (değişmedi). Öneriler quality azalan sırada.
4. Rating paketi API'si: `balance_roles(ratings_by_role, top_n)` — saf fonksiyon
   (matematik rating paketinde kalır). `ratings_by_role[i]` = i. oyuncunun
   `{role: Rating}` haritası (5 rolün tamamı zorunlu); dönen öneri takım index'leri +
   hizalı rol atamaları + p_win içerir.
5. Hiç rol verisi olmayan oyuncular her rolde nötr (score 0) olduğundan atamaları
   fiilen serbesttir — sistem az veriyle "dümdüz" çalışır, veri biriktikçe keskinleşir
   (kabul edilen davranış, Teoman 2026-08-11).
6. **Kısıtlı dengeleme (GÖREV 3, Teoman 2026-08-12):** rating paketi aynı optimizasyonun
   kısıtlı varyantını sunar: verilen iki oyuncu index'i KARŞI takımlara ayrılır ve her
   ikisi verilen role sabitlenir; kalan oyuncular/roller normal aramayla dağıtılır.
   Ayrım üretimi çifti ayıran ayrımlara daralır; atama aramasında sabit rol dışarıda
   tutulur. Determinizm, eşitlik kırılımı ve sıralama kuralları §2-3 ile aynıdır.
   API: `balance_roles`'un kısıt parametreli saf bir kardeş fonksiyonu (matematik
   rating paketinde kalır; api_contract "Nemesis maçı" bunu tüketir).

## Test yükümlülükleri (rol evreni)

- Uygun olmayan maç (herhangi bir position null / takımda rol seti bozuk) rol evrenine
  girmez; ana evren etkilenmez.
- Uygun maçta mu/sigma güncellemesi aktif blend çekirdeğiyle aynı mekaniktedir; replay
  deterministiktir (iki kez koş → bit-bit aynı).
- `balance_roles`: elle kurgulanmış senaryoda optimal atama; "sadece TOP oynamış" iki
  güçlü oyuncu, rol skorları ayrıştığında aynı takıma düşmez; determinizm (aynı girdi →
  aynı çıktı).
- Position güncellemesi → rol replay → tutarlı state; ana rating_history bit-bit
  değişmemiş.
