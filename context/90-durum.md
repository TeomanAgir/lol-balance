# 90 — Güncel durum (yaşayan dosya — orkestratör her görev sonunda tazeler)

Son güncelleme: 2026-08-13 (orkestratör)

## Canlı sistem
- https://lol.teomanagir.com — K8s/VPS, TLS, günlük yedek. 18+ maç, 14+ oyuncu
  (grup büyüyor: utK, XqRahSe4d, STAJYERARKACİZGİ yeni).
- CI/CD: main push = test → GHCR image → SSH deploy (`cideploy@`, zorunlu-komut;
  anahtar `SSH_DEPLOY_KEY_B64` + `SSH_KNOWN_HOSTS` secret'ları; ssh öncesi
  sızdırmasız anahtar doğrulama adımı var). 6443 dışarıya KAPALI.
- Repo PUBLIC sürecinde: fixture'lar anonim, VPS raporları kaldırıldı, PR/issue
  metinleri tarandı (temiz). Teoman tarafı: ayarlar + visibility flip.
- Collector: tek exe (PyInstaller), ilk açılış sihirbazı, oto-yetişme
  (CATCHUP_DAYS=14), tiresiz `backfill` alias. Arkadaşlara dağıtılan exe güncel.
- Backend: sıra-dışı ingest'te iki evren otomatik replay (2026-08-13'te canlıya çıktı).

## Tamamlanan görevler (new_modules.md)
0 rol rating evreni · 1 oyuncu profili · 2 haftanın enleri · 3 nemesis ·
4 harita rol enleri · 5 collector exe · 6 i18n (tr/en) · 7 public repo hazırlığı.
Ayrıntı ve kararlar: `docs/CHANGE_REQUESTS.md`.

## Açık işler
- **GÖREV 8** (new_modules.md): maç detay ekranı — rol-eşleşmeli karşılıklı stat
  bar graph'ları (gold/hasar/CS/+1 stat, graph üstü butonlarla değişir).
  Teoman ÖNCE PROTOTİP istiyor; onay sonrası tam iş.
- Canlıda 2 eski maçın pozisyonları eksik (#16=1734940206, #17=1734956802;
  selectedPosition'ı boş gönderen client'ın exe-öncesi kayıtları). Çare: Teoman
  UI'dan elle giriyor / arkadaş `backfill-positions` koşuyor. Kod işi DEĞİL.
- İzleme: o client'tan MH-format yetişme maçı boş rolle gelirse ham
  `raw_archive/<gameId>.json` istenip MH'ye öncelik katmanı eklenecek (henüz gerekmedi).
- Uzak vizyon: GÖREV IMPOSSIBLE (mobil app, hesaplar, lobi oylaması) — başlamadı;
  savunulan kararların Teoman onayıyla revizyonunu gerektirir.
- Faz 2 pair-synergy rating modeli KAPSAM DIŞI (gösterim sinerjisi zaten var).

## Bilinen tuzaklar (özet — ayrıntı 00-ortak.md)
- GitHub Actions pull_request bazen run üretmez → PR'ı close/reopen.
- OneDrive altındaki repo yolu; PowerShell 5.1 tırnak tuzakları → çok satırlı
  python'ı dosyaya yazıp koş.
