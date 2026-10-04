# 00 — Ortak zemin (her worker önce bunu okur)

**Proje:** LoL custom maç dengeleyicisi (arkadaş grubu). Canlı: https://lol.teomanagir.com
Akış: collector (arkadaş PC'lerinde exe) → backend (FastAPI+SQLite, VPS/k8s) →
rating (OpenSkill blend25, ana + rol evreni) → web UI (framework'süz).

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

## Ortam — İKİ MAKİNE (worker, hangi makinede olduğunu `uname`/yoldan anlar)

### macOS (2026-10-04'ten beri; repo `/Users/shadepb/Desktop/REPO/balance`)
- Sistem python3 3.9'dur (proje 3.11+ ister) — KULLANMA. Venv'ler `uv` ile kurulur
  (`/opt/homebrew/bin/uv`), Python 3.12 (CI ile aynı):
  - `cd backend && uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -r requirements.txt -r requirements-dev.txt -r ../collector/requirements.txt`
  - `cd backend/rating && uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -e ".[dev]"`
- Interpreter (repo kökünden): backend + collector + webui testleri `backend/.venv/bin/python`;
  rating testleri `backend/rating/.venv/bin/python`.
- rating paketi backend venv'ine KOPYA kurulur: `backend/rating/` değiştiyse
  `uv pip install --python backend/.venv/bin/python ./backend/rating` (editable BOZUK, aynı tuzak).
- **macOS `.pth` TUZAĞI (2026-10-04):** bu makinede bir arka plan süreci `.venv` içindeki
  dosyalara saniyeler içinde `hidden` bayrağı koyuyor (`ls -lO`), Python 3.12.13 ise gizli
  `.pth` dosyalarını ATLIYOR → rating venv'indeki editable kurulum (`__editable__*.pth`)
  görünmez olur, `No module named 'rating'` ile 9-10 collection error çıkar. `chflags
  nohidden` birkaç saniye sonra geri geliyor. KALICI ÇÖZÜM: site-packages'a symlink —
  `ln -sfn "$PWD/backend/rating/rating" backend/rating/.venv/lib/python3.12/site-packages/rating`
  (uygulandı; venv yeniden kurulursa tekrar gerekir). Geçici alternatif:
  `PYTHONPATH=backend/rating backend/rating/.venv/bin/python -m pytest backend/rating`.
  Backend venv'i kopya kurulum kullandığı için etkilenmez.
- Test komutları (repo kökünden):
  - backend: `backend/.venv/bin/python -m pytest backend/tests`
  - collector: `backend/.venv/bin/python -m pytest collector`
  - rating: `backend/rating/.venv/bin/python -m pytest backend/rating`
  - webui: `backend/.venv/bin/python -m pytest webui/tests`
- `gh`: `/opt/homebrew/bin/gh` (TeomanAgir hesabı, HTTPS kimlik yardımcısı; worker kullanmaz).
  Remote `origin` HTTPS'tir (SSH anahtarı GitHub'da kayıtlı değil). LoL client bu makinede
  YOK; collector'ın canlı doğrulaması yine Windows PC'de.
- Yerel-only görev listesi (`new_modules.md`, `modules/`) bu makinede YOK — görev tanımı
  Teoman'dan sohbetle gelir.

### Windows (Teoman'ın PC'si — tarihsel ana ortam)
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
- Test tabanları (2026-08-20, blend25 sonrası): rating 167 · backend 473 · collector 479 (475+4 skip)
  · webui 118 (`pytest webui/tests`, backend venv'iyle). macOS'ta 2026-10-04'te
  aynı sayılar doğrulandı (167 / 473 / 475+4 skip / 118).
  Worker, taban sayıyı DÜŞÜRMEDEN teslim eder ve önce/sonra sayısını raporlar.
  **Sayım tuzağı:** pytest çıktısını `tail`/`head` ile boruya sokma — renkli ilerleme
  noktaları kesilince özet satırı yanlış okunur (bir test worker'ı böylece 406'yı 361
  sandı). Çıktıyı dosyaya yaz, sonunu oku. Ayrıca `backend/tests` ve `webui/tests` aynı
  anda koşulurken dosya adları benzersiz olmalıdır (aynı basename = import çakışması).

## E2E deseni (orkestratör koşar; worker'a bilgi)
`backend/data/lol_balance.db` scratchpad'e kopyalanır → `API_KEY=e2e-test-key
ADMIN_KEY=e2e-admin-key DB_PATH=... uvicorn` (port 8123+) → `POST /admin/replay`
(fix-2'den beri `X-API-Key` YANINDA `X-Admin-Key` ister; ADMIN_KEY verilmezse 503,
ASCII olmayan değer de 503 — fix-3) → senaryo → tarayıcı doğrulaması.
Scratchpad oturumlar arası silinir; her seferinde yeniden kurulur.
