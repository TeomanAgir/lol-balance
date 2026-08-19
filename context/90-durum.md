# 90 — Güncel durum (yaşayan dosya — orkestratör her görev sonunda tazeler)

Son güncelleme: 2026-08-19 (orkestratör)

## 2026-08-19: fix-2 — Kontrol Paneli + isim tazeleme + mobil stack (PR #64/#65/#66)
- Görev listesi artık `modules/` klasöründe (yerel-only; new_modules.md kalktı).
- **fix-2a (PR #64, CANLIDA):** puuid eşleşmesinde isim tazeleme — riot_id her zaman,
  display_name yalnız özelleştirilmemişse; DUPLICATE ingest'te de çalışır (backfill
  adları onarır). `refresh_player_name(s)` @ backend/app/services/ingest.py.
- **fix-2c (PR #65, CANLIDA):** Geçmiş kartında ≤420px'te takım sütunları alt alta
  (mavi üst) + `.match-teams > .team { min-width:0 }`. Eski "<410px taşma" kapandı;
  Sıralama ~330px taşması hâlâ AÇIK.
- **fix-2b (PR #66):** Kontrol Paneli — sol panelde şifreli sayfa (`cp-`); şifre yalnız
  bellekte, `GET /admin/ping` ile doğrulanır. `ADMIN_KEY` env (k8s secret, optional
  ref; DEĞER REPODA YOK — bkz. hafıza/CHANGE_REQUESTS) + `X-Admin-Key` katmanı:
  void (artık 422 void-üstüne-void) / YENİ unvoid (valid + iki evren replay) /
  /admin/replay / ping. Geçmiş kartındaki herkese açık void düğmesi KALDIRILDI.
  Panel v1: maç void/geri al listesi + tüm-replay + oyuncu adı düzeltme (PATCH).
  E2E tarayıcıda PASS (şifre kapısı 403/204, void↔unvoid+replay determinizmi,
  rename, 359px stack).
- **Deploy sonrası bekleyen:** (1) VPS'te secret'a ADMIN_KEY eklenmesi (Teoman;
  komut PR #66 gövdesinde) — yoksa idari uçlar 503. (2) Canlı maç #22 (1736190243,
  yanlış void) yeni unvoid ucuyla geri getirilecek. (3) Oyuncu #5 "YETİ VE PİÇİ"
  yeni nick'i: Teoman söylerse PATCH, yoksa arkadaş backfill'i otomatik düzeltir.

## 2026-08-17/19: GÖREV 18-23 (PR #56-#63) — hepsi CANLIDA
- 18 Geçmiş delta = efektif score farkı · 19 KDA gösterimi · 20 Manuel ekranı
  kaldırıldı (Sağlık kendi satırında) · 21 Seçim danışmanı (S3, advisor.js, rafta
  değil ama 21-FIX'e evrildi) · 21-FIX Eşleşme Optimizasyonu (M1 Sahne, mo-;
  S3 rafta) + negatif counter uyarısı · 22 sol panel gruplaması (GRUP ORTAMI /
  ŞAMPİYON SEÇİMİ) · 23 RULET (PR #63): çekiliş ekranı, migration 0006,
  /roulette uçları, oto-eşleşme/unlink, 3 rozet, `status='roulette'` rating dışı,
  void edilemez (409); eşya havuzu kanonik id düzeltmesi (132→112, mod
  varyantları elendi).

## 2026-08-16: aktif engine `openskill-pl-blend20-v1` — CANLIDA TAMAM
- Teoman kararı (simülasyon destekli, CHANGE_REQUESTS 2026-08-16): W/L %20 + perf %80
  (`mu_eff = 0.2*mu + 0.8*(25+20*(P_avg-1))`). blend50 tanımlı kaldı, aktif değil.
- Testler: rating 156 · backend 251 · collector 479; E2E scratch'te iki evren replay
  determinizmi + leaderboard formülü + eski engine satırlarının korunumu PASS.
- PR #47 merge + deploy + canlıda `POST /admin/replay` KOŞULDU (Teoman); canlı
  leaderboard simülasyonun w=0.20 kolonuyla birebir doğrulandı (Konna 7.45 ...).

## 2026-08-16: GÖREV 17 — sol navigasyon (K1 "Sade Ray") CANLIDA
- new_modules.md'de GÖREV 17 yeniden tanımlandı (frontend rebuild); eski sinerji
  maddesi artık GÖREV X. Teoman kararları (AskUserQuestion): 4 konsept artifact'ından
  K1; masaüstünde hep açık sabit panel; düz liste (gruplamaya hazır); dil/API
  kontrolleri panel altına. PR #49 merge + deploy edildi.
- webui kabuğu: `#sb-app` / `#sb-nav` / `#sb-scrim` / `#sb-burger`, `sb-` öneki;
  <880px çekmece + scrim + `body.sb-lock`; `.tab` → `.sb-item`. 2 yeni i18n anahtarı.
- Deploy sonrası olay: tarayıcı cache'i eski style.css'i tuttu → stilsiz görünüm
  (sunucu doğruydu, hard refresh çözdü). Kalıcı çözüm PR #52 (statik yanıtlara
  `Cache-Control: no-cache`, backend 260 test) — AÇIK, merge Teoman'da; merge
  sonrası 00-ortak test tabanı 260'a güncellenecek. Arkadaşlara bir defalık
  "bozuk görünürse Ctrl+F5" notu gerekir.
- Takip (GÖREV 17'den bağımsız, önceden var): Sıralama tablosu ≤~330px'te ~28px
  taşıyor (EN, rating-sub nowrap); Geçmiş kartlarının takım sütunları (200px×2)
  ~<410px'te taşıyor.

## Canlı sistem
- https://lol.teomanagir.com — K8s/VPS, TLS, günlük yedek. 18+ maç, 14+ oyuncu
  (grup büyüyor: utK, XqRahSe4d, STAJYERARKACİZGİ yeni).
- CI/CD: main push = test → GHCR image → SSH deploy (`cideploy@`, zorunlu-komut;
  anahtar `SSH_DEPLOY_KEY_B64` + `SSH_KNOWN_HOSTS` secret'ları; ssh öncesi
  sızdırmasız anahtar doğrulama adımı var). 6443 dışarıya KAPALI.
- Repo PUBLIC sürecinde: fixture'lar anonim, VPS raporları kaldırıldı, PR/issue
  metinleri tarandı (temiz). Teoman tarafı: ayarlar + visibility flip.
- Collector: tek exe (PyInstaller), ilk açılış sihirbazı, oto-yetişme
  (CATCHUP_DAYS=14), tiresiz `backfill` alias. SR-only filtre (yalnız Sihirdar
  Vadisi custom'ları; PR #24) canlıda; exe 2026-08-14'te yeniden derlendi,
  arkadaşlara dağıtım Teoman'da.
- Backend: sıra-dışı ingest'te iki evren otomatik replay (2026-08-13'te canlıya çıktı).

## Tamamlanan görevler (new_modules.md)
0 rol rating evreni · 1 oyuncu profili · 2 haftanın enleri · 3 nemesis ·
4 harita rol enleri · 5 collector exe · 6 i18n (tr/en) · 7 public repo hazırlığı ·
8 maç detay ekranı (PR #23) · 9 maç detayı KS1 modernizasyonu (global ölçek +
ibre + sade TOPLAM; 11 konsept + 5 varyant artifact'ından Teoman seçimi) ·
10 profilde rating tarihçesi grafiği (GET rating-history + GET /matches/{id}) ·
11+12 rozetler + MVP (13 rozetlik katalog + Sonsuz Bench; GET /players/{id}/badges,
salt-okur türetilmiş; profilde pb- vitrini) · 13 collector sağlık paneli
(heartbeat + CLIENT_ID + migration 0004; webui ch- görünümü Manuel'den girişli) ·
14 eşya build'leri (BUILD sekmesi + Data Dragon build-time vendoring
`deploy/fetch_ddragon.py` sürüm 16.16.1 + migration 0005 + backfill-items +
profilde favori eşya; varlıklar gitignore'lu, dd-/mb-/fi- blokları) ·
15 boş slot hatası (global .empty tuzağı, 4. kurban) · 16 Collector Remaster
(tkinter arayüz `gui.py`/`commands.py`/`updates.py`, sürüm 0.3.0, CI release
`release.yml`: v* etiketi → exe GitHub Release'e; güncelleme bildirimi bant+link) ·
17 sol navigasyon paneli (K1 "Sade Ray", PR #49; ayrıntı yukarıdaki bölümde).

## 2026-08-14/15 diğer işler
- META sekmesi (M1 tasarımı; `webui/assets/meta/tiers.json` + `deploy/fetch_meta.py`
  OP.GG'den yarı otomatik, --write onaylı; alt çubuk 6 sekme, vw-tabanlı punto).
- Geçmiş + maç detayında resmî rol ikonları (`pos-ico`, CommunityDragon vendored);
  Geçmiş kartlarında şampiyon portreleri; maç detayında ada tık → profil
  (backStack geri zinciri); trinket 7. slota sabit; favori karakter = en çok
  KAZANILAN (wins alanı); display_name XSS kaçışlaması (12 nokta, tam denetim).
- backfill-items canlıya koşuldu (15 maç/150 envanter); HANDOFF/ORCHESTRATION
  docs/ altına taşındı (CLAUDE.md kökte).

## Açık not
- İLK RELEASE bekleniyor: `git tag v0.3.0 && git push origin v0.3.0` → CI exe'yi
  Release'e ekler; arkadaşlara releases/latest linki gönderilir (GÖREV 13+14+16
  tek dağıtımda; sonraki sürümlerde pencere kendisi haber verir).
- Data Dragon patch güncellemesi: `deploy/fetch_ddragon.py` DDRAGON_VERSION +
  redeploy; META verisi: `deploy/fetch_meta.py` → fark → `--write` → commit.
- new_modules.md'de bekleyen: GÖREV X (sinerji seçiminde perf katkısı — tartışma
  aşamasında; eski "GÖREV 17 sinerji" maddesinin yeni adı).
Ayrıntı ve kararlar: `docs/CHANGE_REQUESTS.md`.

## Açık işler
Not: Görev listesi `new_modules.md` YEREL-ONLY'dir (gitignore'lu, public repo'da
yok — Teoman'ın PC'sinde repo kökünde durur; orkestratör oradan okur).
- Canlıda 2 eski maçın pozisyonları eksik (#16=1734940206, #17=1734956802;
  selectedPosition'ı boş gönderen client'ın exe-öncesi kayıtları). Çare: Teoman
  UI'dan elle giriyor / arkadaş `backfill-positions` koşuyor. Kod işi DEĞİL.
- İzleme: o client'tan MH-format yetişme maçı boş rolle gelirse ham
  `raw_archive/<gameId>.json` istenip MH'ye öncelik katmanı eklenecek (henüz gerekmedi).
- Uzak vizyon: GÖREV IMPOSSIBLE (mobil app, hesaplar, lobi oylaması) — başlamadı;
  savunulan kararların Teoman onayıyla revizyonunu gerektirir.
- Faz 2 pair-synergy rating modeli KAPSAM DIŞI (gösterim sinerjisi zaten var).

## Bilinen tuzaklar (özet — İŞLETİM DEFTERİ: docs/HANDOFF.md, mutlaka oku)
- Kritik üçlü: git commit ÇIKTISINI doğrula (sessiz düşebilir) · gh'a çok satırlı
  metin HEP --body-file ile · etiket daima güncel MAIN'de atılır (workflow tanımı
  etiketlenen commit'ten okunur). Tamamı + worker/doğrulama dersleri HANDOFF'ta.
- GitHub Actions pull_request bazen run üretmez → PR'ı close/reopen.
- Yerel `backend/data/lol_balance.db` ESKİ kopyadır (10 maç, pozisyonsuz) —
  canlı DB değil; E2E'de rol senaryosu için scratch kopyaya elle pozisyon yazılır.
- OneDrive altındaki repo yolu; PowerShell 5.1 tırnak tuzakları → çok satırlı
  python'ı dosyaya yazıp koş.
