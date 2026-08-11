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
- Bilinmeyen oyuncu → `404`.

## 3. Maçlar
```
GET  /matches?limit=20             → son maçlar, katılımcılar ve rating değişimleriyle
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
    "rating_change": {"mu_before": 25.0, "sigma_before": 8.333,
                      "mu_after": 26.1, "sigma_after": 7.9}
  }]
}]
```
- `stats` alanları nullable (ingest_contract ile tutarlı).
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

## 6. Hata formatı
Tüm hatalar: `{"detail": "insan-okur açıklama"}` + uygun HTTP kodu. Web UI bu `detail`'i kullanıcıya aynen gösterebilir, o yüzden mesajlar Türkçe yazılır.

## 7. Statik servis
Backend, `webui/` dizinindeki dosyaları `/` altından servis eder (FastAPI StaticFiles). API `/api/v1` prefix'inde kaldığı için çakışma yoktur. Deploy modeli: lokalde tek uvicorn prosesi; VPS'e taşıma = aynı Docker container'ı (backend + webui birlikte) çalıştırmak, ekstra web server gerekmez (istenirse önüne reverse proxy konulabilir, kapsam dışı).
