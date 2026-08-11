-- docs/db_schema.md "GÖREV 0 (migration 0003)" DDL'inin birebir kopyası.
-- Rol rating evreni: ana rating_history'nin (player, role) bazlı simetriği.
-- Oyuncu maç başına TEK rol oynar → UNIQUE role içermez (rol, satırın verisidir).
CREATE TABLE role_rating_history (
    id             INTEGER PRIMARY KEY,
    player_id      INTEGER NOT NULL REFERENCES players(id),
    match_id       INTEGER NOT NULL REFERENCES matches(id),
    role           TEXT NOT NULL
                   CHECK (role IN ('TOP','JUNGLE','MIDDLE','BOTTOM','UTILITY')),
    engine_version TEXT NOT NULL,
    mu_before  REAL NOT NULL, sigma_before REAL NOT NULL,
    mu_after   REAL NOT NULL, sigma_after  REAL NOT NULL,
    perf_score REAL,
    UNIQUE (player_id, match_id, engine_version)
);

CREATE VIEW current_role_ratings AS
SELECT rrh.player_id, rrh.role, rrh.engine_version,
       rrh.mu_after AS mu, rrh.sigma_after AS sigma
FROM role_rating_history rrh
JOIN matches m ON m.id = rrh.match_id
WHERE m.status = 'valid'
GROUP BY rrh.player_id, rrh.role, rrh.engine_version
HAVING m.played_at = MAX(m.played_at);
