# 10 — Backend haritası (FastAPI + SQLite)

Yazma izni: yalnız `backend/` (ama `backend/rating/` rating worker'ınındır, dokunma).

## Dizin
- `backend/app/routers/` — ingest, matches (GET /{id} tekil, PUT positions, void), players
  (+`/{id}/stats`, `/{id}/rating-history`), balance (`/balance`, `/balance/nemesis`),
  highlights, nemesis, admin (replay).
- `backend/app/services/` — iş kuralları:
  - `ingest.py` — `ingest_match`: doğrulama, oyuncu auto-create, idempotency
    (DB UNIQUE source_game_id), incremental rating; SIRA-DIŞI maçta
    (`ratings.is_out_of_order`, replay sort-key'iyle hizalı) iki evreni replay eder.
  - `ratings.py` — ana evren: `apply_match_incremental`, `replay`,
    `effective_score` (blend dallanmasının TEK noktası), `is_out_of_order`, `STAT_FIELDS`,
    `replay_order_by` (replay sort-key'inin tek doğruluk noktası; rating_history de kullanır).
  - `rating_history.py` — GÖREV 10: tarihsel efektif score serisi (kümülatif P_avg).
  - `role_ratings.py` — rol evreni: `is_role_eligible` (10 pozisyon dolu + takım
    başına 5 farklı rol), `apply_match_incremental_roles`, `replay_roles`,
    `current_role_ratings`.
  - `player_stats.py` (profil) · `weekly.py` (`weekly_window` paylaşımlı) · `nemesis.py`.
- `backend/migrations/` — 0001 temel, 0002 perf_score, 0003 role_rating_history.
- `backend/tests/` — 136 test. Kalıp: geçici DB fixture'ları, spy/monkeypatch ile
  "incremental yolu korunur" kanıtları, bit-bit replay eşitlikleri.

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
