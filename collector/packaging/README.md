# Collector paketleme — tek `.exe` (GÖREV 5, GÖREV 16)

Arkadaş PC'lerinde Python/derleme gerektirmeden çalışan tek dosyalık bir **pencere**
uygulaması üretir: **`LoLBalanceCollector.exe`** (PyInstaller onefile + `--windowed`).

> **GÖREV 16'dan beri exe `--windowed` derlenir** (`collector.spec` → `console=False`):
> çift tıklayan kullanıcı siyah konsol yerine tkinter penceresini görür, log
> pencerenin içindedir. Ayar `spec` dosyasındadır — `build.bat`'a `--windowed`
> eklenmez.

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
2. Çift tıkla — program penceresi açılır. İlk açılışta küçük kutularla sorar:
   - **Dil** → `tr` ya da `en`.
   - **Backend adresi** → boş bırakıp Tamam'a bas (varsayılan doğru adres).
   - **API anahtarı** → Teoman'ın verdiği anahtarı yapıştır (Ctrl+V).
   - **LoL klasörü** → otomatik bulunur, doğruysa **Evet**.
   - **Cihaz adı** → boş bırakırsan bilgisayarının adı kullanılır.
   Windows "Bilgisayarınız korundu" uyarısı verirse: **Ek bilgi → Yine de çalıştır**.
3. **Canlı Başlat**'a bas ve custom maçları oyna. Maç biter bitmez otomatik
   gönderilir; olan biten pencerenin içindeki log alanında akar. Durdurmak için
   **Canlı Durdur** ya da pencereyi kapat. Oyun akşamı başında tekrar aç.

Penceredeki diğer düğmeler:

| Düğme | Ne yapar |
|---|---|
| **Maçları Tara** | LoL client açıkken maç geçmişini geriye tarar (`--backfill` ile aynı) |
| **Eşyaları Doldur** | Önce dry-run listeler, "Uygula" dersen eski maçların eşyalarını yükler |
| **Rolleri Doldur** | Aynı dry-run→uygula deseni, roller için |
| **Ayarlar** | Kurulum sihirbazını yeniden çalıştırır (`--setup` ile aynı) |

Yeni bir sürüm çıkmışsa pencerenin üstünde **sarı bir bant** belirir; "İndir"
düğmesi indirme sayfasını tarayıcıda açar (indirme otomatik DEĞİLDİR — yeni exe'yi
indirip eskisinin üzerine kopyalarsın, ayarların ve arşivin klasörde kalır).
İnternet yoksa bant hiç görünmez, program normal çalışır.

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
| Rolleri sonradan düzeltmek | Penceredeki **Rolleri Doldur** (ya da `backfill-positions --dry-run`) |
| Eski maçlarda eşyalar görünmüyor | Penceredeki **Eşyaları Doldur** (ya da `backfill-items --dry-run`) |
| Pencere hiç açılmıyor | Klasördeki `.env` bozulmuş olabilir; komut isteminden `LoLBalanceCollector.exe --setup` |

Argümanlı çalıştırmak için klasörde bir komut istemi aç:

```
LoLBalanceCollector.exe --help
LoLBalanceCollector.exe --setup
LoLBalanceCollector.exe --console                       (pencere yerine konsol canlı mod)
LoLBalanceCollector.exe --backfill --since 2026-08-01
LoLBalanceCollector.exe backfill --since 2026-08-01     (aynısı, tiresiz)
LoLBalanceCollector.exe backfill-positions --dry-run
LoLBalanceCollector.exe backfill-items --dry-run
```

> **`--windowed` uyarısı:** exe konsolsuz derlendiği için CLI komutları **çalışır
> ama çıktıları görünmez** (`--help` dahil; Windows windowed exe'yi konsola
> bağlamaz). İş yapılır, log'lar yalnız pencereye/dosyaya gider. Çıktıyı görmek
> gerekiyorsa kaynaktan `py -m collector ...` koş; günlük kullanımda pencere
> zaten aynı işleri düğmelerle sunar.

Aynı maç iki kez gönderilse bile backend'de tek kayıt olur (idempotent), bu yüzden
backfill'i istediğin kadar tekrarlayabilirsin.
