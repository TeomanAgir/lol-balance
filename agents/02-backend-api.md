# Agent 2 — Backend API

## Rol
Ingest, oyuncu/maç yönetimi, dengeleme ve rating orkestrasyonunu sunan FastAPI servisi. `docs/api_contract.md` ve `docs/ingest_contract.md`'yi harfiyen implemente eder; rating matematiğini KENDİSİ YAPMAZ, `backend/rating/` paketini (Agent 3) çağırır.

## Ortam
- **Çalışma dizini: `backend/`** (ama `backend/rating/` Agent 3'ündür — oraya dokunma, sadece import et).
- Python 3.11+, FastAPI, uvicorn, SQLite (stdlib `sqlite3` veya `aiosqlite`; ORM kullanma — şema `docs/db_schema.md`'de SQL olarak tanımlı, migration dosyaları da yalın SQL).
- Deploy hedefi: tek Docker container (Dockerfile yaz), volume'da SQLite dosyası. Lokal `uvicorn` ile de koşabilmeli.
- Agent 3 henüz bitmemişse: `rating` paketinin public arayüzünü (aşağıda) stub'layarak ilerle; entegrasyonda stub'ı gerçek paketle değiştir.

## Rating paketinin sana sunduğu arayüz (Agent 3 ile mutabık)
```python
from rating import Engine
engine = Engine(version="openskill-pl-v1")
engine.default_rating() -> Rating(mu, sigma)
engine.update(team100: list[Rating], team200: list[Rating], winner: int) -> (list[Rating], list[Rating])
engine.predict_win(team100, team200) -> float   # P(team100 kazanır)
```

## Görevler
1. Migration runner + `docs/db_schema.md`'deki DDL'in migration dosyaları.
2. Ingest endpoint: contract'taki tüm kurallar (10 katılımcı doğrulaması, duplicate → 200, bilinmeyen puuid için önce riot_id ile puuid'siz kayda bağlama, yoksa auto-create — bkz. db_schema "Yeni oyuncu"; `duration_s < 300` → void, ham gövdenin `ingest_events`'e aynen yazılması). Test: önce `POST /players` ile puuid'siz eklenen oyuncu, sonra aynı riot_id'li ingest → aynı player id, duplicate satır yok.
2b. Statik servis: `webui/` dizinini `/` altından FastAPI StaticFiles ile sun (api_contract §7). `webui/` içeriğine dokunma — o Agent 4'ün alanı; sadece mount et.
3. Valid ingest sonrası incremental rating update (`rating_history`'ye before/after satırları).
4. `/balance`: 126 ayrımı brute force değerlendir, contract'taki response formatı. (itertools.combinations; ayna ayrımları çifte sayma.)
5. `/admin/replay`: rating_history truncate + valid maçları `played_at` sırasıyla yeniden işle. `/matches/{id}/void` sonrası otomatik replay tetikle.
6. Kalan endpoint'ler: players CRUD, matches listesi, leaderboard.
7. `X-API-Key` middleware; key `.env`'den.

## Definition of done
- Contract'lardaki örnek payload'lar birebir test fixture'ı olarak kullanılıyor ve testler geçiyor.
- Idempotency testi: aynı payload iki kez → tek maç, ikinci yanıt `duplicate: true`.
- Replay determinizm testi: incremental update'lerle oluşan rating_history == replay sonrası rating_history (aynı engine_version için).
- `backend/README.md`: lokal çalıştırma, Docker, .env alanları.

## Yasaklar
- `docs/` ve `backend/rating/` değiştirmek yasak; sorunları `docs/CHANGE_REQUESTS.md`'ye yaz.
- Rating matematiği (mu/sigma güncelleme formülleri) backend koduna sızmayacak — tamamı rating paketinde.
