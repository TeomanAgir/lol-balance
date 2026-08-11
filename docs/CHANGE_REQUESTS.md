# Change Requests

Agent'lar contract değişiklik önerilerini buraya ekler. Format:
- [agent-adı] [tarih] Sorun + önerilen değişiklik. Karar: (orkestratör doldurur)

- [lcu-collector] [2026-08-11] Backfill roster filtresi brief'e göre "backend `GET /players`'tan puuid'ler" ile kurulmalı, ancak `api_contract.md`'de `GET /players` yanıtında `puuid` alanı yok (yalnızca `riot_id`). Bloklayıcı değil: collector şimdilik `riot_id` ile eşleştiriyor ve yanıtta `puuid` alanı görürse ileriye dönük olarak onu da kullanıyor. Öneri: `GET /players` yanıtına opsiyonel `puuid` alanı eklensin (riot_id değişebilir/yeniden adlandırılabilir, puuid kalıcıdır). Karar: (orkestratör doldurur)

- [web-ui] [2026-08-11] `api_contract.md` §3'te `GET /matches?limit=20` yanıtı yalnızca sözle tarif edilmiş ("katılımcılar ve rating değişimleriyle"), alan bazlı örnek yok. Bloklayıcı değil: web UI (ve mock'u) şu şekli varsayıyor; backend farklı dönerse UI'daki alan adları güncellenmeli. Öneri: bu örnek contract'a eklensin.
  ```json
  [{
    "id": 42, "source_game_id": "6874231955", "played_at": "2026-08-11T20:41:03Z",
    "duration_s": 1874, "winner_team": 100, "status": "valid",
    "participants": [{
      "player_id": 1, "display_name": "Teoman", "team": 100,
      "position": "MIDDLE", "champion": "Ahri",
      "mu_before": 25.0, "mu_after": 26.1
    }]
  }]
  ```
  Karar: (orkestratör doldurur)

