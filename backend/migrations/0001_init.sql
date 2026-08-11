-- docs/db_schema.md v1 DDL'inin birebir kopyası.
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
    -- (bkz. docs/rating_contract.md):
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
    -- perf_score REAL kolonu 0002_perf_score.sql'de eklenir; buraya EKLEME —
    -- runner taze kurulumda 0002'yi de koşar ve ALTER "duplicate column" verir.
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
