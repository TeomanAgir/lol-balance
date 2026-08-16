# lol-balance backend

FastAPI servisi: maç ingest, oyuncu/maç yönetimi, 5v5 dengeleme (`/balance`) ve
rating orkestrasyonu. Rating matematiği bu pakette DEĞİLDİR — `rating/` paketi
(OpenSkill Plackett-Luce) çağrılır. Contract'lar: `docs/api_contract.md`,
`docs/ingest_contract.md`, `docs/db_schema.md`.

## Lokal çalıştırma

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-dev.txt
copy .env.example .env      # API_KEY değerini düzenleyin
.\.venv\Scripts\uvicorn app.main:app --reload
```

- API: `http://localhost:8000/api/v1/...` (tüm isteklerde `X-API-Key` header'ı zorunlu)
- `webui/` dizini repo kökünde mevcutsa `http://localhost:8000/` altından servis edilir.
- Migration'lar (`migrations/*.sql`) uygulama açılışında otomatik uygulanır.
- Not: `rating` paketi requirements üzerinden normal (editable olmayan) kurulur;
  `backend/rating/` güncellenirse `pip install -r requirements.txt` tekrar çalıştırın.

Testler:

```powershell
.\.venv\Scripts\python -m pytest tests
```

## Docker

Build context repo köküdür (webui de imaja girdiği için):

```bash
docker build -f backend/Dockerfile -t lol-balance .
docker run -d -p 8000:8000 \
  -e API_KEY=<secret> \
  -v lol-balance-data:/data \
  lol-balance
```

SQLite dosyası `/data/lol_balance.db` yolunda, `lol-balance-data` volume'unda kalıcıdır.

## .env alanları

| Alan | Zorunlu | Varsayılan | Açıklama |
|---|---|---|---|
| `API_KEY` | evet | — | Tüm `/api/v1` isteklerinde beklenen `X-API-Key` değeri |
| `DB_PATH` | hayır | `backend/data/lol_balance.db` | SQLite dosya yolu |
| `ENGINE_VERSION` | hayır | `openskill-pl-blend20-v1` | Aktif rating engine versiyonu |
| `WEBUI_DIR` | hayır | `../webui` | Statik servis edilecek dizin |

## Tasarım notları

- **Incremental vs replay:** Normal ingest akışı yalnızca son rating'lerin üstüne tek
  maç uygular. `POST /admin/replay` (ve `POST /matches/{id}/void` sonrası otomatik
  tetiklenen replay) aktif `ENGINE_VERSION`'ın `rating_history` satırlarını silip valid
  maçları `played_at` sırasıyla baştan işler. Diğer engine versiyonlarının satırlarına
  dokunulmaz (db_schema ilke 3: versiyonlar yan yana yaşayabilir).
- **Ham veri immutable:** ingest gövdesi `ingest_events.payload_json`'a byte'ı byte'ına
  yazılır; rating tabloları her an bu kayıtlardan yeniden üretilebilir.
- **Idempotency:** `source_game_id` UNIQUE; aynı payload ikinci kez `200 {duplicate: true}`.
- **Kısa maç:** `duration_s < 300` otomatik `void` — veri saklanır, rating'e girmez.
