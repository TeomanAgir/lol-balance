# Rating Contract — Performans Ağırlıklı Engine — v2

**Karar dayanağı:** Teoman, 2026-08-11 — "KDA, hasar payı gibi metrikler rating'e de girsin"
(CHANGE_REQUESTS kaydı). Bu, önceki "rating'e giren tek sinyal W/L'dir" kararının insan
tarafından revize edilmiş hâlidir.

**v2 eki (Teoman, 2026-08-11, ikinci karar):** W/L %50 + performans %50 doğrudan katkı —
`openskill-pl-blend50-v1` (bkz. "Harman engine" bölümü). AKTİF version budur.
`openskill-pl-perf-v1` (çarpan yaklaşımı) tanımlı ve geçerli kalır ama aktif değildir.

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

# Harman Engine — `openskill-pl-blend50-v1` (AKTİF)

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
   - `P_avg` aralığı [0.5, 2.0] olduğundan perf terimi mu_eff'e en fazla ±10 (fiilen
     ±%50 perf sapması ≈ ±5 puan) katar; W/L çekirdeğiyle aynı mertebede.
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
