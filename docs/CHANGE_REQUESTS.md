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
- [Teoman → orkestratör] [2026-08-11] Talep: KDA, hasar payı (maç toplamına oran) gibi metrikler sisteme girsin. Orkestratör seçenekleri sundu (yalnız gösterim / ayrı performans skoru / rating'e dahil). **Karar: [Teoman, 2026-08-11] RATING'E DE GİRSİN; metrikler: KDA, hasar payı, gold payı, CS/dk, vizyon.** Bu, "rating'e giren tek sinyal W/L" mimari kararının insan tarafından revizyonudur. Uygulama: yeni `openskill-pl-perf-v1` engine (W/L yönü korunur, performans güncelleme büyüklüğünü [0.7,1.3] bandında modüle eder) — tam spec: `docs/rating_contract.md`. CLAUDE.md karar #1 güncellendi. `openskill-pl-v1` değişmeden kalır.
- [Teoman → orkestratör] [2026-08-11] İkinci rating kararı: perf-v1'in çarpan yaklaşımı yetersiz bulundu ("iyi oyuncuyla aynı takımda oynayan bir anda tırmanıyor"); W/L %50 + performans %50 doğrudan katkı istendi. Orkestratör üç formül sundu; **Karar: [Teoman, 2026-08-11] HARMAN PUANI** — `openskill-pl-blend50-v1`: saf W/L mu/sigma çekirdeği + kariyer perf ortalamasından efektif rating (`mu_eff = 0.5*mu + 0.5*(25+20*(P_avg-1))`, `score = mu_eff - 3*sigma`). Stat kasma teşviki ve "iyi kaybeden > kötü kazanan" ihtimali ödünleşim olarak kabul edildi. Spec: rating_contract.md "Harman Engine"; api_contract rating nesnesi + leaderboard sıralaması, db_schema perf_score kolonu (migration 0002) güncellendi. CLAUDE.md karar #1 ikinci kez revize edildi.
