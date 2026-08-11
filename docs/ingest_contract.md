# Ingest Contract — LCU Collector → Backend — v1

Collector, LCU'nun end-of-game verisini **normalize ederek** aşağıdaki forma çevirir ve backend'e gönderir. Backend LCU'nun ham EOG formatını BİLMEZ; tek bildiği bu contract'tır. (Neden: LCU şeması patch'lerde değişebilir; kırılganlık collector'da izole kalır.)

## Endpoint
```
POST {BACKEND_URL}/api/v1/ingest/match
Header: X-API-Key: <shared secret, .env'den>
Content-Type: application/json
```

## Request body
```json
{
  "source": "lcu_eog",
  "source_game_id": "6874231955",
  "played_at": "2026-08-11T20:41:03Z",
  "duration_s": 1874,
  "winner_team": 100,
  "participants": [
    {
      "puuid": "abc-123-...",
      "riot_id": "Teoman#TR1",
      "team": 100,
      "position": "MIDDLE",
      "champion": "Ahri",
      "stats": {
        "kills": 7, "deaths": 2, "assists": 9,
        "gold": 13250, "cs": 201,
        "damage_to_champs": 24810, "vision_score": 21
      }
    }
  ]
}
```

## Kurallar
- `participants` tam 10 eleman içermelidir; 5 tanesi `team=100`, 5 tanesi `team=200`. Aksi halde backend `422` döner.
- `position` LCU'dan güvenilir alınamazsa `null` gönderilebilir (custom'larda position bazen boş gelir). `stats` alanları da nullable.
- **Rol tahmini (GÖREV 0):** LCU custom maçlarda gerçek rol atamasını hiç vermez; collector, position'ı KISIT-ÇÖZÜMLÜ tahminle doldurur (takım başına: Smite taşıyan → JUNGLE; Riot lane/role etiketleri → UTILITY/BOTTOM/MIDDLE; TOP = eleme ile kalan; herhangi bir adım belirsizse ilgili slotlar null bırakılır — tahmin ZORLANMAZ). Backend değeri olduğu gibi kaydeder; düzeltme `PUT /matches/{id}/positions` iledir (api_contract §3).
- Tüm zamanlar UTC ISO8601.
- Collector, gönderim başarısız olursa (network/5xx) payload'ı lokal `outbox/` klasörüne JSON olarak yazar ve bir sonraki çalışmada yeniden dener (at-least-once delivery). Idempotency backend tarafında `source_game_id` ile sağlanır, bu yüzden çift gönderim güvenlidir.

## Response
- `201 {"match_id": 42, "duplicate": false}` — yeni kayıt
- `200 {"match_id": 42, "duplicate": true}` — daha önce alınmış, işlem yok
- `401` — API key hatalı; `422` — şema ihlali (gövdede `detail` alanıyla)

## Manuel giriş
Aynı endpoint `source: "manual"` ve `source_game_id: "manual:<uuid4>"` ile de kullanılır (web UI'daki manuel maç girişi formu bunu çağırır). Manuel girişte `stats` ve `champion` alanları atlanabilir, `puuid` yerine `player_id` gönderilebilir:
```json
{ "player_id": 3, "team": 100, "position": "BOTTOM" }
```
Backend her participant'ta `puuid` VEYA `player_id`'den en az birini zorunlu tutar.
