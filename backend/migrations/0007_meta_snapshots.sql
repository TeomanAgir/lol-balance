-- docs/db_schema.md "GÖREV 34 (migration 0007)" DDL'i.
-- META tier + counter verisi (api_contract §8 "Meta verisi"). Her başarılı
-- güncelleme bir anlık görüntü satırıdır; tek etkin satır partial UNIQUE index
-- ile DB seviyesinde garanti edilir. Rating/ingest tablolarıyla İLİŞKİSİ
-- YOKTUR; replay'e girmez, yedek/geri alma için en fazla 5 satır tutulur
-- (etkin olan silinmez).
CREATE TABLE meta_snapshots (
    id            INTEGER PRIMARY KEY,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    trigger       TEXT NOT NULL CHECK (trigger IN ('panel','cli')),
    source        TEXT NOT NULL,            -- ör. 'op.gg (global, platinum_plus)'
    source_patch  TEXT NOT NULL,            -- ör. '16.19' (belgelerin patch alanıyla aynı)
    dd_version    TEXT NOT NULL,            -- id→ad eşlemesinde kullanılan Data Dragon sürümü
    tiers_json    TEXT NOT NULL,            -- tiers belgesinin TAMAMI (api_contract §8 şeması)
    counters_json TEXT NOT NULL,            -- counters belgesinin TAMAMI
    warnings_json TEXT NOT NULL DEFAULT '[]',
    summary_json  TEXT NOT NULL DEFAULT '{}',  -- refresh.diff.summary + sayımlar
    is_active     INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0,1))
);
CREATE UNIQUE INDEX meta_snapshots_single_active
    ON meta_snapshots(is_active) WHERE is_active = 1;
