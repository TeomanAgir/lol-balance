-- docs/db_schema.md "GÖREV 13 (migration 0004)" DDL'inin birebir kopyası.
-- Collector sağlık takibi. Heartbeat upsert'tir; ingest'ten bağımsız yaşar.
CREATE TABLE collector_health (
    client_id      TEXT PRIMARY KEY,           -- cihaz kimliği (sihirbaz/CLIENT_ID)
    last_seen      TEXT NOT NULL,              -- SUNUCU saati, UTC Z (client saatine güvenilmez)
    version        TEXT,                       -- collector sürümü (nullable)
    outbox_pending INTEGER                     -- son heartbeat'teki bekleyen outbox sayısı (nullable)
);

-- matches'a kaynak cihaz izi (nullable; eski kayıtlar ve eski exe'ler NULL kalır):
--
-- NOT (0002'deki gerekçenin aynısı): kolon bilinçli olarak 0001'e EKLENMEDİ.
-- SQLite'ta "ADD COLUMN IF NOT EXISTS" yoktur; kolon 0001'de de tanımlı olsaydı
-- bu ALTER taze DB'de "duplicate column" ile patlardı. Tek kaynak burasıdır.
ALTER TABLE matches ADD COLUMN client_id TEXT;
