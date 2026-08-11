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
- Gönderim kronolojiktir: adaylar önce toplanır, tarama bitince `played_at`'e göre
  eskiden-yeniye gönderilir; böylece incremental rating doğru sırayla işler ve
  backfill sonrası manuel `POST /admin/replay` gerekmez.
- Kazananı olmayan ve 300 saniyeden kısa süren maçlar **remake** sayılıp sessizce
  atlanır (hata değildir; backend zaten < 300 sn maçları void'ler).
- Bazı LCU sürümleri sayfalama indekslerini yok sayıp hep aynı listeyi döndürür;
  görülen gameId'ler izlenir ve yeni maç içermeyen ilk sayfada tarama sonlanır.

### Rol (position) backfill

```powershell
py -m collector backfill-positions --dry-run   # ne gönderileceğini göster
py -m collector backfill-positions             # backend'e yaz
```

`raw_archive/` altındaki **daha önce toplanmış** maçların rollerini tahmin edip canlı
backend'e yazar (LCU client'a ihtiyaç duymaz). Akış: her ham maç için rol tahmini →
`GET /matches` ile `source_game_id → match.id` → `GET /players` ile `puuid → player_id`
→ `PUT /matches/{id}/positions`. Sadece çözülebilen roller gönderilir (kısmi güncelleme),
`null` kalanlar gönderilmez; böylece web UI'dan elle düzeltilmiş bir rol ezilmez.
Backend'de bulunmayan maç / eşleşmeyen oyuncu uyarı yazdırır, tarama devam eder.
Komut idempotenttir, tekrar tekrar koşturulabilir.

> `GET /matches` limiti 200'dür: 200'den eski maçlar bu komutla güncellenemez.

## Rol tahmini (position)

LCU custom maçlarda gerçek rol atamasını **hiç vermez** ve ham veride görünen
`timeline.lane` alanı Riot'un tahminidir — custom'larda bozuktur (10 gerçek maçta 100
katılımcının 36'sı "JUNGLE" etiketli, oysa gerçek ormancı 20; "TOP" etiketi yalnızca 7
kez geçiyor). Buna karşılık **Smite** (spellId 11) kusursuz sinyaldir.

`role_infer.py` bu yüzden takım başına bir kısıt zinciri koşar:

| # | Rol | Kural |
|---|---|---|
| 1 | JUNGLE | Smite taşıyan |
| 2 | UTILITY | kalanlar içinde `lane=BOTTOM` + `role` destek türevi |
| 3 | BOTTOM | kalanlar içinde `lane=BOTTOM` + `role` carry türevi; yoksa tek kalan BOTTOM |
| 4 | MIDDLE | kalanlar içinde `lane=MIDDLE` |
| 5 | TOP | kalanlar içinde `lane=TOP` etiketli tam 1 kişi |
| 6 | eleme | atanmamış **tam 1 kişi** ve boş **tam 1 rol** kaldıysa eşle |

Her adım **tam bir aday** bulursa atar; 0 veya 2+ aday varsa o rol `null` kalır ve
adaylar havuzda kalır — **tahmin zorlanmaz**. Kısmi sonuç geçerlidir; eksik kalan
roller web UI'daki maç detayından düzeltilir (`PUT /matches/{id}/positions`).

- Ham veride **açık** bir position alanı (`selectedPosition`/`position`) varsa o kazanır.
- 10 gerçek maçta ölçüm: 20 takımın **19'u** 5/5 çözüldü (**98/100 pozisyon**), 20/20
  Smite taşıyıcısı doğru JUNGLE. Tek istisna 1734450310 / takım 200: kalan iki oyuncunun
  ikisi de `TOP/DUO` etiketli, ayırt edilemez → MIDDLE ve TOP null (bkz.
  `tests/test_role_infer.py`, ölçüm testle sabitlenmiştir).
- EOG bloğunda lane/role alanı yoktur → canlı modda genelde yalnızca JUNGLE çözülür;
  aynı maç match-history üzerinden (`--backfill` / `backfill-positions`) tam çözülür.

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
  __main__.py      # CLI: python -m collector [--backfill [--since ...] | backfill-positions]
  config.py        # .env + ortam değişkenleri
  lockfile.py      # LCU lockfile parse
  lcu.py           # LcuClient interface + HttpLcuClient (tek LCU bağımlılığı)
  models.py        # ingest contract pydantic modelleri (10 kişi / 5v5 garantisi)
  normalizer.py    # ham EOG / match-history → contract
  role_infer.py    # kısıt-çözümlü rol (position) tahmini
  sender.py        # backend POST + outbox retry
  roster.py        # backfill roster filtresi
  live.py          # canlı polling döngüsü
  backfill.py      # geçmiş tarama
  backfill_positions.py  # arşivdeki maçların rollerini backend'e yazma
  archive.py       # raw_archive yazımı
  fixtures/        # örnek LCU payload'ları (test verisi)
  tests/           # pytest
  raw_archive/     # (runtime) ham payload arşivi
  outbox/          # (runtime) gönderilemeyen payload'lar
  seed_roster.json # ilk backfill için elle doldurulan riot_id listesi
```
