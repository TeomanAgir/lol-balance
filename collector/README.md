# LCU Collector

LoL client'ın çalıştığı Windows PC'de koşan Python servisi. Biten **custom** maçların
end-of-game verisini LCU API'den çeker, `docs/ingest_contract.md` formatına normalize
eder ve backend'e POST eder.

> **Arkadaşlara dağıtım (Python gerektirmez):** tek dosyalık
> `LoLBalanceCollector.exe` — derleme ve kullanım talimatı
> [`packaging/README.md`](packaging/README.md). Exe ilk açılışta `.env` yoksa
> sihirbazla sorar ve tüm dosyalarını **exe'nin yanına** yazar.

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
| `CATCHUP_DAYS` | hayır (14) | Canlı modda açılışta koşan oto-yetişme penceresi (gün); `0` = kapalı |
| `CLIENT_ID` | hayır (hostname) | Cihaz adı; ingest gövdesine ve heartbeat'e girer. Trim'lenir, 64 karaktere kırpılır. Sihirbaz sorar; eski kurulumlarda alan yoksa çalışma zamanında hostname kullanılır (sihirbaz yeniden koşmaz) |
| `HEARTBEAT_MINUTES` | hayır (5) | Canlı modda backend'e sağlık bildirimi aralığı (dakika); `0` = kapalı |

Ortam değişkenleri `.env` dosyasındaki değerleri ezer.

`.env` arama sırası: **uygulama dizini** → çalışma dizini (`./.env`). Uygulama dizini
kaynaktan çalışırken `collector/`, paketlenmiş exe'de exe'nin bulunduğu klasördür
(`config.app_dir()`). `raw_archive/`, `outbox/` ve `seed_roster.json` de aynı köke bağlıdır.

### Kurulum sihirbazı

`.env` hiç yoksa (ve gerekli alanlar ortam değişkenlerinde de yoksa) program ilk
açılışta interaktif olarak sorar: backend adresi (varsayılan canlı URL), API anahtarı
(zorunlu), LoL klasörü — sonuncusu önce kayıt defteri → Riot metadata → bilinen
yollar sırasıyla otomatik aranır, bulunursa yalnızca onaylatılır — ve cihaz adı
(`CLIENT_ID`; varsayılan öneri bilgisayar adı, Enter = kabul). Sihirbazı sonradan
tekrar çalıştırmak için `--setup`.

Her başlangıçta backend'e hızlı bir `GET /api/v1/players` doğrulaması atılır; yanlış
anahtar/adres ilk saniyede Türkçe raporlanır (program bu yüzden durmaz).

## Çalıştırma

### Canlı mod

```powershell
cd lol-balance
py -m collector
```

- `gameflow-phase`'i poll'lar; `EndOfGame` fazına **geçişte** bir kez tetiklenir
  (aynı maç için gameId ile dedupe — restart'a dayanıklı, `raw_archive/` üzerinden).
- Yalnızca custom maçlar gönderilir. Karar `gameType == "CUSTOM_GAME"` ile verilir;
  `queueId == 0` yalnızca fallback'tir ve **gerçek veride güvenilmezdir** (canlı EOG
  bloğunda `queueId` alanı hiç gelmez ve `queueType` "NORMAL" yazar; match-history
  liste sayfasında custom'lar 3110/3100/3130 gibi queueId'lerle döner).
  Normal/ranked maçlar sessizce atlanır. Canlı modda roster filtresi **yoktur**;
  yanlışlıkla yakalanan bir custom, web UI'dan void edilebilir.
- Ham EOG payload'ı her durumda `collector/raw_archive/{gameId}.json` olarak saklanır.
- `played_at` maçın **gerçek bitiş anıdır**: payload'daki `endOfGameTimestamp`'ten okunur
  (gerçek LCU şeması bu alanı taşır). Böylece proses gecikmesi, outbox retry ya da geç
  işleme maç zamanını kaydırmaz. Alan gelmeyen eski sürümlerde yakalama anına düşülür.
- Client kapalıysa bekler, bağlantı koparsa yeniden bağlanır.
- **Oto-yetişme:** LCU'ya her bağlandığında (ilk bağlantı ve yeniden bağlanmalar dahil)
  canlı döngüye geçmeden önce son `CATCHUP_DAYS` gün (varsayılan 14, `0` = kapalı)
  için sınırlı bir backfill koşar — collector kapalıyken oynanan custom'lar da
  toplanır. Aynı roster filtresi ve kronolojik gönderim kuralları geçerlidir; çift
  gönderim idempotency sayesinde zararsızdır. Yetişme herhangi bir nedenle
  başarısız olursa (backend erişilemez, roster boş, LCU hatası) **canlı mod
  engellenmez**: hata loglanır, döngü başlar.
