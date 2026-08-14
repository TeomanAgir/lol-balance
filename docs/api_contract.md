# Backend API Contract — v1

Base: `{BACKEND_URL}/api/v1` · Auth: tüm endpoint'lerde `X-API-Key` header (tek shared secret; arkadaş grubu ölçeği için yeterli, kullanıcı bazlı auth bilinçli olarak kapsam dışı).

## 1. Ingest
`POST /ingest/match` — bkz. `ingest_contract.md` (tek doğruluk kaynağı orası).

## 2. Oyuncular
```
GET  /players                      → [{id, display_name, riot_id, puuid,
                                       matches_played,
                                       rating: {mu, sigma, ordinal,
                                                perf_avg, score}}]      -- roster listesi; web UI'ın
                                                                        -- seçim ekranının kaynağı
                                     -- puuid nullable'dır (manuel eklenen oyuncu ilk maçına kadar
                                     -- NULL). Collector'ın backfill roster filtresi puuid ile
                                     -- eşleştirir; riot_id değişebilir, puuid kalıcıdır.
                                     -- (CHANGE_REQUESTS: lcu-collector 2026-08-11)
POST /players                      → {display_name, riot_id?}  → 201 {id}
                                     -- oyuncuyu ilk maçından önce roster'a eklemek için;
                                     -- ilk maçında puuid, riot_id eşleşmesiyle bu kayda bağlanır
                                     -- (bkz. db_schema "Yeni oyuncu")
PATCH /players/{id}                → kısmi güncelleme (display_name)
```
`ordinal = mu - 3*sigma` (W/L çekirdeğinin muhafazakâr tahmini). `perf_avg` ve `score`
harman engine alanlarıdır (bkz. rating_contract.md "Harman Engine"): aktif version
`openskill-pl-blend50-v1` iken `score` efektif rating'dir ve **leaderboard `score` ile
sıralanır**; harman olmayan version'larda `perf_avg = null`, `score = ordinal`.
Misafir/üye ayrımı yoktur; ingest'te bilinmeyen puuid otomatik oyuncu oluşturur (bkz. db_schema).

