# 10 — Backend haritası (FastAPI + SQLite)

Yazma izni: yalnız `backend/` (ama `backend/rating/` rating worker'ınındır, dokunma).

## Dizin
- `backend/app/routers/` — ingest, matches (GET /{id} tekil, PUT positions, void), players
  (+`/{id}/stats`, `/{id}/rating-history`, `/{id}/badges`), balance (`/balance`, `/balance/nemesis`),
  highlights, nemesis, admin (replay + ping; `X-Admin-Key`), roulette (GÖREV 23),
  badges (`GET /badges` katalog, GÖREV 24), health (heartbeat + collectors).
  meta (GÖREV 34): `GET /meta/tiers|counters` (herkese açık, etkin snapshot → tohum dosya)
  + `/admin/meta/{status,refresh,history,activate/{id}}` (`X-Admin-Key`).
- `backend/app/services/` — iş kuralları:
  - `ingest.py` — `ingest_match`: doğrulama, oyuncu auto-create, idempotency
    (DB UNIQUE source_game_id), incremental rating; SIRA-DIŞI maçta
    (`ratings.is_out_of_order`, replay sort-key'iyle hizalı) iki evreni replay eder.
  - `ratings.py` — ana evren: `apply_match_incremental`, `replay`,
    `effective_score` (blend dallanmasının TEK noktası), `is_out_of_order`, `STAT_FIELDS`,
    `replay_order_by` (replay sort-key'inin tek doğruluk noktası; rating_history de kullanır).
  - `rating_history.py` — GÖREV 10: tarihsel efektif score serisi (kümülatif P_avg).
  - `badges.py` — GÖREV 24: 28 rozetlik salt-okur katalog (DB'ye yazılmaz; ID sırası
    `badges/rozetler.md`'de dondurulmuş).
  - `roulette.py` (GÖREV 23) · `rank_delta.py` (sıra değişimi okları) · `tx.py`
    (`maybe_transaction`: durum yazımı + iki evren replay TEK transaction, fix-3).
  - `role_ratings.py` — rol evreni: `is_role_eligible` (10 pozisyon dolu + takım
    başına 5 farklı rol), `apply_match_incremental_roles`, `replay_roles`,
    `current_role_ratings`.
  - `player_stats.py` (profil) · `weekly.py` (`weekly_window` paylaşımlı) · `nemesis.py`.
- `backend/migrations/` — 0001 temel, 0002 perf_score, 0003 role_rating_history,
  0004 collector_health + matches.client_id, 0005 match_participants.items_json,
  0006 roulette (sessions/assignments + matches.status 'roulette').
  0007 meta_snapshots (GÖREV 34; tek etkin satır partial UNIQUE index).
  - `items.py` — GÖREV 14: items doğrulama/serileştirme kuralının tek tanımı.
  - `health.py` (services+routers) — GÖREV 13: heartbeat upsert + collectors listesi.
  - `meta_source.py` — GÖREV 34: OP.GG → tiers/counters belgesi dönüşümü + fark (saf, stdlib-only;
    `deploy/fetch_meta.py` bunu çağıran ince CLI'dır, kod kopyalanmaz). `meta_store.py` —
    okuma önceliği, status, refresh (süreç içi kilit 409, ≤10 dk ham önbellek, guard,
    already_current, tek transaction yazma + saklama 5), history, activate. Ağ `fetch`
    parametresiyle enjekte edilir; testler gerçek ağa çıkmaz.
- `backend/tests/` — 580 test (2026-11-10, GÖREV 35 sonrası). Kalıp: geçici DB fixture'ları, spy/monkeypatch ile
  "incremental yolu korunur" kanıtları, bit-bit replay eşitlikleri.

## Çoklu grup (GÖREV 35 — api_contract "Çoklu grup")
- Tek süreç, `X-API-Key` → grup → o grubun SQLite dosyası. Çözüm TEK noktada:
  `config.Settings.resolve_group` → `deps.require_api_key` (Group döner) → `deps.get_db`.
  Ana grup `API_KEY/ADMIN_KEY/DB_PATH`; ek grup `GROUP_<AD>_API_KEY/_ADMIN_KEY`,
  dosya `group_<ad>.db` (türetilir). Migration açılışta her dosyaya koşar (`main.py`).
- Yeni uç/servis yazarken DB'ye YALNIZ `Depends(get_db)` ile bağlan; `settings.db_path`'i
  doğrudan açmak izolasyonu deler. TEK istisna meta: `deps.get_meta_db` (ana grubun dosyası).
- Modül seviyesi önbellek/kilit grup verisi TUTAMAZ (bugün tutan yok; meta kilidi/önbelleği
  ortak veri olduğu için global). Testler: `tests/test_multi_group.py`.

## Değişmezler (worker bunları BOZAMAZ)
1. `ingest_events` immutable; rating her an replay ile yeniden üretilebilir.
2. Idempotency DB seviyesinde UNIQUE(source_game_id) — uygulama seviyesine taşınmaz.
3. "incremental sonuç == tam replay sonucu" — replay sıralaması `ORDER BY played_at, id`;
   bu anahtara dokunan her değişiklik `is_out_of_order` ile birlikte düşünülür.
4. `match_participants.position` KÜRATÖRLÜ alandır (PUT ile düzeltilir, ham veri değişmez);
   düzeltme yalnız ROL evrenini replay eder, ana rating'e dokunmaz.
5. Yanıt şekilleri `docs/api_contract.md`'de sabittir; hassasiyet: 2 ondalık göster,
   sıralama/kırılım ham değerle.

## Çalıştırma
`backend\.venv\Scripts\python.exe -m uvicorn app.main:app` (cwd: backend/), env:
`API_KEY`, `DB_PATH`. Prod imajı `backend/Dockerfile`; deploy CI'da SSH ile (worker ilgilenmez).
