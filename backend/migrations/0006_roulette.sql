-- docs/db_schema.md "GÖREV 23 (migration 0006)" DDL'i.
-- Rulet eğlence modu: oturum + oyuncu başına atama tabloları ve
-- matches.status CHECK'inin ('valid','void','roulette') olarak genişletilmesi.
--
-- SQLite'ta CHECK değişikliği ALTER ile yapılamaz; matches tablosu yeniden
-- kurulur (rebuild + veri taşıma). `ingest_events`'e DOKUNULMAZ (immutable
-- ilkesi). current_ratings / current_role_ratings view'ları matches'a
-- başvurduğu için rebuild sırasında düşürülüp BİREBİR aynı tanımla yeniden
-- kurulur — davranışları değişmez.
--
-- PRAGMA foreign_keys transaction içinde no-op olduğundan OFF/ON, BEGIN/COMMIT
-- DIŞINDA durur (runner executescript'i autocommit'te başlatır); rebuild'in
-- kendisi tek transaction'dır. FK tanımları ada göre çözüldüğü için
-- match_participants/rating_history/role_rating_history'nin "REFERENCES
-- matches" cümleleri rename sonrası yeni tabloya işaret eder; satır kopyası
-- id'leri birebir koruduğundan foreign_key_check temiz kalır.
PRAGMA foreign_keys=OFF;

BEGIN;

DROP VIEW current_ratings;
DROP VIEW current_role_ratings;

-- 0001'deki matches tanımı + 0004'ün client_id kolonu (kolon sırası korunur),
-- tek fark: status CHECK'ine 'roulette' eklendi.
CREATE TABLE matches_rebuild (
    id              INTEGER PRIMARY KEY,
    ingest_event_id INTEGER NOT NULL UNIQUE REFERENCES ingest_events(id),
    source_game_id  TEXT NOT NULL UNIQUE,
    played_at       TEXT NOT NULL,              -- maç bitiş zamanı (UTC ISO8601)
    duration_s      INTEGER,
    winner_team     INTEGER NOT NULL CHECK (winner_team IN (100, 200)),
    status          TEXT NOT NULL DEFAULT 'valid'
                    CHECK (status IN ('valid','void','roulette')),
                    -- void: remake/erken ff → rating'e girmez
                    -- roulette: rulet eğlence maçı → rating + valid süzgeçli
                    -- tüm istatistiklerin dışında, geçmişte görünür
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    client_id       TEXT                        -- kaynak cihaz izi (0004)
);

INSERT INTO matches_rebuild (id, ingest_event_id, source_game_id, played_at,
                             duration_s, winner_team, status, created_at,
                             client_id)
SELECT id, ingest_event_id, source_game_id, played_at,
       duration_s, winner_team, status, created_at, client_id
FROM matches;

DROP TABLE matches;
ALTER TABLE matches_rebuild RENAME TO matches;

-- View'lar 0001/0003'teki tanımların BİREBİR kopyasıdır.
CREATE VIEW current_ratings AS
SELECT rh.player_id, rh.engine_version, rh.mu_after AS mu, rh.sigma_after AS sigma
FROM rating_history rh
JOIN matches m ON m.id = rh.match_id
WHERE m.status = 'valid'
GROUP BY rh.player_id, rh.engine_version
HAVING m.played_at = MAX(m.played_at);

CREATE VIEW current_role_ratings AS
SELECT rrh.player_id, rrh.role, rrh.engine_version,
       rrh.mu_after AS mu, rrh.sigma_after AS sigma
FROM role_rating_history rrh
JOIN matches m ON m.id = rrh.match_id
WHERE m.status = 'valid'
GROUP BY rrh.player_id, rrh.role, rrh.engine_version
HAVING m.played_at = MAX(m.played_at);

-- Rulet oturumu: aynı anda en fazla 1 'open' (uygulama değişmezi; yeni POST
-- öncekileri 'cancelled' yapar). match_id yalnız 'linked' durumda doludur.
CREATE TABLE roulette_sessions (
    id         INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    status     TEXT NOT NULL DEFAULT 'open'
               CHECK (status IN ('open','linked','cancelled')),
    match_id   INTEGER UNIQUE REFERENCES matches(id)  -- yalnız linked'te dolu
);

CREATE TABLE roulette_assignments (
    id            INTEGER PRIMARY KEY,
    session_id    INTEGER NOT NULL REFERENCES roulette_sessions(id),
    player_id     INTEGER NOT NULL REFERENCES players(id),
    team          INTEGER NOT NULL CHECK (team IN (100, 200)),
    position      TEXT NOT NULL
                  CHECK (position IN ('TOP','JUNGLE','MIDDLE','BOTTOM','UTILITY')),
    champion      TEXT NOT NULL,
    item_ids_json TEXT NOT NULL,                      -- ör. '[3031,3026]' — tam 2 eleman
    UNIQUE (session_id, player_id)
);

COMMIT;

PRAGMA foreign_keys=ON;
