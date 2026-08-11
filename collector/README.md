# LCU Collector

LoL client'ın çalıştığı Windows PC'de koşan Python servisi. Biten **custom** maçların
end-of-game verisini LCU API'den çeker, `docs/ingest_contract.md` formatına normalize
eder ve backend'e POST eder.

## Kurulum

Gereksinim: Windows 10/11, Python 3.11+, LoL client kurulu.

```powershell
cd lol-balance
py -m pip install -r collector\requirements.txt
copy collector\.env.example collector\.env
notepad collector\.env   # LOL_DIR, BACKEND_URL, API_KEY doldurun
```

### .env alanları

| Alan | Zorunlu | Açıklama |
|---|---|---|
| `LOL_DIR` | evet | LoL kurulum dizini (client açıkken içinde `lockfile` oluşur), ör. `C:\Riot Games\League of Legends` |
| `BACKEND_URL` | evet | Backend adresi, sondaki `/` olmadan, ör. `http://127.0.0.1:8000` |
| `API_KEY` | evet | Backend ile paylaşılan `X-API-Key` değeri |
| `MIN_KNOWN` | hayır (6) | Backfill roster filtresi eşiği: 10 katılımcıdan en az kaçı bilinen oyuncu olmalı |
| `POLL_INTERVAL_S` | hayır (2.5) | Gameflow polling aralığı (saniye) |

Ortam değişkenleri `.env` dosyasındaki değerleri ezer.

## Çalıştırma

### Canlı mod

```powershell
cd lol-balance
py -m collector
```

- `gameflow-phase`'i poll'lar; `EndOfGame` fazına **geçişte** bir kez tetiklenir
  (aynı maç için gameId ile dedupe — restart'a dayanıklı, `raw_archive/` üzerinden).
- Yalnızca custom maçlar gönderilir (`gameType == "CUSTOM_GAME"` / `queueId == 0`);
  normal/ranked maçlar sessizce atlanır. Canlı modda roster filtresi **yoktur**;
  yanlışlıkla yakalanan bir custom, web UI'dan void edilebilir.
- Ham EOG payload'ı her durumda `collector/raw_archive/{gameId}.json` olarak saklanır.
- Client kapalıysa bekler, bağlantı koparsa yeniden bağlanır.

### Backfill modu

```powershell
py -m collector --backfill              # tüm geçmiş
py -m collector --backfill --since 2026-06-01
```

Kendi hesabının LCU match history'sini sayfalayarak geriye tarar; custom olan ve
**roster filtresinden** geçen maçları normalize edip gönderir.

- Bilinen oyuncu kümesi = backend `GET /players` (riot_id) ∪ `collector/seed_roster.json`.
- Sistem boşken ilk backfill için `seed_roster.json` dosyasını elle doldurun:
  ```json
  ["Teoman#TR1", "Kaan#TR1", "Mert#EUW"]
  ```
- Maçın 10 katılımcısından en az `MIN_KNOWN` (default 6) tanesi bilinen kümedeyse maç
  gönderilir. Bilinmeyen katılımcılar backend'de otomatik oyuncu kaydı oluşturur.
- Çift gönderim zararsızdır: idempotency backend'de `source_game_id` ile sağlanır;
  backfill'i istediğiniz kadar tekrar koşabilirsiniz.

## Teslimat garantisi (outbox)

Gönderim başarısız olursa (ağ hatası / 5xx) payload `collector/outbox/`'a JSON olarak
yazılır; başlangıçta ve her polling döngüsünde yeniden denenir, başarılı olunca dosya
silinir (at-least-once delivery). Backend'in **reddettiği** payload'lar (401/422) tekrar
denenmez, `collector/outbox/rejected/` altına taşınır — log'daki `detail` mesajına bakıp
sorunu giderdikten sonra dosyayı `outbox/`'a geri taşıyarak yeniden deneyebilirsiniz.

## Windows başlangıcında otomatik çalıştırma (Task Scheduler)

1. Başlat → "Task Scheduler" (Görev Zamanlayıcı) → **Create Task…**
2. **General:** Ad: `LoL Collector`. "Run only when user is logged on" seçili kalsın
   (LCU kullanıcı oturumunda çalışır).
3. **Triggers:** New… → Begin the task: **At log on** → OK.
4. **Actions:** New… →
   - Program/script: `py` (veya tam yol: `C:\...\Python312\python.exe`)
   - Add arguments: `-m collector`
   - Start in: repo kök dizini, ör. `C:\Users\teoma\OneDrive\Desktop\lol-balance`
5. **Settings:** "Stop the task if it runs longer than" işaretini KALDIRIN;
   "If the task fails, restart every" → 1 minute önerilir.
6. OK ile kaydedin. Test: göreve sağ tık → Run; log'lar görünmez çalışır, doğrulamak
   için `raw_archive/` ve backend'e düşen maçlara bakın.

## İşletme notları

- **Kapsam:** Collector yalnızca kurulu olduğu hesabın oynadığı (ve gördüğü) maçları
  yakalayabilir. Tam kapsam için grubun düzenli oynayan **2-3 oyuncusunun PC'sine**
  kurulması önerilir — idempotency sayesinde aynı maçın birden çok PC'den gönderilmesi
  güvenlidir, çift kayıt oluşmaz.
- **Canlı doğrulama:** LCU endpoint'leri ve alan adları patch'lerde değişebilir.
  Yeni bir kurulumda ilk custom maçtan sonra `raw_archive/`'daki ham JSON'a bakıp alan
  adlarının `collector/fixtures/` örnekleriyle uyuştuğunu doğrulayın; normalizer hem
  eski `UPPER_SNAKE` hem yeni `camelCase` stat anahtarlarını dener.
- Nadir bir pencerede (maç arşivlendi ama gönderim öncesi proses öldü) canlı maç
  atlanmış olabilir; `--backfill` bu boşluğu telafi eder.

## Geliştirme ve test

LCU'ya bağımlı her şey `LcuClient` interface'inin arkasında; testler
`collector/fixtures/` altındaki örnek JSON'larla, client'sız çalışır:

```powershell
cd lol-balance
py -m pytest collector -q
```

## Dizin yapısı

```
collector/
  __main__.py      # CLI: python -m collector [--backfill [--since ...]]
  config.py        # .env + ortam değişkenleri
  lockfile.py      # LCU lockfile parse
  lcu.py           # LcuClient interface + HttpLcuClient (tek LCU bağımlılığı)
  models.py        # ingest contract pydantic modelleri (10 kişi / 5v5 garantisi)
  normalizer.py    # ham EOG / match-history → contract
  sender.py        # backend POST + outbox retry
  roster.py        # backfill roster filtresi
  live.py          # canlı polling döngüsü
  backfill.py      # geçmiş tarama
  archive.py       # raw_archive yazımı
  fixtures/        # örnek LCU payload'ları (test verisi)
  tests/           # pytest
  raw_archive/     # (runtime) ham payload arşivi
  outbox/          # (runtime) gönderilemeyen payload'lar
  seed_roster.json # ilk backfill için elle doldurulan riot_id listesi
```
