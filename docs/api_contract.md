# Backend API Contract — v1

Base: `{BACKEND_URL}/api/v1` · Auth: tüm endpoint'lerde `X-API-Key` header (tek shared secret; arkadaş grubu ölçeği için yeterli, kullanıcı bazlı auth bilinçli olarak kapsam dışı).

## 1. Ingest
`POST /ingest/match` — bkz. `ingest_contract.md` (tek doğruluk kaynağı orası).

## 2. Oyuncular
```
GET  /players                      → [{id, display_name, riot_id, puuid,
                                       matches_played,
                                       rating: {mu, sigma, ordinal}}]   -- roster listesi; web UI'ın
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
`ordinal = mu - 3*sigma` (muhafazakâr güç tahmini; leaderboard bu değerle sıralanır).
Misafir/üye ayrımı yoktur; ingest'te bilinmeyen puuid otomatik oyuncu oluşturur (bkz. db_schema).

## 3. Maçlar
```
GET  /matches?limit=20             → son maçlar, katılımcılar ve rating değişimleriyle
POST /matches/{id}/void            → maçı void işaretler ve rating replay tetikler
```

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

## 4. Dengeleme (çekirdek özellik)
```
POST /balance
Body: {
  "player_ids": [1,2,3,4,5,6,7,8,9,10],
  "top_n": 3                        // en dengeli kaç alternatif dönsün (default 3)
}
→ 200 {
  "engine_version": "openskill-pl-v1",
  "suggestions": [
    {
      "team_100": [1,4,5,8,9],
      "team_200": [2,3,6,7,10],
      "p_win_team_100": 0.512,
      "quality": 0.988              // 1 - 2*|p_win - 0.5|; 1.0 = mükemmel denge
    }
  ]
}
```
- Tam 10 farklı `player_ids` zorunlu; aksi `422`.
- Rating'i olmayan oyuncu (0 maç) default prior (mu=25, sigma=25/3) ile hesaba katılır.
- Backend 126 ayrımın tamamını değerlendirir (brute force), `quality` azalan sırada döner.

## 5. Rating yönetimi
```
POST /admin/replay                 → tüm rating_history'yi siler, valid maçları
                                     kronolojik sırayla rating engine'den geçirir.
                                     Dönen: {matches_replayed, engine_version}
GET  /leaderboard                  → ordinal'a göre sıralı oyuncu listesi
```
`replay`, engine parametresi/versiyonu değiştiğinde ve `void` işlemlerinden sonra çağrılır. Ingest sırasındaki normal akışta replay DEĞİL, incremental update yapılır (son rating'in üstüne tek maç uygulanır) — replay O(n_maç) olduğundan sadece gerektiğinde koşar.

## 6. Hata formatı
Tüm hatalar: `{"detail": "insan-okur açıklama"}` + uygun HTTP kodu. Web UI bu `detail`'i kullanıcıya aynen gösterebilir, o yüzden mesajlar Türkçe yazılır.

## 7. Statik servis
Backend, `webui/` dizinindeki dosyaları `/` altından servis eder (FastAPI StaticFiles). API `/api/v1` prefix'inde kaldığı için çakışma yoktur. Deploy modeli: lokalde tek uvicorn prosesi; VPS'e taşıma = aynı Docker container'ı (backend + webui birlikte) çalıştırmak, ekstra web server gerekmez (istenirse önüne reverse proxy konulabilir, kapsam dışı).
