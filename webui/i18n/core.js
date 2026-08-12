// i18n/core.js — framework'süz dil çekirdeği (docs/i18n_contract.md §2).
// Yükleme sırası: tr.js, en.js, core.js, app.js — sözlükler bu dosyadan önce gelir.
// API: window.I18n = { t, getLang, setLang, apply, subscribe }.
(function () {
  "use strict";

  const STORAGE_KEY = "lolbalance.lang";
  const DEFAULT_LANG = "tr";
  const DICTS = window.I18N_DICTS || {};

  // localStorage erişilemeyebilir (ör. bazı gömülü webview'ler) — dil seçimi
  // o durumda oturumluk kalır, uygulama çalışmaya devam eder.
  const readStored = () => {
    try { return localStorage.getItem(STORAGE_KEY); } catch { return null; }
  };
  const writeStored = (v) => {
    try { localStorage.setItem(STORAGE_KEY, v); } catch { /* kalıcı olmadan devam */ }
  };

  let lang = (() => {
    const stored = readStored();
    return stored && DICTS[stored] ? stored : DEFAULT_LANG;
  })();

  const subscribers = [];

  // t(key, params?): sözlükten metin; {ad} yer tutucuları params'tan doldurulur.
  // Anahtar yoksa konsola uyarı yazılır ve anahtarın kendisi döner (asla boş string değil).
  function t(key, params) {
    const dict = DICTS[lang] || {};
    let text = dict[key];
    if (typeof text !== "string" || text === "") {
      console.warn(`[i18n] eksik anahtar: "${key}" (${lang})`);
      return key;
    }
    if (params) {
      text = text.replace(/\{(\w+)\}/g, (m, name) =>
        Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : m);
    }
    return text;
  }

  function getLang() { return lang; }

  // apply(): DOM'daki data-i18n düğümlerini yeniden çevirir.
  // data-i18n → textContent, data-i18n-placeholder / -title / -aria-label → öznitelik.
  // (aria-label contract'taki asgari kümenin üstüne eklendi: ekran okuyucuya
  // görünen metin de kullanıcıya görünen metindir.)
  function apply(root) {
    const scope = root || document;
    scope.querySelectorAll("[data-i18n]").forEach((el) => {
      el.textContent = t(el.dataset.i18n);
    });
    scope.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      el.setAttribute("placeholder", t(el.dataset.i18nPlaceholder));
    });
    scope.querySelectorAll("[data-i18n-title]").forEach((el) => {
      el.setAttribute("title", t(el.dataset.i18nTitle));
    });
    scope.querySelectorAll("[data-i18n-aria-label]").forEach((el) => {
      el.setAttribute("aria-label", t(el.dataset.i18nAriaLabel));
    });
    document.documentElement.lang = lang;
  }

  // setLang: localStorage'a yazar, apply() çağırır ve aboneleri bilgilendirir.
  function setLang(next) {
    if (!DICTS[next]) {
      console.warn(`[i18n] bilinmeyen dil: "${next}"`);
      return;
    }
    if (next === lang) return;
    lang = next;
    writeStored(next);
    apply();
    subscribers.forEach((cb) => {
      try { cb(lang); } catch (e) { console.error("[i18n] abone hatası:", e); }
    });
  }

  // subscribe(cb): dil değişiminde çağrılır; app.js aktif görünümü yeniden
  // çizmek için abone olur. Dönen fonksiyon aboneliği kaldırır.
  function subscribe(cb) {
    subscribers.push(cb);
    return () => {
      const i = subscribers.indexOf(cb);
      if (i !== -1) subscribers.splice(i, 1);
    };
  }

  window.I18n = { t, getLang, setLang, apply, subscribe };

  // Script gövde sonunda yüklendiği için DOM hazır: statik metin app.js'ten
  // önce çevrilir (varsayılan tr olsa bile boş data-i18n düğümleri doldurulur).
  apply();
})();
