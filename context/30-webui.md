# 30 — Web UI haritası (framework'süz)

Yazma izni: yalnız `webui/`. React/bundler/build zinciri ÖNERME (CLAUDE.md karar #5).

## Dosyalar
- `index.html` — tüm görünümlerin iskeleti (tek sayfa). GÖREV 17'den beri gezinme
  SOL PANELDİR (alt sekme çubuğu YOK): `#sb-app` flex kabuğu → `#sb-nav` (aside;
  marka + düz `.sb-item` listesi + alt blokta `#btn-lang`/`#btn-key`) + `#sb-scrim` +
  `.sb-content` (mobil `#sb-burger`'lı üst bar + `main`). <880px'te panel çekmecedir
  (`sb-open`/`body.sb-lock`, scrim/Esc kapatır, basit odak tuzağı app.js'te).
  Yeni gezinme metinleri `common.nav_aria`/`common.menu_btn`.
- `app.js` — tüm mantık. Görünümler: Sıralama (leaderboard; ada tık → profil),
  Maçlar (kartlar; "Rolleri düzenle" → PUT /positions; karta tık → maç detayı
  KS1: GLOBAL ölçekli karşılıklı barlar (statın en iyisi %100 + ⭐), koridor payı
  İBRESİ (%50 çentikli), TOPLAM'da bar yok — `MD_STATS`/`mdGlobalMax`/
  `mdGaugeHtml`/`openMatchDetail`; GÖREV 8+9), Dengele (normal + nemesis modu),
  Enler (haftalık kartlar + Nemesis bölümü; `TAB_OF`/`BACK_LABEL` detay-görünüm mekanizması),
  Harita (satır içi ~3KB özgün SVG, viewBox 0 0 100 100; HTML katmanında yüzde-konumlu
  baloncuk butonlar; `roleRanking`/`openRoleModal`). Profil: `openProfile` (+`esc()` XSS yardımcıcı).
- `style.css` — TEK global ad alanı: sınıf adları görünüm önekli seçilir
  (ders: global `.empty` çakışması iki kez yaşandı → `.hl-none`/`.rb-none`).
- `i18n/` — tr+en sözlükleri; `I18n.t()` + `data-i18n` kalıbı; dil düğmesi sağ üst,
  seçim localStorage'da; YENİ her metin iki sözlüğe de girer (CI'da pytest bütünlük testi).
- `mock_api.js` — backend'siz geliştirme; api_contract şekilleriyle senkron tutulur.
- Data Dragon varlık katmanı (GÖREV 14): `assets/ddragon/` (gitignore'lu, build-time
  vendoring) — `dd-` yardımcıları (tek yükleme, img hatasında 600ms tek retry,
  yer tutucu fallback; lazy-loading BİLEREK yok), BUILD sekmesi `mb-`, favori
  eşya kartı `fi-`.

## Konvansiyonlar
- API çağrıları `X-API-Key` ile; anahtar localStorage'da (modalla girilir), koda gömülmez.
- Sayı gösterimi 2 ondalık; sıralamayı backend verir, UI yeniden SIRALAMAZ.
- Yeni görünüm eklerken sol panele `.sb-item` satırı eklenir (dikey liste sayı
  kısıtını gevşetti; yine de mobil çekmecede taşma kontrol edilir). Tarihsel
  ≥320px alt-çubuk ölçüm kuralı tabbar'la birlikte emekli oldu (GÖREV 17).
- Doğrulama: worker kendi tarayıcı E2E'sini mock ile yapabilir; canlıya benzer doğrulamayı
  orkestratör scratchpad backend'i + Chrome ile koşar.
