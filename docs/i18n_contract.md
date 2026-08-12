# i18n Contract — Dil Altyapısı (GÖREV 6)

Bu contract, webui ve collector'daki KULLANICIYA GÖRÜNEN tüm metinlerin dil yönetimini tanımlar.
Bundan sonra eklenecek HER modül bu contract'a uyar; uymayan kod CI'da kırmızıdır (bkz. §5).

## 1. Kararlar (Teoman, 2026-08-12)

- Diller: `tr`, `en`. **Varsayılan: `tr`.**
- webui: sağ üstte, mevcut temaya uyan bir dil düğmesi (TR/EN). Seçim ANINDA tüm arayüzü
  değiştirir ve `localStorage["lolbalance.lang"]`'a yazılır; sonraki açılışlar onu kullanır.
- collector: ilk açılış sihirbazının İLK sorusu İngilizce dil seçimidir —
  `Select language / Dil secin [tr/en]:` — kullanıcı terminale `tr` ya da `en` yazar
  (geçersiz girişte aynı soru tekrarlanır), seçim collector config'ine (`language` alanı)
  yazılır ve sihirbazın devamı + sonraki tüm çalıştırmalar o dilde akar. Config'de
  `language` varsa soru bir daha sorulmaz.
- README: `README.md` İngilizce (asıl), `README.tr.md` Türkçe ayna; ikisi tepeden birbirine
  linkli. Diğer README'ler (webui/, collector/) bu görevin kapsamı DIŞINDA.
- Backend API yanıtları LOKALİZE EDİLMEZ (contract değişikliği yok). Web UI, bilinen hata
  durumlarını kendi sözlük anahtarlarıyla gösterir; bilinmeyen hata metni olduğu gibi geçer.

## 2. webui mimarisi (framework'süzlük korunur — CLAUDE.md karar #5)

Dosyalar:
```
webui/i18n/core.js   # I18n nesnesi (aşağıdaki API)
webui/i18n/tr.js     # window.I18N_DICTS.tr = { "anahtar": "metin", ... }
webui/i18n/en.js     # window.I18N_DICTS.en = { ... }
```
`index.html` yükleme sırası: tr.js, en.js, core.js, sonra app.js.

API (`window.I18n`):
- `t(key, params?)` — sözlükten metin; `{ad}` biçimli yer tutucuları `params`'tan doldurur.
  Anahtar yoksa: konsola uyarı + anahtarın kendisini döndürür (asla boş string değil).
- `getLang()` / `setLang("tr"|"en")` — setLang localStorage'a yazar, `apply()` çağırır ve
  abonelere haber verir.
- `apply()` — DOM'daki `data-i18n` düğümlerini yeniden çevirir.
- `subscribe(cb)` — dil değişiminde çağrılır; app.js aktif görünümü yeniden çizmek için abone olur.

Statik metin (index.html): `data-i18n="anahtar"` (textContent),
`data-i18n-placeholder` / `data-i18n-title` (öznitelikler).
Dinamik metin (app.js): İSTİSNASIZ `I18n.t(...)` üzerinden.

Anahtar adlandırma: düz (nested değil), nokta ile ad alanı: `<görünüm>.<ad>`
(ör. `leaderboard.title`, `balance.suggest_btn`), ortaklar `common.*`.
Görünüm adları mevcut sekmelerle eşleşir; yeni modül = yeni ad alanı.

Oyun terimleri (top/jungle/mid/adc/sup, KDA, W/L, mu/sigma) her iki dilde de aynı
kalabilir — ama YİNE DE sözlükten geçer (hardcode edilmez).

## 3. collector mimarisi

- `collector/i18n.py`: `MESSAGES = {"en": {...}, "tr": {...}}` + `msg(key, **params)`.
  Dil çözümü: config'deki `language` → yoksa §1'deki İngilizce prompt → yanıt config'e yazılır.
- Kullanıcıya dönük TÜM `print`/`input` metinleri `msg()` üzerinden. Log/debug satırları
  (geliştiriciye dönük) kapsam dışıdır ve İngilizce'ye çevrilir.
- Paketleme notu: onefile exe metinleri gömer — bu contract'ın uygulanmasından sonra
  PyInstaller paketi YENİDEN üretilmelidir (orkestratör sorumluluğu, GÖREV 5 spec'i değişmez).

## 4. Sözlük bütünlüğü kuralları

1. `tr` ve `en` anahtar kümeleri BİREBİR aynı olmalı; ikisinde de boş değer olamaz.
2. `en` değerlerinde Türkçe'ye özgü karakter ([çğıöşüÇĞİÖŞÜ]) bulunamaz.
3. `webui/index.html` ve `webui/app.js` içinde (yorumlar hariç) Türkçe'ye özgü karakter
   kalamaz — tüm görünen metin sözlüğe taşınmıştır. `mock_api.js` veri taklidi olduğu için
   muaftır (oyuncu adları gibi VERİ, çeviri kapsamında değildir).
4. Aynı kurallar `collector/i18n.py` MESSAGES için de geçerlidir.

## 5. CI zorlaması

- `webui/tests/test_i18n.py` (pytest, yalnız stdlib): §4/1-3'ü doğrular (sözlükleri JS
  dosyalarından regex/ast ile çıkarmak yeterlidir; Node gerekmez).
- `collector/tests/test_i18n.py`: §4/1-2 (MESSAGES) + "config'de dil varsa prompt sorulmaz,
  yoksa geçersiz giriş yeniden sorulur" birim testleri.
- CI workflow'una webui test adımı orkestratör tarafından eklenir.

## 6. Gelecek modül kuralı

Yeni bir görünüm/özellik ekleyen HER agent:
1. Görünen her metni kendi ad alanıyla `tr.js` VE `en.js`'e AYNI commit'te ekler.
2. `t()` dışına metin yazmaz (test kırmızı yakalar).
3. Bu contract'ı değiştirmek isterse `docs/CHANGE_REQUESTS.md` sürecine gider.
