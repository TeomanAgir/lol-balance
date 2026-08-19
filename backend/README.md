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
| `ADMIN_KEY` | hayır | — | İdari uçların (`/matches/{id}/void`, `/matches/{id}/unvoid`, `/matches/{id}/roulette/unlink`, `POST /players`, `PATCH /players/{id}`, `/admin/replay`, `/admin/ping`) EK olarak beklediği `X-Admin-Key` değeri. Tanımlı değilse bu uçlar `503` döner (yüzey kapalı); yanlış/eksik header `403`. **Yalnız ASCII** olabilir (fix-3): header'lar latin-1 taşındığı için Türkçe karakterli anahtar doğru girilse bile doğrulanamaz — backend böyle bir anahtarda idari uçlarda `503` + açıklayıcı hata döner, uygulamanın geri kalanı çalışır. Prod'da değer yalnız k8s secret'ında yaşar |
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
- **void ⇄ unvoid (fix-2):** `POST /matches/{id}/unvoid` void'un simetriğidir; maç
  `valid` olur ve her iki evren replay edilir. Rating türetilmiş veri olduğu için
  sonuç, maç hiç void edilmemiş gibi bit-bit aynıdır. İkisi de `X-Admin-Key` ister.
  Durum kuralları simetriktir: zaten `void` maça void → `422`, `void` olmayan maça
  unvoid → `409`, `roulette` maça ikisi de reddedilir; hiçbirinde replay koşmaz.
- **Durum değişimi + replay atomiktir (fix-3):** `void`, `unvoid` ve `roulette/unlink`
  uçlarında `matches.status` yazımı ile her iki evrenin replay'i TEK transaction'dadır
  (`services/tx.maybe_transaction` + `replay(..., join_transaction=True)`). Replay
  patlarsa durum yazımı da geri alınır — istemci `500` görür, veri tutarlı kalır.
- **Admin hız sınırı (fix-3):** başarısız `X-Admin-Key` denemesi sabit
  `ADMIN_FAIL_DELAY_S` (0.25 sn) geciktirilir; istemci IP'si başına
  `ADMIN_FAIL_WINDOW_S` (60 sn) kayan penceresinde `ADMIN_FAIL_LIMIT` (10) başarısız
  denemeden sonra uç `429` + `Retry-After` döner. Başarılı doğrulama sayacı sıfırlar.
  Sayaç süreç belleğindedir (tek replica); sabitler `app/deps.py` modül seviyesindedir
  ve testler monkeypatch ile kısaltabilir.
