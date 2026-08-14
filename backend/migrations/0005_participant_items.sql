-- docs/db_schema.md "GÖREV 14 (migration 0005)" DDL'inin birebir kopyası.
-- Maç sonu envanteri. JSON int dizisi (ham sıra korunur), NULL = bilinmiyor.
-- Rating'e GİRMEZ; gösterim/istatistik verisidir.
--
-- NOT (0002/0004'teki gerekçenin aynısı): kolon bilinçli olarak 0001'e EKLENMEDİ.
-- SQLite'ta "ADD COLUMN IF NOT EXISTS" yoktur; kolon 0001'de de tanımlı olsaydı
-- bu ALTER taze DB'de "duplicate column" ile patlardı. Tek kaynak burasıdır.
ALTER TABLE match_participants ADD COLUMN items_json TEXT;  -- ör. '[6697,6676,3036]'
