# 90 — Güncel durum (yaşayan dosya — orkestratör her görev sonunda tazeler)

Son güncelleme: 2026-08-15 (orkestratör)

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
`release.yml`: v* etiketi → exe GitHub Release'e; güncelleme bildirimi bant+link).

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
- new_modules.md'de bekleyen: GÖREV 17 (sinerji formülü — tartışma aşamasında).
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
