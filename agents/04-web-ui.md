# Agent 4 — Web UI

## Rol
Sistemin tek kullanıcı arayüzü: backend'in servis ettiği, build-tool'suz, tek sayfalık statik web uygulaması. `docs/api_contract.md`'nin ince bir istemcisidir; **hiçbir iş mantığı içermez** — rating, dengeleme, doğrulama tamamı backend'dedir.

## Ortam
- **Çalışma dizini: yalnızca `webui/`.** Çıktı: `webui/index.html` (+ istersen ayrı `app.js`, `style.css` — en fazla 3 dosya).
- Vanilla HTML/CSS/JS. **Framework, bundler, npm YOK.** Neden: tek sayfa + 4 görünüm için build zinciri bakım yükünden ibaret; backend bu dosyaları FastAPI `StaticFiles` ile `/` altından servis edecek (Agent 2'nin görevi), deploy = dosya kopyalamak.
- Backend hazır değilken geliştirme: api_contract'taki örnek response'ları dönen `webui/mock_api.js` (fetch'i saran basit stub) ile çalış; gerçek/mock seçimi tek satır config.
- Mobil uyumlu olmalı (VPS'e taşınınca telefondan kullanılacak) — responsive, dokunmatik dostu büyük seçim öğeleri.

## Görünümler
1. **Dengeleme (ana ekran):**
   - `GET /players`'tan roster listesi; her oyuncu `display_name (ordinal, N maç)` etiketli bir checkbox kartı.
   - Seçim sayacı görünür (`7/10` gibi); tam 10 seçilmeden "Dengele" butonu pasif.
   - "Dengele" → `POST /balance` → en iyi 3 öneri; her öneri iki takım sütunu + quality yüzdesi; en iyisi vurgulu.
2. **Leaderboard:** `GET /leaderboard` tablosu (display_name, ordinal, maç sayısı).
3. **Maç geçmişi:** `GET /matches?limit=20` — tarih, takımlar, kazanan, oyuncu başına rating değişimi (mu_after - mu_before). Satırda "void" butonu → `POST /matches/{id}/void` (onay dialogu ile — geri alınamaz replay tetikler).
4. **Manuel maç girişi (yedek yol):** collector çalışmadıysa kullanılacak form — kazanan taraf + iki takıma 5'er oyuncu seçimi; ingest contract'taki `source: "manual"` formatıyla `POST /ingest/match`.

## API key
- Tüm istekler `X-API-Key` header'ı ile. Key ilk açılışta bir input ile sorulur, `localStorage`'a yazılır; 401 dönerse tekrar sorulur. (Lokal kullanımda önemsiz, VPS'e taşınınca tek koruma katmanı bu — contract'taki bilinçli sadelik kararı.)

## Definition of done
- Mock API ile 4 görünüm de uçtan uca çalışıyor; 13-14 kişilik gerçekçi mock roster'la ekran görüntüsü alınabilir kalitede.
- 10'dan az/çok seçimle "Dengele" tetiklenemiyor (UI seviyesinde; asıl doğrulama zaten backend'de).
- Hata yanıtlarındaki `detail` alanı kullanıcıya aynen gösteriliyor (Türkçe geliyor).
- `webui/README.md`: mock ile çalıştırma, backend'e bağlama.

## Yasaklar
- İş mantığı yazmak yasak (ör. UI içinde dengeleme/ordinal hesabı — ordinal API'den gelir).
- `docs/` değiştirmek yasak; eksikler `docs/CHANGE_REQUESTS.md`'ye.
