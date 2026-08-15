# lol-balance

🇬🇧 English: [README.md](README.md)

Arkadaş grubunun League of Legends 5v5 custom maçları için: LCU'dan otomatik veri
toplama → rating (OpenSkill tabanlı harman modeli) → takım dengeleme → web UI.

## Bileşenler

| Dizin | Ne | Teknoloji |
|---|---|---|
| `collector/` | LoL client'ın (LCU) yerel API'sinden biten custom maçları yakalar, normalize eder, backend'e gönderir | Python, httpx |
| `backend/` | REST API + statik web UI servis + SQLite | FastAPI |
| `backend/rating/` | Saf rating kütüphanesi (I/O yok): OpenSkill PlackettLuce + performans harmanı + takım dengeleme | Python, openskill |
| `webui/` | Framework'süz tek sayfa: roster, dengeleme, maç geçmişi, leaderboard | Vanilla HTML/JS |
| `docs/` | **CONTRACT'lar — tek doğruluk kaynağı** (API, ingest, DB şeması, rating modeli) | — |

## Geliştirici rehberi (önce bunu oku)

1. **Contract'lar donmuştur.** `docs/` altındaki dosyalar tek taraflı değiştirilmez;
   sorun bulursan `docs/CHANGE_REQUESTS.md`'ye yaz, karar orkestrasyon sürecinden çıkar
   (bkz. `CLAUDE.md` ve `docs/ORCHESTRATION.md`).
2. **Dizin sınırı:** her bileşen yalnızca kendi dizininde değişir; bileşenler birbirini
   contract'taki örnek payload'larla mock'lar.
3. **Test zorunlu.** Üç paket de pytest kullanır; CI her push/PR'da üçünü koşar.

## Lokal kurulum

```powershell
# Backend + collector bağımlılıkları (tek venv yeterli)
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt -r requirements-dev.txt
.\.venv\Scripts\python -m pip install -r ..\collector\requirements.txt
copy .env.example .env   # API_KEY doldur

# Rating paketinin kendi test venv'i (hypothesis dahil)
cd rating
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .[dev]
```

Not: rating paketi backend venv'ine **kopya** kurulur (`pip install ./rating`);
`backend/rating/` altında değişiklik yaptıysan backend venv'inde yeniden kur
(editable kurulum, backend/ çalışma dizinindeki `rating/` klasör gölgelemesiyle
çakıştığı için bilinçli olarak kullanılmıyor).

## Çalıştırma

```powershell
cd backend
.\.venv\Scripts\python -m uvicorn app.main:app --reload   # http://127.0.0.1:8000
```
Web UI kökten servis edilir; API `/api/v1` altındadır ve `X-API-Key` ister.
Collector için `collector/README.md`'ye bak (canlı mod + backfill + Task Scheduler).

## Testler

```powershell
cd backend\rating && .\.venv\Scripts\python -m pytest -q          # rating
cd backend && .\.venv\Scripts\python -m pytest tests -q            # backend
cd <repo kökü> && backend\.venv\Scripts\python -m pytest collector -q  # collector
```

## Deploy

- CI (`.github/workflows/ci.yml`): her push/PR'da üç test paketi; `main`'e push'ta
  GHCR'a Docker image (`backend/Dockerfile`, backend+webui tek container).
- Kubernetes (VPS): `deploy/VPS_AGENT_BRIEF.md`.

## Gizlilik notu

`collector/fixtures/` altındaki gerçek LCU kayıtları oyuncuların puuid ve Riot
ID'lerini içerir. **Repo private kalmalıdır**; public yapılacaksa fixture'lar
önce anonimleştirilmelidir.
