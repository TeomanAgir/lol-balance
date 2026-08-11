# Rating Contract — Performans Ağırlıklı Engine — v1

**Karar dayanağı:** Teoman, 2026-08-11 — "KDA, hasar payı gibi metrikler rating'e de girsin"
(CHANGE_REQUESTS kaydı). Bu, önceki "rating'e giren tek sinyal W/L'dir" kararının insan
tarafından revize edilmiş hâlidir.

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
