# Agent 1 — LCU Collector

## Rol
LoL client'ın çalıştığı Windows PC'de koşan, biten custom maçın end-of-game verisini LCU API'den çekip `docs/ingest_contract.md` formatına normalize ederek backend'e POST eden Python servisi.

## Ortam
- **Çalışma dizini: yalnızca `collector/`.** `docs/` read-only referans.
- Hedef runtime: Windows 10/11, Python 3.11+, LoL client kurulu.
- Geliştirme ortamın client'sız olabilir: LCU'ya bağımlı her fonksiyonu, `collector/fixtures/` altına koyacağın örnek EOG JSON'larıyla test edilebilir yaz (bağlantı katmanını interface arkasına al).
- Bağımlılıklar: `httpx` (hem LCU hem backend çağrıları), `pydantic` (normalize edilen modelin doğrulanması). Ağır framework yok.

## Teknik gerçekler (araştırmaya başlamadan bil)
1. LCU auth: client açıkken LoL kurulum dizinindeki `lockfile` dosyası `name:pid:port:password:https` formatındadır. İstekler `https://127.0.0.1:{port}` adresine, `riot:{password}` Basic auth ile, **TLS doğrulaması kapalı** (self-signed sertifika) yapılır.
2. İlgili endpoint'ler (patch'e göre değişebilir, ilk iş canlı doğrula):
   - `GET /lol-gameflow/v1/gameflow-phase` → `"EndOfGame"` fazını yakalamak için polling (2-3 sn aralık yeterli).
   - `GET /lol-end-of-game/v1/eog-stats-block` → maç istatistikleri.
   - Fallback: `GET /lol-match-history/v1/games/{gameId}` (kendi hesabının geçmişi, custom'lar dahil).
3. Custom maçlarda `position` alanı boş/güvenilmez gelebilir → contract gereği `null` gönder, tahmin etme.

## Görevler
1. `lockfile` bulucu: LoL kurulum yolunu config'ten al (`.env`: `LOL_DIR`), lockfile'ı parse et.
2. Gameflow polling loop'u: `EndOfGame` fazına geçişte bir kez tetiklenen handler (aynı maç için tek tetik — gameId ile dedupe).
3. Normalizer: ham EOG payload → ingest contract modeli. Ham payload'ı da `collector/raw_archive/{gameId}.json` olarak diske yaz (debug + ileride yeniden işleme için).
4. Sender: backend'e POST; 2xx dışı durumda payload'ı `collector/outbox/`'a yaz, başlangıçta ve her döngüde outbox'ı yeniden dene.
5. Filtre (canlı mod): yalnızca custom maçları gönder — EOG/match verisinde `gameType == "CUSTOM_GAME"` (queueId 0); alan adlarını fixture'dan doğrula. Normal/ranked maçlar sessizce atlanır.
6. **Backfill modu** (`python -m collector --backfill [--since YYYY-MM-DD]`): kendi hesabının LCU match history'sini sayfalayarak geriye tarar, `CUSTOM_GAME` olanları alır ve **roster filtresinden** geçenleri normalize edip gönderir. Roster filtresi:
   - Bilinen oyuncu kümesi = backend `GET /players`'tan puuid'ler ∪ lokal `collector/seed_roster.json` (riot_id listesi; sistem boşken ilk backfill için elle doldurulur).
   - Kural: maçın 10 katılımcısından en az `MIN_KNOWN` (config, default 6) tanesi bilinen kümede ise maç grubundur → gönder. Eşik 10 YAPILMAZ (yeni oyunculu maçları elemesin); bilinmeyen katılımcılar backend'de auto-register olur.
   - Aynı filtre canlı modda UYGULANMAZ (canlı yakalanan custom zaten bilinçli kurulmuş lobidir); yanlış-pozitif canlı custom olursa maç web UI'dan void edilir.
   - Backfill'in çift gönderimi zararsızdır: idempotency backend'de `source_game_id` ile sağlanır.
7. Çalıştırma: `python -m collector` ile başlayan tek proses; Windows'ta başlangıçta koşması için basit bir Task Scheduler talimatı README'ye yaz. README'ye ayrıca şu işletme notunu ekle: collector yalnızca kurulu olduğu hesabın oynadığı maçları görebilir; tam kapsam için 2-3 oyuncunun PC'sine kurulması önerilir (idempotency sayesinde çoklu gönderim güvenlidir).

## Definition of done
- Client'sız ortamda: fixture EOG JSON → contract'a uygun payload üreten normalizer testleri geçiyor (pytest).
- Contract'taki 10-katılımcı, team=100/200 kuralları normalizer çıktısında garanti.
- Outbox retry mekanizması testli (mock backend 500 → dosya yazılır → sonraki turda gönderilir → dosya silinir).
- `collector/README.md`: kurulum, .env alanları (`LOL_DIR`, `BACKEND_URL`, `API_KEY`), Task Scheduler adımları.

## Yasaklar
- `docs/` değiştirmek yasak; sorun varsa `docs/CHANGE_REQUESTS.md`'ye yaz ve dur.
- Backend'in iç yapısı hakkında varsayım yapma; tek arayüzün ingest contract.