**Rol ratingleri (GÖREV 0):** `GET /players` ve `GET /leaderboard` her oyuncuda ek olarak
`role_ratings` nesnesi döner — 5 anahtar her zaman mevcut:
```json
"role_ratings": {
  "TOP":     {"mu": 25.0, "sigma": 8.333, "perf_avg": 1.0, "score": 0.0, "matches": 0},
  "JUNGLE":  {"mu": 26.4, "sigma": 7.1,  "perf_avg": 1.12, "score": 6.3, "matches": 4},
  "MIDDLE":  {"...": "..."}, "BOTTOM": {"...": "..."}, "UTILITY": {"...": "..."}
}
```
Hiç oynanmamış rol default döner (mu=25, sigma=25/3, perf_avg=1.0, score=0.0, matches=0).
Harman olmayan aktif version'da ana rating kuralının aynısı geçerlidir: `perf_avg = null`,
`score = mu - 3*sigma` (rol çekirdeğinin ordinal'i). Spec: rating_contract.md "Rol Rating Evreni".

### Oyuncu profili (GÖREV 1)
```
GET /players/{id}/stats
→ 200 {
  "player": {"id": 3, "display_name": "Teoman", "riot_id": "Teoman#TR1"},
  "totals": {"matches": 10, "wins": 6, "losses": 4, "winrate": 0.6},
  "kda": {"kills_avg": 5.2, "deaths_avg": 3.1, "assists_avg": 7.4, "ratio": 4.06},
  "favorite_champion": {"champion": "Ahri", "matches": 4, "winrate": 0.75},
  "favorite_role": {"role": "MIDDLE", "matches": 5},
  "synergy": [
    {"player_id": 7, "display_name": "Fugori",
     "matches_together": 5, "wins_together": 4, "winrate": 0.8}
  ]
}
```
Kurallar (tümü yalnız `status='valid'` maçlar üzerinden; GÖSTERİM istatistiğidir,
rating'e girmez — Faz 2 pair-synergy rating modeli AYRI ve hâlâ kapsam dışıdır):
- `totals`: oyuncunun valid maç sayısı ve W/L; `winrate = wins / matches` (maçsız oyuncuda
  `matches: 0`, `winrate: null`).
- `kda`: yalnız kills/deaths/assists ÜÇÜ DE null olmayan maçlardan; `*_avg` maç başına
  ortalama, `ratio = (ΣK + ΣA) / max(1, ΣD)`. Hiç statlı maç yoksa `kda: null`.
- `favorite_champion`: champion null olanlar hariç en çok oynanan; eşitlikte ad alfabetik
  küçük olan; `winrate` o şampiyonla oynanan maçlardaki W/L. Hiç yoksa `null`.
- `favorite_role`: position null hariç en çok oynanan rol; eşitlikte kanonik sıra
  (TOP < JUNGLE < MIDDLE < BOTTOM < UTILITY); hiç yoksa `null`.
- `synergy`: AYNI TAKIMDA birlikte oynanan valid maçlar; en az 2 ortak maç; sıralama
  winrate azalan → matches_together azalan → display_name alfabetik; en fazla 3 kayıt
  döner (UI ilkini "en yüksek sinerji" olarak vurgular). Uygun kimse yoksa `[]`.
- `top_items` (GÖREV 14): oyuncunun `items` bilgisi DOLU valid maçlarındaki eşya
  sayımları — `[{"item_id": 3031, "matches": 5}]`, en fazla 10 kayıt, sıralama
  sayım azalan → item_id artan. Aynı maçta aynı eşya bir kez sayılır. Hiç items'lı
  maç yoksa `[]`. "Favori eşya" SEÇİMİ web UI'dadır: üretilmiş eşya haritasındaki
  `tags` ile trinket/tüketilebilir olanlar atlanır, kalan ilk kayıt favori gösterilir
  (backend eşya meta verisi bilmez).
- Bilinmeyen oyuncu → `404`.
- Hassasiyet: tüm oran/ortalama alanları (`*_avg`, `ratio`, `winrate`) 2 ondalığa
  yuvarlanır; sıralama ve eşitlik kırılımları yuvarlanmamış değerle yapılır.

### Rating tarihçesi (GÖREV 10)
```
GET /players/{id}/rating-history
→ 200 {
  "player_id": 3,
  "engine_version": "openskill-pl-blend50-v1",
  "points": [
    {"match_id": 12, "played_at": "2026-08-11T20:41:03Z", "win": true,
     "champion": "Ahri", "position": "MIDDLE",
     "score_after": 3.41,
     "stats": {"kills": 7, "deaths": 2, "assists": 9}}
  ]
}
```
Kurallar (salt-okur; rating'e etkisi yok):
- Yalnız `status='valid'` maçlar; sıra replay sort-key'iyle birebir aynı (kronolojik artan).
  Determinizm: `POST /admin/replay` sonrası yanıt bit-bit aynı kalmalıdır.
- `score_after` = o maç SONRASI efektif score (leaderboard `score` alanıyla aynı tanım):
  aktif engine harmansa `mu_eff - 3*sigma_after`, `mu_eff` o ana kadarki KÜMÜLATİF
  `P_avg` ile hesaplanır (o maç dahil, kronolojik önekteki perf_score'ların ortalaması;
  `perf_score` NULL satırlar ortalamaya katılmaz — rating_contract P_avg tanımıyla
  tutarlı). Hesap rating paketinin mevcut yardımcılarıyla yapılır, formül backend'e
  KOPYALANMAZ. Harman olmayan engine'de `score_after = mu_after - 3*sigma_after`.
- `win` = katılımcının takımı `winner_team` ile aynı mı. `champion`/`position` ve
  `stats` içindeki k/d/a alanları nullable'dır (ingest ile tutarlı); k/d/a'nın üçü de
  null ise `stats: null` döner.
- Hassasiyet: `score_after` 2 ondalığa yuvarlanır (leaderboard ile aynı).
- Bilinmeyen oyuncu → `404`; hiç valid maçı olmayan oyuncuda `points: []`.
- Zaman aralığı filtresi SUNUCUDA YOKTUR: yanıt tam tarihçedir, aralık seçimi web UI'da
  istemci tarafında yapılır (maç hacmi küçük; parametre gerekirse ayrı karar).

### Rozetler (GÖREV 11+12)
```
GET /players/{id}/badges
→ 200 {
  "player_id": 3,
  "badges": [
    {"key": "mvp", "count": 4, "last_match_id": 42},
    {"key": "win_streak_5", "count": 1, "last_match_id": 37}
  ]
}
```
Kurallar (salt-okur GÖSTERİM katmanı; rating'e etkisi yok; yalnız valid maçlar;
determinizm: `POST /admin/replay` sonrası yanıt aynı kalmalıdır):
- Yalnız `count > 0` rozetler döner; sıra SABİT katalog sırası: `mvp, vision, damage,
  cs_per_min, gold, deathless, comeback, win_streak_5, bench_3, versatile,
  veteran_10, veteran_25, veteran_50`. Bilinmeyen oyuncu → `404`; rozetsiz oyuncuda
  `badges: []`. `last_match_id` = rozeti son kazandıran maç (blok rozetlerinde bloğun
  son maçı, eşik rozetlerinde eşiği tamamlayan maç).
- **mvp** (GÖREV 12): maç başına, KAZANAN takımın aktif engine `rating_history`
  satırındaki en yüksek `perf_score`'lusu (yuvarlanmamış). Kırılım: perf → kills
  çok → assists çok → deaths az → player_id küçük. `perf_score` NULL satır aday
  değildir; kazanan takımda hiç perf yoksa o maçta MVP yoktur. Kırılımda NULL
  kills/assists en düşük, NULL deaths en yüksek sayılır (son anahtar player_id
  olduğundan sonuç her hâlükârda deterministiktir).
- **vision / damage / gold**: maçtaki 10 oyuncu içinde ilgili statın (vision_score /
  damage_to_champs / gold) en yükseği; NULL statlılar aday değildir; EŞİTLİKTE eşit
  olan HERKES rozeti alır; hiç non-null yoksa o maçta rozet yoktur. **cs_per_min**:
  aynı kural, metrik `cs / (duration_s/60)`; `duration_s` NULL veya `<= 0` olan maç
  bu rozet için dışıdır (diğer rekor rozetleri etkilenmez).
- **deathless**: `deaths == 0` (NULL değil) bitirilen her maç.
- **comeback**: oyuncu kazanan takımda + İKİ takımın da 5 oyuncusunun gold'u non-null
  + kazanan takımın gold toplamı kaybedenden KÜÇÜK.
- **win_streak_5**: oyuncunun kronolojik (replay sort-key) valid maçlarında her
  TAMAMLANAN ardışık 5 galibiyet bloğu 1 rozet; bloklar ayrıktır (6-9. galibiyetler
  yeni bloğu doldurur), mağlubiyet sayacı sıfırlar.
- **bench_3** ("Sonsuz Bench"): oyuncunun kronolojik valid maçlarında, KENDİ
  takımının TEK BAŞINA en düşük `perf_score`'lusu olduğu her tamamlanan ardışık
  3 maç bloğu 1 rozet (ayrık bloklar). Karşılaştırılabilirlik: kendi takımının
  5 oyuncusunun da perf'i non-null olmalıdır; karşılaştırılamayan maç seriyi KIRAR.
  En düşükte eşitlik varsa o maç bench SAYILMAZ ve seriyi kırar (kırılım uygulanmaz).
- **versatile**: 5 rolün hepsinde (position; NULL sayılmaz) ≥1 valid maç — tek seferlik.
- **veteran_10 / veteran_25 / veteran_50**: valid maç sayısı eşikleri — her biri tek
  seferlik, bağımsız (50 maçlıda üçü de görünür).
- Rozet adları/açıklamaları backend'de TUTULMAZ (yanıt yalnız `key` taşır); çeviri
  web UI i18n sözlüklerindedir (i18n_contract kuralı).

### Haftanın enleri (GÖREV 2)
```
GET /highlights/weekly
→ 200 {
  "window": {"start": "2026-08-05T21:00:00Z", "end": "2026-08-12T21:00:00Z",
             "fallback": false},
  "best_player":  {"player_id": 3, "display_name": "Konna Netlaka",
                   "score": 5.5, "matches_in_window": 4} | null,
  "rising_star":  {"player_id": 7, "display_name": "Fugori",
                   "delta": 2.31, "matches_in_window": 4} | null,
  "best_by_role": {
    "TOP":     {"player_id": 9, "display_name": "SauronunAgzi",
                "score": 2.9, "matches_in_window": 2} | null,
    "JUNGLE": "... | null", "MIDDLE": "... | null",
    "BOTTOM": "... | null", "UTILITY": "... | null"
  }
}
```
Kurallar (tümü valid maçlar; salt-okur, rating'e etkisi yok):
- **Pencere:** `end` = şimdi (UTC), `start` = end − 7 gün; maç dahil olma koşulu
  `start < played_at <= end`. Bu pencerede hiç valid maç yoksa `end` = en son valid
  maçın `played_at`'i kabul edilir ve `fallback: true` döner (ekran veri varken asla
  boş kalmaz). Hiç valid maç yoksa üç alan da `null`/`null`'lu döner.
- **best_player:** pencerede ≥1 maç oynamışlar arasında GÜNCEL `score`
  (leaderboard değeri) en yüksek olan.
- **rising_star ("yıldız rukisi"):** pencerede ≥1 maç oynamışlar arasında pencere
  içi ordinal artışı en yüksek olan: `delta = (mu−3σ) son pencere maçı SONRASI −
  (mu−3σ) ilk pencere maçı ÖNCESİ` (ana evren `rating_history` satırlarından,
  aktif engine_version; 2 ondalık). Negatif de olabilir — yine en yüksek döner.
- **best_by_role:** her rol için pencerede o rolde ≥1 maç oynamışlar
  (role_rating_history) arasında GÜNCEL rol `score`'u en yüksek olan; o rolde kimse
  oynamadıysa `null`.
- Eşitlik kırılımları (hepsinde): ilgili değer azalan → pencere maç sayısı azalan →
  `display_name` alfabetik.
- `matches_in_window` = ilgili oyuncunun penceredeki valid maç sayısı (rol
  kartlarında o roldeki maç sayısı).
- Hiç valid maç yokken `window` rolling pencereyi (`now−7g`, `now`) ve
  `fallback: false` döner (çapalanacak maç yok). `score` ve `delta` 2 ondalığa
  yuvarlanır; sıralama/kırılımlar yuvarlanmamış değerle.
- UI: kartlara tıklanınca oyuncu profiline gider (GÖREV 1 görünümü).

### Nemesis (GÖREV 3)
```
GET /nemesis
→ 200 {
  "all_time": <pair | null>,
  "weekly":   <pair | null>,
  "active":   "weekly" | "all_time" | null    // maç önerisinin kullanacağı çift
}
pair = {
  "role": "MIDDLE",
  "players": [{"player_id": 1, "display_name": "A", "wins": 3},
              {"player_id": 7, "display_name": "B", "wins": 2}],
  "encounters": 5,
  "closeness": 0.8            // 1 - 2*|wins[0]/encounters - 0.5|; 1.0 = tam başa baş
}
```
Kurallar (salt-okur; Teoman kararları 2026-08-12, CHANGE_REQUESTS):
- **Karşılaşma:** valid bir maçta KARŞI takımlarda ve İKİSİ DE AYNI (non-null) position.
  Aday birim (çift, rol) üçlüsüdür; `encounters` o roldeki karşılaşma sayısıdır (aynı
  iki oyuncu farklı rollerde karşılaşmışsa bunlar ayrı adaylardır).
- **Uygunluk eşiği:** `encounters >= 3`. `all_time` tüm valid maçlardan; `weekly`,
  `GET /highlights/weekly` pencere kuralının AYNISI ile (son 7 gün + boşsa son maça
  çapa) pencere içi karşılaşmalardan hesaplanır.
- **Sıralama (önce başa-başlık):** `closeness` azalan → `encounters` azalan → rol
  kanonik sıra (TOP < JUNGLE < MIDDLE < BOTTOM < UTILITY) → (küçük player_id, büyük
  player_id) artan. `players` dizisi player_id küçük olan önce gelir.
- **active:** `weekly` doluysa "weekly", değilse `all_time` doluysa "all_time",
  ikisi de boşsa `null`.
- `closeness` 2 ondalığa yuvarlanır; sıralama ham değerle.

## 3. Maçlar
```
GET  /matches?limit=20             → son maçlar, katılımcılar ve rating değişimleriyle
GET  /matches/{id}                 → tek maç; liste elemanıyla birebir aynı şekil,
                                     bilinmeyen id → 404 (GÖREV 10: profil grafiğinden
                                     maç detayına atlama)
PUT  /matches/{id}/items           → katılımcı envanterlerini yazar (GÖREV 14
                                     backfill-items; rating'e etkisi YOK, replay koşmaz)
POST /matches/{id}/void            → maçı void işaretler ve rating replay tetikler
PUT  /matches/{id}/positions       → katılımcı rollerini günceller (GÖREV 0)
```

`PUT /matches/{id}/positions` (rol düzeltme — web UI'daki maç detayından):
```json
{ "positions": { "1": "TOP", "4": "JUNGLE", "7": null } }
```
- Anahtarlar bu maçın `player_id`'leri (string; JSON nesne anahtarı), değerler
  `TOP|JUNGLE|MIDDLE|BOTTOM|UTILITY|null`. Kısmi güncelleme serbesttir.
- Maçta olmayan `player_id` veya geçersiz rol → `422`. Bilinmeyen maç → `404`.
- Başarıda rol evreni replay'i koşar (ana rating ETKİLENMEZ);
  yanıt: `{"updated": 3, "role_matches_replayed": 7}`.
- Ham `ingest_events` değişmez; güncellenen yalnız `match_participants.position`'dır
  (bkz. db_schema "küratörlü alan" notu).

`PUT /matches/{id}/items` (GÖREV 14 — collector `backfill-items` raw_archive'dan çağırır):
```json
{ "items": { "1": [6697, 6676, 3036, 3031, 1055, 2523, 3340], "4": [] } }
```
- Anahtarlar bu maçın `player_id`'leri (string), değerler 0-7 elemanlı int dizisi
  (ham sıra; `[]` = "bilgi var, envanter boş"). Kısmi güncelleme serbest; mevcut
  değerin ÜZERİNE yazar (ham arşiv otoritedir). Maçta olmayan `player_id` veya
  7'den uzun/int-olmayan dizi → `422`; bilinmeyen maç → `404`.
- Yanıt: `{"updated": 2}`. Rating'e etkisi yoktur, hiçbir replay tetiklenmez;
  ham `ingest_events` değişmez (güncellenen yalnız `match_participants.items_json`).

`GET /matches` yanıt örneği (CHANGE_REQUESTS: web-ui 2026-08-11 — kanonik şekil budur):
```json
[{
  "id": 42, "source_game_id": "6874231955", "played_at": "2026-08-11T20:41:03Z",
  "duration_s": 1874, "winner_team": 100, "status": "valid",
  "participants": [{
    "player_id": 1, "display_name": "Teoman", "team": 100,
    "position": "MIDDLE", "champion": "Ahri",
    "stats": {"kills": 7, "deaths": 2, "assists": 9, "gold": 13250,
              "cs": 201, "damage_to_champs": 24810, "vision_score": 21},
    "items": [6697, 6676, 3036, 3031, 1055, 2523, 3340],
    "rating_change": {"mu_before": 25.0, "sigma_before": 8.333,
                      "mu_after": 26.1, "sigma_after": 7.9}
  }]
}]
```
- `stats` alanları nullable (ingest_contract ile tutarlı). `items` nullable: NULL =
  "bilinmiyor" (eski exe/eski maç), `[]` = "bilgi var, boş" (GÖREV 14).
- `rating_change` **nullable**: maç `void` ise veya bu maç için rating satırı yoksa `null` gelir.
  Rating değişimi düz alan olarak DEĞİL, bu iç nesnede taşınır — `null`, "rating'e girmedi"
  durumunu ifade edebilmek için gereklidir.

## 4. Dengeleme (çekirdek özellik) — HER ZAMAN rol bazlı (GÖREV 0)
```
POST /balance
Body: {
  "player_ids": [1,2,3,4,5,6,7,8,9,10],
  "top_n": 3                        // en dengeli kaç alternatif dönsün (default 3)
}
→ 200 {
  "engine_version": "openskill-pl-blend50-v1",
  "suggestions": [
    {
      "team_100": [{"player_id": 1, "position": "TOP"},
                   {"player_id": 4, "position": "JUNGLE"},
                   {"player_id": 5, "position": "MIDDLE"},
                   {"player_id": 8, "position": "BOTTOM"},
                   {"player_id": 9, "position": "UTILITY"}],
      "team_200": [{"player_id": 2, "position": "TOP"}, "..."],
      "p_win_team_100": 0.512,
      "quality": 0.988              // 1 - 2*|p_win - 0.5|; 1.0 = mükemmel denge
    }
  ]
}
```
- Tam 10 farklı `player_ids` zorunlu; aksi `422`.
- Dengeleme HER ZAMAN rol bazlıdır (Teoman kararı 2026-08-11; eski salt-rating modu
  kaldırıldı). Her takım için rol ataması, rol score'ları toplamını maksimize edecek
  şekilde seçilir; `p_win` atanmış rollerin `(mu_eff_role, sigma_role)` değerleriyle
  hesaplanır. Algoritma spec'i: rating_contract.md "Rol Rating Evreni → Dengeleme".
- Hiç rol verisi olmayan oyuncu her rolde default prior (score 0, nötr) ile hesaba
  katılır — az veriyle sistem "dümdüz" çalışır.
- Backend 126 ayrımın tamamını değerlendirir (brute force), `quality` azalan sırada döner.

### Nemesis maçı (GÖREV 3)
```
POST /balance/nemesis
Body: {"player_ids": [10 farklı id], "top_n": 3}
→ 200 { /balance yanıtının aynısı } + "nemesis": {"source": "weekly"|"all_time",
                                                  "role": "MIDDLE",
                                                  "player_ids": [1, 7]}
```
- Aktif nemesis çifti yoksa (`GET /nemesis.active == null`) → `409` (Türkçe detail).
- Çiftin iki üyesi de `player_ids` içinde değilse → `422`.
- Kısıt: çift KARŞI takımlara ayrılır ve İKİSİ DE nemesis rolüne sabitlenir; kalan
  8 oyuncu ve rol slotu normal rol-bazlı optimizasyonla dağıtılır (rating_contract
  "Dengeleme" kuralları; ayrım uzayı çifti ayıran 70 ayrım, atama araması takım
  başına kalan 4 rolün 24 permütasyonu). Sıralama/quality tanımı değişmez.

## 5. Rating yönetimi
```
POST /admin/replay                 → HER İKİ evreni yeniden kurar: ana rating_history +
                                     role_rating_history (aktif engine_version için siler,
                                     valid maçları kronolojik sırayla yeniden işler).
                                     Dönen: {matches_replayed, role_matches_replayed,
                                             engine_version}
GET  /leaderboard                  → score'a göre sıralı oyuncu listesi
                                     (harman olmayan version'da score = ordinal;
                                      role_ratings alanı burada da döner, bkz. §2)
```
`replay`, engine parametresi/versiyonu değiştiğinde ve `void` işlemlerinden sonra çağrılır. Ingest sırasındaki normal akışta replay DEĞİL, incremental update yapılır (son rating'in üstüne tek maç uygulanır) — replay O(n_maç) olduğundan sadece gerektiğinde koşar.

**Sıra-dışı ingest auto-replay (2026-08-13):** Duplicate olmayan bir maç, rating'e girmiş mevcut en yeni valid maçtan daha ESKİ `played_at` ile gelirse (geriye dönük backfill senaryosu), backend incremental yerine HER İKİ evreni otomatik replay eder — sonuç, tüm maçlar kronolojik gelmiş gibi bire bir aynıdır (determinizm). Tetik koşulu, "incremental == replay" değişmezini koruyacak şekilde replay'in sıralama anahtarıyla hizalıdır. Ingest yanıt şekli DEĞİŞMEZ; elle `POST /admin/replay` yalnız engine değişimi ve olağandışı durumlar için kalır.

## 6. Collector sağlığı (GÖREV 13)
```
POST /health/heartbeat
Body: {"client_id": "Ali-PC", "version": "1.5.0", "outbox_pending": 0}
→ 200 {"ok": true}

GET /health/collectors
→ 200 [{
  "client_id": "Ali-PC", "last_seen": "2026-08-14T20:41:03Z",
  "version": "1.5.0", "outbox_pending": 0,
  "last_ingest_at": "2026-08-13T22:10:00Z", "last_ingest_game_id": "1734999999"
}]
```
Kurallar:
- Heartbeat: `client_id` zorunlu (string ≤64, trim sonrası boş olamaz → `422`);
  `version` ve `outbox_pending` opsiyonel/nullable. `last_seen` SUNUCUDA atanır
  (client saatine güvenilmez). Kayıt upsert'tir (`collector_health`, migration 0004).
- Collector heartbeat'i şu anlarda atar: LCU bağlantısı kurulunca, canlı modda her
  `HEARTBEAT_MINUTES` dakikada bir (varsayılan 5, `0` = kapalı) ve backfill/yetişme
  bitiminde. Heartbeat hatası collector'ı ASLA durdurmaz (logla, devam et).
- `GET /health/collectors`: `last_seen` azalan sıralı. `last_ingest_at` /
  `last_ingest_game_id` = o cihazın `matches.client_id` izinden en son maçı
  (yoksa `null`; void dahil — bu operasyonel izdir, rating süzgeci değil).
- Bu uçlar da `X-API-Key` ister; yanıtlar gösterim içindir, rating'e etkisi yoktur.

## 7. Hata formatı
Tüm hatalar: `{"detail": "insan-okur açıklama"}` + uygun HTTP kodu. Web UI bu `detail`'i kullanıcıya aynen gösterebilir, o yüzden mesajlar Türkçe yazılır.

## 8. Statik servis
Backend, `webui/` dizinindeki dosyaları `/` altından servis eder (FastAPI StaticFiles). API `/api/v1` prefix'inde kaldığı için çakışma yoktur.

**Data Dragon varlıkları (GÖREV 14, build-time vendoring — Teoman kararı):** Eşya/şampiyon
görselleri ve adları Riot Data Dragon'dan DEPLOY imajı kurulurken indirilir; canlı sitede
tarayıcı DIŞARI istek atmaz, repo'ya görsel commit'lenmez. Yerleşim (`webui/assets/ddragon/`):
- `manifest.json` — `{"version": "16.16.1"}` (sabitlenmiş patch; güncelleme = sürümü değiştir + redeploy)
- `items.json` — `{"<item_id>": {"name_tr", "name_en", "desc_tr", "desc_en", "tags": ["Trinket", ...]}}`
  (Data Dragon `item.json` tr_TR + en_US'ten üretilir; `desc_*` düz metin, HTML etiketleri temizlenir)
- `champions.json` — `{"<championName>": {"icon": "champion/<Name>.png"}}` (ad eşleşmesi
  participants.champion string'iyle)
- `item/<id>.png`, `champion/<Name>.png` — ikonlar
- `position/{top,jungle,middle,bottom,utility}.svg` — resmî pozisyon ikonları
  (Data Dragon'da yoktur; CommunityDragon `rcp-fe-lol-static-assets`'ten,
  DDRAGON_VERSION'ın major.minor'una sabitlenir — Teoman kararı: rol
  etiketleri resmî oyun simgeleriyle gösterilir)
İndirme betiği `deploy/fetch_ddragon.py`'dir; Dockerfile imaj kurulumunda koşturur. Yerel
geliştirmede varlıklar yoksa web UI YER TUTUCU gösterir (kırık görsel değil) — betik elle de
koşulabilir. Kaldırılmış/bilinmeyen eşya id'si de yer tutucuya düşer. Deploy modeli: lokalde tek uvicorn prosesi; VPS'e taşıma = aynı Docker container'ı (backend + webui birlikte) çalıştırmak, ekstra web server gerekmez (istenirse önüne reverse proxy konulabilir, kapsam dışı).
