# 00 — Ortak zemin (her worker önce bunu okur)

**Proje:** LoL custom maç dengeleyicisi (arkadaş grubu). Canlı: https://lol.teomanagir.com
Akış: collector (arkadaş PC'lerinde exe) → backend (FastAPI+SQLite, VPS/k8s) →
rating (OpenSkill blend50, ana + rol evreni) → web UI (framework'süz).

## KIRMIZI ÇİZGİLER
- **main'e push = CANLI DEPLOY.** Worker HİÇBİR git komutu çalıştırmaz
  (yalnız `git status/diff/ls-files` salt-okur serbest). Commit/branch/PR orkestratörün işidir.
- **Dizin sınırı:** Worker yalnız kendi bileşen dizinine yazar. `docs/` READ-ONLY;
  contract sorunu bulunursa DURULUR ve final raporda bildirilir (karar orkestratör/Teoman).
- **Davranışsal değişiklik** (endpoint, şema anlamı, rating modeli, kapsam) worker
  kararı DEĞİLDİR. Mimari savunma listesi: `CLAUDE.md` "Savunman gereken kararlar".
- **Repo PUBLIC.** Gerçek kişi verisi (Riot ID, puuid), IP, secret, `.env`, DB
  ASLA commit'lenecek dosyalara giremez. Fixture'lar anonimdir (PlayerNN#FAKE
  kalıbı) ve anonimlik testlerle kilitlidir. Kök dizindeki `17*.json` teşhis
  dosyaları gitignore'ludur.

## Ortam (Teoman'ın PC'si — worker'lar burada koşar)
- PATH'te python YOK. Interpreter (repo kökünden):
  - backend + collector işleri: `backend\.venv\Scripts\python.exe`
  - rating testleri: `backend\rating\.venv\Scripts\python.exe`
- rating paketi backend venv'ine KOPYA kurulur: `backend/rating/` değiştiyse
  `backend\.venv\Scripts\python.exe -m pip install ./backend/rating` (editable BOZUK).
- Test komutları (repo kökünden):
  - backend: `backend\.venv\Scripts\python.exe -m pytest backend/tests`
  - collector: `backend\.venv\Scripts\python.exe -m pytest collector`
  - rating: `backend\rating\.venv\Scripts\python.exe -m pytest backend/rating`
- Not: `pytest backend` (tests yerine kök) rating alt dizini yüzünden collection
  error verir — `backend/tests` kullan.
- `gh`: `C:\Program Files\GitHub CLI\gh.exe` (worker kullanmaz). LoL: `F:\Riot Games\League of Legends`.

## Contract'lar (tek doğruluk kaynağı, READ-ONLY)
`docs/api_contract.md` · `docs/ingest_contract.md` · `docs/rating_contract.md` ·
`docs/db_schema.md` · `docs/i18n_contract.md` · karar günlüğü `docs/CHANGE_REQUESTS.md`

## Genel konvansiyonlar
- Kullanıcıya görünen metinler i18n'lidir (tr + en, eksik anahtar CI'da test kırar):
  webui `webui/i18n/`, collector `collector/i18n.py`. Backend yanıtları lokalize edilmez
  (hata `detail` alanları Türkçe).
- Kod yorumları/log'lar mevcut dosyanın diline uyar (çoğunlukla TR yorum, EN log).
- Deterministiklik esastır: eşitlik kırılımları contract'ta tanımlanır; testler
  bit-bit eşitlik kanıtlayabilmelidir (replay == incremental gibi).
- Test tabanları (2026-08-14): rating 145 · backend 198 · collector 336.
  Worker, taban sayıyı DÜŞÜRMEDEN teslim eder ve önce/sonra sayısını raporlar.

## E2E deseni (orkestratör koşar; worker'a bilgi)
`backend/data/lol_balance.db` scratchpad'e kopyalanır → `API_KEY=e2e-test-key
DB_PATH=... uvicorn` (port 8123+) → `POST /admin/replay` → senaryo → tarayıcı doğrulaması.
Scratchpad oturumlar arası silinir; her seferinde yeniden kurulur.
