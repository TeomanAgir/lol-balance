// app.js — api_contract.md'nin ince istemcisi. İş mantığı yok: rating, dengeleme,
// doğrulama tamamı backend'de; burada yalnızca seçim/gösterim var.
(function () {
  "use strict";

  const CONFIG = window.APP_CONFIG;
  const $ = (sel) => document.querySelector(sel);

  const state = {
    apiKey: localStorage.getItem("apiKey") || "",
    roster: [],                 // GET /players sonucu
    selected: new Set(),        // dengeleme seçimi (player_id)
    manualTeams: new Map(),     // manuel giriş: player_id -> 100 | 200
    profileId: null,            // açık olan oyuncu profili (GÖREV 1)
    profileFrom: "leaderboard", // profil hangi görünümden açıldı (sıralama | enler)
    nemesis: null,              // son GET /nemesis yanıtı (GÖREV 3)
    nemesisMode: null,          // açık nemesis modu: {source, role, players:[{player_id, display_name}]}
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
      throw new Error("Sunucuya ulaşılamadı. Backend çalışıyor mu?");
    }
    if (res.status === 401) {
      openKeyModal();
      throw new Error("API anahtarı reddedildi, yeniden gir.");
    }
    if (!res.ok) {
      let detail = "";
      try { detail = (await res.json()).detail; } catch { /* gövde JSON değil */ }
      // status hata nesnesinde taşınır: çağıran yer duruma göre davranabilsin
      // (ör. nemesis modunda 409 = aktif çift kalmadı → modu kapat).
      const e = new Error(detail || `Beklenmeyen hata (HTTP ${res.status}).`);
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
      : `W/L ${fmtRating(r.ordinal)} · Perf ${r.perf_avg.toFixed(2)}`;
  const fmtDelta = (d) => (d >= 0 ? "+" : "−") + Math.abs(d).toFixed(1);
  // Haftanın enleri delta'sı contract'ta 2 ondalıklı gelir ("+2.31") — o hassasiyet korunur.
  const fmtDelta2 = (d) => (d >= 0 ? "+" : "−") + Math.abs(d).toFixed(2);
  const fmtDate = (iso) =>
    new Date(iso).toLocaleString("tr-TR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const fmtDuration = (s) => (s == null ? "—" : Math.round(s / 60) + " dk");
  // innerHTML'e giren serbest metin (oyuncu adı, riot_id, şampiyon, hata detayı) için.
  const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ESC[c]);
  const playerName = (id) => {
    const p = state.roster.find(x => x.id === id);
    return p ? p.display_name : "#" + id;
  };

  // ── Roller (GÖREV 0) ──────────────────────────────────────────
  // Sıra contract'taki kanonik sıradır; gösterim her yerde bu sırayı izler.
  const ROLES = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"];
  const ROLE_TR = { TOP: "Üst", JUNGLE: "Orman", MIDDLE: "Orta", BOTTOM: "Alt", UTILITY: "Destek" };
  const ROLE_ABBR = { TOP: "ÜST", JUNGLE: "ORM", MIDDLE: "ORT", BOTTOM: "ALT", UTILITY: "DES" };
  const roleLabel = (pos) => (pos == null ? "—" : ROLE_TR[pos] || pos);
  const roleOrder = (pos) => { const i = ROLES.indexOf(pos); return i === -1 ? ROLES.length : i; };

  // role_ratings kompakt şeridi. long=true → geniş yerleşim (sıralama tablosu).
  // matches === 0 olan rol soluk gösterilir (default prior, gerçek veri değil).
  function roleCells(rr, long = false) {
    if (!rr) return ""; // backend eski şekli dönüyorsa şerit hiç çizilmez
    const cells = ROLES.map(r => {
      const v = rr[r];
      if (!v || typeof v.score !== "number") return "";
      const zero = !v.matches;
      const title = `${ROLE_TR[r]} · ${fmtRating(v.score)} puan · ${v.matches} maç`;
      return `<div class="role-cell${zero ? " zero" : ""}" title="${title}">
          <span class="rc-role">${long ? ROLE_TR[r] : ROLE_ABBR[r]}</span>
          <span class="rc-score">${fmtRating(v.score)}</span>
          <span class="rc-matches">${v.matches}${long ? " maç" : ""}</span>
        </div>`;
    }).join("");
    return cells ? `<div class="role-strip${long ? " long" : ""}">${cells}</div>` : "";
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
  $("#btn-key").addEventListener("click", openKeyModal);

  // ── Sekme yönlendirme ─────────────────────────────────────────
  const loaders = {
    balance: loadBalance, leaderboard: loadLeaderboard, highlights: loadHighlights,
    matches: loadMatches, manual: loadManual, profile: loadProfile,
  };
  // Sekmesi olmayan "detay" görünümü (GÖREV 1: profil) hangi sekmeyi aktif tutar.
  // Profil iki yerden açılır (sıralama, enler) → geldiği görünümün sekmesi yanar.
  const tabOf = (name) => (name === "profile" ? state.profileFrom : name);
  let currentView = "balance";

  function showView(name, forceReload = false) {
    currentView = name;
    const tab = tabOf(name);
    document.querySelectorAll(".view").forEach(v => { v.hidden = v.id !== "view-" + name; });
    document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.view === tab));
    window.scrollTo({ top: 0 });
    loaders[name](forceReload).catch(e => toast(e.message));
  }
  document.querySelectorAll(".tab").forEach(t =>
    t.addEventListener("click", () => showView(t.dataset.view)));

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
        `<span class="p-name">${p.display_name}</span>` +
        `<span class="p-meta">${fmtRating(p.rating.score)} · ${p.matches_played} maç</span>` +
        roleCells(p.role_ratings);
      card.addEventListener("click", () => {
        if (state.selected.has(p.id)) state.selected.delete(p.id);
        else if (state.selected.size < 10) state.selected.add(p.id);
        else { toast("En fazla 10 oyuncu seçilebilir.", "warn"); return; }
        card.classList.toggle("selected", state.selected.has(p.id));
        updatePickCounter();
      });
      grid.appendChild(card);
    }
    updatePickCounter();
  }

  function updatePickCounter() {
    const n = state.selected.size;
    $("#pick-counter").innerHTML = `${n}<span>/10 seçildi</span>`;
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
    $("#nem-mode-pair").textContent =
      `${a.display_name} vs ${b.display_name} — ${roleLabel(nm.role)}`;
    const missing = nm.players.filter(x => !state.selected.has(x.player_id));
    const hint = $("#nem-mode-hint");
    hint.textContent = missing.length
      ? `Çiftin ikisi de seçili olmalı — eksik: ${missing.map(x => x.display_name).join(", ")}`
      : "Çift karşı takımlara ayrılıp bu koridora sabitlenecek.";
    hint.classList.toggle("warn", missing.length > 0);
  }

  function startNemesisMode(n) {
    const pair = n && n.active ? n[n.active] : null;
    if (!pair) { toast("Aktif nemesis çifti yok.", "warn"); return; }
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
    btn.textContent = "Hesaplanıyor…";
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
        toast(e.message + " Nemesis modu kapatıldı.");
      } else {
        toast(e.message);
      }
    } finally {
      btn.textContent = "Dengele";
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
                `<span class="pos-tag">${roleLabel(m.position)}</span>` +
                `<span class="p-who">${playerName(m.player_id)}</span></li>`)
      .join("") + "</ul>";

  // nemesis: yalnız POST /balance/nemesis yanıtında gelir ({source, role, player_ids}) —
  // öneri çizimi aynıdır, çiftin satırları vurgulanır.
  function renderSuggestions(suggestions, nemesis) {
    const box = $("#suggestions");
    const nemIds = nemesis ? new Set(nemesis.player_ids) : null;
    box.innerHTML = "<h2 class='sug-title'>Öneriler</h2>" +
      (nemesis && suggestions.length
        ? `<p class="sug-note">Nemesis maçı: ` +
          `${esc(nemesis.player_ids.map(playerName).join(" vs "))} — ` +
          `${roleLabel(nemesis.role)} (${nemesis.source === "weekly" ? "bu haftanın çifti" : "tüm zamanların çifti"})</p>`
        : "");
    suggestions.forEach((s, i) => {
      const best = i === 0;
      const bluePct = Math.round(s.p_win_team_100 * 100);
      const card = document.createElement("article");
      card.className = "sug-card" + (best ? " best" : "");
      card.innerHTML =
        (best ? `<div class="best-badge">En dengeli</div>` : "") +
        `<div class="sug-teams">
           ${teamList(s.team_100, "blue", nemIds)}
           <div class="sug-mid">
             <div class="quality">%${(s.quality * 100).toFixed(1)}</div>
             <div class="quality-label">denge</div>
           </div>
           ${teamList(s.team_200, "red", nemIds)}
         </div>
         <div class="winbar" role="img" aria-label="Mavi taraf kazanma olasılığı %${bluePct}">
           <div class="winbar-blue" style="width:${bluePct}%"></div>
         </div>
         <div class="winbar-caption"><span>Mavi %${bluePct}</span><span>Kırmızı %${100 - bluePct}</span></div>`;
      box.appendChild(card);
    });
    box.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // ── 2) Leaderboard ────────────────────────────────────────────
  // Oyuncu adı artık profili açar (GÖREV 1). Eski satır-içi rol açılırı kaldırıldı:
  // rol şeridi profilde daha geniş biçimde zaten var, iki ayrı açılır tekrar olurdu.
  async function loadLeaderboard() {
    const rows = await api("/leaderboard"); // backend score'a göre sıralı döner
    const body = $("#board-body");
    body.innerHTML = rows.map((p, i) => {
      const sub = ratingSub(p.rating);
      return `<tr>
         <td class="rank">${i + 1}</td>
         <td><button type="button" class="name-link" data-player="${p.id}">${esc(p.display_name)}</button></td>
         <td class="num strong">${fmtRating(p.rating.score)}${sub ? `<span class="rating-sub">${sub}</span>` : ""}</td>
         <td class="num">${p.matches_played}</td>
       </tr>`;
    }).join("");

    body.querySelectorAll(".name-link").forEach(btn =>
      btn.addEventListener("click", () => openProfile(Number(btn.dataset.player))));
  }

  // ── 2b) Oyuncu profili (GÖREV 1) ──────────────────────────────
  // Alt sekmelerin dışında bir "detay" görünümü: sıralamadan açılır, geri döner.
  const BACK_LABEL = { leaderboard: "← Sıralamaya dön", highlights: "← Enlere dön" };

  function openProfile(id) {
    state.profileId = id;
    // Profilden profile geçilebilir (sinerji linkleri) — çıkış noktası ilk giriş yeridir.
    if (currentView !== "profile") state.profileFrom = currentView;
    $("#btn-profile-back").textContent = BACK_LABEL[state.profileFrom] || BACK_LABEL.leaderboard;
    showView("profile");
  }
  $("#btn-profile-back").addEventListener("click", () => showView(state.profileFrom));

  const num1 = (x) => (typeof x === "number" ? x.toFixed(1) : "—");
  const num2 = (x) => (typeof x === "number" ? x.toFixed(2) : "—");
  // winrate contract'ta 0..1 oran ve null olabilir.
  const pctText = (x) => (typeof x === "number" ? "%" + Math.round(x * 100) : "—");

  const statCard = (title, main, sub) =>
    `<article class="stat-card">
       <h3 class="sc-title">${title}</h3>
       <div class="sc-main">${main}</div>
       ${sub ? `<div class="sc-sub">${sub}</div>` : ""}
     </article>`;

  // s = GET /players/{id}/stats yanıtı. kda / favoriler null, synergy boş,
  // winrate null olabilir — hepsi kısa notla gösterilir.
  function profileHtml(s) {
    const p = s.player || {};
    const rp = state.roster.find(x => x.id === p.id); // rol şeridi + puan roster'dan
    const t = s.totals || {};
    const played = t.matches || 0;
    const k = s.kda, fc = s.favorite_champion, fr = s.favorite_role;
    const syn = s.synergy || [];

    const head =
      `<header class="prof-head">
         <h2 class="prof-name">${esc(p.display_name)}</h2>
         ${p.riot_id ? `<span class="prof-riot">${esc(p.riot_id)}</span>` : ""}
         ${rp ? `<div class="prof-score">${fmtRating(rp.rating.score)}<span>puan</span></div>` : ""}
       </header>`;

    const cards =
      statCard("Maç & W/L",
        played ? `${played} maç · ${t.wins}G ${t.losses}M` : "Henüz maç yok",
        played && t.winrate != null ? `${pctText(t.winrate)} galibiyet` : "") +
      statCard("Ortalama KDA",
        k ? `${num1(k.kills_avg)} / ${num1(k.deaths_avg)} / ${num1(k.assists_avg)}` : "—",
        k ? `${num2(k.ratio)} KDA` : "İstatistikli maç yok") +
      statCard("Favori karakter",
        fc ? esc(fc.champion) : "—",
        fc ? `${fc.matches} maç · ${pctText(fc.winrate)} galibiyet` : "Şampiyon verisi yok") +
      statCard("Favori koridor",
        fr ? roleLabel(fr.role) : "—",
        fr ? `${fr.matches} maç` : "Rol verisi yok");

    const strip = rp ? roleCells(rp.role_ratings, true) : "";
    const roleSec = strip
      ? `<section class="prof-section"><h3 class="ps-title">Rol ratingleri</h3>${strip}</section>`
      : "";

    const synMeta = (x) =>
      `<span class="syn-meta">${x.matches_together} ortak maç · ${pctText(x.winrate)} galibiyet</span>`;
    const synLink = (x, cls) =>
      `<button type="button" class="syn-link${cls ? " " + cls : ""}" data-player="${x.player_id}">${esc(x.display_name)}</button>`;
    const synSec =
      `<section class="prof-section">
         <h3 class="ps-title">En yüksek sinerji</h3>` +
      (syn.length
        ? `<div class="syn-top">${synLink(syn[0], "syn-name")}${synMeta(syn[0])}</div>` +
          (syn.length > 1
            ? `<ul class="syn-rest">` +
              syn.slice(1).map(x => `<li>${synLink(x)}${synMeta(x)}</li>`).join("") +
              `</ul>`
            : "")
        : `<p class="ps-empty">En az 2 ortak maç gerekiyor.</p>`) +
      `</section>`;

    return head + `<div class="stat-grid">${cards}</div>` + roleSec + synSec;
  }

  async function loadProfile() {
    const box = $("#profile-body");
    if (state.profileId == null) {
      box.innerHTML = "<p class='empty'>Oyuncu seçilmedi.</p>";
      return;
    }
    box.innerHTML = "<p class='empty'>Yükleniyor…</p>";
    try {
      await fetchRoster(); // rol şeridi + puan için; önbellekliyse istek gitmez
      const s = await api(`/players/${state.profileId}/stats`);
      box.innerHTML = profileHtml(s);
      // Sinerji listesindeki isimler o oyuncunun profiline geçer.
      box.querySelectorAll(".syn-link").forEach(btn =>
        btn.addEventListener("click", () => openProfile(Number(btn.dataset.player))));
    } catch (e) {
      box.innerHTML = `<p class='empty'>${esc(e.message)}</p>`;
      throw e; // toast'ı showView gösterir
    }
  }

  // ── 2c) Haftanın enleri (GÖREV 2) ─────────────────────────────
  // Salt-okur ekran: GET /highlights/weekly. Contract'taki her alan null olabilir;
  // dolu kartlar tıklanabilir (profile gider), null kartlar soluk "—" olarak kalır.

  // Pencere metni: "5–12 Ağu arası"; ay sınırını aşarsa "29 Tem – 5 Ağu arası".
  function windowText(w) {
    const s = new Date(w.start), e = new Date(w.end);
    if (isNaN(s) || isNaN(e)) return "";
    const day = (d) => d.toLocaleDateString("tr-TR", { day: "numeric" });
    const mon = (d) => d.toLocaleDateString("tr-TR", { month: "short" });
    return s.getFullYear() === e.getFullYear() && s.getMonth() === e.getMonth()
      ? `${day(s)}–${day(e)} ${mon(e)} arası`
      : `${day(s)} ${mon(s)} – ${day(e)} ${mon(e)} arası`;
  }

  // Büyük kartlar (haftanın oyuncusu / yıldız rukisi). d null ise dokunma hedefi
  // üretilmez: <button> yerine soluk <div> çizilir.
  function hlCard(cls, label, d, valueHtml) {
    if (!d) {
      return `<div class="hl-card ${cls} hl-none">
          <span class="hl-label">${label}</span>
          <span class="hl-name">—</span>
          <span class="hl-sub">Pencerede maç yok</span>
        </div>`;
    }
    return `<button type="button" class="hl-card ${cls}" data-player="${d.player_id}">
        <span class="hl-label">${label}</span>
        <span class="hl-name">${esc(d.display_name)}</span>
        ${valueHtml}
        <span class="hl-sub">pencerede ${d.matches_in_window} maç</span>
      </button>`;
  }

  // Rol kartı: etiket ROLE_TR adıdır; d null ise o rolde pencerede kimse oynamamıştır.
  function hlRoleCard(role, d) {
    const label = `<span class="hl-label">${ROLE_TR[role]}</span>`;
    if (!d) {
      return `<div class="hl-role hl-none">${label}
          <span class="hl-name">—</span>
          <span class="hl-sub">oynanmadı</span>
        </div>`;
    }
    return `<button type="button" class="hl-role" data-player="${d.player_id}">${label}
        <span class="hl-name">${esc(d.display_name)}</span>
        <span class="hl-value">${num1(d.score)}</span>
        <span class="hl-sub">${d.matches_in_window} maç</span>
      </button>`;
  }

  // ── 2d) Nemesis (GÖREV 3) ─────────────────────────────────────
  // GET /nemesis: (çift, rol) adaylarından en başa baş geçen rekabet. Ekranda
  // TÜM ZAMANLARIN çifti büyük gösterilir; weekly farklıysa tek satır not düşülür.
  // Maç kurma her zaman `active` çiftle olur — hangisi olduğu ekranda işaretlenir.
  const nemKey = (p) =>
    p ? p.role + ":" + p.players.map(x => x.player_id).sort((a, b) => a - b).join("-") : "";
  const nemPct = (c) => "%" + Math.round((c || 0) * 100);
  const nemLink = (x, cls) =>
    `<button type="button" class="${cls}" data-player="${x.player_id}">${esc(x.display_name)}</button>`;

  function nemesisCard(pair, isActive) {
    const [a, b] = pair.players;
    return `<div class="nem-card">
        ${nemLink(a, "nem-who")}
        <div class="nem-mid">
          <span class="nem-role">${roleLabel(pair.role)}</span>
          <span class="nem-score">${a.wins}–${b.wins}</span>
          <span class="nem-sub">${pair.encounters} karşılaşma</span>
        </div>
        ${nemLink(b, "nem-who")}
      </div>
      <p class="nem-close">${nemPct(pair.closeness)} başa baş${
        isActive ? `<span class="nem-active">maç bu çiftle kurulur</span>` : ""}</p>`;
  }

  // n null ise (backend /nemesis bilmiyor / istek düştü) bölüm hiç çizilmez.
  function nemesisSection(n) {
    if (!n) return "";
    const at = n.all_time, wk = n.weekly;
    let body;
    if (!at) {
      body = `<p class="ps-empty">Nemesis için en az 3 koridor karşılaşması gerekiyor.</p>`;
    } else {
      body = nemesisCard(at, n.active === "all_time");
      if (wk && nemKey(wk) !== nemKey(at)) {
        const [wa, wb] = wk.players;
        body += `<p class="nem-weekly">Bu haftanın çifti: ${nemLink(wa, "nem-link")} vs ` +
          `${nemLink(wb, "nem-link")} — ${roleLabel(wk.role)} · ${wk.encounters} karşılaşma · ` +
          `${nemPct(wk.closeness)} başa baş` +
          (n.active === "weekly" ? `<span class="nem-active">maç bu çiftle kurulur</span>` : "") + `</p>`;
      }
    }
    const btn = n.active
      ? `<button type="button" id="btn-nemesis-setup" class="btn-primary btn-nemesis">Nemesis maçı kur</button>`
      : "";
    return `<section class="prof-section nem-section">
        <h3 class="ps-title">Nemesis</h3>${body}${btn}
      </section>`;
  }

  async function loadHighlights() {
    const box = $("#highlights-body");
    box.innerHTML = "<p class='empty'>Yükleniyor…</p>";
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
        box.innerHTML = "<p class='empty'>Değerlendirilecek maç yok.</p>";
        return;
      }
      const w = h.window || {};
      const head = windowText(w)
        ? `<div class="hl-window">${windowText(w)}` +
          (w.fallback ? `<span class="hl-fb">(son maç haftası)</span>` : "") + `</div>`
        : "";
      const rs = h.rising_star;
      const up = rs && rs.delta >= 0;
      box.innerHTML = head +
        hlCard("hero", "Haftanın Oyuncusu", h.best_player,
          h.best_player
            ? `<span class="hl-value">${num1(h.best_player.score)}<span class="hl-unit">puan</span></span>`
            : "") +
        hlCard("rising", "Yıldız Rukisi", rs,
          rs ? `<span class="hl-value delta ${up ? "up" : "down"}">${fmtDelta2(rs.delta)}</span>` : "") +
        `<section class="prof-section">
           <h3 class="ps-title">Rol enleri</h3>
           <div class="hl-roles">${ROLES.map(r => hlRoleCard(r, roles[r])).join("")}</div>
         </section>` +
        nemesisSection(n);

      // Nemesis bölümündeki isimler de data-player taşır → aynı kayıtla profile gider.
      box.querySelectorAll("button[data-player]").forEach(btn =>
        btn.addEventListener("click", () => openProfile(Number(btn.dataset.player))));
      const setup = box.querySelector("#btn-nemesis-setup");
      if (setup) setup.addEventListener("click", () => startNemesisMode(state.nemesis));
    } catch (e) {
      box.innerHTML = `<p class='empty'>${esc(e.message)}</p>`;
      throw e; // toast'ı showView gösterir
    }
  }

  // ── 3) Maç geçmişi ────────────────────────────────────────────
  async function loadMatches() {
    await fetchRoster();
    const list = await api("/matches?limit=20");
    const box = $("#match-list");
    box.innerHTML = list.length ? "" : "<p class='empty'>Henüz kayıtlı maç yok.</p>";

    for (const m of list) {
      const voided = m.status === "void";
      const teamCol = (team) => {
        const members = m.participants.filter(p => p.team === team)
          .sort((a, b) => roleOrder(a.position) - roleOrder(b.position));
        const won = m.winner_team === team;
        return `<ul class="team ${team === 100 ? "blue" : "red"} ${won ? "won" : ""}">` +
          members.map(p => {
            const rc = p.rating_change; // nullable: void maç / rating satırı yok → delta gösterme
            const deltaHtml = rc
              ? `<span class="delta ${rc.mu_after - rc.mu_before >= 0 ? "up" : "down"}">${fmtDelta(rc.mu_after - rc.mu_before)}</span>`
              : `<span class="delta none">—</span>`;
            return `<li><span class="pos-tag">${roleLabel(p.position)}</span>` +
                   `<span class="p-who">${p.display_name}</span>${deltaHtml}</li>`;
          }).join("") + "</ul>";
      };
      // Rol düzeltme paneli: yalnız DEĞİŞEN roller PUT edilir (kısmi güncelleme serbest).
      const roleEditor = () => {
        const rows = [...m.participants]
          .sort((a, b) => (a.team - b.team) || (roleOrder(a.position) - roleOrder(b.position)))
          .map(p => {
            const cur = p.position == null ? "" : p.position;
            const opts = `<option value=""${cur === "" ? " selected" : ""}>—</option>` +
              ROLES.map(r => `<option value="${r}"${cur === r ? " selected" : ""}>${ROLE_TR[r]}</option>`).join("");
            return `<li class="re-row ${p.team === 100 ? "blue" : "red"}">
                <span class="p-who">${p.display_name}</span>
                <select data-player="${p.player_id}" data-original="${cur}"
                        aria-label="${p.display_name} rolü">${opts}</select>
              </li>`;
          }).join("");
        return `<div class="role-editor" hidden>
            <ul class="re-list">${rows}</ul>
            <button class="btn-primary btn-save-roles" type="button">Rolleri Kaydet</button>
          </div>`;
      };
      const card = document.createElement("article");
      card.className = "match-card" + (voided ? " voided" : "");
      card.innerHTML =
        `<header class="match-head">
           <span>${fmtDate(m.played_at)} · ${fmtDuration(m.duration_s)}</span>
           ${voided
             ? `<span class="void-badge">void</span>`
             : `<span class="win-tag ${m.winner_team === 100 ? "blue" : "red"}">${m.winner_team === 100 ? "Mavi" : "Kırmızı"} kazandı</span>`}
         </header>
         <div class="match-teams">${teamCol(100)}${teamCol(200)}</div>
         <div class="match-actions">
           <button class="btn-roles" type="button" aria-expanded="false">Rolleri düzenle</button>
           ${voided ? "" : `<button class="btn-void" type="button">Maçı void yap</button>`}
         </div>` +
        roleEditor();

      const editor = card.querySelector(".role-editor");
      const btnRoles = card.querySelector(".btn-roles");
      btnRoles.addEventListener("click", () => {
        editor.hidden = !editor.hidden;
        btnRoles.setAttribute("aria-expanded", String(!editor.hidden));
        btnRoles.textContent = editor.hidden ? "Rolleri düzenle" : "Düzenlemeyi kapat";
      });

      card.querySelector(".btn-save-roles").addEventListener("click", async (e) => {
        const positions = {};
        editor.querySelectorAll("select[data-player]").forEach(sel => {
          if (sel.value !== sel.dataset.original)
            positions[sel.dataset.player] = sel.value === "" ? null : sel.value;
        });
        if (!Object.keys(positions).length) { toast("Değişen rol yok.", "warn"); return; }
        const btn = e.target;
        btn.disabled = true;
        btn.textContent = "Kaydediliyor…";
        try {
          const res = await api(`/matches/${m.id}/positions`, { method: "PUT", body: { positions } });
          toast(`${res.updated} rol güncellendi · rol evreninde ${res.role_matches_replayed} maç yeniden işlendi.`, "ok");
          state.roster = []; // rol ratingleri değişti → roster önbelleği geçersiz
          loadMatches().catch(err => toast(err.message));
        } catch (err) {
          btn.disabled = false;
          btn.textContent = "Rolleri Kaydet";
          toast(err.message);
        }
      });

      if (!voided) {
        card.querySelector(".btn-void").addEventListener("click", async (e) => {
          const ok = confirm("Bu maç void işaretlenecek ve tüm rating'ler yeniden hesaplanacak. Bu işlem geri alınamaz. Emin misin?");
          if (!ok) return;
          e.target.disabled = true;
          try {
            await api(`/matches/${m.id}/void`, { method: "POST" });
            toast("Maç void işaretlendi, rating'ler yeniden hesaplanıyor.", "ok");
            loadMatches().catch(err => toast(err.message));
          } catch (err) {
            e.target.disabled = false;
            toast(err.message);
          }
        });
      }
      box.appendChild(card);
    }
  }

  // ── 4) Manuel maç girişi ──────────────────────────────────────
  async function loadManual(force) {
    await fetchRoster(force);
    const box = $("#manual-roster");
    box.innerHTML = "";
    for (const p of state.roster) {
      const row = document.createElement("div");
      row.className = "manual-row";
      row.innerHTML =
        `<span class="p-name">${p.display_name}</span>
         <div class="team-toggle">
           <button type="button" class="tt-blue" aria-pressed="false">Mavi</button>
           <button type="button" class="tt-red" aria-pressed="false">Kırmızı</button>
         </div>`;
      const btnB = row.querySelector(".tt-blue");
      const btnR = row.querySelector(".tt-red");
      const setTeam = (team) => {
        if (state.manualTeams.get(p.id) === team) state.manualTeams.delete(p.id);
        else state.manualTeams.set(p.id, team);
        const cur = state.manualTeams.get(p.id);
        btnB.setAttribute("aria-pressed", cur === 100);
        btnR.setAttribute("aria-pressed", cur === 200);
        updateManualCounter();
      };
      btnB.addEventListener("click", () => setTeam(100));
      btnR.addEventListener("click", () => setTeam(200));
      const cur = state.manualTeams.get(p.id);
      btnB.setAttribute("aria-pressed", cur === 100);
      btnR.setAttribute("aria-pressed", cur === 200);
      box.appendChild(row);
    }
    updateManualCounter();
  }

  function manualCounts() {
    let blue = 0, red = 0;
    for (const t of state.manualTeams.values()) t === 100 ? blue++ : red++;
    return { blue, red };
  }

  function updateManualCounter() {
    const { blue, red } = manualCounts();
    $("#manual-counter").textContent = `Mavi ${blue}/5 · Kırmızı ${red}/5`;
    const winner = document.querySelector("input[name=winner]:checked");
    $("#btn-manual-submit").disabled = !(blue === 5 && red === 5 && winner);
  }
  document.querySelectorAll("input[name=winner]").forEach(r =>
    r.addEventListener("change", updateManualCounter));

  $("#btn-manual-submit").addEventListener("click", async () => {
    const btn = $("#btn-manual-submit");
    const winner = Number(document.querySelector("input[name=winner]:checked").value);
    btn.disabled = true;
    btn.textContent = "Kaydediliyor…";
    try {
      const res = await api("/ingest/match", {
        method: "POST",
        body: {
          source: "manual",
          source_game_id: "manual:" + crypto.randomUUID(),
          played_at: new Date().toISOString(),
          duration_s: null,
          winner_team: winner,
          participants: [...state.manualTeams].map(([player_id, team]) =>
            ({ player_id, team, position: null })),
        },
      });
      toast(res.duplicate ? "Bu maç zaten kayıtlıydı." : "Maç kaydedildi.", "ok");
      state.manualTeams.clear();
      document.querySelectorAll("input[name=winner]").forEach(r => { r.checked = false; });
      loadManual(true).catch(e => toast(e.message));
    } catch (e) {
      toast(e.message);
    } finally {
      btn.textContent = "Maçı kaydet";
      updateManualCounter();
    }
  });

  // ── Başlangıç ─────────────────────────────────────────────────
  if (!state.apiKey) openKeyModal();
  showView("balance");
})();