- **Cihaz kimliği ve heartbeat (GÖREV 13):** gönderilen her maç gövdesinde üst
  seviye `client_id` alanı bulunur (`.env` `CLIENT_ID`, yoksa hostname). Ayrıca
  `POST /health/heartbeat` ile `{client_id, version, outbox_pending}` bildirilir:
  LCU'ya bağlanınca, canlı modda her `HEARTBEAT_MINUTES` dakikada (varsayılan 5,
  `0` = kapalı) ve backfill/yetişme bitiminde. Heartbeat **hiçbir koşulda** maç
  toplamayı engellemez: her hata loglanıp yutulur ve başarısız heartbeat
  `outbox/`'a yazılmaz (orası yalnız maç payload'ları içindir). GÖREV 13
  öncesinden kalmış `client_id`'siz outbox dosyaları olduğu gibi gönderilir.

### Backfill modu

```powershell
py -m collector --backfill              # tüm geçmiş
py -m collector --backfill --since 2026-06-01
py -m collector backfill --since 2026-06-01   # aynısı (tiresiz alias)
```

Kendi hesabının LCU match history'sini sayfalayarak geriye tarar; custom olan ve
**roster filtresinden** geçen maçları normalize edip gönderir.

- Bilinen oyuncu kümesi = backend `GET /players` (riot_id) ∪ `collector/seed_roster.json`.
- `seed_roster.json` repo'da **boş** (`[]`) gelir; şablonu
  [`seed_roster.example.json`](seed_roster.example.json) dosyasındadır. Backend'de
  oyuncu varsa dosyaya hiç dokunmanız gerekmez (küme backend'den gelir); dosya boş
  ya da hiç yoksa collector düzgün çalışır.
- Sistem tamamen boşken (backend'de de oyuncu yokken) ilk backfill için dosyayı
  elle doldurun — düz riot_id listesi:
  ```powershell
  copy collector\seed_roster.example.json collector\seed_roster.json
  ```
  ```json
  ["Player01#TR1", "Player02#TR1", "Player03#EUW"]
  ```
  > Bu dosya arkadaşlarınızın gerçek Riot ID'lerini taşır; public bir fork'a
  > doldurulmuş halde commit etmeyin.
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

`raw_archive/` altındaki **daha önce toplanmış** maçların rollerini çözüp canlı
backend'e yazar (LCU client'a ihtiyaç duymaz). Arşivde iki format bulunur ve ikisi de
desteklenir: backfill'den gelen match-history kaydında açık position alanı yoktur
(tahmin zinciri koşar), canlı EOG bloğunda vardır (`selectedPosition` doğrudan okunur,
10/10 rol; bazı patch'lerde boş string gelir — o zaman `detectedTeamPosition` devralır,
bkz. "Rol tahmini"). Akış: her ham maç için rol çözümü →
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

- **Rol önceliği üç katmandır** (ingest_contract "Rol önceliği", 2026-08-13 revizyonu):
  (a) ham veride **açık** bir position alanı (`selectedPosition`/`position`, boş olmayan)
  varsa o kazanır; (b) açık alan boşsa Riot'un kendi tespiti **`detectedTeamPosition`**
  kullanılır — bazı patch'lerde custom draft EOG'unda `selectedPosition` 10/10 boş string
  gelirken bu alan 10/10 dolu gelir (kanıt: gameId 1734940206, anonimleştirilmiş fixture
  `eog_custom_detected.json`); yalnızca kanonik rol adları kabul edilir, tanınmayan değer
  zincire düşer; (c) ikisi de yoksa kısıt zinciri. Boş string hiçbir katmanda değer
  değildir. Bu öncelik kuralı tek yerde, `normalizer.positions_from_raw()` içinde durur;
  hem normalize yolu hem `backfill-positions` onu kullanır.
- 10 gerçek maçta ölçüm: 20 takımın **19'u** 5/5 çözüldü (**98/100 pozisyon**), 20/20
  Smite taşıyıcısı doğru JUNGLE. Tek istisna 1734450310 / takım 200: kalan iki oyuncunun
  ikisi de `TOP/DUO` etiketli, ayırt edilemez → MIDDLE ve TOP null (bkz.
  `tests/test_role_infer.py`, ölçüm testle sabitlenmiştir).
- EOG bloğunda lane/role alanı yoktur → tahmin zinciri orada yalnızca JUNGLE'ı çözer.
  Ancak **gerçek EOG bloğu açık `selectedPosition` alanı taşır** (2026-08-11 tarihli
  canlı maç 1734664864'te 10/10 dolu ve `detectedTeamPosition` ile tutarlı), bu yüzden
  canlı modda pozisyonlar pratikte tahmine hiç düşmeden tam gelir; zincir yalnızca
  emniyet ağıdır. Match-history yolunda (`--backfill` / `backfill-positions`) açık alan
  yoktur, orada zincir çalışır.

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
- **Canlı doğrulama (TAMAMLANDI):** EOG yolu 2026-08-11 gecesi oynanan gerçek custom
  maçla (gameId **1734664864**) uçtan uca doğrulandı: 10/10 pozisyon, 7/7 stat alanı,
  kazanan takım ve süre doğru işlendi. Ham payload `fixtures/eog_custom_real.json`
  olarak dondurularak `tests/test_real_fixtures.py::TestNormalizeRealEog` ile regresyona
  kapatıldı. Match-history yolu daha önce `mh_game_custom_real.json` (gameId 1734450310)
  ile doğrulanmıştı. Artık **bekleyen canlı doğrulama yoktur**.
- **Patch kırılganlığı:** LCU endpoint'leri ve alan adları patch'lerde yine de
  değişebilir. Yeni bir kurulumda ilk custom maçtan sonra `raw_archive/`'daki ham JSON'a
  bakıp alan adlarının `collector/fixtures/*_real.json` örnekleriyle uyuştuğunu
  doğrulayın; normalizer hem eski `UPPER_SNAKE` hem yeni `camelCase` stat anahtarlarını
  dener. Uyuşmazlık görürseniz yeni ham maçı fixture olarak ekleyip testi çoğaltın.
- Nadir bir pencerede (maç arşivlendi ama gönderim öncesi proses öldü) canlı maç
  atlanmış olabilir; `--backfill` bu boşluğu telafi eder.

## Geliştirme ve test

LCU'ya bağımlı her şey `LcuClient` interface'inin arkasında; testler
`collector/fixtures/` altındaki örnek JSON'larla, client'sız çalışır:

```powershell
cd lol-balance
py -m pytest collector -q
```

Fixture'lar iki sınıftır:

| Dosya | Ne belgeler |
|---|---|
| `eog_custom.json`, `mh_game_custom.json`, ... | **sentetik** — yapıyı ve uç durumları (eksik stat, ms süre, dengesiz takım) belgeler |
| `eog_custom_real.json` (gameId 1734664864) | **gerçek şema** canlı EOG bloğu: UPPER_SNAKE statlar, dolu `selectedPosition`, `championName`, `queueId` yokluğu |
| `eog_custom_detected.json` (gameId 1734940206) | **gerçek şema** EOG bloğu (yeni patch şekli): `selectedPosition` 10/10 BOŞ string, `detectedTeamPosition` 10/10 dolu — tespit katmanının kanıt maçı |
| `mh_game_custom_real.json` (gameId 1734450310) | **gerçek şema** match-history kaydı: camelCase statlar, açık position yok |
| `mh_list_page_real.json`, `champion_summary_real.json` | **gerçek** liste sayfası / champion özeti |

**Anonimlik (GÖREV 7, repo public):** fixture'ların hiçbirinde gerçek PII yoktur.
`*_real.json` ve `eog_custom_detected.json` dosyalarında yalnız KİMLİKLER
deterministik olarak sahtelenmiştir: puuid `00000000-0000-4000-8000-{N:012d}`,
riot_id `PlayerNN#FAKE`, summonerId `1000+N`, accountId `2000+N`; chat JWT'leri
`FAKE.FAKE.FAKE`. Aynı kişi dosyalar arasında aynı `N`'yi taşır
(`eog_custom_detected.json` başka bir maç olduğu için 01-10'u, ortak grup maçları
11+'yı kullanır). Şema/alan sırası, gameId'ler, zaman damgaları, statlar,
şampiyon/spell/position alanları **hiç değişmedi** — gerçek şemayı belgeleme
amacı korunur. Bu değişmezler `tests/test_real_fixtures.py::TestFixtureAnonymity`
ile kilitlidir. `champion_summary_real.json` Riot'un statik şampiyon verisidir,
kimlik taşımaz.
Sentetik fixture'lar mevcut davranışı sabitler — gerçek şemayla farkları bilinçlidir,
gerçek doğrulama `tests/test_real_fixtures.py` üzerinden yapılır.

## Dizin yapısı

```
collector/
  __main__.py      # CLI: python -m collector [--backfill|backfill [--since ...] | backfill-positions]
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
  catchup.py       # canlı moddan önce koşan sınırlı backfill (oto-yetişme)
  backfill_positions.py  # arşivdeki maçların rollerini backend'e yazma
  archive.py       # raw_archive yazımı
  fixtures/        # örnek LCU payload'ları (test verisi)
  tests/           # pytest
  raw_archive/     # (runtime) ham payload arşivi
  outbox/          # (runtime) gönderilemeyen payload'lar
  seed_roster.json # ilk backfill için elle doldurulan riot_id listesi (repo'da boş)
  seed_roster.example.json  # şablon (2-3 sahte kayıt)
```
