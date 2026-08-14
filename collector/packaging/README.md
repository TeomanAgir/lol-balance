# Collector paketleme — tek `.exe` (GÖREV 5)

Arkadaş PC'lerinde Python/derleme gerektirmeden çalışan tek dosyalık bir konsol
uygulaması üretir: **`LoLBalanceCollector.exe`** (PyInstaller onefile).

---

## A. Teoman için: derleme

Tek komut (repo kökünden ya da herhangi bir yerden):

```
collector\packaging\build.bat
```

Ne yapar:

1. `collector/packaging/.build_venv` yoksa oluşturur (backend venv'i temel alınır) ve
   içine `pyinstaller` + `collector/requirements.txt` kurar.
   **Backend venv'ine PyInstaller KURULMAZ** — build ortamı ayrıdır.
2. Tüm collector testlerini koşar (kırmızıysa derleme durur).
3. `collector.spec` ile onefile exe üretir.

Çıktı: `collector\packaging\dist\LoLBalanceCollector.exe` (~15 MB).
`.build_venv/`, `build/`, `dist/` git'e girmez (`collector/.gitignore`).

Elle derlemek istersen:

```
collector\packaging\.build_venv\Scripts\python.exe -m PyInstaller --noconfirm --clean ^
    --distpath collector\packaging\dist --workpath collector\packaging\build ^
    collector\packaging\collector.spec
```

### Arkadaşa gönderirken

- **Yalnız `LoLBalanceCollector.exe` dosyasını gönder.** Yanına `.env` KOYMA —
  kendi API anahtarın ve klasör yolun sızmasın; exe ilk açılışta sihirbazla sorar.
- API anahtarını ayrı kanaldan ilet (exe'nin içinde anahtar yoktur).
- Exe imzasızdır: Windows SmartScreen "bilinmeyen yayımcı" uyarısı verir. Bu bilinen
  ve kabul edilmiş bir ödünleşimdir (bkz. `docs/CHANGE_REQUESTS.md`, GÖREV 5).

### Teknik not (neden `app_dir()`)

Onefile modda paketin içindeki dosyalar her çalıştırmada geçici `sys._MEIPASS`
dizinine açılır ve program kapanınca silinir. Bu yüzden kalıcı olması gereken her şey
(`.env`, `raw_archive/`, `outbox/`, `seed_roster.json`) **exe'nin yanındaki** dizine
yazılır: `collector/config.py → app_dir()`. Kaynaktan çalıştırmada (`python -m collector`)
davranış eskisi gibi paket dizinidir; ikisi tek yardımcıda toplanmıştır ve testlerle
sabitlenmiştir (`collector/tests/test_packaging.py`).

---

## B. Arkadaş için: kullanım (3 adım)

1. `LoLBalanceCollector.exe`'yi **kendine ait bir klasöre** koy
   (ör. `C:\LoLBalance\`) — program ayarlarını ve maç arşivini bu klasöre yazar.
   Masaüstüne ya da İndirilenler'e bırakma.
2. Çift tıkla. İlk açılışta üç şey sorar:
   - **Backend adresi** → Enter'a bas (varsayılan doğru adres).
   - **API anahtarı** → Teoman'ın verdiği anahtarı yapıştır (sağ tık = yapıştır).
   - **LoL klasörü** → otomatik bulunur, doğruysa Enter'a bas.
   Windows "Bilgisayarınız korundu" uyarısı verirse: **Ek bilgi → Yine de çalıştır**.
3. Pencereyi açık bırak ve custom maçları oyna. Maç biter bitmez otomatik gönderilir.
   Durdurmak için Ctrl+C ya da pencereyi kapat. Oyun akşamı başında tekrar aç.

Program LoL client'ine bağlanır bağlanmaz **son 14 günü otomatik tarar** ve sen
kapalıyken oynanmış custom maçları gönderir ("Yetişiliyor: ..."), sonra canlı moda
geçer. Yani exe'yi kapalı bırakmış olman maç kaybettirmez. Pencereyi başka bir gün
`CATCHUP_DAYS=30` gibi bir değerle (`.env` içinde) daha geniş tarayacak şekilde
ayarlayabilirsin; `CATCHUP_DAYS=0` bu taramayı kapatır. Tarama bir sebeple
başarısız olursa canlı mod yine de başlar.

Program açılırken backend'e bağlanıp anahtarı dener; bir sorun varsa ilk saniyede
Türkçe yazar (`API anahtarı REDDEDİLDİ`, `Backend'e ULAŞILAMADI` gibi).

### Sık sorulanlar

| Durum | Ne yapmalı |
|---|---|
| Yanlış anahtar/adres girdim | Exe'yi `--setup` ile çalıştır ya da yanındaki `.env`'i düzenle |
| Programı kapalıyken maç oynadım | Maçlar kaçmaz: exe açılışta son 14 günü kendi tarar; daha eskisi için `--backfill` |
| Rolleri sonradan düzeltmek | `backfill-positions` (kontrol için `--dry-run` ekle) |
| Eski maçlarda eşyalar görünmüyor | `backfill-items` — arşivdeki maçların eşya envanterlerini yükler (kontrol için `--dry-run`) |
| Pencere hemen kapanıyor | Kapanmaz; hata olsa bile "Kapatmak için Enter'a bas" der |

Argümanlı çalıştırmak için klasörde bir komut istemi aç:

```
LoLBalanceCollector.exe --help
LoLBalanceCollector.exe --setup
LoLBalanceCollector.exe --backfill --since 2026-08-01
LoLBalanceCollector.exe backfill --since 2026-08-01     (aynısı, tiresiz)
LoLBalanceCollector.exe backfill-positions --dry-run
LoLBalanceCollector.exe backfill-items --dry-run
```

Aynı maç iki kez gönderilse bile backend'de tek kayıt olur (idempotent), bu yüzden
backfill'i istediğin kadar tekrarlayabilirsin.
