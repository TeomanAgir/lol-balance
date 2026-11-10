# 20 — Collector haritası (LCU → backend, Windows exe)

Yazma izni: yalnız `collector/` (`packaging/.build_venv`, `raw_archive/`, `.env` HARİÇ).

## Modüller
- `__main__.py` — CLI: canlı mod (varsayılan), `--backfill` / pozisyonel `backfill`
  (alias), `backfill-positions [--dry-run]`, `--setup`. Frozen'da pencere bekletme + UTF-8.
- `live.py` — `LiveRunner.poll_forever` (EOG yakalama). `catchup.py` — `run_catchup`:
  her LCU bağlantısında canlı döngüden ÖNCE son `CATCHUP_DAYS` (varsayılan 14, 0=kapalı)
  günü `run_backfill` ile tarar; HER hata yutulur, canlı mod engellenmez.
- `backfill.py` — `run_backfill(since=...)`: MH taraması, roster filtresi
  (`roster.py`: backend GET /players ∪ seed), remake atlama, KRONOLOJİK gönderim.
- `normalizer.py` — LCU ham → ingest_contract. ROL ÖNCELİĞİ (3 katman, spec:
  ingest_contract "Kurallar"): açık `selectedPosition` > `detectedTeamPosition` >
  `role_infer.py` kısıt zinciri (Smite→JUNGLE...; belirsizse null, ZORLANMAZ).
  `played_at`: `endOfGameTimestamp` > captured_at. `is_summoners_rift` — yalnız SR
  custom'ları toplanır (gameMode CLASSIC ana sinyal, mapId!=11 ek eleme, alan
  yoksa tolerans); `is_custom` ile aynı üç çağrı noktasında (canlı EOG, MH
  fallback, backfill) uygulanır [Teoman, 2026-08-14].
- `backfill_positions.py` / `backfill_items.py` — raw_archive'dan mevcut maçlara
  PUT /positions (aynı öncelik) / PUT /items (GÖREV 14); ortak parçalar `backfill_common.py`.
  Normalizer artık `items` da üretir (EOG `items` / MH `item0..6`; 0=boş slot atılır).
- `sender.py` — gönderim + `outbox/` retry. `config.py` — `.env`; frozen'da
  (`is_frozen`/`app_dir`) tüm kalıcı yollar exe-bitişiği (PyInstaller `_MEIPASS` tuzağı!).
- `wizard.py` — ilk açılış sihirbazı (dil → API key → backend URL → LOL_DIR
  otomatik: registry → Riot product_settings.yaml → bilinen yollar). `i18n.py` — tr+en
  sözlükleri, `msg()`; eksik anahtar testi CI'da.
- `lcu.py` — endpoint sabitleri + `LcuClient` protokolü; testler `tests/fakes.py` sahteleriyle.

## Çoklu grup (GÖREV 36 — ingest_contract "Çoklu grup — collector tarafı")
- `groups.py` — profiller (`groups.json`, exe yanı; ilk profil = `.env` `API_KEY`, dosyaya
  YAZILMAZ), `choose_group` (yönlendirme kuralının TEK tanımı), `GroupRouter` (profil başına
  Sender + roster; Sender ile aynı flush/heartbeat/close arayüzü). Tek profilde düz `Sender`
  kullanılır ve davranış eskisiyle aynıdır (canlı EOG filtresiz).
- Ek grupların outbox'ı `outbox/groups/<id>/` (hedef = klasör); kök `outbox/*.json` ilk profilin.
- `backfill.scan_first_setup` (sender parametresi YOK — listeleme gönderemez) +
  `send_first_setup`; pencerede "İlk Kurulum Taraması" (işaretle → onayla → seçili gruba).
- Anahtar değeri log/ekranda yalnız maskeli (`groups.mask_key`); testle kilitli.

## Fixture envanteri (`collector/fixtures/`)
Hepsi ANONİM (PlayerNN#FAKE; anonimlik testle kilitli: `test_real_fixtures.py`).
`eog_custom_real` (gerçek şema, patch A) · `eog_custom_detected` (selectedPosition boş +
detectedTeamPosition dolu patch'i, gameId 1734940206) · `mh_game_custom_real` ·
`mh_list_page_real` · `champion_summary_real` (Riot statik verisi, PII yok) + sentetikler.
Yeni gerçek fixture eklerken: ÖNCE anonimleştir (Player numaraları çakışmasın), teste bağla.

## Paketleme
`collector/packaging/build.bat` → `.build_venv` kurar, testleri koşar, PyInstaller
onefile → `dist/LoLBalanceCollector.exe` (~15MB). Exe repo'ya GİRMEZ; .env asla
exe'yle dağıtılmaz. Yeni collector özelliği merge edilince exe yeniden derlenip dağıtılır.

## Arayüz (GÖREV 16)
Argümansız açılış = tkinter penceresi (`gui.py`; tkinter YALNIZ orada, geç import —
AST testiyle kilitli). CLI/GUI ortak komut katmanı `commands.py`; güncelleme
kontrolü `updates.py` (GitHub releases/latest, her hata sessiz). `--console` eski
konsol canlı modu. Paketleme --windowed; çökme günlüğü `collector-error.log`.

## Sağlık (GÖREV 13)
`CLIENT_ID` (.env; sihirbaz sorar, yoksa hostname) her ingest payload'ına eklenir
(`sender.with_client_id`); heartbeat `sender.send_heartbeat` — anlar: LCU bağlantısı,
canlı modda HEARTBEAT_MINUTES (varsayılan 5, 0=kapalı), backfill/catchup bitimi.
Heartbeat hatası HER ZAMAN yutulur, outbox'a yazılmaz. Sürüm: `__init__.__version__`
(dağıtım öncesi yükselt).

## Test
533 test (2026-11-10, GÖREV 36 sonrası): `backend\.venv\Scripts\python.exe -m pytest collector`. Gerçek `.env`/backend'e
dokunmadan, fake/fixture tabanlı.
