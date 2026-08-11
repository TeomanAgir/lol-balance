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
      throw new Error(detail || `Beklenmeyen hata (HTTP ${res.status}).`);
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

  const fmtOrdinal = (o) => o.toFixed(1);
  const fmtDelta = (d) => (d >= 0 ? "+" : "−") + Math.abs(d).toFixed(1);
  const fmtDate = (iso) =>
    new Date(iso).toLocaleString("tr-TR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const fmtDuration = (s) => (s == null ? "—" : Math.round(s / 60) + " dk");
  const playerName = (id) => {
    const p = state.roster.find(x => x.id === id);
    return p ? p.display_name : "#" + id;
  };

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
  const loaders = { balance: loadBalance, leaderboard: loadLeaderboard, matches: loadMatches, manual: loadManual };
  let currentView = "balance";

  function showView(name, forceReload = false) {
    currentView = name;
    document.querySelectorAll(".view").forEach(v => { v.hidden = v.id !== "view-" + name; });
    document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.view === name));
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
    for (const p of state.roster) {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "player-card";
      card.classList.toggle("selected", state.selected.has(p.id));
      card.innerHTML =
        `<span class="p-name">${p.display_name}</span>` +
        `<span class="p-meta">${fmtOrdinal(p.rating.ordinal)} · ${p.matches_played} maç</span>`;
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
  }

  $("#btn-balance").addEventListener("click", async () => {
    const btn = $("#btn-balance");
    btn.disabled = true;
    btn.textContent = "Hesaplanıyor…";
    try {
      const res = await api("/balance", {
        method: "POST",
        body: { player_ids: [...state.selected], top_n: 3 },
      });
      renderSuggestions(res.suggestions);
    } catch (e) {
      toast(e.message);
    } finally {
      btn.textContent = "Dengele";
      btn.disabled = state.selected.size !== 10;
    }
  });

  function renderSuggestions(suggestions) {
    const box = $("#suggestions");
    box.innerHTML = "<h2 class='sug-title'>Öneriler</h2>";
    suggestions.forEach((s, i) => {
      const best = i === 0;
      const bluePct = Math.round(s.p_win_team_100 * 100);
      const card = document.createElement("article");
      card.className = "sug-card" + (best ? " best" : "");
      card.innerHTML =
        (best ? `<div class="best-badge">En dengeli</div>` : "") +
        `<div class="sug-teams">
           <ul class="team blue">${s.team_100.map(id => `<li>${playerName(id)}</li>`).join("")}</ul>
           <div class="sug-mid">
             <div class="quality">%${(s.quality * 100).toFixed(1)}</div>
             <div class="quality-label">denge</div>
           </div>
           <ul class="team red">${s.team_200.map(id => `<li>${playerName(id)}</li>`).join("")}</ul>
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
  async function loadLeaderboard() {
    const rows = await api("/leaderboard");
    $("#board-body").innerHTML = rows.map((p, i) =>
      `<tr>
         <td class="rank">${i + 1}</td>
         <td>${p.display_name}</td>
         <td class="num strong">${fmtOrdinal(p.rating.ordinal)}</td>
         <td class="num">${p.matches_played}</td>
       </tr>`).join("");
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
        const members = m.participants.filter(p => p.team === team);
        const won = m.winner_team === team;
        return `<ul class="team ${team === 100 ? "blue" : "red"} ${won ? "won" : ""}">` +
          members.map(p => {
            const d = p.mu_after - p.mu_before;
            return `<li>${p.display_name}` +
              `<span class="delta ${d >= 0 ? "up" : "down"}">${fmtDelta(d)}</span></li>`;
          }).join("") + "</ul>";
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
         <div class="match-teams">${teamCol(100)}${teamCol(200)}</div>` +
        (voided ? "" : `<button class="btn-void" type="button">Maçı void yap</button>`);
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
