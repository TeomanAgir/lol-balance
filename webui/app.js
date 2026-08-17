// app.js — api_contract.md'nin ince istemcisi. İş mantığı yok: rating, dengeleme,
// doğrulama tamamı backend'de; burada yalnızca seçim/gösterim var.
// Görünen HER metin i18n sözlüğünden gelir (docs/i18n_contract.md, GÖREV 6):
// statik düğümler index.html'de data-i18n taşır, dinamik metin t() üzerinden kurulur.
// Backend'in döndürdüğü `detail` metni contract gereği lokalize EDİLMEZ, aynen geçer.
(function () {
  "use strict";

  const CONFIG = window.APP_CONFIG;
  const $ = (sel) => document.querySelector(sel);
  // Kısayol: sözlük çevirisi. profileHtml içindeki "totals" değişkeni bu yüzden
  // "tot" adını taşır — t adı görünürde yalnız çeviriye aittir.
  const t = (key, params) => window.I18n.t(key, params);
  const uiLocale = () => (window.I18n.getLang() === "tr" ? "tr-TR" : "en-GB");

  const state = {
    apiKey: localStorage.getItem("apiKey") || "",
    roster: [],                 // GET /players sonucu
    board: [],                  // GET /leaderboard sonucu (harita ekranı, GÖREV 4)
    selected: new Set(),        // dengeleme seçimi (player_id)
    profileId: null,            // açık olan oyuncu profili (GÖREV 1)
    profileFrom: "leaderboard", // profil hangi görünümden açıldı (sıralama | enler | harita | maç detayı)
    mapFrom: "highlights",      // harita hangi görünümden açıldı (enler | sıralama)
    meta: null,                 // assets/meta/tiers.json içeriği (GÖREV 16; null = henüz çekilmedi)
    metaFilter: "ALL",          // META süzgeci: "ALL" | ROLES elemanı
    faqSlug: null,              // açık olan SSS maddesinin slug'ı (SSS görevi; #faq/<slug>)
    nemesis: null,              // son GET /nemesis yanıtı (GÖREV 3)
    nemesisMode: null,          // açık nemesis modu: {source, role, players:[{player_id, display_name}]}
    matches: [],                // son GET /matches yanıtı (GÖREV 10: grafikten detaya atlarken önbellek)
    matchDetail: null,          // açık maç detayı: GET /matches listesinden gelen maç nesnesi (GÖREV 8)
    matchStat: "gold",          // maç detayında seçili stat (MD_STATS anahtarı)
    matchFrom: "matches",       // maç detayı hangi görünümden açıldı (geçmiş | profil, GÖREV 10)
    ratingHistory: null,        // GET /players/{id}/rating-history yanıtı (GÖREV 10; null = çekilemedi)
    badges: null,               // GET /players/{id}/badges yanıtı (GÖREV 11+12; null = çekilemedi)
    historyRange: "all",        // grafikteki zaman aralığı: PH_RANGES anahtarı (istemci tarafı)
    histOpen: null,             // grafikte popup'ı açık olan noktanın match_id'si
    backStack: [],              // profil ⇄ maç detayı geri zinciri (bkz. pushBack)
    pick: null,                 // Seçim danışmanı girişleri (GÖREV 21; ensurePickState kurar)
    matchup: null,               // Eşleşme ekranı seçimleri (GÖREV 21-FIX; ensureMatchupState kurar)
  };

  // ── API istemcisi ─────────────────────────────────────────────
  async function api(path, { method = "GET", body } = {}) {
    const headers = { "X-API-Key": state.apiKey };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const doFetch = CONFIG.USE_MOCK ? window.mockFetch : window.fetch.bind(window);
    let res;
    try {
      res = await doFetch(CONFIG.API_BASE + path, {
        method, headers, body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch {
      throw new Error(t("common.err_network"));
    }
    if (res.status === 401) {
      openKeyModal();
      throw new Error(t("common.err_unauthorized"));
    }
    if (!res.ok) {
      let detail = "";
      try { detail = (await res.json()).detail; } catch { /* gövde JSON değil */ }
      // status hata nesnesinde taşınır: çağıran yer duruma göre davranabilsin
      // (ör. nemesis modunda 409 = aktif çift kalmadı → modu kapat).
      const e = new Error(detail || t("common.err_http", { status: res.status }));
      e.status = res.status;
      throw e;
    }
    return res.json();
  }

  // ── Toast + yardımcılar ───────────────────────────────────────
  let toastTimer;
  function toast(msg, kind = "error") {
    const el = $("#toast");
    el.textContent = msg;
    el.className = "toast " + kind;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 5000);
  }

  // Birincil değer rating.score'dur (harman engine; harman-dışı version'da score = ordinal).
  const fmtRating = (x) => x.toFixed(1);
  // İkincil bilgi: W/L çekirdeği (ordinal) + kariyer performans çarpanı.
  // perf_avg null ise (harman-dışı version) gösterilmez — score zaten ordinal'dir.
  const ratingSub = (r) =>
    r.perf_avg == null
      ? ""
      : t("common.rating_sub", { wl: fmtRating(r.ordinal), perf: r.perf_avg.toFixed(2) });
  const fmtDelta = (d) => (d >= 0 ? "+" : "−") + Math.abs(d).toFixed(1);
  // Haftanın enleri delta'sı contract'ta 2 ondalıklı gelir ("+2.31") — o hassasiyet korunur.
  const fmtDelta2 = (d) => (d >= 0 ? "+" : "−") + Math.abs(d).toFixed(2);
  const fmtDate = (iso) =>
    new Date(iso).toLocaleString(uiLocale(), { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const fmtDuration = (s) => (s == null ? "—" : t("common.minutes_short", { n: Math.round(s / 60) }));
  // innerHTML'e giren serbest metin (oyuncu adı, riot_id, şampiyon, hata detayı) için.
  const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ESC[c]);
  const playerName = (id) => {
    const p = state.roster.find(x => x.id === id);
    return p ? p.display_name : "#" + id;
  };

  // ── Roller (GÖREV 0) ──────────────────────────────────────────
  // Sıra contract'taki kanonik sıradır; gösterim her yerde bu sırayı izler.
  // Ad ve kısaltmalar sözlükten gelir (common.role_* / common.role_abbr_*).
  const ROLES = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"];
  const roleName = (r) => t("common.role_" + r.toLowerCase());
  const roleAbbr = (r) => t("common.role_abbr_" + r.toLowerCase());
  // Bilinmeyen pozisyon değeri (ileri sürüm backend'i) olduğu gibi gösterilir.
  const roleLabel = (pos) =>
    pos == null ? "—" : (ROLES.includes(pos) ? roleName(pos) : pos);
  const roleOrder = (pos) => { const i = ROLES.indexOf(pos); return i === -1 ? ROLES.length : i; };

  // role_ratings kompakt şeridi. long=true → geniş yerleşim (sıralama tablosu).
  // matches === 0 olan rol soluk gösterilir (default prior, gerçek veri değil).
  function roleCells(rr, long = false) {
    if (!rr) return ""; // backend eski şekli dönüyorsa şerit hiç çizilmez
    const cells = ROLES.map(r => {
      const v = rr[r];
      if (!v || typeof v.score !== "number") return "";
      const zero = !v.matches;
      const title = t("common.role_cell_title",
        { role: roleName(r), score: fmtRating(v.score), matches: v.matches });
      return `<div class="role-cell${zero ? " zero" : ""}" title="${title}">
          <span class="rc-role">${long ? roleName(r) : roleAbbr(r)}</span>
          <span class="rc-score">${fmtRating(v.score)}</span>
          <span class="rc-matches">${long ? t("common.n_matches", { n: v.matches }) : v.matches}</span>
        </div>`;
    }).join("");
    return cells ? `<div class="role-strip${long ? " long" : ""}">${cells}</div>` : "";
  }

  // ── Data Dragon varlıkları (GÖREV 14) ─────────────────────────
  // api_contract §8: eşya/şampiyon görselleri ve adları DEPLOY sırasında
  // webui/assets/ddragon/ altına indirilir; tarayıcı dışarı istek atmaz.
  // Varlıklar hiç yoksa (yerel geliştirme, indirme yarım) ya da bir id sözlükte
  // değilse KIRIK GÖRSEL gösterilmez: sessizce yer tutucu moduna düşülür.
  //
  // JSON'lar bir kez çekilir ve önbelleğe alınır: loadAssets() ikinci çağrıda
  // istek atmaz, aynı promise'i döner ve ASLA reject etmez (varlık yokluğu
  // hata değil, gösterim modudur — profil/maç detayı bu yüzden bloke olmaz).
  const DD = { loaded: false, version: null, items: null, champs: null, positions: false };
  const DD_BASE = "assets/ddragon/";
  let ddPromise = null;

  function loadAssets() {
    if (ddPromise) return ddPromise;
    // Varlık dosyaları API DEĞİLDİR: X-API-Key taşımaz, USE_MOCK yolundan geçmez.
    const grab = (name) =>
      window.fetch(DD_BASE + name)
        .then(r => (r.ok ? r.json() : null))
        .catch(() => null);
    // Pozisyon ikonları (GÖREV 15) sözlüklerde LİSTELENMEZ, dosya olarak durur:
    // varlıkları TEK yoklamayla anlaşılır. Beş ikon için beş istek atılmaz —
    // indirme betiği beşini aynı döngüde yazar, biri varsa hepsi vardır. Yoklanan
    // dosya ikonun kendisidir, yani istek boşa gitmez: mask onu önbellekten okur.
    const probe = (name) => window.fetch(DD_BASE + name).then(r => r.ok).catch(() => false);
    ddPromise = Promise.all([
      grab("manifest.json"), grab("items.json"), grab("champions.json"), probe("position/top.svg"),
    ])
      .then(([man, items, champs, hasPos]) => {
        DD.version = man && typeof man.version === "string" ? man.version : null;
        DD.items = items && typeof items === "object" ? items : null;
        DD.champs = champs && typeof champs === "object" ? champs : null;
        DD.positions = hasPos === true;
        DD.loaded = true;
      });
    return ddPromise;
  }

  const itemMeta = (id) => (DD.items ? DD.items[String(id)] || null : null);
  // Ad/açıklama aktif dile göre okunur (name_tr/name_en, desc_tr/desc_en);
  // alan yoksa diğer dile düşülür, o da yoksa boş döner.
  function ddText(meta, field) {
    if (!meta) return "";
    const order = window.I18n.getLang() === "tr" ? ["_tr", "_en"] : ["_en", "_tr"];
    for (const suffix of order) {
      const v = meta[field + suffix];
      if (typeof v === "string" && v) return v;
    }
    return "";
  }
  // Sözlükte olmayan/kaldırılmış eşya adı "Esya #id" olarak gösterilir.
  const itemName = (id) => ddText(itemMeta(id), "name") || t("common.item_unknown", { id });
  const itemDesc = (id) => ddText(itemMeta(id), "desc");
  // Etiketler yalnız dd varlıkları yüklüyken bilinir; varlık yoksa BOŞ dizi
  // döner → etikete dayalı her karar (eleme, totem tespiti) devre dışı kalır.
  const itemTags = (id) => {
    const meta = itemMeta(id);
    return meta && Array.isArray(meta.tags) ? meta.tags : [];
  };
  // Favori eşya seçiminde atlanan etiketler (api_contract §2 "top_items":
  // eleme backend'de DEĞİL burada yapılır, backend eşya meta verisi bilmez).
  const SKIP_TAGS = ["Trinket", "Consumable"];
  const itemSkipped = (id) => itemTags(id).some(x => SKIP_TAGS.indexOf(x) !== -1);
  // Ziynet eşyası (totem): "Trinket" etiketi. Kontrol totemi (2055) Consumable'dır,
  // Trinket DEĞİL — bilerek taşınmaz, normal eşya gibi sırasında kalır.
  const itemIsTrinket = (id) => itemTags(id).indexOf("Trinket") !== -1;
  const itemIconSrc = (id) =>
    itemMeta(id) ? DD_BASE + "item/" + encodeURIComponent(String(id)) + ".png" : null;
  const champIconSrc = (name) => {
    const c = DD.champs && name ? DD.champs[name] : null;
    return c && typeof c.icon === "string" ? DD_BASE + c.icon : null;
  };
  // Yer tutucu metni: eşyada id'nin son 2 hanesi, şampiyonda baş harf, ikisi de
  // çıkmazsa soru işareti.
  const itemPh = (id) => {
    const s = String(id);
    return /^\d+$/.test(s) ? s.slice(-2) : "?";
  };
  const champPh = (name) => (name ? String(name).slice(0, 1).toUpperCase() : "?");

  // Yer tutucu kutusu HER ZAMAN çizilir, görsel onun ÜSTÜNE biner: dosya 404
  // verirse img kaldırılır ve altındaki kutu görünür → kırık görsel imkânsız.
  // alt: görselin erişilebilir adı. VARSAYILAN BOŞTUR — build slotları ve favori
  // eşya kartı adı zaten saran öğenin aria-label'ında taşır, orada alt yazmak
  // ekran okuyucuya aynı adı iki kez okuturdu. Sarmalayıcısı olmayan yerlerde
  // (maç kartı satırındaki şampiyon portresi) ad buraya verilir.
  function ddIconHtml(src, ph, cls, alt = "") {
    // Yer tutucu metni SALT GÖRSELDİR (aria-hidden): erişilebilir adı slot'un
    // aria-label'ı ya da kartın kendi metni taşır, "58" gibi ekler okunmaz.
    return `<span class="dd-ico ${cls}">` +
      `<span class="dd-ph" aria-hidden="true">${esc(ph)}</span>` +
      // loading="lazy" KULLANILMAZ: ikonlar aynı container'dan gelen ~5KB'lık
      // dosyalar, tembel yükleme kazanç getirmiyor; buna karşılık arka plandaki
      // sekmede istek hiç başlamayabiliyor (yer tutucu takılı kalırdı).
      (src ? `<img class="dd-img" src="${esc(src)}" alt="${esc(alt)}">` : "") +
      `</span>`;
  }
  // Yükleme hatasında HEMEN yer tutucuya düşülmez: tek prosesli sunucuda ilk
  // açılışta ~80 ikon isteği aynı ana denk gelince bir kısmı GEÇİCİ olarak
  // düşebiliyor (dosyalar aslında 200 dönüyor). Bu yüzden kısa gecikmeyle AYNI
  // URL bir kez daha denenir — cache-buster parametresi YOKTUR, yoksa her
  // yeniden çizim önbelleği ıskalar. İkinci hatada img kaldırılır, altındaki
  // yer tutucu görünür (kırık görsel yine imkânsız).
  const DD_RETRY_MS = 600;

  function ddRetryImage(img) {
    if (img.dataset.ddRetried === "1") { img.remove(); return; }
    img.dataset.ddRetried = "1";
    const src = img.getAttribute("src");
    setTimeout(() => {
      // Sekme/dil değişimiyle yeniden çizildiyse düğüm artık DOM'da değildir.
      if (!img.isConnected || !src) return;
      // Aynı URL'yi yeniden istemenin güvenilir yolu: src'yi düşürüp geri koymak
      // (aynı değeri yeniden atamak bazı tarayıcılarda yeni istek doğurmuyor).
      img.removeAttribute("src");
      img.setAttribute("src", src);
    }, DD_RETRY_MS);
  }

  // innerHTML sonrası çağrılır: yüklenemeyen görselleri tek denemeden sonra kaldırır.
  function ddBindImages(root) {
    (root || document).querySelectorAll(".dd-img").forEach(img => {
      img.addEventListener("error", () => ddRetryImage(img));
      // Dinleyici bağlanmadan önce düşmüş olabilir (önbellekten gelen hata).
      if (img.complete && img.naturalWidth === 0) ddRetryImage(img);
    });
  }

  // ── Resmî rol simgesi (GÖREV 15) — ORTAK yardımcı ─────────────
  // Simge <img> DEĞİL, CSS mask'idir: tek renkli SVG kapsayıcının metin rengiyle
  // (currentColor) boyanır, yani kullanıldığı yerin paletine uyar; img olsaydı
  // dosyanın sabit altın rengi temadan bağımsız yanardı.
  // Varlık katmanının "yoksa yer tutucu" ilkesi burada da geçerli — iki katmanlı
  // emniyet, kırık/boş kutu imkânsız:
  //   1) İkonlar indirilmemişse (DD.positions false) ya da rol bilinmiyorsa
  //      pos-ico sınıfı HİÇ basılmaz, ETİKET DÜZ METİN kalır.
  //   2) Tarayıcı mask desteklemiyorsa style.css'teki @supports bloğu hiç
  //      uygulanmaz; içerideki metin görünür kaldığı için yine etiket okunur.
  // Bu yüzden metin DOM'da HER ZAMAN durur, yalnız simge çizilebilirken gizlenir.
  // text  = simge çizilemezse görünecek etiket (çağıranın kendi biçimi: maç
  //         kartında tam ad, maç detayında kısaltma, eşleşmeyen satırda "?").
  // cls   = çağıranın kendi sınıfı (maç kartı "pos-tag", maç detayı "md-role");
  //         boyut/renk oradan gelir, yardımcı yerleşime karışmaz.
  const POS_FILE = { TOP: "top", JUNGLE: "jungle", MIDDLE: "middle", BOTTOM: "bottom", UTILITY: "utility" };
  function posIconHtml(pos, text, cls) {
    const file = pos == null ? null : POS_FILE[pos];
    if (!file || !DD.positions) return `<span class="${cls}">${esc(text)}</span>`;
    // role="img" + aria-label: simge görsel olarak metnin yerine geçtiğinde ekran
    // okuyucu rolü yine TAM ADIYLA duyar (sözlükteki common.role_*), title de
    // aynı adı fare ucunda gösterir — kısaltmayla yetinilmez.
    const name = roleName(pos);
    return `<span class="${cls} pos-ico pos-ico-${file}" role="img"` +
      ` aria-label="${esc(name)}" title="${esc(name)}">` +
      `<span class="pos-ico-txt">${esc(text)}</span></span>`;
  }

  // ── API key modalı ────────────────────────────────────────────
  function openKeyModal() {
    $("#key-input").value = state.apiKey;
    $("#key-modal").hidden = false;
    $("#key-input").focus();
  }
  $("#key-form").addEventListener("submit", (e) => {
    e.preventDefault();
    state.apiKey = $("#key-input").value.trim();
    localStorage.setItem("apiKey", state.apiKey);
    $("#key-modal").hidden = true;
    showView(currentView, true); // aktif görünümü yeni anahtarla yeniden yükle
  });
  // Mobilde anahtar modalı çekmecenin üstüne binmesin: önce çekmece kapanır
  // (masaüstünde sbCloseNav no-op'tur, panel zaten sabittir).
  $("#btn-key").addEventListener("click", () => { sbCloseNav(); openKeyModal(); });

  // ── Sol gezinme kabuğu (GÖREV 17, K1 "Sade Ray") ──────────────
  // Masaüstünde (≥880px) panel hep açıktır; bu blok yalnız mobil çekmeceyi
  // sürer. Açıkken: scrim tıkı ve Esc kapatır, odak çekmecede döner (basit
  // odak tuzağı), body scroll'u kilitlenir (body.sb-lock). Kapatan etkileşim
  // klavyeden geldiyse odak hamburger düğmesine iade edilir.
  const sbApp = $("#sb-app");
  const sbNav = $("#sb-nav");
  const sbBurger = $("#sb-burger");
  const sbIsOpen = () => sbApp.classList.contains("sb-open");
  function sbOpenNav() {
    sbApp.classList.add("sb-open");
    sbBurger.setAttribute("aria-expanded", "true");
    document.body.classList.add("sb-lock");
    const target = sbNav.querySelector(".sb-item.active") || sbNav.querySelector("button");
    if (target) target.focus();
  }
  function sbCloseNav(refocus = false) {
    if (!sbIsOpen()) return;
    sbApp.classList.remove("sb-open");
    sbBurger.setAttribute("aria-expanded", "false");
    document.body.classList.remove("sb-lock");
    if (refocus) sbBurger.focus();
  }
  sbBurger.addEventListener("click", () => (sbIsOpen() ? sbCloseNav(true) : sbOpenNav()));
  $("#sb-scrim").addEventListener("click", () => sbCloseNav());
  document.addEventListener("keydown", (e) => {
    if (!sbIsOpen()) return;
    if (e.key === "Escape") { sbCloseNav(true); return; }
    if (e.key !== "Tab") return;
    // Basit odak tuzağı: Tab sırası çekmecedeki düğmeler arasında döner.
    const focusables = sbNav.querySelectorAll("button:not([disabled])");
    if (!focusables.length) return;
    const first = focusables[0], last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    else if (!sbNav.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
  });
  // Çekmece açıkken pencere masaüstü genişliğine dönerse durum sıfırlanır
  // (panel zaten sabit görünür; kilit/scrim asılı kalmasın).
  const sbMq = window.matchMedia("(min-width: 880px)");
  const sbOnMq = () => { if (sbMq.matches) sbCloseNav(); };
  if (sbMq.addEventListener) sbMq.addEventListener("change", sbOnMq);
  else sbMq.addListener(sbOnMq); // eski Safari yedeği

  // ── Sekme yönlendirme ─────────────────────────────────────────
  const loaders = {
    balance: loadBalance, leaderboard: loadLeaderboard, highlights: loadHighlights,
    map: loadMap, matches: loadMatches, profile: loadProfile,
    matchdetail: loadMatchDetail, health: loadHealth, meta: loadMeta,
    faq: loadFaq, faqdetail: loadFaqDetail, pick: loadPick, matchup: loadMatchup,
  };
  // Sekmesi olmayan "detay" görünümleri (GÖREV 1: profil, GÖREV 4: harita) hangi sekmeyi
  // aktif tutar. İkisi de birden çok yerden açılır → geldiği görünümün sekmesi yanar,
  // zincir (harita → profil) özyinelemeyle gerçek sekmeye çözülür.
  // Maç detayı (GÖREV 8) iki yerden açılır: Geçmiş kartı ve (GÖREV 10) profil
  // grafiğindeki nokta → geldiği görünümün sekmesi yanar, profilden gelişte zincir
  // profile → profileFrom olarak çözülür.
  // META (GÖREV 16) ve Sağlık (GÖREV 13, GÖREV 20 ile kendi sekmesine taşındı)
  // burada YOKTUR → normal sekme gibi çözülür, geri düğmesi yoktur.
  //
  // Zincir artık ÇİFT YÖNLÜ olabilir (GÖREV 15: maç detayı satırındaki addan
  // profile) → profile→matchdetail→profile sonsuz özyinelemeye girerdi. Bu yüzden
  // çözüm döngüsel yürütülür: bir ad ikinci kez gelirse zincirin GERÇEK kökü
  // geri yığınının dibindeki karedir (zincire ilk girilen görünüm), o da yoksa
  // maç detayının doğal sekmesi ("matches") kullanılır.
  const DETAIL_FROM = {
    profile: () => state.profileFrom,
    map: () => state.mapFrom,
    matchdetail: () => state.matchFrom,
    faqdetail: () => "faq",   // SSS detayı TEK yerden açılır (SSS listesi) → sabit eşleme
  };
  function tabOf(name, seen) {
    seen = seen || new Set();
    while (DETAIL_FROM[name] && !seen.has(name)) { seen.add(name); name = DETAIL_FROM[name](); }
    if (!DETAIL_FROM[name]) return name;
    const root = state.backStack[0];
    return root && !seen.has(root.from) ? tabOf(root.from, seen) : "matches";
  }
  let currentView = "balance";

  function showView(name, forceReload = false) {
    currentView = name;
    // Görünüm-bazlı genişlik istisnası (GÖREV 21): Seçim ekranı iki sütunlu
    // analiz paneli için 1080px kullanır, diğer görünümler 720px'te kalır.
    $("#main").classList.toggle("pa-wide", name === "pick");
    syncFaqHash(name);
    const tab = tabOf(name);
    document.querySelectorAll(".view").forEach(v => { v.hidden = v.id !== "view-" + name; });
    document.querySelectorAll(".sb-item").forEach(tb => tb.classList.toggle("active", tb.dataset.view === tab));
    window.scrollTo({ top: 0 });
    loaders[name](forceReload).catch(e => toast(e.message));
  }
  // Sekmeye basmak zinciri TERK ETMEKTİR: birikmiş geri kareleri düşer
  // (yeni zincir sıfırdan kurulur, bayat kare geri düğmesine karışmaz).
  // Mobil çekmece seçimden sonra kapanır (masaüstünde sbCloseNav no-op).
  document.querySelectorAll(".sb-item").forEach(tb =>
    tb.addEventListener("click", () => { clearBack(); showView(tb.dataset.view); sbCloseNav(true); }));

  async function fetchRoster(force = false) {
    if (state.roster.length && !force) return state.roster;
    state.roster = await api("/players");
    return state.roster;
  }

  // ── 1) Dengeleme ──────────────────────────────────────────────
  async function loadBalance(force) {
    await fetchRoster(force);
    const grid = $("#roster");
    grid.innerHTML = "";
    // Nemesis modunda çiftin iki üyesi kartta işaretlenir (ikisi de seçilmek zorunda).
    const nemIds = new Set(state.nemesisMode ? state.nemesisMode.players.map(x => x.player_id) : []);
    for (const p of state.roster) {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "player-card";
      card.classList.toggle("nem-pick", nemIds.has(p.id));
      card.classList.toggle("selected", state.selected.has(p.id));
      card.innerHTML =
        `<span class="p-name">${esc(p.display_name)}</span>` +
        `<span class="p-meta">${fmtRating(p.rating.score)} · ${t("common.n_matches", { n: p.matches_played })}</span>` +
        roleCells(p.role_ratings);
      card.addEventListener("click", () => {
        if (state.selected.has(p.id)) state.selected.delete(p.id);
        else if (state.selected.size < 10) state.selected.add(p.id);
        else { toast(t("balance.err_max_players"), "warn"); return; }
        card.classList.toggle("selected", state.selected.has(p.id));
        updatePickCounter();
      });
      grid.appendChild(card);
    }
    updatePickCounter();
  }

  function updatePickCounter() {
    const n = state.selected.size;
    $("#pick-counter").innerHTML = `${n}<span>${t("balance.pick_suffix")}</span>`;
    $("#btn-balance").disabled = n !== 10;
    renderNemesisBadge();
  }

  // ── 1b) Nemesis modu (GÖREV 3) ────────────────────────────────
  // Mod yalnız Enler ekranındaki "Nemesis maçı kur" ile açılır; açıkken Dengele
  // düğmesi POST /balance/nemesis'e gider (çift karşı takımlara + sabit rol).
  function renderNemesisBadge() {
    const box = $("#nemesis-mode");
    const nm = state.nemesisMode;
    if (!nm) { box.hidden = true; return; }
    box.hidden = false;
    const [a, b] = nm.players;
    $("#nem-mode-pair").textContent = t("balance.nem_pair",
      { a: a.display_name, b: b.display_name, role: roleLabel(nm.role) });
    const missing = nm.players.filter(x => !state.selected.has(x.player_id));
    const hint = $("#nem-mode-hint");
    hint.textContent = missing.length
      ? t("balance.nem_missing", { names: missing.map(x => x.display_name).join(", ") })
      : t("balance.nem_locked");
    hint.classList.toggle("warn", missing.length > 0);
  }

  function startNemesisMode(n) {
    const pair = n && n.active ? n[n.active] : null;
    if (!pair) { toast(t("balance.err_no_active_pair"), "warn"); return; }
    state.nemesisMode = {
      source: n.active,
      role: pair.role,
      players: pair.players.map(x => ({ player_id: x.player_id, display_name: x.display_name })),
    };
    $("#suggestions").innerHTML = "";   // önceki (nemesissiz) öneriler artık geçersiz
    showView("balance");
  }

  function exitNemesisMode() {
    if (!state.nemesisMode) return;
    state.nemesisMode = null;
    $("#suggestions").innerHTML = "";
    renderNemesisBadge();
    if (currentView === "balance") loadBalance().catch(e => toast(e.message)); // işaretleri kaldır
  }
  $("#btn-nemesis-off").addEventListener("click", exitNemesisMode);

  $("#btn-balance").addEventListener("click", async () => {
    const btn = $("#btn-balance");
    const nm = state.nemesisMode;
    btn.disabled = true;
    btn.textContent = t("balance.calculating");
    try {
      const res = await api(nm ? "/balance/nemesis" : "/balance", {
        method: "POST",
        body: { player_ids: [...state.selected], top_n: 3 },
      });
      renderSuggestions(res.suggestions, res.nemesis);
    } catch (e) {
      // 409 = backend'de artık aktif nemesis çifti yok (veri değişmiş olabilir);
      // modda kalmanın anlamı kalmaz, kapatıp normal dengelemeye dönülür.
      if (e.status === 409 && state.nemesisMode) {
        exitNemesisMode();
        toast(e.message + " " + t("balance.nem_mode_closed"));
      } else {
        toast(e.message);
      }
    } finally {
      btn.textContent = t("balance.balance_btn");
      btn.disabled = state.selected.size !== 10;
    }
  });

  // Dengeleme yanıtı artık rol atamalı: team_100/team_200 = [{player_id, position}].
  // Eski salt-id şekli gelirse (backend güncellenmemişse) rolsüz gösterilir.
  const teamEntry = (e) =>
    (e !== null && typeof e === "object") ? e : { player_id: e, position: null };
  const teamList = (members, side, nemIds) =>
    `<ul class="team ${side}">` +
    [...members].map(teamEntry)
      .sort((a, b) => roleOrder(a.position) - roleOrder(b.position))
      .map(m => `<li${nemIds && nemIds.has(m.player_id) ? ' class="nem-row"' : ""}>` +
                `<span class="pos-tag">${esc(roleLabel(m.position))}</span>` +
                `<span class="p-who">${esc(playerName(m.player_id))}</span></li>`)
      .join("") + "</ul>";

  // nemesis: yalnız POST /balance/nemesis yanıtında gelir ({source, role, player_ids}) —
  // öneri çizimi aynıdır, çiftin satırları vurgulanır.
  function renderSuggestions(suggestions, nemesis) {
    const box = $("#suggestions");
    const nemIds = nemesis ? new Set(nemesis.player_ids) : null;
    box.innerHTML = `<h2 class='sug-title'>${t("balance.suggestions_title")}</h2>` +
      (nemesis && suggestions.length
        ? `<p class="sug-note">` + t("balance.nem_match_note", {
            pair: esc(nemesis.player_ids.map(playerName).join(" vs ")),
            role: esc(roleLabel(nemesis.role)),
            source: t(nemesis.source === "weekly" ? "balance.pair_weekly" : "balance.pair_alltime"),
          }) + `</p>`
        : "");
    suggestions.forEach((s, i) => {
      const best = i === 0;
      const bluePct = Math.round(s.p_win_team_100 * 100);
      const card = document.createElement("article");
      card.className = "sug-card" + (best ? " best" : "");
      card.innerHTML =
        (best ? `<div class="best-badge">${t("balance.best_badge")}</div>` : "") +
        `<div class="sug-teams">
           ${teamList(s.team_100, "blue", nemIds)}
           <div class="sug-mid">
             <div class="quality">${t("common.percent", { n: (s.quality * 100).toFixed(1) })}</div>
             <div class="quality-label">${t("balance.quality_label")}</div>
           </div>
           ${teamList(s.team_200, "red", nemIds)}
         </div>
         <div class="winbar" role="img" aria-label="${t("balance.winbar_aria", { pct: bluePct })}">
           <div class="winbar-blue" style="width:${bluePct}%"></div>
         </div>
         <div class="winbar-caption"><span>${t("balance.win_blue", { pct: bluePct })}</span><span>${t("balance.win_red", { pct: 100 - bluePct })}</span></div>`;
      box.appendChild(card);
    });
    box.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // ── 1c) Seçim danışmanı (GÖREV 21, tasarım S3 "Analiz Paneli") ──
  // Sol yarı: iki kompakt giriş listesi (Takımım / Karşı Takım) + "Analizi
  // tazele". Sağ yarı: AD/AP denge çubukları + eksik/tehdit rozetleri + gerekçe
  // rozetli öneri kartları. Analiz MOTORU ayrı modüldedir (advisor.js,
  // window.PickAdvisor): saf fonksiyon, metinsiz — rozet TANIMLAYICILARI döner,
  // görünen metni burada i18n kurar. Veri katmanı:
  //   - tiers.json fetchMeta() ile ORTAK (META sekmesiyle aynı önbellek);
  //     yeni şema {name, win_rate, pick_rate} + eski düz-string ikisi de okunur.
  //   - counters.json ayrı fetch (aynı desen: API değil, X-API-Key yok,
  //     USE_MOCK yolundan geçmez, asla reject etmez).
  //   - champions.json tags/info: dd- katmanının zaten çektiği sözlükten okunur
  //     (paralel veri işi alanları ekler; yoksa kompozisyon sinyali atlanır).
  //   - Grup rozeti GET /matches'tan İSTEMCİDE sayılır (yeni endpoint YOK) ve
  //     öneri SIRASINI ETKİLEMEZ (Teoman kararı — yalnız bilgi rozeti).
  // Mock modunda tiers/counters/tags-info window.MOCK_ADVISOR'dan gelir.
  // Her seçim değişikliği analizi canlı tazeler; "Analizi tazele" düğmesi
  // ayrıca grup verisini (GET /matches) yeniden çeker.
  const PA_COUNTERS_URL = "assets/meta/counters.json";
  let paCountersPromise = null;

  function fetchCounters() {
    if (paCountersPromise) return paCountersPromise;
    paCountersPromise = window.fetch(PA_COUNTERS_URL)
      .then(r => {
        if (!r.ok) return { err: { kind: "http", status: r.status } };
        return r.json().then(
          d => (d && typeof d === "object" && d.counters && typeof d.counters === "object"
            ? { data: d } : { err: { kind: "shape" } }),
          () => ({ err: { kind: "shape" } }));
      })
      .catch(() => ({ err: { kind: "network" } }));
    return paCountersPromise;
  }

  // Grup verisi: valid maç örneklemi + şampiyon×oyuncu W-L endeksi. Uç düşerse
  // sinyal sessizce atlanır (rozetler çıkmaz, ekranın kalanı çalışır).
  let paGroupPromise = null;
  function paGroup() {
    if (!paGroupPromise) {
      paGroupPromise = api("/matches?limit=200")
        .then(list => ({
          index: window.PickAdvisor.buildGroupIndex(list),
          sample: Array.isArray(list) ? list.filter(m => m && m.status === "valid").length : null,
        }))
        .catch(() => ({ index: {}, sample: null }));
    }
    return paGroupPromise;
  }

  let paData = null; // {tiers, counters, group, sample, champInfo, names}

  // Girişler görünüm değişse de kalır (in-memory): ilk açılışta satır i kanonik
  // rol i'yi alır; karşı tarafta rol "Bilinmiyor"a (null) çevrilebilir.
  function ensurePickState() {
    if (!state.pick) {
      state.pick = {
        mine: ROLES.map(r => ({ champ: null, role: r })),
        enemy: ROLES.map(r => ({ champ: null, role: r })),
        me: null,
      };
    }
    return state.pick;
  }

  // Şampiyon meta sözlüğü: DD champions.json girdileri (tags/info paralel veri
  // işiyle gelir). Mock modunda MOCK_ADVISOR.champ_info tags'siz girdileri doldurur.
  function paChampInfo() {
    const out = {};
    if (DD.champs) Object.keys(DD.champs).forEach(k => { out[k] = DD.champs[k]; });
    const mock = CONFIG.USE_MOCK && window.MOCK_ADVISOR ? window.MOCK_ADVISOR.champ_info : null;
    if (mock) Object.keys(mock).forEach(k => {
      const cur = out[k];
      if (!cur || !Array.isArray(cur.tags)) out[k] = Object.assign({}, cur, mock[k]);
    });
    return out;
  }

  // Otomatik tamamlama adları: DD sözlüğü ∪ tier listeleri. İkisi de yoksa boş
  // liste kalır → seçici SERBEST METİN girişi gibi davranır (varlık yokluğunda
  // yer tutucu metin girişi — görev tanımındaki düşüş yolu).
  function paNames(tiers) {
    const set = new Set();
    if (DD.champs) Object.keys(DD.champs).forEach(n => set.add(n));
    if (tiers && typeof tiers === "object") Object.keys(tiers).forEach(rk => {
      const cell = tiers[rk];
      if (!cell || typeof cell !== "object") return;
      ["S", "A", "B"].forEach(tier => {
        (Array.isArray(cell[tier]) ? cell[tier] : []).forEach(x => {
          const name = typeof x === "string" ? x
            : x && typeof x === "object" && typeof x.name === "string" ? x.name : "";
          if (name.trim()) set.add(name.trim());
        });
      });
    });
    return [...set].sort((a, b) => a.localeCompare(b, "en"));
  }

  // Serbest metni bilinen ada çözer (büyük/küçük harf duyarsız); bilinmeyen ad
  // OLDUĞU GİBİ kabul edilir (sinyalsiz kalır, portresi yer tutucuya düşer).
  function paCanonName(text) {
    const q = String(text || "").trim();
    if (!q) return null;
    const ln = q.toLowerCase();
    const hit = paData && paData.names.find(n => n.toLowerCase() === ln);
    return hit || q;
  }

  const paPortHtml = (champ) =>
    ddIconHtml(champ ? champIconSrc(champ) : null, champPh(champ), "champ");

  function paRoleOpts(side, cur) {
    const opts = ROLES.map(r =>
      `<option value="${r}"${cur === r ? " selected" : ""}>${roleName(r)}</option>`);
    if (side === "enemy")
      opts.push(`<option value=""${cur == null ? " selected" : ""}>${t("pick.role_unknown")}</option>`);
    return opts.join("");
  }

  function paRowHtml(side, i, row) {
    const meHtml = side === "mine"
      ? `<label class="pa-me"><input type="radio" name="pa-me"${state.pick.me === i ? " checked" : ""}
           aria-label="${esc(t("pick.me_aria", { n: i + 1 }))}"><span>${t("pick.me")}</span></label>`
      : "";
    return `<div class="pa-row${side === "mine" && state.pick.me === i ? " mine" : ""}"
          data-side="${side}" data-i="${i}">
        <span class="pa-port">${paPortHtml(row.champ)}</span>
        <span class="pa-pickbox">
          <input class="pa-input" type="text" value="${esc(row.champ || "")}"
                 placeholder="${esc(t("pick.champ_placeholder"))}"
                 aria-label="${esc(t(side === "mine" ? "pick.my_champ_aria" : "pick.enemy_champ_aria", { n: i + 1 }))}"
                 autocomplete="off" spellcheck="false">
          <ul class="pa-list" hidden></ul>
        </span>
        <select class="pa-role"
                aria-label="${esc(t(side === "mine" ? "pick.my_role_aria" : "pick.enemy_role_aria", { n: i + 1 }))}">${paRoleOpts(side, row.role)}</select>
        ${meHtml}
      </div>`;
  }

  function bindPickRow(rowEl) {
    const side = rowEl.dataset.side, idx = Number(rowEl.dataset.i);
    const row = state.pick[side === "mine" ? "mine" : "enemy"][idx];
    const input = rowEl.querySelector(".pa-input");
    const list = rowEl.querySelector(".pa-list");
    const port = rowEl.querySelector(".pa-port");
    let active = -1; // klavyeyle gezilen öneri

    const closeList = () => { list.hidden = true; list.innerHTML = ""; active = -1; };
    const commit = (name) => {
      const canon = paCanonName(name);
      row.champ = canon;
      input.value = canon || "";
      port.innerHTML = paPortHtml(canon);
      ddBindImages(port);
      closeList();
      renderAnalysis();
    };
    const openList = () => {
      const q = input.value.trim().toLowerCase();
      if (!q || !paData || !paData.names.length) { closeList(); return; }
      const starts = [], contains = [];
      for (const n of paData.names) {
        const ln = n.toLowerCase();
        if (ln.startsWith(q)) starts.push(n);
        else if (ln.indexOf(q) !== -1) contains.push(n);
        if (starts.length >= 8) break;
      }
      const found = starts.concat(contains).slice(0, 8);
      if (!found.length) { closeList(); return; }
      list.innerHTML = found.map(n =>
        `<li><button type="button" class="pa-opt" data-name="${esc(n)}">${paPortHtml(n)}<span>${esc(n)}</span></button></li>`).join("");
      ddBindImages(list);
      list.hidden = false;
      active = -1;
      // mousedown: input blur'undan ÖNCE koşar (click olsaydı blur ile yarışırdı).
      list.querySelectorAll(".pa-opt").forEach(btn =>
        btn.addEventListener("mousedown", (e) => { e.preventDefault(); commit(btn.dataset.name); }));
    };
    input.addEventListener("input", openList);
    input.addEventListener("keydown", (e) => {
      const opts = list.querySelectorAll(".pa-opt");
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        if (list.hidden || !opts.length) return;
        e.preventDefault();
        active = e.key === "ArrowDown"
          ? (active + 1) % opts.length : (active - 1 + opts.length) % opts.length;
        opts.forEach((o, j) => o.classList.toggle("on", j === active));
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (!list.hidden && opts.length) commit(opts[active === -1 ? 0 : active].dataset.name);
        else commit(input.value);
      } else if (e.key === "Escape") {
        closeList();
      }
    });
    input.addEventListener("blur", () => {
      // Kısa gecikme: liste öğesinin mousedown commit'i önce koşabilsin.
      setTimeout(() => {
        if (!input.isConnected) return;
        closeList();
        if (input.value.trim() !== (row.champ || "")) commit(input.value);
      }, 120);
    });
    rowEl.querySelector(".pa-role").addEventListener("change", (e) => {
      row.role = e.target.value || null;
      renderAnalysis();
    });
    const me = rowEl.querySelector('input[type="radio"]');
    if (me) me.addEventListener("change", () => {
      state.pick.me = idx;
      $("#pick-body").querySelectorAll('.pa-row[data-side="mine"]').forEach(r =>
        r.classList.toggle("mine", Number(r.dataset.i) === state.pick.me));
      renderAnalysis();
    });
  }

  function renderPickShell() {
    const box = $("#pick-body");
    const rows = (side, arr) => arr.map((row, i) => paRowHtml(side, i, row)).join("");
    box.innerHTML =
      `<div class="pa-left">
         <section class="pa-panel">
           <h2 class="pa-title pa-blue">${t("pick.my_team")}</h2>
           ${rows("mine", state.pick.mine)}
         </section>
         <section class="pa-panel">
           <h2 class="pa-title pa-red">${t("pick.enemy_team")}</h2>
           ${rows("enemy", state.pick.enemy)}
         </section>
         <button id="pa-refresh" class="btn-primary pa-refresh" type="button">${t("pick.refresh_btn")}</button>
       </div>
       <div id="pa-right" class="pa-right"></div>`;
    ddBindImages(box);
    box.querySelectorAll(".pa-row").forEach(bindPickRow);
    $("#pa-refresh").addEventListener("click", async (e) => {
      const btn = e.target;
      btn.disabled = true;
      btn.textContent = t("balance.calculating");
      paGroupPromise = null; // grup rozetleri taze /matches sayımıyla yenilensin
      try {
        const grp = await paGroup();
        paData.group = grp.index;
        paData.sample = grp.sample;
        renderAnalysis();
      } finally {
        btn.disabled = false;
        btn.textContent = t("pick.refresh_btn");
      }
    });
  }

  // ── Seçim: sağ yarım (analiz çıktısı) ─────────────────────────
  function paTilesHtml(res) {
    const sample = paData.sample == null ? "—" : paData.sample;
    return `<div class="pa-tiles">
        <div class="pa-tile"><div class="pa-tl">${t("pick.tile_role")}</div>
          <div class="pa-tv">${res.myRole ? esc(roleName(res.myRole)) : "—"}</div>
          <div class="pa-ts">${t(res.myRole ? "pick.tile_role_sub" : "pick.tile_role_none")}</div></div>
        <div class="pa-tile"><div class="pa-tl">${t("pick.tile_sugs")}</div>
          <div class="pa-tv">${res.suggestions.length}</div>
          <div class="pa-ts">${t(res.counterContext ? "pick.tile_sugs_counter" : "pick.tile_sugs_sub")}</div></div>
        <div class="pa-tile"><div class="pa-tl">${t("pick.tile_data")}</div>
          <div class="pa-tv">${sample}</div>
          <div class="pa-ts">${t("pick.tile_data_sub")}</div></div>
      </div>`;
  }

  // Çubukta renk tek başına taşıyıcı değildir: yüzdeler segmentin İÇİNE yazılır
  // (dar segmentte yazı sığmazsa aria-label aynı bilgiyi yine taşır).
  function paDmgBar(side, d) {
    const label = t(side === "us" ? "pick.side_us" : "pick.side_them");
    if (!d || !d.known) {
      return `<div class="pa-dmg-row"><span class="pa-dmg-side">${label}</span>
          <span class="pa-dmg-none">${t("pick.dmg_empty")}</span></div>`;
    }
    const aria = label + ": " + t("pick.ad_pct", { n: d.ad_pct }) + " / " + t("pick.ap_pct", { n: d.ap_pct });
    return `<div class="pa-dmg-row"><span class="pa-dmg-side">${label}</span>
        <div class="pa-dmg-bar" role="img" aria-label="${esc(aria)}">
          <span class="pa-seg ad" style="width:${d.ad_pct}%">${d.ad_pct >= 14 ? t("pick.ad_pct", { n: d.ad_pct }) : ""}</span>
          <span class="pa-seg ap" style="width:${d.ap_pct}%">${d.ap_pct >= 14 ? t("pick.ap_pct", { n: d.ap_pct }) : ""}</span>
        </div></div>`;
  }

  function paDamageHtml(res) {
    const keys = res.gaps.map(g => g.key);
    const warn = keys.indexOf("ap") !== -1 ? t("pick.dmg_warn_ad")
      : keys.indexOf("ad") !== -1 ? t("pick.dmg_warn_ap") : "";
    return `<section class="pa-panel">
        <h2 class="pa-title">${t("pick.damage_title")}</h2>
        ${paDmgBar("us", res.damage.us)}
        ${paDmgBar("them", res.damage.them)}
        <div class="pa-dmg-caption">
          <span><i class="pa-dot ad"></i>${t("pick.ad_word")}</span>
          <span><i class="pa-dot ap"></i>${t("pick.ap_word")}</span>
        </div>
        ${warn ? `<p class="pa-warn">${warn}</p>` : ""}
      </section>`;
  }

  const PA_GAP_KEY = {
    ap: "pick.gap_ap", ad: "pick.gap_ad", front: "pick.gap_front", carry: "pick.gap_carry",
  };

  function paGapsHtml(res) {
    const badges = res.gaps
      .filter(g => PA_GAP_KEY[g.key])
      .map(g => `<span class="pa-badge pa-gapb">${t(PA_GAP_KEY[g.key])}</span>`).join("");
    const threat = res.threats.length
      ? `<p class="pa-threat">${t("pick.threat_line", {
          list: res.threats.map(x =>
            `<b>${esc(x.name)}</b>` + (x.role ? ` (${esc(roleLabel(x.role))})` : "")).join(" · "),
        })}</p>`
      : "";
    const unknown = res.unknownRoles.length
      ? `<p class="pa-threat pa-dim">${t("pick.threat_unknown", { names: esc(res.unknownRoles.join(", ")) })}</p>`
      : "";
    return `<section class="pa-panel">
        <h2 class="pa-title">${t("pick.gaps_title")}</h2>
        ${badges ? `<div class="pa-badges">${badges}</div>` : `<p class="pa-none">${t("pick.gap_none")}</p>`}
        ${threat}${unknown}
      </section>`;
  }

  // Rozet tanımlayıcısı → görünen rozet. kind görsel dili seçer: data = dolu
  // pirinç kenar, gut = kesikli gri (sezgisel), info = grup bilgi rozeti.
  function paBadgeHtml(b) {
    let txt = "";
    switch (b.type) {
      case "tier": txt = t("pick.b_tier", { tier: b.params.tier }); break;
      case "wr": txt = t("pick.b_wr", { n: b.params.n }); break;
      case "counter": txt = t("pick.b_counter", { name: esc(b.params.name), n: b.params.n }); break;
      case "classadv": txt = t("pick.b_class"); break;
      case "gap_ap": txt = t("pick.b_gap_ap"); break;
      case "gap_ad": txt = t("pick.b_gap_ad"); break;
      case "gap_front": txt = t("pick.b_gap_front"); break;
      case "gap_carry": txt = t("pick.b_gap_carry"); break;
      case "early": txt = t("pick.b_early"); break;
      case "late": txt = t("pick.b_late"); break;
      case "group": txt = t("pick.b_group",
        { name: esc(b.params.name), w: b.params.w, l: b.params.l }); break;
      default: return ""; // ileri sürüm motoru yeni tip eklerse eski UI sessiz atlar
    }
    const cls = b.kind === "gut" ? " gut" : b.kind === "info" ? " grp" : "";
    return `<span class="pa-badge${cls}">${txt}</span>`;
  }

  function paSugCard(s) {
    return `<article class="pa-sug${s.best ? " best" : ""}">
        ${s.best ? `<span class="pa-best">${t("pick.best_badge")}</span>` : ""}
        <div class="pa-sug-head">
          <span class="pa-port lg">${paPortHtml(s.name)}</span>
          <div><div class="pa-sname">${esc(s.name)}</div>
            <div class="pa-srole">${esc(roleLabel(s.role))}</div></div>
        </div>
        <div class="pa-badges">${s.badges.map(paBadgeHtml).join("")}</div>
      </article>`;
  }

  function paSugsHtml(res) {
    let body;
    if (!res.myRole) body = `<p class="pa-none">${t("pick.sug_need_me")}</p>`;
    else if (!res.suggestions.length) body = `<p class="pa-none">${t("pick.sug_no_data")}</p>`;
    else body = `<div class="pa-deck">${res.suggestions.map(paSugCard).join("")}</div>`;
    const title = res.myRole
      ? t("pick.sug_title", { role: roleName(res.myRole) }) : t("pick.sug_title_plain");
    return `<section class="pa-panel">
        <div class="pa-sug-head-row">
          <h2 class="pa-title">${esc(title)}</h2>
          ${res.suggestions.length ? `<span class="pa-count">${t("pick.sug_count", { n: res.suggestions.length })}</span>` : ""}
        </div>
        <p class="pa-legend">${t("pick.legend")}
          <span><i class="pa-chip"></i>${t("pick.legend_data")}</span>
          <span><i class="pa-chip gut"></i>${t("pick.legend_gut")}</span></p>
        ${body}
      </section>`;
  }

  // Analiz saf ve ucuzdur: her seçim değişikliğinde yalnız SAĞ yarım yeniden
  // çizilir (sol listeye dokunulmaz — odak/imleç kaybolmaz).
  function renderAnalysis() {
    const boxR = $("#pa-right");
    if (!boxR || !paData) return;
    const res = window.PickAdvisor.analyze({
      mine: state.pick.mine, enemy: state.pick.enemy, myIndex: state.pick.me,
      champInfo: paData.champInfo, tiers: paData.tiers, counters: paData.counters,
      group: paData.group,
    });
    boxR.innerHTML = paTilesHtml(res) + paDamageHtml(res) + paGapsHtml(res) + paSugsHtml(res);
    ddBindImages(boxR);
  }

  async function loadPick() {
    ensurePickState();
    const box = $("#pick-body");
    if (!box.firstChild) box.innerHTML = `<p class='empty'>${t("common.loading")}</p>`;
    await loadAssets();
    // Veri dosyaları paralel işte üretiliyor olabilir: yokluk/eski şema hata
    // DEĞİLDİR — eksik sinyal atlanır, mevcut sinyallerle devam edilir.
    let tiers = null, counters = null;
    if (CONFIG.USE_MOCK && window.MOCK_ADVISOR) {
      tiers = window.MOCK_ADVISOR.tiers || null;
      counters = window.MOCK_ADVISOR.counters || null;
    } else {
      const [mRes, cRes] = await Promise.all([fetchMeta(), fetchCounters()]);
      if (!mRes.err && mRes.data && mRes.data.tiers) tiers = mRes.data.tiers;
      if (!cRes.err && cRes.data && cRes.data.counters) counters = cRes.data.counters;
    }
    const grp = await paGroup();
    paData = {
      tiers, counters, group: grp.index, sample: grp.sample,
      champInfo: paChampInfo(), names: paNames(tiers),
    };
    renderPickShell();
    renderAnalysis();
  }

  // ── 1d) Eşleşme optimizasyonu (GÖREV 21-FIX, tasarım M1 "Sahne") ──
  // S3 "Seçim" ekranından AYRI bir sayfa: Teoman geri bildirimi üzerine (çok
  // adımlı akış ağır, sezgisel early/late ve grup W/R rozetleri alakasız
  // bulundu) hafif bir akış kurulur — rol seç → sahne daralır → rakip şampiyonu
  // gir (opsiyonel) → META ya da counter listesi. Veri katmanı S3 ile PAYLAŞILIR
  // (kod kopyalanmaz): fetchMeta()/fetchCounters()/loadAssets()/paNames() yukarıdaki
  // Seçim bloğunda tanımlıdır; tier/counter ayrıştırması advisor.js'in dışa
  // açtığı tierIndex()/counterRecords() saf yardımcılarıyla yapılır. Bu ekranda
  // sezgisel rozet ve grup rozeti YOKTUR — yalnız tier + winrate + counter verisi.
  const MO_DECK_META = 8;
  const MO_DECK_COUNTER = 10;
  let moData = null; // {tiers, counters, names}

  function ensureMatchupState() {
    if (!state.matchup) state.matchup = { role: null, enemy: null };
    return state.matchup;
  }

  const moPortHtml = (champ) =>
    ddIconHtml(champ ? champIconSrc(champ) : null, champPh(champ), "champ");

  // Serbest metni bilinen ada çözer (pick ekranındaki paCanonName ile aynı
  // fikir, kendi veri kümesine bakar — paData'ya bağımlı DEĞİLDİR).
  function moCanonName(text) {
    const q = String(text || "").trim();
    if (!q) return null;
    const ln = q.toLowerCase();
    const hit = moData && moData.names.find(n => n.toLowerCase() === ln);
    return hit || q;
  }

  // Tier + winrate sıralaması: kademe önce (S→A→B), sonra winrate azalan
  // (bilinmeyen winrate en sona düşer), son kırılım ad — dosya/girdi sırasından
  // bağımsız DETERMİNİSTİK sonuç.
  function moSortTierWr(a, b) {
    return (META_TIERS.indexOf(a.tier) - META_TIERS.indexOf(b.tier)) ||
      ((b.wr == null ? -1 : b.wr) - (a.wr == null ? -1 : a.wr)) ||
      (a.name < b.name ? -1 : 1);
  }

  // Bir koridorun TAM tier+winrate listesi (moSortTierWr sırasıyla, kesilmemiş)
  // — moMetaItems ilk 8'ini gösterir, moCounterItems dolgu için tamamını tarar.
  function moSortedTierList(tiers, roleKey) {
    const idx = window.PickAdvisor.tierIndex(tiers, roleKey);
    return [...idx.entries()]
      .map(([name, e]) => ({ name, tier: e.tier, wr: e.win_rate }))
      .sort(moSortTierWr);
  }

  function moMetaItems(tiers, roleKey) {
    return moSortedTierList(tiers, roleKey).slice(0, MO_DECK_META);
  }

  // Rakip biliniyorsa: gerçek counter kayıtları (win_rate_against yüksekten,
  // yalnız ≥%50) ÖNCE, ardından tier dolgusu ~DECK büyüklüğüne tamamlar.
  // Kayıttaki/tierdeki aynı ad iki kez düşmez (taken kümesi rakibi de kapsar).
  function moCounterItems(tiers, counters, roleKey, enemyName) {
    const taken = new Set([enemyName.toLowerCase()]);
    const out = [];
    if (counters) {
      window.PickAdvisor.counterRecords(counters, roleKey, enemyName)
        .filter(r => r.win_rate_against >= 0.5)
        .sort((a, b) => b.win_rate_against - a.win_rate_against)
        .forEach(r => {
          const key = r.champion.toLowerCase();
          if (taken.has(key)) return;
          taken.add(key);
          out.push({ name: r.champion, counterPct: Math.round(r.win_rate_against * 100) });
        });
    }
    if (tiers && out.length < MO_DECK_COUNTER) {
      moSortedTierList(tiers, roleKey).forEach(c => {
        if (out.length >= MO_DECK_COUNTER) return;
        const key = c.name.toLowerCase();
        if (taken.has(key)) return;
        taken.add(key);
        out.push(c);
      });
    }
    return out.slice(0, MO_DECK_COUNTER);
  }

  // Counter kaydından gelen adayın kendi kademesi biliniyorsa gösterilir
  // (bonus bilgi); bilinmiyorsa boş rozet ("–") — kart hizası bozulmaz.
  function moTierLetter(tiers, roleKey, name) {
    if (!tiers) return null;
    const e = window.PickAdvisor.tierIndex(tiers, roleKey).get(name);
    return e ? e.tier : null;
  }

  function moItemHtml(item, roleKey) {
    const tier = item.tier || moTierLetter(moData.tiers, roleKey, item.name);
    const tierHtml = tier
      ? `<span class="mo-item-tier mo-t-${tier.toLowerCase()}">${tier}</span>`
      : `<span class="mo-item-tier mo-t-none" aria-hidden="true">–</span>`;
    let badgeHtml = "";
    if (item.counterPct != null) {
      badgeHtml = `<span class="mo-item-badge mo-data">` +
        `${t("pick.b_counter", { name: esc(state.matchup.enemy), n: item.counterPct })}</span>`;
    } else if (item.wr != null) {
      const pct = Math.round(item.wr * 100);
      badgeHtml = `<span class="mo-item-badge${pct >= 54 ? " mo-hi" : ""}">${t("pick.b_wr", { n: pct })}</span>`;
    }
    return `<article class="mo-item">
        ${tierHtml}
        <span class="mo-item-port">${moPortHtml(item.name)}</span>
        <span class="mo-item-name">${esc(item.name)}</span>
        ${badgeHtml}
      </article>`;
  }

  function renderMoResult() {
    const titleEl = $("#mo-result-title");
    const listEl = $("#mo-list");
    const role = state.matchup.role;
    if (!role) { titleEl.textContent = ""; listEl.innerHTML = ""; return; }
    const rk = META_ROLE_KEY[role];
    const enemy = state.matchup.enemy;
    const hasData = !!(moData && (moData.tiers || moData.counters));
    titleEl.textContent = enemy
      ? t("matchup.counter_title", { role: roleName(role), enemy })
      : t("matchup.meta_title", { role: roleName(role) });
    if (!hasData) {
      listEl.innerHTML = `<p class="mo-none">${t("matchup.no_data")}</p>`;
      return;
    }
    const items = enemy
      ? moCounterItems(moData.tiers, moData.counters, rk, enemy)
      : (moData.tiers ? moMetaItems(moData.tiers, rk) : []);
    listEl.innerHTML = items.length
      ? items.map(it => moItemHtml(it, rk)).join("")
      : `<p class="mo-none">${t("matchup.no_data")}</p>`;
    ddBindImages(listEl);
  }

  function moSyncEnemyState() {
    $("#mo-enemy-state").textContent = state.matchup.enemy
      ? t("matchup.enemy_state_picked", { name: state.matchup.enemy })
      : t("matchup.enemy_state_none");
  }

  // Arama kutusu pick ekranındaki pa-input/bindPickRow desenine uyarlanmıştır
  // (autocomplete: yaz → aç, ok tuşları gezinir, Enter/tıklama seçer, dışarı
  // tıklama/Enter boş bırakırsa rakip TEMİZLENİR). Kutu her renderMatchupShell
  // çağrısında TAZE kurulur (innerHTML ile) — dinleyici birikmesi olmaz.
  function moSearchWrapHtml() {
    return `<div class="mo-search">
        <span class="mo-search-port">${moPortHtml(state.matchup.enemy)}</span>
        <span class="mo-search-box">
          <input type="text" id="mo-search-input" class="mo-input" autocomplete="off" spellcheck="false"
                 value="${esc(state.matchup.enemy || "")}"
                 placeholder="${esc(t("pick.champ_placeholder"))}"
                 aria-label="${esc(t("matchup.search_aria"))}">
          <ul id="mo-search-list" class="mo-search-list" hidden></ul>
        </span>
      </div>`;
  }

  function moBindSearch() {
    $("#mo-search-wrap").innerHTML = moSearchWrapHtml();
    ddBindImages($("#mo-search-wrap"));
    const input = $("#mo-search-input");
    const list = $("#mo-search-list");
    const port = $("#mo-search-wrap .mo-search-port");
    let active = -1;

    const closeList = () => { list.hidden = true; list.innerHTML = ""; active = -1; };
    const commit = (name) => {
      const canon = moCanonName(name);
      state.matchup.enemy = canon;
      input.value = canon || "";
      port.innerHTML = moPortHtml(canon);
      ddBindImages(port);
      closeList();
      moSyncEnemyState();
      renderMoResult();
    };
    const openList = () => {
      const q = input.value.trim().toLowerCase();
      if (!q || !moData || !moData.names.length) { closeList(); return; }
      const starts = [], contains = [];
      for (const n of moData.names) {
        const ln = n.toLowerCase();
        if (ln.startsWith(q)) starts.push(n);
        else if (ln.indexOf(q) !== -1) contains.push(n);
        if (starts.length >= 8) break;
      }
      const found = starts.concat(contains).slice(0, 8);
      if (!found.length) { closeList(); return; }
      list.innerHTML = found.map(n =>
        `<li><button type="button" class="mo-opt" data-name="${esc(n)}">${moPortHtml(n)}<span>${esc(n)}</span></button></li>`).join("");
      ddBindImages(list);
      list.hidden = false;
      active = -1;
      list.querySelectorAll(".mo-opt").forEach(btn =>
        btn.addEventListener("mousedown", (e) => { e.preventDefault(); commit(btn.dataset.name); }));
    };
    input.addEventListener("input", openList);
    input.addEventListener("keydown", (e) => {
      const opts = list.querySelectorAll(".mo-opt");
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        if (list.hidden || !opts.length) return;
        e.preventDefault();
        active = e.key === "ArrowDown"
          ? (active + 1) % opts.length : (active - 1 + opts.length) % opts.length;
        opts.forEach((o, j) => o.classList.toggle("on", j === active));
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (!list.hidden && opts.length) commit(opts[active === -1 ? 0 : active].dataset.name);
        else commit(input.value);
      } else if (e.key === "Escape") {
        closeList();
      }
    });
    input.addEventListener("blur", () => {
      setTimeout(() => {
        if (!input.isConnected) return;
        closeList();
        if (input.value.trim() !== (state.matchup.enemy || "")) commit(input.value);
      }, 120);
    });
  }

  function moRoleButtonHtml(role) {
    const sel = state.matchup.role === role;
    return `<button type="button" class="mo-role${sel ? " sel" : ""}" data-role="${role}"
              aria-pressed="${sel}" aria-label="${esc(roleName(role))}">
        <span class="mo-role-glow" aria-hidden="true"></span>
        ${posIconHtml(role, roleAbbr(role), "mo-role-ico")}
        <span class="mo-role-label" aria-hidden="true">${esc(roleName(role))}</span>
      </button>`;
  }

  function renderMatchupRoles() {
    const box = $("#mo-roles");
    box.innerHTML = ROLES.map(moRoleButtonHtml).join("");
    box.querySelectorAll(".mo-role").forEach(btn =>
      btn.addEventListener("click", () => selectMoRole(btn.dataset.role)));
  }

  // Rol seçimi sahneyi daraltır (mo-picked) ve sonuç panelini yumuşak kaydırarak
  // görünüre getirir; çubuk yeniden KURULMAZ, yalnız durum güncellenir (odak
  // korunur — meta süzgeci deseniyle aynı fikir).
  function selectMoRole(role) {
    state.matchup.role = role;
    $("#mo-app").classList.add("mo-picked");
    $("#mo-roles").querySelectorAll(".mo-role").forEach(b => {
      const on = b.dataset.role === role;
      b.classList.toggle("sel", on);
      b.setAttribute("aria-pressed", String(on));
    });
    renderMoResult();
    const target = $("#mo-stepwrap");
    setTimeout(() => target.scrollIntoView({ behavior: "smooth", block: "start" }), 320);
  }

  function renderMatchupShell() {
    $("#mo-app").classList.toggle("mo-picked", !!state.matchup.role);
    renderMatchupRoles();
    moBindSearch();
    moSyncEnemyState();
    renderMoResult();
  }

  // Yükleyici hiç THROW ETMEZ (META/Seçim deseni): veri dosyası eksikse ilgili
  // taraf sessizce atlanır, ekranın kalanı çalışır (matchup.no_data mesajı).
  async function loadMatchup() {
    ensureMatchupState();
    const box = $("#mo-list");
    if (!box.firstChild) box.innerHTML = `<p class="mo-none">${t("common.loading")}</p>`;
    await loadAssets();
    let tiers = null, counters = null;
    if (CONFIG.USE_MOCK && window.MOCK_ADVISOR) {
      tiers = window.MOCK_ADVISOR.tiers || null;
      counters = window.MOCK_ADVISOR.counters || null;
    } else {
      const [mRes, cRes] = await Promise.all([fetchMeta(), fetchCounters()]);
      if (!mRes.err && mRes.data && mRes.data.tiers) tiers = mRes.data.tiers;
      if (!cRes.err && cRes.data && cRes.data.counters) counters = cRes.data.counters;
    }
    moData = { tiers, counters, names: paNames(tiers) };
    renderMatchupShell();
  }

  // ── 2) Leaderboard ────────────────────────────────────────────
  // Oyuncu adı artık profili açar (GÖREV 1). Eski satır-içi rol açılırı kaldırıldı:
  // rol şeridi profilde daha geniş biçimde zaten var, iki ayrı açılır tekrar olurdu.
  async function loadLeaderboard() {
    const rows = await api("/leaderboard"); // backend score'a göre sıralı döner
    const body = $("#board-body");
    body.innerHTML = rows.map((p, i) => {
      const sub = ratingSub(p.rating);
      const subHtml = sub ? `<span class="rating-sub">` + sub + `</span>` : "";
      return `<tr>
         <td class="rank">${i + 1}</td>
         <td><button type="button" class="name-link" data-player="${p.id}">${esc(p.display_name)}</button></td>
         <td class="num strong">${fmtRating(p.rating.score)}${subHtml}</td>
         <td class="num">${p.matches_played}</td>
       </tr>`;
    }).join("");

    body.querySelectorAll(".name-link").forEach(btn =>
      btn.addEventListener("click", () => openProfile(Number(btn.dataset.player))));
  }

  // ── 2a) Detaylar arası geri zinciri (GÖREV 15) ────────────────
  // Profil grafiğindeki nokta maç detayını, maç detayı satırındaki ad da profili
  // açar. İki yön AYNI iki görünümü kullandığı için tek bir "nereden geldim"
  // alanı (profileFrom/matchFrom) zincirde döngüye giriyordu: profil A → maç →
  // profil B → geri → maç → geri → profil B → geri → maç ... (A'ya hiç dönülmez).
  //
  // Çözüm: detaydan detaya geçerken TERK EDİLEN görünümün TAM bağlamı (hangi
  // oyuncu / hangi maç + o görünümün kendi geri hedefi) bir yığına konur; geri
  // düğmesi kareyi yığından ÇEKER. Kare tüketildiği için döngü kapanmaz ve
  // zincir derinlikten bağımsız tutarlıdır (profil A → maç → profil B → geri →
  // maç → geri → profil A → geri → Sıralama). Sekmeye basmak zinciri terk eder.
  //
  // Yığın "tarayıcı geçmişi" DEĞİLDİR: yalnız profil ⇄ maç detayı geçişlerinde
  // kare birikir. Profilden profile (sinerji linki) eski davranışını korur —
  // çıkış noktası ilk giriş yeridir, o yüzden orada kare konmaz.
  const BACK_MAX = 20;   // makul zincir sınırı; taşarsa en eski kare düşer
  const clearBack = () => { state.backStack.length = 0; };
  function pushBack(frame) {
    state.backStack.push(frame);
    if (state.backStack.length > BACK_MAX) state.backStack.shift();
  }
  const profileFrame = () => ({
    view: "profile", from: state.profileFrom,
    playerId: state.profileId, range: state.historyRange,
  });
  const matchFrame = () => ({
    view: "matchdetail", from: state.matchFrom,
    match: state.matchDetail, stat: state.matchStat,
  });

  function restoreFrame(f) {
    if (f.view === "profile") {
      state.profileId = f.playerId;
      state.profileFrom = f.from;
      state.historyRange = f.range;
      // Önbellekler başka oyuncuya ait olabilir: profil zaten her açılışta taze çeker.
      state.ratingHistory = null;
      state.badges = null;
    } else {
      state.matchDetail = f.match;
      state.matchStat = f.stat;
      state.matchFrom = f.from;
    }
    showView(f.view);
  }

  // Geri: yığının tepesi beklenen görünümse ona KENDİ bağlamıyla dönülür.
  // Kare yoksa (zincir sekme değişimiyle kopmuş ya da BACK_MAX'ı taşmış) zincir
  // temizlenip güvenli sekmeye düşülür — asla döngüye girilmez.
  function goBack(expect, fallback) {
    const top = state.backStack[state.backStack.length - 1];
    if (top && top.view === expect) { restoreFrame(state.backStack.pop()); return; }
    clearBack();
    showView(fallback);
  }

  // ── 2b) Oyuncu profili (GÖREV 1) ──────────────────────────────
  // Alt sekmelerin dışında bir "detay" görünümü: sıralamadan açılır, geri döner.
  // Geri düğmesi metinleri sözlükten gelir; dil değişince abone yeniden yazar.
  const BACK_VIEWS = ["leaderboard", "highlights", "map", "matchdetail"];
  const backLabel = (from) =>
    t("common.back_" + (BACK_VIEWS.includes(from) ? from : "leaderboard"));

  // from: profilin hangi görünümden açıldığı (varsayılan: açık görünüm).
  // Yalnız maç detayı satırındaki ad (GÖREV 15) bunu açıkça verir.
  function openProfile(id, from) {
    // Yeni oyuncu → tarihçe grafiği baştan başlar (aralık seçimi taşınmaz),
    // rozet vitrini de önceki oyuncunun verisiyle bir an görünmesin diye sıfırlanır.
    if (id !== state.profileId) {
      state.historyRange = "all";
      state.ratingHistory = null;
      state.badges = null;
    }
    state.profileId = id;
    const src = from || currentView;
    // Maç detayından geliniyorsa detayın kendi bağlamı saklanır (geri o maça döner).
    if (src === "matchdetail") pushBack(matchFrame());
    // Profilden profile geçilebilir (sinerji linkleri) — çıkış noktası ilk giriş yeridir.
    else if (src !== "profile") clearBack();
    if (src !== "profile") state.profileFrom = src;
    showView("profile");
  }
  $("#btn-profile-back").addEventListener("click", () => {
    if (state.profileFrom === "matchdetail") { goBack("matchdetail", "matches"); return; }
    clearBack();
    showView(state.profileFrom);
  });

  const num1 = (x) => (typeof x === "number" ? x.toFixed(1) : "—");
  const num2 = (x) => (typeof x === "number" ? x.toFixed(2) : "—");
  // winrate contract'ta 0..1 oran ve null olabilir. Yüzde biçimi dile göre değişir
  // (tr "%50", en "50%") — common.percent anahtarı taşır.
  const pctText = (x) => (typeof x === "number" ? t("common.percent", { n: Math.round(x * 100) }) : "—");

  const statCard = (title, main, sub) =>
    `<article class="stat-card">
       <h3 class="sc-title">${title}</h3>
       <div class="sc-main">${main}</div>
       ${sub ? `<div class="sc-sub">${sub}</div>` : ""}
     </article>`;

  // ── Favori eşya kartı (GÖREV 14) ──────────────────────────────
  // Veri: GET /players/{id}/stats → top_items (sayım azalan, en fazla 10 kayıt).
  // Contract §2: "favori eşya" SEÇİMİ web UI'dadır — totem/tüketilebilir etiketli
  // kayıtlar atlanır, kalan İLK kayıt favoridir. Uygun kayıt yoksa kart çizilmez.
  // Varlıklar yoksa tags bilinemez → eleme yapılamaz, ilk kayıt olduğu gibi alınır
  // (ad "Esya #id", ikon yer tutucu; kartı gizlemek veriyi büsbütün saklardı).
  function favItem(list) {
    if (!Array.isArray(list)) return null;
    const rows = list.filter(x => x && Number.isFinite(Number(x.item_id)));
    const usable = DD.items ? rows.filter(x => !itemSkipped(x.item_id)) : rows;
    return usable.length ? usable[0] : null;
  }

  function favItemCard(x) {
    const id = Number(x.item_id);
    const n = Number.isFinite(Number(x.matches)) ? Number(x.matches) : 0;
    return `<article class="stat-card fi-card">
        <h3 class="sc-title">${t("profile.card_fav_item")}</h3>
        <div class="fi-row">
          ${ddIconHtml(itemIconSrc(id), itemPh(id), "item")}
          <span class="sc-main fi-name">${esc(itemName(id))}</span>
        </div>
        <div class="sc-sub">${t("profile.fav_item_matches", { n })}</div>
      </article>`;
  }

  // s = GET /players/{id}/stats yanıtı. kda / favoriler null, synergy boş,
  // winrate null olabilir — hepsi kısa notla gösterilir.
  function profileHtml(s) {
    const p = s.player || {};
    const rp = state.roster.find(x => x.id === p.id); // rol şeridi + puan roster'dan
    const tot = s.totals || {};
    const played = tot.matches || 0;
    const k = s.kda, fc = s.favorite_champion, fr = s.favorite_role;
    const syn = s.synergy || [];
    const fi = favItem(s.top_items);

    const scoreHtml = rp
      ? `<div class="prof-score">${fmtRating(rp.rating.score)}<span>${t("common.points_word")}</span></div>`
      : "";
    const head =
      `<header class="prof-head">
         <h2 class="prof-name">${esc(p.display_name)}</h2>
         ${p.riot_id ? `<span class="prof-riot">${esc(p.riot_id)}</span>` : ""}
         ${scoreHtml}
       </header>`;

    const cards =
      statCard(t("profile.card_matches"),
        played ? t("profile.matches_line", { n: played, w: tot.wins, l: tot.losses }) : t("profile.no_matches"),
        played && tot.winrate != null ? t("profile.win_pct", { pct: pctText(tot.winrate) }) : "") +
      statCard(t("profile.card_kda"),
        k ? `${num1(k.kills_avg)} / ${num1(k.deaths_avg)} / ${num1(k.assists_avg)}` : "—",
        k ? t("profile.kda_ratio", { ratio: num2(k.ratio) }) : t("profile.no_stat_matches")) +
      // Favori karakter [REVİZE 2026-08-15]: seçim ölçütü galibiyet SAYISI →
      // alt yazı da galibiyeti önde gösterir ("3 galibiyet · 4 mac").
      statCard(t("profile.card_champion"),
        fc ? esc(fc.champion) : "—",
        fc ? t("profile.champ_line", { w: fc.wins, n: fc.matches }) : t("profile.no_champion_data")) +
      statCard(t("profile.card_role"),
        fr ? esc(roleLabel(fr.role)) : "—",
        fr ? t("common.n_matches", { n: fr.matches }) : t("profile.no_role_data")) +
      // Favori eşya kartı yalnız uygun kayıt varsa şeride girer (GÖREV 14).
      (fi ? favItemCard(fi) : "");

    const strip = rp ? roleCells(rp.role_ratings, true) : "";
    const roleSec = strip
      ? `<section class="prof-section"><h3 class="ps-title">${t("profile.role_ratings_title")}</h3>${strip}</section>`
      : "";

    const synMeta = (x) =>
      `<span class="syn-meta">${t("profile.syn_meta", { n: x.matches_together, pct: pctText(x.winrate) })}</span>`;
    const synLink = (x, cls) =>
      `<button type="button" class="syn-link${cls ? " " + cls : ""}" data-player="${x.player_id}">${esc(x.display_name)}</button>`;
    const synSec =
      `<section class="prof-section">
         <h3 class="ps-title">${t("profile.synergy_title")}</h3>` +
      (syn.length
        ? `<div class="syn-top">${synLink(syn[0], "syn-name")}${synMeta(syn[0])}</div>` +
          (syn.length > 1
            ? `<ul class="syn-rest">` +
              syn.slice(1).map(x => `<li>${synLink(x)}${synMeta(x)}</li>`).join("") +
              `</ul>`
            : "")
        : `<p class="ps-empty">${t("profile.synergy_empty")}</p>`) +
      `</section>`;

    // Tarihçe bölümü (GÖREV 10) burada yalnız YER AÇAR: içeriğini renderHistory()
    // doldurur — aralık düğmeleri profil yeniden çekilmeden yeniden çizebilsin diye.
    const histSec = `<section class="prof-section" id="prof-history" hidden></section>`;
    // Rozet vitrini (GÖREV 11+12) tarihçe grafiğinin ALTINDA; aynı desenle yalnız
    // yer açar, içeriğini renderBadges() doldurur (uç düşerse hiç görünmez).
    const badgeSec = `<section class="prof-section" id="prof-badges" hidden></section>`;

    return head + `<div class="stat-grid">${cards}</div>` + histSec + badgeSec + roleSec + synSec;
  }

  async function loadProfile() {
    // Geri düğmesi metni burada yazılır (maç detayındaki desenin aynısı): profil
    // hem openProfile'dan hem geri zincirinden (restoreFrame) açılıyor, dil de
    // değişebiliyor — tek yer yazarsa etiket her yolda doğru kalır.
    $("#btn-profile-back").textContent = backLabel(state.profileFrom);
    const box = $("#profile-body");
    if (state.profileId == null) {
      box.innerHTML = `<p class='empty'>${t("profile.no_player")}</p>`;
      return;
    }
    box.innerHTML = `<p class='empty'>${t("common.loading")}</p>`;
    try {
      await fetchRoster(); // rol şeridi + puan için; önbellekliyse istek gitmez
      // rating-history ve badges ayrı uçlardır (GÖREV 10, 11+12): düşerlerse
      // profilin kalanı çalışsın — /nemesis'teki desenin aynısı, o bölüm çizilmez.
      // loadAssets (GÖREV 14) reject etmez: varlık yoksa favori eşya kartı yer
      // tutucuyla çizilir, profil beklemez.
      const [s, h, b] = await Promise.all([
        api(`/players/${state.profileId}/stats`),
        api(`/players/${state.profileId}/rating-history`).catch(() => null),
        api(`/players/${state.profileId}/badges`).catch(() => null),
        loadAssets(),
      ]);
      state.ratingHistory = h;
      state.badges = b;
      box.innerHTML = profileHtml(s);
      ddBindImages(box);
      renderHistory();
      renderBadges();
      // Sinerji listesindeki isimler o oyuncunun profiline geçer.
      box.querySelectorAll(".syn-link").forEach(btn =>
        btn.addEventListener("click", () => openProfile(Number(btn.dataset.player))));
    } catch (e) {
      box.innerHTML = `<p class='empty'>${esc(e.message)}</p>`;
      throw e; // toast'ı showView gösterir
    }
  }

  // ── 2b2) Rating tarihçesi grafiği (GÖREV 10) ──────────────────
  // Veri: GET /players/{id}/rating-history — contract §2: yanıt TAM tarihçedir,
  // sunucuda zaman aralığı filtresi YOKTUR; "Tümü / 30 gün / 7 gün" seçimi burada,
  // istemci tarafında uygulanır (maç hacmi küçük).
  //
  // Çizim framework'süz satır içi SVG'dir. viewBox sabit, genişlik %100 → grafik
  // kapsayıcıya oranlı ölçeklenir, 320px'de yatay taşma olmaz. Eksen etiketleri
  // SVG'de DEĞİL HTML katmanındadır: SVG ölçeklenince yazı boyu da ölçeklenirdi
  // (harita ekranındaki baloncuk deseninin aynısı).
  //
  // Renk TEK BAŞINA taşıyıcı değildir: nokta mavi/kırmızı ama G/M bilgisi popup'ta
  // metin olarak ve noktanın aria-label'ında da vardır.
  // W/H oranı grafiğin en-boyudur: 320px ekranda ~125px, geniş ekranda ~300px yüksek.
  const PH = { W: 320, H: 160, PADX: 10, TOP: 10, BOT: 13 };
  const PH_RANGES = [
    { key: "all", label: "profile.range_all", days: null },
    { key: "30", label: "profile.range_30d", days: 30 },
    { key: "7", label: "profile.range_7d", days: 7 },
  ];
  const DAY_MS = 24 * 60 * 60 * 1000;
  const fmtDay = (iso) =>
    new Date(iso).toLocaleDateString(uiLocale(), { day: "numeric", month: "short" });

  let histLayout = null;  // son çizimin geometrisi ({xy}) — popup konumu buradan okunur
  let histReturn = null;  // popup kapanınca odağın döneceği nokta (klavye erişimi)

  const histAll = () => (state.ratingHistory && state.ratingHistory.points) || [];

  function histPoints() {
    const all = histAll();
    const r = PH_RANGES.find(x => x.key === state.historyRange) || PH_RANGES[0];
    if (!r.days) return all;
    const from = Date.now() - r.days * DAY_MS;
    return all.filter(p => Date.parse(p.played_at) >= from);
  }

  const histNum = (v) => (typeof v === "number" ? String(v) : "—");
  // stats null olabilir (contract: k/d/a'nın üçü de null ise stats null); tek tek
  // alanlar da nullable → her biri ayrı ayrı "—" düşer.
  const histKda = (s) =>
    s ? `${histNum(s.kills)} / ${histNum(s.deaths)} / ${histNum(s.assists)}` : "—";
  const histResult = (p) => t(p.win ? "profile.hist_win" : "profile.hist_loss");

  // Tek nokta → çizgi ve alan dolgusu yoktur, yalnız nokta çizilir.
  function histChart(pts) {
    const x0 = PH.PADX, x1 = PH.W - PH.PADX;
    const y0 = PH.TOP, y1 = PH.H - PH.BOT;
    const vals = pts.map(p => Number(p.score_after));
    let lo = Math.min(...vals), hi = Math.max(...vals);
    if (!(hi > lo)) { lo -= 1; hi += 1; }          // tek nokta ya da düz seri
    const pad = (hi - lo) * 0.12;
    lo -= pad; hi += pad;
    const ts = pts.map(p => Date.parse(p.played_at));
    // Bozuk/eksik zaman damgası gelirse eşit aralıklı yerleşime düşülür.
    const okTs = ts.every(v => !isNaN(v));
    const t0 = Math.min(...ts), t1 = Math.max(...ts);
    const span = x1 - x0;
    const xAt = (i) =>
      pts.length < 2 ? (x0 + x1) / 2
        : !okTs || t1 <= t0 ? x0 + (i / (pts.length - 1)) * span
        : x0 + ((ts[i] - t0) / (t1 - t0)) * span;
    const xy = pts.map((p, i) => ({
      x: xAt(i),
      y: y1 - ((Number(p.score_after) - lo) / (hi - lo)) * (y1 - y0),
      p,
    }));

    const gridY = [0, 0.5, 1].map(f => y0 + f * (y1 - y0));
    const grid = gridY.map(y =>
      `<line class="ph-grid" x1="${x0}" y1="${y.toFixed(1)}" x2="${x1}" y2="${y.toFixed(1)}"/>`
    ).join("");
    const chain = xy.map(q => `${q.x.toFixed(1)},${q.y.toFixed(1)}`).join(" ");
    const area = xy.length > 1
      ? `<polygon class="ph-area" points="${xy[0].x.toFixed(1)},${y1} ${chain} ${xy[xy.length - 1].x.toFixed(1)},${y1}"/>`
      : "";
    const line = xy.length > 1 ? `<polyline class="ph-line" points="${chain}"/>` : "";
    const dots = xy.map((q, i) => {
      const last = i === xy.length - 1;
      return `<circle class="ph-dot ${q.p.win ? "win" : "loss"}${last ? " last" : ""}"
          cx="${q.x.toFixed(1)}" cy="${q.y.toFixed(1)}" r="${last ? 4.6 : 3.4}"/>`;
    }).join("");
    // Dokunma hedefi noktadan büyüktür (r=10 viewBox birimi ≈ 18px @320px ekran)
    // ve saydamdır; en sona çizilir ki tıklama hep hedefe gitsin.
    const hits = xy.map((q, i) =>
      `<circle class="ph-hit" cx="${q.x.toFixed(1)}" cy="${q.y.toFixed(1)}" r="10"
         tabindex="0" role="button" data-i="${i}"
         aria-label="${esc(t("profile.hist_point_aria", {
           date: fmtDate(q.p.played_at),
           result: histResult(q.p),
           score: fmtRating(Number(q.p.score_after)),
         }))}"/>`).join("");

    const yaxis = gridY.map(y => {
      const v = lo + ((y1 - y) / (y1 - y0)) * (hi - lo);
      return `<span class="ph-ytick" style="top:${(y / PH.H * 100).toFixed(2)}%">${fmtRating(v)}</span>`;
    }).join("");
    const xaxis = `<div class="ph-xaxis"><span>${esc(fmtDay(pts[0].played_at))}</span>` +
      (pts.length > 1 ? `<span>${esc(fmtDay(pts[pts.length - 1].played_at))}</span>` : "") +
      `</div>`;

    const html =
      `<div class="ph-chart">
         <div class="ph-yaxis">${yaxis}</div>
         <div class="ph-plot">
           <svg class="ph-svg" viewBox="0 0 ${PH.W} ${PH.H}" role="group"
                aria-label="${esc(t("profile.hist_chart_aria", { n: pts.length }))}">
             ${grid}${area}${line}${dots}${hits}
           </svg>
         </div>
       </div>${xaxis}`;
    return { xy, html };
  }

  function renderHistory() {
    const sec = $("#prof-history");
    if (!sec) return;
    histLayout = null;
    histReturn = null;
    state.histOpen = null;
    // Uç yoksa/düştüyse bölüm hiç görünmez (profilin kalanı etkilenmez).
    if (!state.ratingHistory) { sec.hidden = true; sec.innerHTML = ""; return; }
    sec.hidden = false;

    const title = `<h3 class="ps-title">${t("profile.history_title")}</h3>`;
    // Hiç maç yok → aralık düğmeleri de anlamsız, tek satır boş durum.
    if (!histAll().length) {
      sec.innerHTML = title + `<p class="ps-empty">${t("profile.history_empty")}</p>`;
      return;
    }
    const pills = `<div class="ph-ranges" role="group" aria-label="${esc(t("profile.range_aria"))}">` +
      PH_RANGES.map(r =>
        `<button type="button" class="ph-pill${r.key === state.historyRange ? " active" : ""}"
           data-range="${r.key}" aria-pressed="${r.key === state.historyRange}">${t(r.label)}</button>`
      ).join("") + `</div>`;

    const pts = histPoints();
    let body;
    if (!pts.length) {
      body = `<p class="ps-empty ph-empty">${t("profile.history_range_empty")}</p>`;
    } else {
      histLayout = histChart(pts);
      body = histLayout.html;
    }
    sec.innerHTML = title + pills + body;

    sec.querySelectorAll(".ph-pill").forEach(btn =>
      btn.addEventListener("click", () => {
        state.historyRange = btn.dataset.range;
        renderHistory();
      }));
    sec.querySelectorAll(".ph-hit").forEach(node => {
      const i = Number(node.dataset.i);
      node.addEventListener("click", () => histActivate(i, node));
      // SVG öğesi <button> değildir: Enter/Space'i kendimiz bağlarız.
      node.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); histActivate(i, node); }
      });
    });
  }

  // Teoman'ın tarifi: noktaya İLK tık popup'ı açar, AYNI noktaya (ya da popup'a)
  // İKİNCİ tık o maçın detayına gider.
  function histActivate(i, node) {
    const q = histLayout && histLayout.xy[i];
    if (!q) return;
    if (state.histOpen === q.p.match_id) { openMatchFromHistory(q.p.match_id); return; }
    openHistPopup(q, node);
  }

  function histPopHtml(q) {
    const p = q.p;
    const above = q.y > PH.H * 0.45;   // grafiğin alt yarısındaki nokta → popup üstte
    return `<button type="button" class="ph-pop ${above ? "above" : "below"}"
        style="left:${(q.x / PH.W * 100).toFixed(2)}%;top:${(q.y / PH.H * 100).toFixed(2)}%">
        <span class="ph-pop-date">${esc(fmtDate(p.played_at))}</span>
        <span class="ph-pop-line">${esc(p.champion || "—")} · ${esc(roleLabel(p.position))}</span>
        <span class="ph-pop-line">${esc(histKda(p.stats))}</span>
        <span class="ph-pop-foot">
          <span class="ph-pop-res ${p.win ? "win" : "loss"}">${histResult(p)}</span>
          <span class="ph-pop-score">${fmtRating(Number(p.score_after))}<small>${t("common.points_word")}</small></span>
        </span>
        <span class="ph-pop-hint">${t("profile.hist_pop_hint")}</span>
      </button>`;
  }

  function openHistPopup(q, node) {
    closeHistPopup(false);
    const plot = $("#prof-history .ph-plot");
    if (!plot) return;
    plot.insertAdjacentHTML("beforeend", histPopHtml(q));
    const pop = plot.querySelector(".ph-pop");
    state.histOpen = q.p.match_id;
    histReturn = node || null;
    pop.addEventListener("click", () => openMatchFromHistory(q.p.match_id));
    // Kenardaki noktalarda popup kutusu grafiğin dışına taşabilir: ölçüp içeri çekilir
    // (320px'de yatay taşma yok kuralı). marginLeft translateX(-50%)'den önce uygulanır.
    const pr = pop.getBoundingClientRect();
    const wr = plot.getBoundingClientRect();
    const shift = pr.left < wr.left ? wr.left - pr.left
      : pr.right > wr.right ? wr.right - pr.right : 0;
    if (shift) pop.style.marginLeft = Math.round(shift) + "px";
    pop.focus();
  }

  function closeHistPopup(restoreFocus = true) {
    const pop = document.querySelector("#prof-history .ph-pop");
    if (pop) pop.remove();
    state.histOpen = null;
    if (restoreFocus && histReturn && document.contains(histReturn)) histReturn.focus();
    histReturn = null;
  }

  // Maça atlama: maç Geçmiş ekranından zaten yüklüyse önbellekten, değilse
  // GET /matches/{id} ile çekilir (contract §3, GÖREV 10 notu).
  async function openMatchFromHistory(matchId) {
    closeHistPopup(false);
    const cached = state.matches.find(m => m.id === matchId);
    if (cached) { openMatchDetail(cached, "profile"); return; }
    try {
      openMatchDetail(await api(`/matches/${matchId}`), "profile");
    } catch (e) {
      toast(e.message);
    }
  }

  // Popup dışına tıklama kapatır (rol pop-up'ıyla aynı desen; Esc aşağıdaki
  // ortak keydown dinleyicisinde).
  document.addEventListener("click", (e) => {
    if (state.histOpen == null) return;
    if (e.target.closest && e.target.closest(".ph-pop, .ph-hit")) return;
    closeHistPopup(false);
  });

  // ── 2b3) Rozet vitrini (GÖREV 11+12) ──────────────────────────
  // Veri: GET /players/{id}/badges — yanıt yalnız {key, count, last_match_id}
  // taşır; ad ve açıklama BURADA, sözlüktedir (api_contract §2 "Rozetler").
  // Sıra contract'ta SABİT katalog sırasıdır; yine de burada katalog sırasına göre
  // dizilir (ileri sürüm backend'i sırayı değiştirirse vitrin bozulmasın diye).
  // Bilinmeyen anahtar SESSİZCE atlanır: backend yeni rozet eklediğinde eski UI
  // "profile.badge_xxx" anahtar adını ekrana yazmaz.
  //
  // İkon emoji değil, satır içi SVG'dir (tema rengini currentColor ile alır,
  // platformdan platforma değişmez). Renk tek başına anlam taşımaz: rozet adı
  // her kartçıkta yazılıdır, açıklama da ekran okuyucuya .pb-sr ile verilir.
  const BADGE_KEYS = [
    "mvp", "vision", "damage", "cs_per_min", "gold", "deathless", "comeback",
    "win_streak_5", "bench_3", "versatile", "veteran_10", "veteran_25", "veteran_50",
  ];

  // 24×24 viewBox, tek renk çizgi grafikleri (pb-fill sınıfı dolu parçalar için).
  const BADGE_ICONS = {
    mvp: `<path class="pb-fill" d="M12 3.2l2.6 5.4 5.9.9-4.3 4.1 1 5.9-5.2-2.8-5.2 2.8 1-5.9-4.3-4.1 5.9-.9z"/>`,
    vision: `<path d="M2.5 12s3.6-5.5 9.5-5.5S21.5 12 21.5 12s-3.6 5.5-9.5 5.5S2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.6"/>`,
    damage: `<circle cx="12" cy="12" r="3.2"/><path d="M12 2.6v3.5M12 17.9v3.5M2.6 12h3.5M17.9 12h3.5M5.4 5.4l2.5 2.5M16.1 16.1l2.5 2.5M18.6 5.4l-2.5 2.5M7.9 16.1l-2.5 2.5"/>`,
    cs_per_min: `<circle cx="12" cy="12" r="8.6"/><path d="M12 6.8v5.4l3.4 2"/>`,
    gold: `<ellipse cx="12" cy="6.4" rx="7.4" ry="2.9"/><path d="M4.6 6.4v5c0 1.6 3.3 2.9 7.4 2.9s7.4-1.3 7.4-2.9v-5"/><path d="M4.6 11.4v5c0 1.6 3.3 2.9 7.4 2.9s7.4-1.3 7.4-2.9v-5"/>`,
    deathless: `<path d="M12 2.8l7.4 2.7v6c0 4.4-3 8-7.4 9.7-4.4-1.7-7.4-5.3-7.4-9.7v-6z"/><path d="M8.8 12.1l2.3 2.3 4.1-4.5"/>`,
    comeback: `<path d="M4.8 19.5V13a5.6 5.6 0 0 1 11.2 0v6.5"/><path d="M12.4 16.3l3.6 3.4 3.6-3.4"/>`,
    win_streak_5: `<path d="M12 21c3.5 0 6-2.4 6-5.6 0-4.2-4.1-5.9-3.3-11.4-2.9 1.2-5.2 4-5.2 6.4 0 1.2.4 2 .4 2S8.1 11.6 7 10c-.6 1.2-1 2.9-1 4.6C6 18.3 8.5 21 12 21z"/>`,
    bench_3: `<path d="M3.6 9.6h16.8M3.6 13.1h16.8"/><path d="M5.8 13.1v6.1M18.2 13.1v6.1M5.8 9.6V5.4M18.2 9.6V5.4"/>`,
    versatile: `<path d="M12 3.1l8.6 6.2-3.3 10.1H6.7L3.4 9.3z"/><circle class="pb-fill" cx="12" cy="12" r="1.7"/>`,
    veteran_10: `<path d="M4.8 15.2L12 9l7.2 6.2"/>`,
    veteran_25: `<path d="M4.8 12.4L12 6.2l7.2 6.2M4.8 18L12 11.8l7.2 6.2"/>`,
    veteran_50: `<path d="M4.8 10.2L12 4l7.2 6.2M4.8 15L12 8.8l7.2 6.2M4.8 19.8L12 13.6l7.2 6.2"/>`,
  };

  const badgeIcon = (key) =>
    `<svg class="pb-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${BADGE_ICONS[key]}</svg>`;

  // Yanıttaki rozetler → katalog sırasında, tanınmayanlar atılmış liste.
  function badgeList() {
    const raw = (state.badges && state.badges.badges) || [];
    return raw
      .filter(b => b && BADGE_KEYS.indexOf(b.key) !== -1)
      .sort((a, b) => BADGE_KEYS.indexOf(a.key) - BADGE_KEYS.indexOf(b.key));
  }

  const badgeCount = (b) => (typeof b.count === "number" && b.count > 1 ? b.count : 0);
  // last_match_id contract'ta zorunlu ama ileri sürümde null gelebilir → satır düşer.
  const badgeLast = (b) =>
    Number.isFinite(Number(b.last_match_id))
      ? t("profile.badge_last", { id: Number(b.last_match_id) })
      : "";

  function badgeCard(b) {
    // MVP vitrinin ilkidir (katalog sırası zaten öyle) ve pirinç vurgulu;
    // bench_3 esprili olduğu için nötr gri tonda kalır.
    const tone = b.key === "mvp" ? " pb-mvp" : b.key === "bench_3" ? " pb-bench" : "";
    const n = badgeCount(b);
    const last = badgeLast(b);
    // Görsel tooltip aria-hidden'dır; aynı bilgi ekran okuyucuya .pb-sr ile
    // düğmenin erişilebilir adının parçası olarak zaten verilir.
    const sr = [t("profile.badge_" + b.key + "_desc"),
      n ? t("profile.badge_count_aria", { n }) : "", last].filter(Boolean).join(" ");
    return `<button type="button" class="pb-card${tone}" data-key="${b.key}">
        ${badgeIcon(b.key)}
        <span class="pb-name">${t("profile.badge_" + b.key)}</span>
        ${n ? `<span class="pb-count" aria-hidden="true">${t("profile.badge_count", { n })}</span>` : ""}
        <span class="pb-sr">${sr}</span>
      </button>`;
  }

  let badgeOpen = null;   // tooltip'i açık olan kartçık düğümü

  function renderBadges() {
    const sec = $("#prof-badges");
    if (!sec) return;
    badgeOpen = null;
    // Uç yoksa/düştüyse bölüm hiç görünmez (profilin kalanı etkilenmez).
    if (!state.badges) { sec.hidden = true; sec.innerHTML = ""; return; }
    sec.hidden = false;

    const title = `<h3 class="ps-title">${t("profile.badges_title")}</h3>`;
    const list = badgeList();
    if (!list.length) {
      sec.innerHTML = title + `<p class="ps-empty">${t("profile.badges_empty")}</p>`;
      return;
    }
    sec.innerHTML = title + `<div class="pb-grid">${list.map(badgeCard).join("")}</div>`;

    sec.querySelectorAll(".pb-card").forEach(card => {
      const b = list.find(x => x.key === card.dataset.key);
      // Tıklama ve odak AÇAR (kapatmaz): fare tıklamasında odak+tık ard arda
      // gelir, "toggle" olsaydı tooltip açılıp hemen kapanırdı.
      card.addEventListener("click", () => openBadgeTip(card, b));
      card.addEventListener("focus", () => openBadgeTip(card, b));
      card.addEventListener("blur", () => { if (badgeOpen === card) closeBadgeTip(); });
    });
  }

  function openBadgeTip(card, b) {
    if (!card || !b || badgeOpen === card) return;
    closeBadgeTip();
    const last = badgeLast(b);
    card.insertAdjacentHTML("beforeend",
      `<span class="pb-tip" aria-hidden="true">
         <span>${t("profile.badge_" + b.key + "_desc")}</span>
         ${last ? `<span class="pb-tip-last">${last}</span>` : ""}
       </span>`);
    badgeOpen = card;
    // Kenardaki kartçıkta kutu ızgaranın dışına taşabilir: ölçüp içeri çekilir
    // (320px'de yatay taşma yok kuralı; tarihçe popup'ındaki desenin aynısı).
    const tip = card.querySelector(".pb-tip");
    const grid = card.closest(".pb-grid");
    if (!tip || !grid) return;
    const tr = tip.getBoundingClientRect();
    const gr = grid.getBoundingClientRect();
    const shift = tr.left < gr.left ? gr.left - tr.left
      : tr.right > gr.right ? gr.right - tr.right : 0;
    if (shift) tip.style.marginLeft = Math.round(shift) + "px";
  }

  // Esc ile kapanır; odak kartçıkta KALIR (tetikleyici zaten kartçığın kendisi).
  function closeBadgeTip() {
    const tip = document.querySelector("#prof-badges .pb-tip");
    if (tip) tip.remove();
    badgeOpen = null;
  }

  // ── 2c) Haftanın enleri (GÖREV 2) ─────────────────────────────
  // Salt-okur ekran: GET /highlights/weekly. Contract'taki her alan null olabilir;
  // dolu kartlar tıklanabilir (profile gider), null kartlar soluk "—" olarak kalır.

  // Pencere metni: tr "5–12 Ağu arası" / en "Aug 5–12"; ay sınırını aşarsa
  // tr "29 Tem – 5 Ağu arası" / en "Jul 29 – Aug 5". Biçim sözlük anahtarındadır.
  function windowText(w) {
    const s = new Date(w.start), e = new Date(w.end);
    if (isNaN(s) || isNaN(e)) return "";
    const day = (d) => d.toLocaleDateString(uiLocale(), { day: "numeric" });
    const mon = (d) => d.toLocaleDateString(uiLocale(), { month: "short" });
    return s.getFullYear() === e.getFullYear() && s.getMonth() === e.getMonth()
      ? t("highlights.window_same", { d1: day(s), d2: day(e), m: mon(e) })
      : t("highlights.window_cross", { d1: day(s), m1: mon(s), d2: day(e), m2: mon(e) });
  }

  // Büyük kartlar (haftanın oyuncusu / yıldız rukisi). d null ise dokunma hedefi
  // üretilmez: <button> yerine soluk <div> çizilir.
  function hlCard(cls, label, d, valueHtml) {
    if (!d) {
      return `<div class="hl-card ${cls} hl-none">
          <span class="hl-label">${label}</span>
          <span class="hl-name">—</span>
          <span class="hl-sub">${t("highlights.no_window_matches")}</span>
        </div>`;
    }
    return `<button type="button" class="hl-card ${cls}" data-player="${d.player_id}">
        <span class="hl-label">${label}</span>
        <span class="hl-name">${esc(d.display_name)}</span>
        ${valueHtml}
        <span class="hl-sub">${t("highlights.in_window", { n: d.matches_in_window })}</span>
      </button>`;
  }

  // Rol kartı: etiket sözlükteki rol adıdır; d null ise o rolde pencerede kimse oynamamıştır.
  function hlRoleCard(role, d) {
    const label = `<span class="hl-label">${roleName(role)}</span>`;
    if (!d) {
      return `<div class="hl-role hl-none">${label}
          <span class="hl-name">—</span>
          <span class="hl-sub">${t("highlights.role_not_played")}</span>
        </div>`;
    }
    return `<button type="button" class="hl-role" data-player="${d.player_id}">${label}
        <span class="hl-name">${esc(d.display_name)}</span>
        <span class="hl-value">${num1(d.score)}</span>
        <span class="hl-sub">${t("common.n_matches", { n: d.matches_in_window })}</span>
      </button>`;
  }

  // ── 2d) Nemesis (GÖREV 3) ─────────────────────────────────────
  // GET /nemesis: (çift, rol) adaylarından en başa baş geçen rekabet. Ekranda
  // TÜM ZAMANLARIN çifti büyük gösterilir; weekly farklıysa tek satır not düşülür.
  // Maç kurma her zaman `active` çiftle olur — hangisi olduğu ekranda işaretlenir.
  const nemKey = (p) =>
    p ? p.role + ":" + p.players.map(x => x.player_id).sort((a, b) => a - b).join("-") : "";
  const nemPct = (c) => t("common.percent", { n: Math.round((c || 0) * 100) });
  const nemLink = (x, cls) =>
    `<button type="button" class="${cls}" data-player="${x.player_id}">${esc(x.display_name)}</button>`;
  const nemActiveBadge = () => `<span class="nem-active">${t("highlights.active_badge")}</span>`;

  function nemesisCard(pair, isActive) {
    const [a, b] = pair.players;
    return `<div class="nem-card">
        ${nemLink(a, "nem-who")}
        <div class="nem-mid">
          <span class="nem-role">${esc(roleLabel(pair.role))}</span>
          <span class="nem-score">${a.wins}–${b.wins}</span>
          <span class="nem-sub">${t("highlights.encounters", { n: pair.encounters })}</span>
        </div>
        ${nemLink(b, "nem-who")}
      </div>
      <p class="nem-close">${t("highlights.close", { pct: nemPct(pair.closeness) })}${
        isActive ? nemActiveBadge() : ""}</p>`;
  }

  // n null ise (backend /nemesis bilmiyor / istek düştü) bölüm hiç çizilmez.
  function nemesisSection(n) {
    if (!n) return "";
    const at = n.all_time, wk = n.weekly;
    let body;
    if (!at) {
      body = `<p class="ps-empty">${t("highlights.nemesis_empty")}</p>`;
    } else {
      body = nemesisCard(at, n.active === "all_time");
      if (wk && nemKey(wk) !== nemKey(at)) {
        const [wa, wb] = wk.players;
        body += `<p class="nem-weekly">` + t("highlights.weekly_pair", {
            a: nemLink(wa, "nem-link"),
            b: nemLink(wb, "nem-link"),
            role: esc(roleLabel(wk.role)),
            enc: t("highlights.encounters", { n: wk.encounters }),
            close: t("highlights.close", { pct: nemPct(wk.closeness) }),
          }) +
          (n.active === "weekly" ? nemActiveBadge() : "") + `</p>`;
      }
    }
    const btn = n.active
      ? `<button type="button" id="btn-nemesis-setup" class="btn-primary btn-nemesis">${t("highlights.nemesis_setup_btn")}</button>`
      : "";
    return `<section class="prof-section nem-section">
        <h3 class="ps-title">${t("highlights.nemesis_title")}</h3>${body}${btn}
      </section>`;
  }

  async function loadHighlights() {
    const box = $("#highlights-body");
    box.innerHTML = `<p class='empty'>${t("common.loading")}</p>`;
    try {
      // /nemesis ayrı bir uçtur: düşerse Enler ekranının kalanı çalışmaya devam etsin.
      const [h, n] = await Promise.all([
        api("/highlights/weekly"),
        api("/nemesis").catch(() => null),
      ]);
      state.nemesis = n;
      const roles = h.best_by_role || {};
      // Hiç valid maç yoksa contract üç alanı da null döner → tek satır boş durum.
      if (!h.best_player && !h.rising_star && !ROLES.some(r => roles[r])) {
        box.innerHTML = `<p class='empty'>${t("highlights.empty")}</p>`;
        return;
      }
      const w = h.window || {};
      const head = windowText(w)
        ? `<div class="hl-window">` + windowText(w) +
          (w.fallback ? `<span class="hl-fb">${t("highlights.fallback_note")}</span>` : "") + `</div>`
        : "";
      const rs = h.rising_star;
      const up = rs && rs.delta >= 0;
      const bestValue = h.best_player
        ? `<span class="hl-value">${num1(h.best_player.score)}<span class="hl-unit">${t("common.points_word")}</span></span>`
        : "";
      box.innerHTML = head +
        hlCard("hero", t("highlights.best_player"), h.best_player, bestValue) +
        hlCard("rising", t("highlights.rising_star"), rs,
          rs ? `<span class="hl-value delta ${up ? "up" : "down"}">${fmtDelta2(rs.delta)}</span>` : "") +
        `<section class="prof-section">
           <div class="ps-head">
             <h3 class="ps-title">${t("highlights.role_bests")}</h3>
             <button type="button" id="btn-map-from-hl" class="map-link">${t("highlights.map_link")}</button>
           </div>
           <div class="hl-roles">${ROLES.map(r => hlRoleCard(r, roles[r])).join("")}</div>
         </section>` +
        nemesisSection(n);

      // Nemesis bölümündeki isimler de data-player taşır → aynı kayıtla profile gider.
      box.querySelectorAll("button[data-player]").forEach(btn =>
        btn.addEventListener("click", () => openProfile(Number(btn.dataset.player))));
      const setup = box.querySelector("#btn-nemesis-setup");
      if (setup) setup.addEventListener("click", () => startNemesisMode(state.nemesis));
      // "Haritada gör →" (GÖREV 4): rol enlerini harita görünümünde açar.
      box.querySelector("#btn-map-from-hl").addEventListener("click", openMap);
    } catch (e) {
      box.innerHTML = `<p class='empty'>${esc(e.message)}</p>`;
      throw e; // toast'ı showView gösterir
    }
  }

  // ── 2e) Harita: rol enleri (GÖREV 4) ──────────────────────────
  // Yeni endpoint yok: veri GET /leaderboard'un role_ratings alanından gelir
  // (sıralama ekranıyla aynı istek şekli; her görünüşte taze çekilir, diğer
  // ekranlarla tutarlı — void/ingest sonrası bayat kalmaz).
  //
  // Baloncuk konumları: SVG viewBox'ıyla aynı yüzde uzayında [sol %, üst %].
  // ÜST üst koridorun ortasında, ORMAN üst-sol orman bölgesinde, ORTA harita
  // merkezinde, ALT alt koridorun ortasında, DESTEK alt koridorun yanında.
  const RIFT_SPOTS = {
    TOP: [24, 15], JUNGLE: [22, 42], MIDDLE: [50, 50], BOTTOM: [80, 80], UTILITY: [48, 86],
  };

  // O rolde ≥1 maçı olanlar; rol score azalan → o roldeki maç azalan → ad alfabetik.
  // matches === 0 default prior'dır (gerçek veri değil) → sıralamaya girmez.
  function roleRanking(rows, role) {
    return rows
      .map(p => ({ p, r: (p.role_ratings || {})[role] }))
      .filter(x => x.r && typeof x.r.score === "number" && x.r.matches > 0)
      .sort((a, b) =>
        b.r.score - a.r.score ||
        b.r.matches - a.r.matches ||
        a.p.display_name.localeCompare(b.p.display_name, window.I18n.getLang()));
  }

  function riftBubble(role, top) {
    const [x, y] = RIFT_SPOTS[role];
    const pos = `left:${x}%;top:${y}%`;
    if (!top) {
      // Sınıf adı "rb-none": global ".empty" (ortalı boş-durum paragrafı, padding 40px)
      // baloncuğun kutusunu bozuyordu — enler ekranındaki ".hl-none" ile aynı desen.
      return `<button type="button" class="rift-bub rb-none" style="${pos}" data-role="${role}"
                aria-label="${t("map.bubble_none_aria", { role: roleName(role) })}">
          <span class="rb-role">${roleAbbr(role)}</span>
          <span class="rb-name">—</span>
        </button>`;
    }
    const score = fmtRating(top.r.score);
    return `<button type="button" class="rift-bub" style="${pos}" data-role="${role}"
              aria-label="${t("map.bubble_aria", { role: roleName(role), name: esc(top.p.display_name), score })}">
        <span class="rb-role">${roleAbbr(role)}</span>
        <span class="rb-name">${esc(top.p.display_name)}</span>
        <span class="rb-score">${score}</span>
      </button>`;
  }

  // Harita alt çubukta sekme DEĞİLDİR: 320px'de 6. sekme "SIRALAMA" etiketini
  // kesiyordu (ölçüm README'de), bu yüzden profil gibi "detay" görünümü olarak
  // Enler ve Sıralama ekranlarından açılır.
  function openMap() {
    if (currentView !== "map") {
      const from = currentView === "profile" ? state.profileFrom : currentView;
      // Kendine dönen geri düğmesi olmasın; maç detayı da harita için geri hedefi
      // DEĞİLDİR (o zincir yığınla yürür, harita zincire girmez).
      state.mapFrom = (from === "map" || from === "matchdetail") ? "highlights" : from;
    }
    $("#btn-map-back").textContent = backLabel(state.mapFrom);
    showView("map");
  }
  $("#btn-map-back").addEventListener("click", () => showView(state.mapFrom));
  $("#btn-map-from-board").addEventListener("click", openMap);

  async function loadMap() {
    const box = $("#rift-bubbles");
    try {
      state.board = await api("/leaderboard");
    } catch (e) {
      box.innerHTML = `<p class="rift-err">${esc(e.message)}</p>`;
      throw e; // toast'ı showView gösterir
    }
    box.innerHTML = ROLES.map(r => riftBubble(r, roleRanking(state.board, r)[0])).join("");
    box.querySelectorAll(".rift-bub").forEach(btn =>
      btn.addEventListener("click", () => openRoleModal(btn.dataset.role, btn)));
  }

  // Pop-up: o rolün tam sıralaması. Kapatma: × / dışına tıklama / Esc.
  let roleModalReturn = null; // pop-up kapanınca odağın döneceği baloncuk

  function roleModalHtml(role) {
    const list = roleRanking(state.board, role);
    if (!list.length) return `<p class="ps-empty">${t("map.role_empty")}</p>`;
    return `<ol class="rr-list">` + list.map(({ p, r }, i) =>
      `<li class="rr-row">
         <span class="rr-rank">${i + 1}</span>
         <button type="button" class="rr-name" data-player="${p.id}">${esc(p.display_name)}</button>
         <span class="rr-score">${fmtRating(r.score)}</span>
         <span class="rr-matches">${t("common.n_matches", { n: r.matches })}</span>
       </li>`).join("") + `</ol>`;
  }

  function openRoleModal(role, fromBtn) {
    roleModalReturn = fromBtn || null;
    $("#role-modal-title").textContent = t("map.role_ranking_title", { role: roleName(role) });
    const body = $("#role-modal-body");
    body.innerHTML = roleModalHtml(role);
    body.querySelectorAll(".rr-name").forEach(btn =>
      btn.addEventListener("click", () => {
        const id = Number(btn.dataset.player);
        closeRoleModal(false);
        openProfile(id); // pop-up kapanır, profile gidilir
      }));
    $("#role-modal").hidden = false;
    $("#role-modal-close").focus();
  }

  function closeRoleModal(restoreFocus = true) {
    if ($("#role-modal").hidden) return;
    $("#role-modal").hidden = true;
    if (restoreFocus && roleModalReturn && document.contains(roleModalReturn)) roleModalReturn.focus();
    roleModalReturn = null;
  }

  $("#role-modal-close").addEventListener("click", () => closeRoleModal());
  // Dışına tıklama: yalnız backdrop'un kendisi (modal içi tıklamalar sayılmaz).
  $("#role-modal").addEventListener("click", (e) => {
    if (e.target === $("#role-modal")) closeRoleModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    closeRoleModal();
    closeHistPopup();   // GÖREV 10: tarihçe popup'ı da Esc ile kapanır
    closeBadgeTip();    // GÖREV 11+12: rozet tooltip'i (klavye erişimi)
    closeBuildTip();    // GÖREV 14: build ikonu tooltip'i (klavye erişimi)
  });

  // ── 2f) META: şampiyon kademeleri (GÖREV 16) ──────────────────
  // Veri API'den DEĞİL statik dosyadan gelir: assets/meta/tiers.json
  // (api_contract §8 "Meta tier verisi"; yarı otomatik akış — deploy/fetch_meta.py
  // üretir, Teoman onaylayıp commit'ler). Bu yüzden istek dd- varlık katmanıyla
  // aynı desendedir: X-API-Key TAŞIMAZ, USE_MOCK yolundan geçmez, bir kez çekilip
  // önbelleğe alınır ve ASLA reject etmez — dosyanın yokluğu bu görünümün hata
  // durumudur, uygulamanın değil.
  const META_URL = "assets/meta/tiers.json";
  const META_TIERS = ["S", "A", "B"];
  // Dosyadaki rol anahtarları küçük harftir; kanonik ROLES sırasına eşlenir.
  const META_ROLE_KEY = {
    TOP: "top", JUNGLE: "jungle", MIDDLE: "middle", BOTTOM: "bottom", UTILITY: "utility",
  };
  let metaPromise = null;

  // Hata METNİ değil, hata TÜRÜ önbelleğe alınır: dil değişince mesaj yeniden
  // üretilebilsin (metin saklansaydı eski dilde donardı).
  function fetchMeta() {
    if (metaPromise) return metaPromise;
    metaPromise = window.fetch(META_URL)
      .then(r => {
        if (!r.ok) return { err: { kind: "http", status: r.status } };
        return r.json().then(
          d => (d && typeof d === "object" && d.tiers && typeof d.tiers === "object"
            ? { data: d } : { err: { kind: "shape" } }),
          () => ({ err: { kind: "shape" } }));
      })
      .catch(() => ({ err: { kind: "network" } }));
    return metaPromise;
  }

  // Çoğul kuralı sözlüktedir (sağlık ekranındaki desen): <base>_one / _other.
  const metaPlural = (n) => t("meta.n_champs" + (n === 1 ? "_one" : "_other"), { n });

  const metaErrText = (e) =>
    e.kind === "http" ? t("meta.err_http", { status: e.status })
      : e.kind === "shape" ? t("meta.err_shape")
      : t("meta.err_network");

  // Bir (rol, kademe) hücresinin adları. Şema dışı değerler (sayı, boş dize,
  // eksik anahtar) sessizce elenir: bozuk tek hücre ekranı düşürmez.
  // GÖREV 21 şema genişlemesi (api_contract §8): tier listeleri düz string YA DA
  // {name, win_rate, pick_rate} nesnesi taşıyabilir — META ekranı yalnız adı
  // kullanır, iki biçim de okunur (geriye uyum contract gereği).
  function metaList(tiers, role, tier) {
    const cell = tiers[META_ROLE_KEY[role]];
    const arr = cell && Array.isArray(cell[tier]) ? cell[tier] : [];
    return arr
      .map(x => (typeof x === "string" ? x
        : x && typeof x === "object" && typeof x.name === "string" ? x.name : ""))
      .filter(x => x.trim() !== "");
  }

  // TÜMÜ görünümü: şampiyon EN İYİ kademesinde BİR KEZ görünür, adının altındaki
  // rol rozetleri O KADEMEYİ tuttuğu koridorlardır (daha düşük kademedeki rolleri
  // burada göstermek sütunun anlamıyla çelişirdi — o bilgi rol süzgecinde durur).
  function metaBestIndex(tiers) {
    const best = new Map();
    ROLES.forEach(role => META_TIERS.forEach((tier, ti) => {
      metaList(tiers, role, tier).forEach(name => {
        const cur = best.get(name);
        if (!cur || ti < cur.ti) best.set(name, { ti, roles: [role] });
        else if (ti === cur.ti && cur.roles.indexOf(role) === -1) cur.roles.push(role);
      });
    }));
    return best;
  }

  // Sütun içeriği kademe-öncelikli gezilir (rol kanonik sırada, rol içinde dosya
  // sırası korunur) → aynı dosya her zaman aynı sırayı üretir.
  function metaColumnItems(tiers, tier) {
    if (state.metaFilter !== "ALL") {
      return metaList(tiers, state.metaFilter, tier).map(name => ({ name, roles: [] }));
    }
    const best = metaBestIndex(tiers);
    const ti = META_TIERS.indexOf(tier);
    const seen = new Set();
    const out = [];
    ROLES.forEach(role => metaList(tiers, role, tier).forEach(name => {
      const b = best.get(name);
      if (!b || b.ti !== ti || seen.has(name)) return;
      seen.add(name);
      out.push({ name, roles: b.roles });
    }));
    return out;
  }

  // Portre yuvarlaktır (dd- sözleşmesi: ölçüyü kapsayıcı verir). champions.json'da
  // olmayan ad da LİSTELENİR, yalnız portre yer tutucuya düşer (veri onay akışı
  // adları zaten deploy/fetch_meta.py'de doğruluyor).
  function metaChampHtml(item) {
    const badges = item.roles.length
      ? `<span class="mt-roles">` +
        item.roles.map(r => posIconHtml(r, roleAbbr(r), "mt-role")).join("") + `</span>`
      : "";
    return `<li class="mt-champ">
        <span class="mt-portrait">${ddIconHtml(champIconSrc(item.name), champPh(item.name), "champ")}</span>
        <span class="mt-name">${esc(item.name)}</span>
        ${badges}
      </li>`;
  }

  function metaColumnHtml(tier, items) {
    return `<section class="mt-col mt-${tier.toLowerCase()}"
              aria-label="${esc(t("meta.tier_aria", { tier }))}">
        <h3 class="mt-col-head">
          <span class="mt-tier">${tier}</span>
          <span class="mt-count">${metaPlural(items.length)}</span>
        </h3>
        ${items.length
          ? `<ul class="mt-list">${items.map(metaChampHtml).join("")}</ul>`
          : `<p class="mt-empty">${t("meta.tier_empty")}</p>`}
      </section>`;
  }

  // Süzgeç düğmeleri gerçek <button>'dır (Tab + Enter/Space); seçili olan
  // aria-pressed taşır. Rol düğmesinin içeriği ortak posIconHtml'dir: ikonlar
  // indirilmemişse kendiliğinden kısaltma metnine düşer.
  function metaFiltersHtml() {
    const btn = (val, cls, inner, label) =>
      `<button type="button" class="mt-filter ${cls}${state.metaFilter === val ? " on" : ""}"
         data-filter="${val}" aria-pressed="${state.metaFilter === val}"
         aria-label="${esc(label)}">${inner}</button>`;
    return btn("ALL", "mt-all",
        `<span class="mt-star" aria-hidden="true">★</span>` +
        `<span class="mt-all-txt">${t("meta.filter_all")}</span>`, t("meta.filter_all")) +
      ROLES.map(r => btn(r, "mt-frole",
        posIconHtml(r, roleAbbr(r), "mt-fico"), roleName(r))).join("");
  }

  // patch / updated eksik ya da bozuksa o parça hiç yazılmaz (başlık boş kalır).
  function metaHeadText(d) {
    const parts = [];
    if (typeof d.patch === "string" && d.patch.trim()) parts.push(t("meta.patch", { patch: d.patch }));
    // Tarih YEREL saatle kurulur: new Date("2026-08-15") UTC gece yarısıdır ve
    // negatif ofsetli cihazda bir gün geriye kayardı.
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(d.updated || ""));
    if (m) {
      const dt = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
      if (!isNaN(dt.getTime())) parts.push(dt.toLocaleDateString(uiLocale(), { day: "numeric", month: "short" }));
    }
    return parts.join(" · ");
  }

  // Süzgeç değişiminde ÇUBUK YENİDEN KURULMAZ, yalnız durumu güncellenir: innerHTML
  // ile kurulsaydı basılan düğme DOM'dan silinir ve klavye odağı body'ye düşerdi
  // (Tab yeniden sayfanın başından başlardı).
  function syncMetaFilters() {
    $("#meta-filters").querySelectorAll(".mt-filter").forEach(b => {
      const on = b.dataset.filter === state.metaFilter;
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", String(on));
    });
  }

  function renderMetaBody() {
    const box = $("#meta-body");
    const lists = META_TIERS.map(tier => metaColumnItems(state.meta.tiers, tier));
    const cols = META_TIERS.map((tier, i) => metaColumnHtml(tier, lists[i])).join("");
    // Hiçbir kademede ad yoksa (boş ya da tanınmayan rol anahtarlı dosya) sütun
    // iskeleti yerine tek satır boş durum yazılır.
    const total = lists.reduce((n, l) => n + l.length, 0);
    box.innerHTML = total
      ? `<div class="mt-cols">${cols}</div>` +
        (state.metaFilter === "ALL" ? `<p class="mt-note">${t("meta.all_note")}</p>` : "")
      : `<p class='empty'>${t("meta.empty")}</p>`;
    ddBindImages(box);
  }

  function renderMeta() {
    const filters = $("#meta-filters");
    $("#meta-patch").textContent = metaHeadText(state.meta);
    filters.hidden = false;
    filters.innerHTML = metaFiltersHtml();
    filters.querySelectorAll(".mt-filter").forEach(b =>
      b.addEventListener("click", () => {
        if (state.metaFilter === b.dataset.filter) return;
        state.metaFilter = b.dataset.filter;
        syncMetaFilters();
        renderMetaBody();
      }));
    renderMetaBody();
  }

  // Yükleyici hiç THROW ETMEZ: veri bir uç değil statik dosyadır, hata bu
  // görünümün içinde yazılı durur (toast'a gerek yok, sağlık ekranı deseni).
  async function loadMeta() {
    const box = $("#meta-body");
    box.innerHTML = `<p class='empty'>${t("common.loading")}</p>`;
    $("#meta-filters").hidden = true;
    $("#meta-patch").textContent = "";
    const [res] = await Promise.all([fetchMeta(), loadAssets()]);
    if (res.err) {
      state.meta = null;
      box.innerHTML = `<div class="mt-error">
          <p class="mt-err-title">${t("meta.error_title")}</p>
          <p class="mt-err-detail">${esc(metaErrText(res.err))}</p>
          <p class="mt-err-hint">${t("meta.error_hint")}</p>
        </div>`;
      return;
    }
    state.meta = res.data;
    renderMeta();
  }

  // ── 2g) SSS (FAQ) — statik içerikli sekme + madde detayı ──────
  // Veri backend'den DEĞİL statik dosyalardan gelir (META deseni): manifest
  // assets/faq/index.json kartları, assets/faq/{tr,en}/*.md dosyaları içeriği
  // taşır. İstekler X-API-Key TAŞIMAZ, USE_MOCK yolundan geçmez, bir kez çekilip
  // önbelleğe alınır ve ASLA reject etmez — dosya yokluğu bu görünümün hata
  // durumudur, uygulamanın değil.
  //
  // Madde detayının KALICI adresi vardır: #faq/<slug>. Uygulamanın kalanı hash
  // kullanmadığı için kural dardır: yalnız #faq ve #faq/<slug> tanınır, diğer
  // görünümlere geçerken FAQ hash'i temizlenir (başka hash'e dokunulmaz).
  // Adres yazımı replaceState iledir (hashchange tetiklemez, geçmişi şişirmez);
  // hashchange dinleyicisi yalnız DIŞ değişimi (elle yazılan/yapıştırılan adres)
  // yakalar. Geri düğmesi health desenidir: her zaman SSS listesine döner.
  const FAQ_URL = "assets/faq/index.json";
  const FAQ_BASE = "assets/faq/";
  const FAQ_SLUG_RE = /^[a-z0-9-]+$/;
  const FAQ_HASH_RE = /^#faq(?:\/([a-z0-9-]+))?$/;
  let faqPromise = null;
  const faqDocCache = new Map(); // md yolu -> Promise<{text} | {err}>

  // Şema dışı madde (slug yok/bozuk, title/file nesne değil, slug tekrarı)
  // sessizce elenir: bozuk tek kayıt listeyi düşürmez (META hücre deseni).
  function faqParseItems(d) {
    if (!d || typeof d !== "object" || !Array.isArray(d.items)) return null;
    const seen = new Set();
    const out = [];
    for (const it of d.items) {
      if (!it || typeof it !== "object") continue;
      if (typeof it.slug !== "string" || !FAQ_SLUG_RE.test(it.slug) || seen.has(it.slug)) continue;
      if (!it.title || typeof it.title !== "object") continue;
      if (!it.file || typeof it.file !== "object") continue;
      seen.add(it.slug);
      out.push(it);
    }
    return out;
  }

  // Hata METNİ değil TÜRÜ önbelleğe alınır (fetchMeta dersi): dil değişince
  // mesaj yeniden üretilir.
  function fetchFaq() {
    if (faqPromise) return faqPromise;
    faqPromise = window.fetch(FAQ_URL)
      .then(r => {
        if (!r.ok) return { err: { kind: "http", status: r.status } };
        return r.json().then(
          d => {
            const items = faqParseItems(d);
            return items ? { items } : { err: { kind: "shape" } };
          },
          () => ({ err: { kind: "shape" } }));
      })
      .catch(() => ({ err: { kind: "network" } }));
    return faqPromise;
  }

  function fetchFaqDoc(path) {
    if (!faqDocCache.has(path)) {
      faqDocCache.set(path, window.fetch(FAQ_BASE + path)
        .then(r => (r.ok
          ? r.text().then(text => ({ text }))
          : { err: { kind: "http", status: r.status } }))
        .catch(() => ({ err: { kind: "network" } })));
    }
    return faqDocCache.get(path);
  }

  const faqErrText = (e) =>
    e.kind === "http" ? t("faq.err_http", { status: e.status })
      : e.kind === "shape" ? t("faq.err_shape")
      : t("faq.err_network");

  const faqErrorHtml = (title, e) =>
    `<div class="fq-error">
       <p class="fq-err-title">${title}</p>
       <p class="fq-err-detail">${esc(faqErrText(e))}</p>
     </div>`;

  // Manifest'teki {tr, en} nesnesinden aktif dilin metni; yoksa diğer dile
  // düşülür (ddText deseni), o da yoksa boş döner.
  function faqLangText(obj) {
    if (!obj || typeof obj !== "object") return "";
    const order = window.I18n.getLang() === "tr" ? ["tr", "en"] : ["en", "tr"];
    for (const k of order) {
      const v = obj[k];
      if (typeof v === "string" && v.trim()) return v;
    }
    return "";
  }
  const faqFilePath = (item) => faqLangText(item.file) || null;

  // ── SSS: markdown → HTML (mini, framework'süz) ────────────────
  // GÜVENLİK: kaynak metnin TAMAMI önce esc() ile kaçışlanır; dönüşüm kaçışlanmış
  // metin üzerinde çalışır ve yalnız kendi ürettiği etiketleri ekler → md dosyası
  // içine gömülü HTML asla çalışmaz (display_name XSS dersindeki disiplin).
  // Kapsam bilinçli dar: başlık, paragraf, **kalın**, *italik*, `kod`, ``` blok,
  // tablo, alıntı, sıralı/sırasız liste, [link](url). Alt çizgi italik BİLEREK
  // yok: P_avg / mu_eff gibi adlar metinde geçiyor, _..._ kuralı onları bozardı.

  // Yalnız güvenli hedefler: http(s), mailto, sayfa içi #, göreli yol.
  // javascript: gibi şema taşıyan diğer URL'ler linke ÇEVRİLMEZ (düz metin kalır).
  function fqHref(u) {
    if (/^(https?:\/\/|mailto:|#)/i.test(u)) return u;
    if (!/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(u)) return u; // şemasız = göreli
    return null;
  }

  function mdInline(s) {
    // Kod parçaları önce ayrılır: içlerinde * [ ] gibi imler biçimlendirilmez.
    const codes = [];
    s = s.replace(/`([^`]+)`/g, (m, c) => {
      codes.push(c);
      return "\x00" + (codes.length - 1) + "\x00";
    });
    s = s.replace(/\[([^\]]+)\]\(([^()\s]+)\)/g, (m, txt, url) => {
      const href = fqHref(url);
      if (!href) return txt;
      const ext = /^https?:\/\//i.test(href) ? ` target="_blank" rel="noopener"` : "";
      return `<a href="${href}"${ext}>${txt}</a>`;
    });
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    // Tek yıldız italik: ** artıklarıyla çakışmasın diye solunda * olmayan eş.
    s = s.replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
    return s.replace(/\x00(\d+)\x00/g, (m, i) => `<code>${codes[Number(i)]}</code>`);
  }

  // Tablo = hücreli satır + hemen altında ayraç satırı (|---|---|).
  const fqIsSepRow = (s) =>
    typeof s === "string" && /^\s*\|?[\s|:-]+\|[\s|:-]*$/.test(s) && s.indexOf("-") !== -1;
  const fqIsTableAt = (lines, i) =>
    lines[i].indexOf("|") !== -1 && i + 1 < lines.length && fqIsSepRow(lines[i + 1]);
  // Paragraf biriktirmeyi kesen blok başlangıçları (alıntı imi kaçış sonrası &gt;).
  const FQ_BLOCK_RE = /^(#{1,6}\s|```|&gt;( |$)|[-*+]\s|\d+\.\s)/;

  function mdBlocks(lines) {
    const out = [];
    const blank = (s) => !s || !s.trim();
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (blank(line)) { i++; continue; }
      // ``` çitli kod bloğu: içerik OLDUĞU GİBİ (satır içi biçim yok)
      if (/^```/.test(line)) {
        const buf = [];
        i++;
        while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
        i++; // kapanış çiti (dosya sonunda eksikse sorun değil)
        out.push(`<pre class="fq-pre"><code>${buf.join("\n")}</code></pre>`);
        continue;
      }
      const h = /^(#{1,6})\s+(.*)$/.exec(line);
      if (h) {
        const n = h[1].length;
        out.push(`<h${n}>${mdInline(h[2])}</h${n}>`);
        i++;
        continue;
      }
      // Alıntı: ardışık &gt; satırları toplanır, içeriği yeniden blok işlenir.
      if (/^&gt;( |$)/.test(line)) {
        const buf = [];
        while (i < lines.length && /^&gt;( |$)/.test(lines[i]))
          buf.push(lines[i++].replace(/^&gt; ?/, ""));
        out.push(`<blockquote>${mdBlocks(buf)}</blockquote>`);
        continue;
      }
      // Liste: madde imiyle başlar; 2+ boşluk girintili satırlar maddenin devamıdır.
      if (/^[-*+]\s+/.test(line) || /^\d+\.\s+/.test(line)) {
        const ordered = /^\d+\.\s+/.test(line);
        const startRe = ordered ? /^\d+\.\s+/ : /^[-*+]\s+/;
        const items = [];
        while (i < lines.length && startRe.test(lines[i])) {
          let item = lines[i].replace(startRe, "");
          i++;
          while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !startRe.test(lines[i].trim()))
            item += " " + lines[i++].trim();
          items.push(`<li>${mdInline(item)}</li>`);
        }
        out.push(ordered ? `<ol>${items.join("")}</ol>` : `<ul>${items.join("")}</ul>`);
        continue;
      }
      if (fqIsTableAt(lines, i)) {
        const cells = (s) =>
          s.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map(c => mdInline(c.trim()));
        const head = cells(line);
        i += 2; // başlık + ayraç
        const rows = [];
        while (i < lines.length && !blank(lines[i]) && lines[i].indexOf("|") !== -1)
          rows.push(cells(lines[i++]));
        // Sarmalayıcı yatay kaydırır: dar ekranda tablo sayfayı genişletmez.
        out.push(`<div class="fq-tablewrap"><table><thead><tr>` +
          head.map(c => `<th>${c}</th>`).join("") + `</tr></thead><tbody>` +
          rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join("")}</tr>`).join("") +
          `</tbody></table></div>`);
        continue;
      }
      // Paragraf: boş satıra ya da yeni blok başlangıcına dek biriktirilir.
      const buf = [line.trim()];
      i++;
      while (i < lines.length && !blank(lines[i]) && !FQ_BLOCK_RE.test(lines[i]) && !fqIsTableAt(lines, i))
        buf.push(lines[i++].trim());
      out.push(`<p>${mdInline(buf.join(" "))}</p>`);
    }
    return out.join("");
  }

  const mdToHtml = (src) =>
    mdBlocks(esc(String(src).replace(/\r\n?/g, "\n")).split("\n"));

  // ── SSS: liste + detay görünümleri ────────────────────────────
  // Yükleyiciler hiç THROW ETMEZ (META deseni): hata görünümün içinde yazılı durur.
  async function loadFaq() {
    const box = $("#faq-list");
    box.innerHTML = `<p class='empty'>${t("common.loading")}</p>`;
    const res = await fetchFaq();
    if (res.err) {
      box.innerHTML = faqErrorHtml(t("faq.error_title"), res.err);
      return;
    }
    if (!res.items.length) {
      box.innerHTML = `<p class='empty'>${t("faq.empty")}</p>`;
      return;
    }
    // Kartlar GitHub issue listesi hissinde: başlık + tek cümlelik özet.
    box.innerHTML = res.items.map(it =>
      `<button type="button" class="fq-card" data-slug="${esc(it.slug)}">
         <span class="fq-card-title">${esc(faqLangText(it.title))}</span>
         <span class="fq-card-sum">${esc(faqLangText(it.summary))}</span>
       </button>`).join("");
    box.querySelectorAll(".fq-card").forEach(btn =>
      btn.addEventListener("click", () => openFaqItem(btn.dataset.slug)));
  }

  function openFaqItem(slug) {
    state.faqSlug = slug;
    clearBack();
    showView("faqdetail");
  }
  $("#btn-faqdetail-back").addEventListener("click", () => showView("faq"));

  // Geri düğmesi metni burada yazılır → dil değişiminde kendiliğinden tazelenir.
  // Deep-link ile ilk giriş bu görünüm olabilir: manifest burada da çekilir.
  async function loadFaqDetail() {
    $("#btn-faqdetail-back").textContent = t("common.back_faq");
    const box = $("#faqdetail-body");
    box.innerHTML = `<p class='empty'>${t("common.loading")}</p>`;
    const res = await fetchFaq();
    if (res.err) {
      box.innerHTML = faqErrorHtml(t("faq.error_title"), res.err);
      return;
    }
    const item = res.items.find(x => x.slug === state.faqSlug);
    if (!item) {
      // Bayat/bozuk deep-link: madde yok — kısa mesaj, liste geri düğmesi duruyor.
      box.innerHTML = `<p class='empty'>${t("faq.not_found")}</p>`;
      return;
    }
    const path = faqFilePath(item);
    const doc = path ? await fetchFaqDoc(path) : { err: { kind: "shape" } };
    if (doc.err) {
      box.innerHTML = faqErrorHtml(t("faq.item_error"), doc.err);
      return;
    }
    box.innerHTML = `<article class="fq-doc">${mdToHtml(doc.text)}</article>`;
  }

  // ── SSS: kalıcı adres (#faq, #faq/<slug>) ─────────────────────
  const fqSetUrl = (u) => {
    try { history.replaceState(null, "", u); } catch { /* file:// vb. kısıtlı ortam */ }
  };
  // showView her geçişte çağırır: SSS görünümleri adresi yazar, diğerleri
  // yalnız FAQ hash'ini temizler (uygulamanın başka hash'i yok, ona dokunulmaz).
  function syncFaqHash(name) {
    const h = name === "faq" ? "#faq"
      : name === "faqdetail" && state.faqSlug ? "#faq/" + state.faqSlug
      : null;
    if (h) {
      if (location.hash !== h) fqSetUrl(h);
    } else if (FAQ_HASH_RE.test(location.hash)) {
      fqSetUrl(location.pathname + location.search);
    }
  }
  // Adresteki FAQ hash'ini görünüme çevirir; FAQ hash'i değilse false döner
  // (başlangıçta varsayılan görünüme düşülür).
  function faqRouteFromHash() {
    const m = FAQ_HASH_RE.exec(location.hash);
    if (!m) return false;
    if (m[1]) state.faqSlug = m[1];
    clearBack();
    showView(m[1] ? "faqdetail" : "faq");
    return true;
  }
  // Yalnız DIŞ hash değişimi (adres çubuğuna yazma, tarayıcı geri'si): kendi
  // yazdığımız replaceState bu olayı tetiklemez. Zaten açık görünümse dokunulmaz.
  window.addEventListener("hashchange", () => {
    const m = FAQ_HASH_RE.exec(location.hash);
    if (!m) return;
    const already = m[1]
      ? currentView === "faqdetail" && state.faqSlug === m[1]
      : currentView === "faq";
    if (!already) faqRouteFromHash();
  });

  // ── 3) Maç geçmişi ────────────────────────────────────────────
  // Kart satırındaki şampiyon portresi (GÖREV 14 uzantısı): kartlar arasında
  // gezerken aranan maç yüzlerden tanınsın diye adın ÖNÜNE küçük portre girer.
  // Yeni veri YOK — zaten çekilen participants[].champion kullanılır; varlık
  // katmanı da yeni değil, build/favori eşya ile AYNI dd- yardımcılarıdır.
  // champion null (manuel giriş) ise görünmez bir kutu çizilir: satır yüksekliği
  // ve adların hizası şampiyonu bilinen satırlarla birebir aynı kalır.
  const mcChampHtml = (champ) => champ
    ? `<span class="mc-champ">${ddIconHtml(champIconSrc(champ), champPh(champ), "champ", champ)}</span>`
    : `<span class="mc-champ mc-none" aria-hidden="true"></span>`;

  // Kart satırındaki ROL sütunu (GÖREV 15 — Teoman kararı): metin etiket
  // ("UST/ORMAN/...") yerine resmi oyun ici pozisyon simgesi. Simgeyi ortak
  // posIconHtml() basar (aynı desen maç detayı satır başlıklarında da kullanılır).
  // Rol bilinmiyorsa (position null) eski "—" aynen kalır: simgesi yoktur.
  // Kapsam yalnız bu sütun ve maç detayı satır başlıklarıdır — rol düzenleyici
  // <select>, dengeleme kartları ve profil metin etiketi kullanmaya devam eder.
  const mcRoleHtml = (pos) => posIconHtml(pos, roleLabel(pos), "pos-tag");

  // Ham K/D/A metni (GÖREV 19) — Geçmiş kartı VE maç detayının beş sekmesi
  // aynı yardımcıyı kullanır. Kural (CHANGE_REQUESTS 2026-08-17): k/d/a'nın
  // ÜÇÜNDEN HERHANGİ BİRİ null ise KDA HİÇ gösterilmez — kısmi değer de "—" de
  // basılmaz (çağıran null'da span'ı atlar). Etiketsiz salt sayıdır ("7/2/9"),
  // bu yüzden i18n anahtarı gerekmez (KDA gösterimi evrensel).
  const kdaText = (stats) =>
    stats && stats.kills != null && stats.deaths != null && stats.assists != null
      ? `${stats.kills}/${stats.deaths}/${stats.assists}`
      : null;

  async function loadMatches() {
    await fetchRoster();
    // Sözlükler bir kez yüklenir ve reject etmez; yoksa portreler yer tutucu
    // moduna düşer (maç listesi varlık yokluğunda BLOKE OLMAZ).
    await loadAssets();
    const list = await api("/matches?limit=20");
    state.matches = list;   // GÖREV 10: profil grafiğinden detaya atlarken önbellek
    const box = $("#match-list");
    box.innerHTML = list.length ? "" : `<p class='empty'>${t("matches.empty")}</p>`;

    for (const m of list) {
      const voided = m.status === "void";
      const teamCol = (team) => {
        const members = m.participants.filter(p => p.team === team)
          .sort((a, b) => roleOrder(a.position) - roleOrder(b.position));
        const won = m.winner_team === team;
        return `<ul class="team ${team === 100 ? "blue" : "red"} ${won ? "won" : ""}">` +
          members.map(p => {
            const rc = p.rating_change; // nullable: void maç / rating satırı yok → delta gösterme
            // GÖREV 18: delta = EFEKTİF score farkı (api_contract §3) — W/L çekirdek
            // mu farkı değil. Eski cache'li yanıtta score alanları yoksa mu farkına
            // düşülür (hata fırlatılmaz); renk sınıfları (up/down) aynı kalır.
            const rcDelta = rc
              ? (rc.score_after != null && rc.score_before != null
                  ? rc.score_after - rc.score_before
                  : rc.mu_after - rc.mu_before)
              : null;
            const deltaHtml = rc
              ? `<span class="delta ${rcDelta >= 0 ? "up" : "down"}">${fmtDelta(rcDelta)}</span>`
              : `<span class="delta none">—</span>`;
            // GÖREV 19: ham K/D/A adla delta ARASINDA ayrı (soluk) bir sütundur —
            // .p-who'nun içine girmez ki adın ellipsis'i KDA'yı kırpmasın; null'da
            // span hiç basılmaz (yer tutucu yok, satır eski haliyle çizilir).
            const kda = kdaText(p.stats);
            const kdaHtml = kda ? `<span class="mc-kda">${kda}</span>` : "";
            return `<li>${mcRoleHtml(p.position)}` +
                   mcChampHtml(p.champion) +
                   `<span class="p-who">${esc(p.display_name)}</span>${kdaHtml}${deltaHtml}</li>`;
          }).join("") + "</ul>";
      };
      // Rol düzeltme paneli: yalnız DEĞİŞEN roller PUT edilir (kısmi güncelleme serbest).
      const roleEditor = () => {
        const rows = [...m.participants]
          .sort((a, b) => (a.team - b.team) || (roleOrder(a.position) - roleOrder(b.position)))
          .map(p => {
            const cur = p.position == null ? "" : p.position;
            const opts = `<option value=""${cur === "" ? " selected" : ""}>—</option>` +
              ROLES.map(r => `<option value="${r}"${cur === r ? " selected" : ""}>${roleName(r)}</option>`).join("");
            return `<li class="re-row ${p.team === 100 ? "blue" : "red"}">
                <span class="p-who">${esc(p.display_name)}</span>
                <select data-player="${p.player_id}" data-original="${esc(cur)}"
                        aria-label="${esc(t("matches.role_select_aria", { name: p.display_name }))}">${opts}</select>
              </li>`;
          }).join("");
        return `<div class="role-editor" hidden>
            <ul class="re-list">${rows}</ul>
            <button class="btn-primary btn-save-roles" type="button">${t("matches.save_roles")}</button>
          </div>`;
      };
      const headBadge = voided
        ? `<span class="void-badge">${t("matches.void_badge")}</span>`
        : `<span class="win-tag ${m.winner_team === 100 ? "blue" : "red"}">${m.winner_team === 100 ? t("matches.win_blue") : t("matches.win_red")}</span>`;
      const voidBtn = voided
        ? ""
        : `<button class="btn-void" type="button">${t("matches.void_btn")}</button>`;
      const card = document.createElement("article");
      card.className = "match-card" + (voided ? " voided" : "");
      card.innerHTML =
        `<header class="match-head">
           <button class="md-open" type="button" title="${t("matches.open_detail")}">${fmtDate(m.played_at)} · ${fmtDuration(m.duration_s)}</button>
           ${headBadge}
         </header>
         <div class="match-teams">${teamCol(100)}${teamCol(200)}</div>
         <div class="match-actions">
           <button class="btn-roles" type="button" aria-expanded="false">${t("matches.edit_roles")}</button>
           ${voidBtn}
         </div>` +
        roleEditor();

      // Karta tıklama maç detayını açar (GÖREV 8). Düğmeler ve rol düzenleyici
      // içindeki tıklamalar detayı AÇMAZ: aksi halde "Rolleri düzenle"/"void"/
      // <select> her tıklamada görünüm değiştirirdi. Klavye erişimi başlıktaki
      // .md-open düğmesindedir (kartın kendisi odaklanabilir bir öğe değildir).
      card.addEventListener("click", (e) => {
        if (e.target.closest("button, select, label, .role-editor")) return;
        openMatchDetail(m);
      });
      card.querySelector(".md-open").addEventListener("click", () => openMatchDetail(m));

      const editor = card.querySelector(".role-editor");
      const btnRoles = card.querySelector(".btn-roles");
      btnRoles.addEventListener("click", () => {
        editor.hidden = !editor.hidden;
        btnRoles.setAttribute("aria-expanded", String(!editor.hidden));
        btnRoles.textContent = editor.hidden ? t("matches.edit_roles") : t("matches.close_editor");
      });

      card.querySelector(".btn-save-roles").addEventListener("click", async (e) => {
        const positions = {};
        editor.querySelectorAll("select[data-player]").forEach(sel => {
          if (sel.value !== sel.dataset.original)
            positions[sel.dataset.player] = sel.value === "" ? null : sel.value;
        });
        if (!Object.keys(positions).length) { toast(t("matches.no_changes"), "warn"); return; }
        const btn = e.target;
        btn.disabled = true;
        btn.textContent = t("common.saving");
        try {
          const res = await api(`/matches/${m.id}/positions`, { method: "PUT", body: { positions } });
          toast(t("matches.roles_saved", { updated: res.updated, replayed: res.role_matches_replayed }), "ok");
          state.roster = []; // rol ratingleri değişti → roster önbelleği geçersiz
          loadMatches().catch(err => toast(err.message));
        } catch (err) {
          btn.disabled = false;
          btn.textContent = t("matches.save_roles");
          toast(err.message);
        }
      });

      if (!voided) {
        card.querySelector(".btn-void").addEventListener("click", async (e) => {
          const ok = confirm(t("matches.void_confirm"));
          if (!ok) return;
          e.target.disabled = true;
          try {
            await api(`/matches/${m.id}/void`, { method: "POST" });
            toast(t("matches.void_done"), "ok");
            loadMatches().catch(err => toast(err.message));
          } catch (err) {
            e.target.disabled = false;
            toast(err.message);
          }
        });
      }
      box.appendChild(card);
    }
    // Portrelerin 404/geçici hata yolu (tek retry → yer tutucu) build satırlarıyla
    // aynı yardımcıdan gelir; tüm kartlar eklendikten sonra bir kez bağlanır.
    ddBindImages(box);
  }

  // ── 3b) Maç detayı (GÖREV 8) ──────────────────────────────────
  // Yeni endpoint YOK: veri, Geçmiş ekranının zaten çektiği GET /matches
  // yanıtındaki `participants[].stats` alanından gelir; kart tıklanınca o maç
  // nesnesi state'e konur ve görünüm ondan çizilir (yeniden istek atılmaz).
  //
  // Gösterim (tasarım KS1, GÖREV 9): 4 stat düğmesi (gold / hasar / CS / vizyon)
  // + rol eşleşmeli satırlar (sol mavi = team 100, sağ kırmızı = team 200).
  // Her oyuncu satırında:
  //   (a) karşılıklı bar — ölçek GLOBAL'dir: seçili statta maçtaki 10 oyuncunun
  //       en büyük değeri %100'dür, herkes ona oranlanır; en iyi bar pirinç
  //       çerçeve + parıltı, değeri de ⭐ alır (eşitlikte hepsi alır),
  //   (b) ibre — koridor payı mavi/(mavi+kırmızı); %50 çentikli ray üzerinde
  //       önde olan takımın renginde üçgen iğne (fark <%2 ise nötr gri).
  // TOPLAM satırında bar YOKTUR: iki büyük takım değeri + büyütülmüş takım
  // ibresi. Toplamlar global ölçeğe DAHİL EDİLMEZ (yoksa 10 oyuncu barı
  // toplamın yanında ezilirdi).
  // BUILD (GÖREV 14) düğmelerin İLKİDİR ve bar/ibre çizmez: aynı rol-eşleşmeli
  // satırlarda iki tarafın şampiyon portresi + eşya ikonları gösterilir.
  const MD_STATS = [
    { key: "build", label: "matchdetail.stat_build", build: true },
    { key: "gold", label: "matchdetail.stat_gold", big: true },
    { key: "damage_to_champs", label: "matchdetail.stat_damage", big: true },
    { key: "cs", label: "matchdetail.stat_cs", big: false },
    { key: "vision_score", label: "matchdetail.stat_vision", big: false },
  ];

  // Değerler nullable (contract: stats alanları nullable) → "—" ve 0 genişlikte bar.
  const mdFmt = (stat, v) =>
    v == null ? "—"
      : stat.big ? t("matchdetail.thousands", { n: (v / 1000).toFixed(1) })
      : String(v);
  const mdValue = (p, key) => {
    const v = p && p.stats ? p.stats[key] : null;
    return typeof v === "number" ? v : null;
  };

  // Satır eşleştirme: önce kanonik rol sırasıyla İKİ tarafta da bulunan roller
  // eşlenir (mükerrer rol olursa listede ilk gelen eşlenir), artakalanlar
  // listelenme sırasıyla kalan satırlara düşer ve rol etiketi "?" olur.
  // Canlıda position'ı null/mükerrer olan eski maçlar bu yolu kullanır.
  function mdRows(m) {
    const blue = m.participants.filter(p => p.team === 100);
    const red = m.participants.filter(p => p.team === 200);
    const rows = [];
    for (const role of ROLES) {
      const bi = blue.findIndex(p => p.position === role);
      const ri = red.findIndex(p => p.position === role);
      if (bi === -1 || ri === -1) continue;
      rows.push({ role, blue: blue.splice(bi, 1)[0], red: red.splice(ri, 1)[0] });
    }
    while (blue.length || red.length)
      rows.push({ role: null, blue: blue.shift() || null, red: red.shift() || null });
    return rows;
  }

  // side: {id, name, champ, value} — eşleşmeyen satırda taraf boş olabilir.
  // id = player_id (contract §3 katılımcı alanı): ad düğmesi profili buradan açar.
  const mdSide = (p, key) =>
    p ? { id: p.player_id, name: p.display_name, champ: p.champion, value: mdValue(p, key),
          kda: kdaText(p.stats) }
      : { id: null, name: "—", champ: null, value: null, kda: null };

  // KDA parçası (GÖREV 19) — oyuncu satırı ad hücresinin KALICI parçasıdır:
  // beş sekmenin ortak satır başlığında durur, sekme değişince kaybolmaz.
  // Ayna düzen: mavi tarafta adın/alt yazının SONUNA, kırmızı tarafta BAŞINA
  // eklenir (merkeze en yakın uç). null → boş string (hiç gösterilmez).
  const mdKdaHtml = (kda, side) => !kda ? ""
    : side === "blue" ? ` <span class="md-kda">${kda}</span>`
    : `<span class="md-kda">${kda}</span> `;
  // Takım toplamı: null'lar toplama girmez; hepsi null ise toplam da null'dır.
  const mdTeamSum = (parts, key) => {
    const vals = parts.map(p => mdValue(p, key)).filter(v => v != null);
    return vals.length ? vals.reduce((a, b) => a + b, 0) : null;
  };
  // Global ölçek: yalnız OYUNCU değerleri (toplam hariç), null'lar yok sayılır.
  // Hiç değer yoksa 0 → tüm barlar boş kalır, değerler "—" gösterilir.
  const mdGlobalMax = (m, key) => {
    const vals = m.participants.map(p => mdValue(p, key)).filter(v => v != null);
    return vals.length ? Math.max(...vals) : 0;
  };
  const mdLead = (a, b) => (a != null && a >= (b == null ? -1 : b) ? " lead" : "");

  // İbre: pay = mavi/(mavi+kırmızı), null = 0 sayılır. İki değer de null/0 ise
  // gösterilecek pay yoktur → boş string döner (satır gizlenir).
  function mdGaugeHtml(lv, rv, cls, titleKey) {
    const sum = (lv || 0) + (rv || 0);
    if (sum <= 0) return "";
    const pct = ((lv || 0) / sum) * 100;
    const side = Math.abs(pct - 50) < 2 ? "neutral" : (pct >= 50 ? "blue" : "red");
    const title = t(titleKey, { pct: pct.toFixed(0) });
    return `<div class="${cls}">
          <div class="md-rail"></div><div class="md-notch"></div>
          <div class="md-needle ${side}" style="left:${pct.toFixed(1)}%" title="${esc(title)}"></div>
        </div>`;
  }

  // Satır ortasındaki rol göstergesi: Geçmiş kartlarıyla AYNI resmî simge
  // (ortak posIconHtml). Simge çizilemezse ya da satır eşleşmemişse (role null,
  // etiket "?") eski metin kısaltma aynen kalır. Beş sekme de bunu kullanır.
  const mdRoleHtml = (role) => posIconHtml(role, role ? roleAbbr(role) : "?", "md-role");

  // Satır başlığındaki ad hücresi — BEŞ sekmenin de (build dahil) ortak şablonu.
  // Oyuncu biliniyorsa profile giden GERÇEK düğmedir (Sıralama'daki .name-link
  // deseni: Tab ile odaklanır, Enter/Space çalışır), eşleşmeyen taraf ("—") ve
  // TOPLAM satırı düz metin kalır. Şampiyon alt yazısı tıklama alanına dahildir.
  // inner ZATEN kaçırılmış HTML'dir (esc çağıranda yapılır).
  function mdNameHtml(side, id, inner) {
    if (id == null) return `<span class="md-name ${side}">${inner}</span>`;
    return `<button type="button" class="md-name md-name-btn ${side}" data-player="${id}"` +
      ` title="${esc(t("matchdetail.open_profile"))}"><span class="md-name-txt">${inner}</span></button>`;
  }

  function mdRowHtml(roleHtml, left, right, stat, gmax) {
    const lv = left.value, rv = right.value;
    const width = (v) => (gmax > 0 && v != null ? (v / gmax) * 100 : 0).toFixed(1);
    const isMax = (v) => gmax > 0 && v === gmax;
    // ⭐ yeri HER satırda ayrılır (en iyi değilse görünmez): değer sütunları eşit
    // genişlikte kalır, barlar ve ibre rayları satırdan satıra hizalı durur.
    const star = (on) => on
      ? `<span class="md-star" title="${esc(t("matchdetail.best_title"))}">⭐</span>`
      : `<span class="md-star off" aria-hidden="true">⭐</span>`;
    return `<div class="md-row">
        <div class="md-row-names">
          ${mdNameHtml("blue", left.id,
            esc(left.name) + (left.champ ? ` <span class="md-champ">· ${esc(left.champ)}</span>` : "")
            + mdKdaHtml(left.kda, "blue"))}
          ${roleHtml}
          ${mdNameHtml("red", right.id,
            mdKdaHtml(right.kda, "red")
            + (right.champ ? `<span class="md-champ">${esc(right.champ)} · </span>` : "") + esc(right.name))}
        </div>
        <div class="md-bars">
          <span class="md-val left${mdLead(lv, rv)}">${star(isMax(lv))} ${mdFmt(stat, lv)}</span>
          <div class="md-track">
            <div class="md-half left"><div class="md-fill${isMax(lv) ? " best" : ""}" style="width:${width(lv)}%"></div></div>
            <div class="md-center-line"></div>
            <div class="md-half right"><div class="md-fill${isMax(rv) ? " best" : ""}" style="width:${width(rv)}%"></div></div>
          </div>
          <span class="md-val right${mdLead(rv, lv)}">${mdFmt(stat, rv)} ${star(isMax(rv))}</span>
        </div>
        ${mdGaugeHtml(lv, rv, "md-gauge", "matchdetail.gauge_title")}
      </div>`;
  }

  // TOPLAM: bar yok — yatay karşılaştırmayı iki büyük sayı + takım ibresi yapar.
  // İbre gizlenirse yerine boş bir esnek alan kalır (sayılar kenarlarda durur).
  function mdTotalHtml(m, stat) {
    const bv = mdTeamSum(m.participants.filter(p => p.team === 100), stat.key);
    const rv = mdTeamSum(m.participants.filter(p => p.team === 200), stat.key);
    const gauge = mdGaugeHtml(bv, rv, "md-team-gauge", "matchdetail.team_gauge_title")
      || `<div class="md-team-gauge"></div>`;
    return `<div class="md-row md-total">
        <div class="md-row-names">
          <span class="md-name">&nbsp;</span>
          <span class="md-role">${t("matchdetail.total")}</span>
          <span class="md-name">&nbsp;</span>
        </div>
        <div class="md-team-vals">
          <span class="md-team-val blue${mdLead(bv, rv)}">${mdFmt(stat, bv)}<small>${t("matchdetail.blue_team")}</small></span>
          ${gauge}
          <span class="md-team-val red${mdLead(rv, bv)}">${mdFmt(stat, rv)}<small>${t("matchdetail.red_team")}</small></span>
        </div>
      </div>`;
  }

  // ── Maç detayı: BUILD satırları (GÖREV 14, "mb-" = match build) ──
  // Slot sayısı EOG envanteriyle aynıdır: 6 eşya + son slotta totem. Eksik slotlar
  // boş kutu olarak çizilir ki satırlar hizada kalsın.
  // items alanı üç durumu ayırır (api_contract §3): NULL = bilinmiyor (kısa metin),
  // [] = bilgi var/envanter boş (boş slotlar), dolu dizi = HAM sıra.
  const MB_SLOTS = 7;

  // Ziynet eşyası HER ZAMAN 7. (son) slotta durur. EOG envanteri totemi ortada
  // bırakabiliyor (oyuncu envanterinde nereye düştüyse orada); satırlar arasında
  // göz karşılaştırması yapılabilsin diye görüntü sırası sabitlenir.
  // SADECE GÖRÜNTÜ SIRASIDIR: API/mock verisi ve tooltip içerikleri değişmez.
  // Varlıklar yoksa etiket bilinmez → tahmin YOK, ham sıra aynen korunur.
  // Dönüş dizisinde null = boş kutu (boşluklar totemden ÖNCE, sona doğru toplanır).
  function mbOrderItems(list) {
    if (!DD.items) return list;
    const i = list.findIndex(itemIsTrinket);
    // Totem yoksa ham sıra: 7 eşya da yerinde kalır, eksikler sonda boş kutu olur.
    if (i === -1) return list;
    // Birden çok Trinket etiketli eşya varsa yalnız İLKİ sona taşınır, diğerleri
    // normal sırasında kalır. i çıkarıldığı için rest en fazla MB_SLOTS-1 uzundur.
    const rest = list.slice(0, i).concat(list.slice(i + 1));
    while (rest.length < MB_SLOTS - 1) rest.push(null);
    rest.push(list[i]);
    return rest;
  }

  // Tooltip taşıyan slot: role="img" + tabindex → klavyeyle odaklanır ama
  // TIKLANABİLİR DEĞİLDİR (button değil, bir yere gitmez). Ad/açıklama data-*
  // özniteliklerinde taşınır: tooltip açılırken yeniden çeviri gerekmez.
  const mbSlotHtml = (cls, label, name, desc, icon) =>
    `<span class="mb-slot ${cls}" tabindex="0" role="img" aria-label="${esc(label)}"` +
    ` data-name="${esc(name)}" data-desc="${esc(desc)}">${icon}</span>`;

  function mbItemHtml(id) {
    const name = itemName(id);
    const desc = itemDesc(id);
    // Erişilebilir ad açıklamayı da taşır: tooltip aria-hidden'dır (rozet deseni).
    return mbSlotHtml("mb-item", desc ? name + " — " + desc : name, name, desc,
      ddIconHtml(itemIconSrc(id), itemPh(id), "item"));
  }

  // Sınıf adı "mb-empty"dir, "empty" DEĞİL: global `.empty` (ortalı boş-durum
  // paragrafı, padding: 40px 0) slotu 26x26 yerine 26x82 çiziyor, satırı
  // şişiriyordu. Bu tuzağa dördüncü düşüş (.hl-none / .rb-none / .mc-none).
  const mbEmptySlot = () => `<span class="mb-slot mb-empty" aria-hidden="true"></span>`;

  function mbChampHtml(champ) {
    const name = champ || t("matchdetail.champ_unknown");
    return mbSlotHtml("mb-champ", name, name, "",
      ddIconHtml(champIconSrc(champ), champPh(champ), "champ"));
  }

  function mbSideHtml(p, side) {
    if (!p) return `<div class="mb-side ${side}"></div>`;
    let body;
    if (p.items == null) {
      body = `<span class="mb-none">${t("matchdetail.no_items")}</span>`;
    } else {
      const list = mbOrderItems(Array.isArray(p.items) ? p.items.slice(0, MB_SLOTS) : []);
      const slots = list.map(id => (id == null ? mbEmptySlot() : mbItemHtml(id)));
      while (slots.length < MB_SLOTS) slots.push(mbEmptySlot());
      body = `<span class="mb-items">${slots.join("")}</span>`;
    }
    return `<div class="mb-side ${side}">${mbChampHtml(p.champion)}${body}</div>`;
  }

  // Satır başlığı diğer sekmelerle aynı (ad · rol · ad) — şampiyon adı portrede
  // zaten var, bu yüzden burada tekrarlanmaz.
  function mbRowHtml(roleHtml, blue, red) {
    // Ad hücresi diğer dört sekmeyle AYNI şablondur (mdNameHtml) → profile tık
    // beş sekmede de aynı davranır. KDA da aynı kalıcı parçadır (GÖREV 19):
    // BUILD sekmesinde de görünür, mdRowHtml ile aynı ayna düzende.
    const cell = (p, side) =>
      mdNameHtml(side, p ? p.player_id : null,
        side === "blue"
          ? esc(p ? p.display_name : "—") + mdKdaHtml(p ? kdaText(p.stats) : null, "blue")
          : mdKdaHtml(p ? kdaText(p.stats) : null, "red") + esc(p ? p.display_name : "—"));
    return `<div class="md-row mb-row">
        <div class="md-row-names">
          ${cell(blue, "blue")}
          ${roleHtml}
          ${cell(red, "red")}
        </div>
        <div class="mb-sides">${mbSideHtml(blue, "blue")}${mbSideHtml(red, "red")}</div>
      </div>`;
  }

  // Tooltip: rozet vitrinindeki (pb-tip) desenin aynısı — hover VE odakta açılır,
  // ayrılınca/Esc ile kapanır, kutu kenardan taşarsa ölçülüp içeri çekilir.
  let buildTipOwner = null;

  function openBuildTip(el) {
    if (!el || buildTipOwner === el) return;
    closeBuildTip();
    const name = el.dataset.name || "";
    const desc = el.dataset.desc || "";
    if (!name) return;
    el.insertAdjacentHTML("beforeend",
      `<span class="mb-tip" aria-hidden="true">
         <span class="mb-tip-name">${esc(name)}</span>
         ${desc ? `<span class="mb-tip-desc">${esc(desc)}</span>` : ""}
       </span>`);
    buildTipOwner = el;
    const tip = el.querySelector(".mb-tip");
    const box = el.closest(".mb-graph");
    if (!tip || !box) return;
    const tr = tip.getBoundingClientRect();
    const br = box.getBoundingClientRect();
    const shift = tr.left < br.left ? br.left - tr.left
      : tr.right > br.right ? br.right - tr.right : 0;
    if (shift) tip.style.marginLeft = Math.round(shift) + "px";
  }

  function closeBuildTip() {
    const tip = document.querySelector(".mb-tip");
    if (tip) tip.remove();
    buildTipOwner = null;
  }

  function matchDetailHtml(m) {
    const stat = MD_STATS.find(s => s.key === state.matchStat) || MD_STATS[0];
    const voided = m.status === "void";
    // Void maç kazananını değil void rozetini taşır (Geçmiş kartıyla aynı kural).
    const outcome = voided
      ? `<span class="md-void">${t("matches.void_badge")}</span>`
      : `<span class="${m.winner_team === 100 ? "win-blue" : "win-red"}">${
          m.winner_team === 100 ? t("matches.win_blue") : t("matches.win_red")}</span>`;
    const head =
      `<header class="md-head">
         <div class="md-title">${t("matchdetail.title", { id: m.id })} — ${outcome}</div>
         <div class="md-meta">${fmtDate(m.played_at)} · ${fmtDuration(m.duration_s)}</div>
       </header>`;
    const statbar =
      `<div class="md-statbar">` +
      MD_STATS.map(s =>
        `<button type="button" class="md-statbtn${s.key === stat.key ? " active" : ""}" data-stat="${s.key}">${t(s.label)}</button>`
      ).join("") + `</div>`;
    // BUILD: bar/ibre/TOPLAM yok, gösterge yerine ikon satırları (GÖREV 14).
    if (stat.build) {
      const buildRows = mdRows(m)
        .map(r => mbRowHtml(mdRoleHtml(r.role), r.blue, r.red)).join("");
      return head + statbar + `<div class="md-graph mb-graph">${buildRows}</div>` +
        `<p class="md-hint">${t("matchdetail.build_hint")}</p>`;
    }
    const gmax = mdGlobalMax(m, stat.key);
    const rows = mdRows(m).map(r =>
      mdRowHtml(mdRoleHtml(r.role), mdSide(r.blue, stat.key), mdSide(r.red, stat.key), stat, gmax)
    ).join("");
    const keys =
      `<div class="md-keys">
         <span><i class="md-sw blue"></i>${t("common.blue")}</span>
         <span><i class="md-sw red"></i>${t("common.red")}</span>
         <span><span class="md-star">⭐</span> ${t("matchdetail.legend_best")}</span>
         <span><span class="md-key-needle">▼</span> ${t("matchdetail.legend_gauge")}</span>
       </div>`;
    return head + statbar + `<div class="md-graph">${rows}${mdTotalHtml(m, stat)}</div>` +
      keys + `<p class="md-hint">${t("matchdetail.hint")}</p>`;
  }

  // from: detayın hangi görünümden açıldığı — "matches" (Geçmiş kartı) ya da
  // "profile" (GÖREV 10: rating tarihçesi grafiğindeki nokta). Geri düğmesi ve
  // yanan sekme (tabOf) buna bakar.
  function openMatchDetail(m, from) {
    // Profilden geliniyorsa profilin bağlamı (kim, kendi geri hedefi, grafik
    // aralığı) yığına konur: detayın geri düğmesi TAM o profile döner (GÖREV 15).
    if (from === "profile") pushBack(profileFrame());
    else clearBack();   // Geçmiş kartı: yeni zincirin başı
    state.matchDetail = m;
    state.matchFrom = from === "profile" ? "profile" : "matches";
    showView("matchdetail");
  }
  $("#btn-matchdetail-back").addEventListener("click", () => {
    if (state.matchFrom === "profile") { goBack("profile", "leaderboard"); return; }
    clearBack();
    showView(state.matchFrom);
  });

  // Geri düğmesi metni burada yazılır → dil değişiminde de kendiliğinden tazelenir.
  async function loadMatchDetail() {
    $("#btn-matchdetail-back").textContent =
      t(state.matchFrom === "profile" ? "common.back_profile" : "common.back_matches");
    const box = $("#matchdetail-body");
    const m = state.matchDetail;
    closeBuildTip();   // yeniden çizim açık tooltip'in düğümünü siler
    if (!m) {
      box.innerHTML = `<p class='empty'>${t("matchdetail.no_match")}</p>`;
      return;
    }
    // Varlık sözlükleri bir kez yüklenir; yoksa yer tutucu modunda çizilir (GÖREV 14).
    await loadAssets();
    box.innerHTML = matchDetailHtml(m);
    ddBindImages(box);
    bindBuildTips(box);
    // Stat değişimi salt gösterimdir: istek atılmaz, aynı maç nesnesi yeniden çizilir.
    box.querySelectorAll(".md-statbtn").forEach(btn =>
      btn.addEventListener("click", () => {
        state.matchStat = btn.dataset.stat;
        loadMatchDetail();
      }));
    // Satır başlığındaki ad → o oyuncunun profili (GÖREV 15). "matchdetail"
    // kaynağı geri zincirine bu maçın bağlamını koydurur.
    box.querySelectorAll(".md-name-btn").forEach(btn =>
      btn.addEventListener("click", () => openProfile(Number(btn.dataset.player), "matchdetail")));
  }

  // Fare ve klavye aynı tooltip'i açar; ayrılmak (mouseleave/blur) kapatır.
  // Açma "toggle" DEĞİLDİR: fare tıklamasında focus+click ard arda gelir, toggle
  // olsaydı tooltip açılıp hemen kapanırdı (rozet vitrinindeki ders).
  function bindBuildTips(root) {
    root.querySelectorAll(".mb-slot[tabindex]").forEach(el => {
      const close = () => { if (buildTipOwner === el) closeBuildTip(); };
      el.addEventListener("mouseenter", () => openBuildTip(el));
      el.addEventListener("mouseleave", close);
      el.addEventListener("focus", () => openBuildTip(el));
      el.addEventListener("blur", close);
    });
  }

  // ── 4) Collector sağlığı (GÖREV 13; GÖREV 20 ile kendi sekmesine taşındı) ──
  // Veri: GET /health/collectors (api_contract §6). Normal sekme gibi çözülür
  // (META deseni, GÖREV 17), geri düğmesi yoktur. Otomatik polling YOK —
  // görünüm açılınca bir kez çekilir, "Yenile" elle tazeler (basit kalsın;
  // heartbeat aralığı zaten dakikalar mertebesinde).
  //
  // EŞİKLER UI SABİTİDİR: contract'ta yoktur, backend bu ayrımı bilmez. Değişirse
  // yalnız burası değişir (yanıt şekli aynı kalır).
  //   < 15 dk → çevrimiçi · < 24 sa → bugün görüldü · ≥ 24 sa → uzun süredir yok
  // Renk TEK BAŞINA taşıyıcı değildir: üç durumun üçünde de durum METNİ değişir
  // (nokta rengi yalnız aynı bilgiyi tekrarlar).
  const CH_ONLINE_MS = 15 * 60 * 1000;      // "çevrimiçi" eşiği (UI sabiti)
  const CH_TODAY_MS = 24 * 60 * 60 * 1000;  // "bugün görüldü" eşiği (UI sabiti)

  // Çoğul kuralı sözlüktedir: <base>_one / <base>_other. İngilizce'de "1 minute
  // ago" ≠ "3 minutes ago"; Türkçe'de iki anahtar da aynı metni taşır.
  const chPlural = (base, n) => t(base + (n === 1 ? "_one" : "_other"), { n });

  // Göreli zaman: "az önce" / "3 dk önce" / "2 sa önce" / "3 gün önce".
  // Bozuk/eksik zaman damgası → "bilinmiyor" (uydurma bir süre gösterilmez).
  function chAgo(iso) {
    const ms = Date.now() - Date.parse(iso);
    if (isNaN(ms)) return t("health.unknown");
    if (ms < 60 * 1000) return t("health.ago_now");
    if (ms < 60 * 60 * 1000) return chPlural("health.ago_min", Math.floor(ms / 60000));
    if (ms < CH_TODAY_MS) return chPlural("health.ago_hour", Math.floor(ms / 3600000));
    return chPlural("health.ago_day", Math.floor(ms / CH_TODAY_MS));
  }

  function chStatus(iso) {
    const ms = Date.now() - Date.parse(iso);
    if (isNaN(ms)) return { cls: "unknown", label: t("health.status_unknown") };
    if (ms < CH_ONLINE_MS) return { cls: "online", label: t("health.status_online") };
    if (ms < CH_TODAY_MS) return { cls: "today", label: t("health.status_today") };
    return { cls: "stale", label: t("health.status_stale") };
  }

  const chRow = (key, valHtml, cls) =>
    `<div class="ch-row">
       <span class="ch-key">${key}</span>
       <span class="ch-val${cls ? " " + cls : ""}">${valHtml}</span>
     </div>`;

  // d = /health/collectors listesinin bir elemanı. version / outbox_pending /
  // last_ingest_* contract'ta nullable → her biri ayrı ayrı soluk metne düşer.
  function chCard(d) {
    const st = chStatus(d.last_seen);
    const pending = typeof d.outbox_pending === "number" ? d.outbox_pending : null;
    const outbox = pending == null ? { cls: "dim", text: t("health.unknown") }
      : pending > 0 ? { cls: "warn", text: chPlural("health.outbox_pending", pending) }
      : { cls: "dim", text: t("health.outbox_none") };
    // game_id küçük mono: sayı dizisi gövde fontunda okunmuyor, ayrıca bu bir
    // kimliktir (metin değil) — kopyalanıp log'da aranır.
    const ingest = d.last_ingest_at
      ? chAgo(d.last_ingest_at) +
        (d.last_ingest_game_id ? `<span class="ch-gid">#${esc(d.last_ingest_game_id)}</span>` : "")
      : t("health.no_ingest");
    return `<article class="ch-card ${st.cls}">
        <header class="ch-head">
          <span class="ch-name">${esc(d.client_id)}</span>
          <span class="ch-status ${st.cls}"><i class="ch-dot" aria-hidden="true"></i>${st.label}</span>
        </header>
        ${chRow(t("health.last_seen"), chAgo(d.last_seen))}
        ${chRow(t("health.version"), d.version ? esc(d.version) : t("health.unknown"),
                d.version ? "" : "dim")}
        ${chRow(t("health.outbox"), outbox.text, outbox.cls)}
        ${chRow(t("health.last_ingest"), ingest, d.last_ingest_at ? "" : "dim")}
      </article>`;
  }

  async function loadHealth() {
    const box = $("#health-body");
    const btn = $("#btn-health-refresh");
    const count = $("#health-count");
    box.innerHTML = `<p class='empty'>${t("common.loading")}</p>`;
    count.textContent = "";
    btn.disabled = true;
    btn.textContent = t("health.refreshing");
    let list;
    try {
      list = await api("/health/collectors");
    } catch (e) {
      // Bu görünümün TEK içeriği cihaz listesidir: uç düşerse ekran boş kalmaz,
      // ne olduğu ve ne yapılacağı yazılı durur (toast'ı showView ayrıca atar).
      box.innerHTML = `<div class="ch-error">
          <p class="ch-err-title">${t("health.error_title")}</p>
          <p class="ch-err-detail">${esc(e.message)}</p>
          <p class="ch-err-hint">${t("health.error_hint")}</p>
        </div>`;
      throw e;
    } finally {
      btn.disabled = false;
      btn.textContent = t("health.refresh");
    }
    // Sıralamayı backend verir (contract §6: last_seen azalan) — UI yeniden SIRALAMAZ.
    const devices = Array.isArray(list) ? list : [];
    if (!devices.length) {
      box.innerHTML = `<div class="ch-empty">
          <p class="ch-empty-title">${t("health.empty")}</p>
          <p class="ch-empty-note">${t("health.empty_note")}</p>
        </div>`;
      return;
    }
    count.textContent = chPlural("health.devices", devices.length);
    box.innerHTML = `<div class="ch-list">${devices.map(chCard).join("")}</div>`;
  }

  // Elle yenileme: görünüm zaten açık, sekme değiştirmeden aynı yükleyici koşar.
  $("#btn-health-refresh").addEventListener("click", () =>
    loadHealth().catch(e => toast(e.message)));

  // ── Dil (GÖREV 6) ─────────────────────────────────────────────
  // Panelin alt bloğundaki düğme (GÖREV 17'de sağ üstten taşındı) hedef dili
  // gösterir (sözlük değeri: tr'de "EN", en'de "TR");
  // apply() data-i18n taşıdığı için metni de kendiliğinden günceller.
  $("#btn-lang").addEventListener("click", () =>
    window.I18n.setLang(window.I18n.getLang() === "tr" ? "en" : "tr"));
  // Dil değişince: statik data-i18n düğümlerini core.js apply() zaten çevirdi;
  // JS'in kurduğu içerik aktif görünüm yeniden çizilerek tazelenir, sekmesiz
  // görünümlerin geri düğmeleri state'ten yeniden yazılır.
  window.I18n.subscribe(() => {
    $("#btn-profile-back").textContent = backLabel(state.profileFrom);
    $("#btn-map-back").textContent = backLabel(state.mapFrom);
    showView(currentView);
  });

  // ── Başlangıç ─────────────────────────────────────────────────
  if (!state.apiKey) openKeyModal();
  // Deep-link: adres #faq ya da #faq/<slug> ise doğrudan o SSS görünümü açılır
  // (paylaşılan link ilk açılışta da çalışır); değilse varsayılan görünüm.
  if (!faqRouteFromHash()) showView("balance");
})();
