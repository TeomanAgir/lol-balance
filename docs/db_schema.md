# DB Schema Contract — v1

DB: SQLite (WAL mode). Migration aracı: yalın SQL migration dosyaları (`backend/migrations/000X_*.sql`), uygulama başlangıcında sırayla uygulanır ve `schema_migrations` tablosuna işlenir.

## Tasarım ilkeleri (neden böyle)

1. **Ham veri immutable, rating türetilmiş veridir.** LCU'dan gelen payload olduğu gibi `ingest_events`'e yazılır ve asla değiştirilmez. Rating tabloları her an silinip `ingest_events` + `matches` üzerinden **replay** edilerek yeniden üretilebilir. Bu, rating algoritması değiştiğinde geçmişi yeniden hesaplamayı mümkün kılar.
2. **Idempotency anahtarı `source_game_id`.** LCU'nun gameId'si maç başına benziqsizdir; UNIQUE constraint çift kaydı DB seviyesinde engeller.
3. **`engine_version` her rating satırında bulunur.** Farklı algoritma/parametre setleriyle üretilen rating'ler yan yana yaşayabilir; aktif versiyon config'te tutulur.
4. **Rol verisi Faz 1'den itibaren toplanır** (Faz 2 pair-synergy için migration gerektirmemek adına), ama Faz 1 rating hesabında KULLANILMAZ.

## DDL

```sql
CREATE TABLE players (
    id            INTEGER PRIMARY KEY,
    puuid         TEXT UNIQUE,            -- LCU'dan; manuel oluşturulan oyuncuda ilk maçına
                                          -- kadar NULL olabilir, ingest'te riot_id ile bağlanır
    riot_id       TEXT,                   -- "GameName#TAG"
    display_name  TEXT NOT NULL,          -- grupta kullanılan isim
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Ham, immutable ingest kaydı. Asla UPDATE/DELETE edilmez.
CREATE TABLE ingest_events (
    id              INTEGER PRIMARY KEY,
    source          TEXT NOT NULL,              -- 'lcu_eog' | 'manual'
    source_game_id  TEXT NOT NULL UNIQUE,       -- LCU gameId; manuelde 'manual:<uuid>'
    payload_json    TEXT NOT NULL,              -- ingest_contract.md'deki gövdenin aynısı
    received_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE matches (
    id              INTEGER PRIMARY KEY,
    ingest_event_id INTEGER NOT NULL UNIQUE REFERENCES ingest_events(id),
    source_game_id  TEXT NOT NULL UNIQUE,
    played_at       TEXT NOT NULL,              -- maç bitiş zamanı (UTC ISO8601)
    duration_s      INTEGER,
    winner_team     INTEGER NOT NULL CHECK (winner_team IN (100, 200)),
    status          TEXT NOT NULL DEFAULT 'valid'
                    CHECK (status IN ('valid','void')),  -- void: remake/erken ff → rating'e girmez
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE match_participants (
    id          INTEGER PRIMARY KEY,
    match_id    INTEGER NOT NULL REFERENCES matches(id),
    player_id   INTEGER NOT NULL REFERENCES players(id),
    team        INTEGER NOT NULL CHECK (team IN (100, 200)),
    position    TEXT CHECK (position IN ('TOP','JUNGLE','MIDDLE','BOTTOM','UTILITY')),
    champion    TEXT,
    -- İstatistikler: gösterim + openskill-pl-perf-v1'de performans çarpanı girdisi
    -- (bkz. rating_contract.md; Teoman kararı 2026-08-11, CHANGE_REQUESTS):
    kills INTEGER, deaths INTEGER, assists INTEGER,
    gold INTEGER, cs INTEGER, damage_to_champs INTEGER, vision_score INTEGER,
    UNIQUE (match_id, player_id)
);

CREATE TABLE rating_history (
    id             INTEGER PRIMARY KEY,
    player_id      INTEGER NOT NULL REFERENCES players(id),
    match_id       INTEGER NOT NULL REFERENCES matches(id),
    engine_version TEXT NOT NULL,               -- ör. 'openskill-pl-v1'
    mu_before  REAL NOT NULL, sigma_before REAL NOT NULL,
    mu_after   REAL NOT NULL, sigma_after  REAL NOT NULL,
    UNIQUE (player_id, match_id, engine_version)
);

-- Güncel rating = ilgili engine_version için oyuncunun son rating_history satırı.
-- Ayrı bir "current_ratings" tablosu YOK; view ile çözülür:
CREATE VIEW current_ratings AS
SELECT rh.player_id, rh.engine_version, rh.mu_after AS mu, rh.sigma_after AS sigma
FROM rating_history rh
JOIN matches m ON m.id = rh.match_id
WHERE m.status = 'valid'
GROUP BY rh.player_id, rh.engine_version
HAVING m.played_at = MAX(m.played_at);
```

## Kenar durumlar
- **Remake / erken bitiş:** backend, `duration_s < 300` olan maçları otomatik `void` işaretler; `void` maçlar veri olarak saklanır ama rating replay'ine girmez.
- **Yeni oyuncu:** Misafir/üye ayrımı YOKTUR. Payload'daki puuid `players`'ta yoksa backend önce riot_id ile (case-insensitive) puuid'i NULL olan bir kayıt arar — bulursa puuid'i o kayda bağlar (manuel eklenen oyuncunun ilk maçı senaryosu). Bulamazsa yeni oyuncu oluşturur (display_name = riot_id'nin GameName kısmı). Aynı kişi için asla iki player satırı oluşmaz. Oyuncu havuzu ~13-14 kişi; maç günü hazır bulunanlar web UI'daki roster listesinden seçilir.
- **Aynı maçın tekrar gönderimi:** `source_game_id` UNIQUE ihlali → backend 200 + `duplicate: true` döner (bkz. api_contract).
- **Faz 2 için rezerv:** pair-synergy terimleri ayrı tabloda tutulacak (`pair_terms(player_a, player_b, engine_version, weight, ...)`); şimdi OLUŞTURULMAZ, sadece isim rezerve edilmiştir.
