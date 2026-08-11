# Change Requests

Agent'lar contract değişiklik önerilerini buraya ekler. Format:
- [agent-adı] [tarih] Sorun + önerilen değişiklik. Karar: (orkestratör doldurur)

- [lcu-collector] [2026-08-11] Backfill roster filtresi brief'e göre "backend `GET /players`'tan puuid'ler" ile kurulmalı, ancak `api_contract.md`'de `GET /players` yanıtında `puuid` alanı yok (yalnızca `riot_id`). Bloklayıcı değil: collector şimdilik `riot_id` ile eşleştiriyor ve yanıtta `puuid` alanı görürse ileriye dönük olarak onu da kullanıyor. Öneri: `GET /players` yanıtına opsiyonel `puuid` alanı eklensin (riot_id değişebilir/yeniden adlandırılabilir, puuid kalıcıdır). **Karar: [orkestratör, 2026-08-11] ONAY (teknik düzeltme).** Var olan DB kolonunu açığa çıkarır, davranış değişikliği değildir; puuid kalıcı kimlik olduğu için doğru eşleştirme anahtarıdır. `api_contract.md` §2 güncellendi; backend `PlayerOut`'a nullable `puuid` ekleyecek. Collector'ın mevcut "puuid görürse kullan" davranışı zaten uyumlu, collector'da değişiklik gerekmez.

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
  **Karar: [orkestratör, 2026-08-11] ÖRNEK EKLENDİ, ANCAK KANONİK ŞEKİL BACKEND'İN MEVCUT ŞEKLİDİR (teknik düzeltme).** Web UI'ın varsaydığı düz `mu_before/mu_after` yerine backend'in döndürdüğü iç içe `stats` + nullable `rating_change` nesnesi contract'a yazıldı (`api_contract.md` §3). Gerekçe: `rating_change: null`, void/ratingsiz maçı ifade edebilir — düz alanlar edemez; `stats` gruplaması ingest_contract ile tutarlıdır. Aksiyon: web UI `app.js` ve `mock_api.js` bu şekle uyarlanacak (backend değişmez).

- [orkestratör] [2026-08-11] Canlı backfill bulgusu: maçlar kronolojik sıra dışında ingest edilirse (ör. ikinci PC'den eski maç gelirse) incremental rating bayat kalıyor; düzeltmek manuel `POST /admin/replay` gerektiriyor. Collector tarafı eskiden-yeniye gönderimle düzeltildi (contract değişikliği değil). Backend'in sıra-dışı geliş tespitinde OTOMATİK replay koşması önerisi ise davranışsal değişikliktir. **Karar: [Teoman, 2026-08-11] ERTELENDİ** — "şu an gerek yok, not al, daha sonra bakacağız." Çoklu-PC kurulumu gündeme geldiğinde yeniden değerlendirilecek.
