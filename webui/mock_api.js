// mock_api.js — api_contract.md'deki örnek response'ları dönen fetch stub'ı.
// Backend hazır olunca index.html'de USE_MOCK: false yapılır; bu dosya devre dışı kalır.
(function () {
  "use strict";

  // ── Mock roster: 14 kişilik gerçekçi havuz (1 tanesi hiç maç oynamamış) ──
  // rating: harman engine (openskill-pl-blend50-v1) şekli {mu, sigma, ordinal, perf_avg, score}.
  // Yigit ve Selin'de perf_avg null: harman-dışı version durumunun temsili (score = ordinal).
  // Ece hiç maç oynamadı → contract gereği perf_avg = 1.0 (nötr), score ≈ 0.
  const players = [
    { id: 1,  display_name: "Teoman", riot_id: "Teoman#TR1",    matches_played: 24, rating: { mu: 29.4, sigma: 3.1, ordinal: 20.1, perf_avg: 1.12 } },
    { id: 2,  display_name: "Baran",  riot_id: "Baranski#EUW",  matches_played: 22, rating: { mu: 27.8, sigma: 3.3, ordinal: 17.9, perf_avg: 1.05 } },
    { id: 3,  display_name: "Kaan",   riot_id: "KaanMid#TR1",   matches_played: 25, rating: { mu: 26.9, sigma: 3.0, ordinal: 17.9, perf_avg: 1.18 } },
    { id: 4,  display_name: "Emir",   riot_id: "Emir#0000",     matches_played: 19, rating: { mu: 26.2, sigma: 3.5, ordinal: 15.7, perf_avg: 0.97 } },
    { id: 5,  display_name: "Deniz",  riot_id: "DenizJG#TR1",   matches_played: 21, rating: { mu: 25.8, sigma: 3.2, ordinal: 16.2, perf_avg: 1.08 } },
    { id: 6,  display_name: "Mert",   riot_id: "MertADC#TR1",   matches_played: 17, rating: { mu: 25.1, sigma: 3.6, ordinal: 14.3, perf_avg: 1.22 } },
    { id: 7,  display_name: "Arda",   riot_id: "ArdaTop#TR1",   matches_played: 15, rating: { mu: 24.6, sigma: 3.8, ordinal: 13.2, perf_avg: 0.91 } },
    { id: 8,  display_name: "Efe",    riot_id: "EfeSup#TR1",    matches_played: 18, rating: { mu: 24.0, sigma: 3.4, ordinal: 13.8, perf_avg: 1.02 } },
    { id: 9,  display_name: "Cem",    riot_id: "CemW#TR1",      matches_played: 12, rating: { mu: 23.5, sigma: 4.1, ordinal: 11.2, perf_avg: 0.88 } },
    { id: 10, display_name: "Ozan",   riot_id: "OzanKral#TR1",  matches_played: 14, rating: { mu: 23.1, sigma: 3.9, ordinal: 11.4, perf_avg: 1.15 } },
    { id: 11, display_name: "Berk",   riot_id: "Berk#TR2",      matches_played: 9,  rating: { mu: 22.4, sigma: 4.6, ordinal: 8.6, perf_avg: 0.95 } },
    { id: 12, display_name: "Yigit",  riot_id: "Yigit#TR1",     matches_played: 7,  rating: { mu: 21.8, sigma: 5.0, ordinal: 6.8, perf_avg: null } },
    { id: 13, display_name: "Selin",  riot_id: "Selin#SUP",     matches_played: 5,  rating: { mu: 21.0, sigma: 5.5, ordinal: 4.5, perf_avg: null } },
    { id: 14, display_name: "Ece",    riot_id: "Ece#NEW",       matches_played: 0,  rating: { mu: 25.0, sigma: 8.333, ordinal: 0.0, perf_avg: 1.0 } },
  ];

  // Contract formülü (rating_contract.md "Harman Engine"): W=0.5, MU_0=25, K=20.
  // perf_avg null → harman-dışı version: score = ordinal.
  const scoreOf = (r) =>
    r.perf_avg == null
      ? r.ordinal
      : +(0.5 * r.mu + 0.5 * (25 + 20 * (r.perf_avg - 1)) - 3 * r.sigma).toFixed(1);
  players.forEach(p => { p.rating.score = scoreOf(p.rating); });

  const CHAMPS = ["Ahri", "Lee Sin", "Jinx", "Thresh", "Darius", "Yasuo", "Lux", "Ezreal", "Vi", "Orianna"];
  const POS = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"];

  // ── Rol rating evreni (GÖREV 0) ──
  // Contract §2: 5 anahtar HER ZAMAN mevcut; hiç oynanmamış rol default prior döner.
  // Mock'ta her oyuncunun bir ana + bir ikincil rolü maç görmüş, kalan 3 rol default.
  const defaultRole = () => ({ mu: 25.0, sigma: 8.333, perf_avg: 1.0, score: 0.0, matches: 0 });
  const roleScoreOf = (mu, sigma, perf) =>
    +(0.5 * mu + 0.5 * (25 + 20 * (perf - 1)) - 3 * sigma).toFixed(1);

  players.forEach(p => {
    const rr = {};
    POS.forEach((role, i) => {
      const main = i === p.id % 5;
      const second = i === (p.id + 2) % 5;
      const matches = Math.round(p.matches_played * (main ? 0.6 : second ? 0.25 : 0));
      if (!matches) { rr[role] = defaultRole(); return; }
      const mu = +(p.rating.mu + (main ? 0.6 : -0.9)).toFixed(2);
      const sigma = +Math.max(1.5, p.rating.sigma + (main ? 0.4 : 1.8)).toFixed(3);
      const perf = +((p.rating.perf_avg == null ? 1.0 : p.rating.perf_avg) + (main ? 0.04 : -0.06)).toFixed(2);
      rr[role] = { mu, sigma, perf_avg: perf, score: roleScoreOf(mu, sigma, perf), matches };
    });
    p.role_ratings = rr;
  });

  // Rol evreni uygunluğu (rating_contract "Rol Rating Evreni" §3): 10 katılımcının
  // hepsinde position dolu VE her takımda 5 farklı rolden tam 1'er tane.
  const roleEligible = (m) =>
    m.participants.length === 10 &&
    [100, 200].every(team => {
      const set = new Set(m.participants.filter(p => p.team === team).map(p => p.position));
      return set.size === 5 && POS.every(r => set.has(r));
    });

  // Deterministik sahte maç geçmişi üret (Date.now/random'a gerek yok).
  let nextMatchId = 100;
  const matches = [];
  for (let m = 0; m < 8; m++) {
    // Her maçta havuz bir kaydırılır, ilk 10 kişi oynar.
    const uniq = players.map(p => p.id).map((_, i, all) => all[(i + m) % all.length]).slice(0, 10);
    const winner = m % 2 === 0 ? 100 : 200;
    matches.push({
      id: nextMatchId++,
      source_game_id: "687423" + (1900 + m),
      played_at: `2026-08-${String(2 + m).padStart(2, "0")}T2${m % 3}:1${m}:00Z`,
      duration_s: 1500 + m * 137,
      winner_team: winner,
      status: "valid",
      participants: uniq.map((pid, i) => {
        const team = i < 5 ? 100 : 200;
        const won = team === winner;
        const delta = (won ? 1 : -1) * (0.4 + ((pid * 7 + m * 3) % 10) / 12);
        const p = players.find(x => x.id === pid);
        // m === 0 maçında iki katılımcıda rating_change null: UI'ın "—" yolu test edilebilsin.
        const noRating = m === 0 && (i === 2 || i === 7);
        return {
          player_id: pid,
          display_name: p.display_name,
          team,
          // m === 1 maçında iki katılımcının rolü boş: UI'ın "—" gösterimi ve rol
          // düzeltme akışı denenebilsin (bu maç rol evrenine girmez).
          position: (m === 1 && (i === 1 || i === 6)) ? null : POS[i % 5],
          champion: CHAMPS[(pid + m) % CHAMPS.length],
          stats: {
            kills: (pid + m) % 12,
            deaths: (pid * 3 + m) % 9,
            assists: (pid * 5 + m) % 15,
            gold: 8000 + ((pid * 911 + m * 137) % 8000),
            cs: 90 + ((pid * 37 + m * 11) % 160),
            damage_to_champs: 9000 + ((pid * 1723 + m * 431) % 22000),
            vision_score: 5 + ((pid * 3 + m) % 40),
          },
          rating_change: noRating ? null : {
            mu_before: +(p.rating.mu - delta).toFixed(2),
            sigma_before: +(p.rating.sigma + 0.05).toFixed(3),
            mu_after: +p.rating.mu.toFixed(2),
            sigma_after: +p.rating.sigma.toFixed(3),
          },
        };
      }),
    });
  }
  matches.reverse(); // en yeni başta

  // ── Yardımcılar ──
  const json = (obj, status = 200) =>
    new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });
  const err = (status, detail) => json({ detail }, status);
  const delay = (ms) => new Promise((r) => setTimeout(r, ms));

  // Takıma rol atar: açgözlü (en yüksek rol skoru önce), eşitlikte ilk bulunan kalır.
  // Gerçek atama backend'de (126 ayrım × 120 atama); burada sadece şekil doğru olsun diye.
  function assignRoles(teamIds) {
    const free = POS.slice();
    const rest = [...teamIds];
    const out = [];
    while (rest.length) {
      let best = null;
      for (const pid of rest) {
        const rr = (players.find(p => p.id === pid) || {}).role_ratings;
        for (const role of free) {
          const s = rr && rr[role] ? rr[role].score : 0;
          if (!best || s > best.s) best = { pid, role, s };
        }
      }
      out.push({ player_id: best.pid, position: best.role });
      free.splice(free.indexOf(best.role), 1);
      rest.splice(rest.indexOf(best.pid), 1);
    }
    return out.sort((a, b) => POS.indexOf(a.position) - POS.indexOf(b.position));
  }

  function balanceSuggestions(ids) {
    // Mock partisyonlar: gerçek hesap backend'de; burada sadece makul görünen 3 örnek.
    // Contract §4: dengeleme HER ZAMAN rol bazlı → takımlar {player_id, position} nesneleri.
    const sorted = [...ids].sort((a, b) => {
      const pa = players.find(p => p.id === a), pb = players.find(p => p.id === b);
      return pb.rating.score - pa.rating.score;
    });
    const snake = [0, 3, 4, 7, 8].map(i => sorted[i]);          // yılan drafta benzer bölme
    const evens = ids.filter((_, i) => i % 2 === 0);
    const half = ids.slice(0, 5);
    const other = (side) => ids.filter(id => !side.includes(id));
    return [
      { side: snake, p_win_team_100: 0.508, quality: 0.984 },
      { side: evens, p_win_team_100: 0.541, quality: 0.918 },
      { side: half,  p_win_team_100: 0.469, quality: 0.938 },
    ]
      .map(s => ({
        team_100: assignRoles(s.side),
        team_200: assignRoles(other(s.side)),
        p_win_team_100: s.p_win_team_100,
        quality: s.quality,
      }))
      .sort((a, b) => b.quality - a.quality);
  }

  // ── fetch stub ──
  window.mockFetch = async function (url, opts = {}) {
    await delay(250); // ağ hissi
    const method = (opts.method || "GET").toUpperCase();
    const key = (opts.headers || {})["X-API-Key"];
    const path = url.replace(/^.*\/api\/v1/, "");

    if (!key) return err(401, "API anahtarı eksik veya hatalı.");

    if (method === "GET" && path === "/players") return json(players);

    if (method === "GET" && path === "/leaderboard")
      return json([...players].sort((a, b) => b.rating.score - a.rating.score));

    if (method === "GET" && path.startsWith("/matches")) return json(matches);

    if (method === "POST" && path === "/balance") {
      const body = JSON.parse(opts.body);
      const ids = [...new Set(body.player_ids || [])];
      if (ids.length !== 10) return err(422, "Dengeleme için tam 10 farklı oyuncu seçilmelidir.");
      return json({ engine_version: "openskill-pl-blend50-v1", suggestions: balanceSuggestions(ids) });
    }

    // Rol düzeltme (GÖREV 0): yalnız match_participants.position değişir,
    // ham ingest ve ana rating evreni etkilenmez.
    const posMatch = path.match(/^\/matches\/(\d+)\/positions$/);
    if (method === "PUT" && posMatch) {
      const match = matches.find(m => m.id === Number(posMatch[1]));
      if (!match) return err(404, "Maç bulunamadı.");
      let body = {};
      try { body = JSON.parse(opts.body); } catch { /* gövde JSON değil */ }
      const positions = (body && body.positions) || {};
      const pending = [];
      for (const [pid, pos] of Object.entries(positions)) {
        const part = match.participants.find(p => String(p.player_id) === String(pid));
        if (!part) return err(422, `Bu maçta ${pid} numaralı oyuncu yok.`);
        if (pos !== null && !POS.includes(pos)) return err(422, `Geçersiz rol: ${pos}`);
        pending.push([part, pos]);
      }
      let updated = 0;
      for (const [part, pos] of pending) {
        if (part.position !== pos) { part.position = pos; updated++; }
      }
      // Rol evreni replay'i: uygun tüm valid maçlar yeniden işlenir.
      const replayed = matches.filter(m => m.status === "valid" && roleEligible(m)).length;
      return json({ updated, role_matches_replayed: replayed });
    }

    const voidMatch = path.match(/^\/matches\/(\d+)\/void$/);
    if (method === "POST" && voidMatch) {
      const match = matches.find(m => m.id === Number(voidMatch[1]));
      if (!match) return err(404, "Maç bulunamadı.");
      if (match.status === "void") return err(422, "Bu maç zaten void işaretli.");
      match.status = "void";
      return json({ match_id: match.id, status: "void" });
    }

    if (method === "POST" && path === "/ingest/match") {
      const body = JSON.parse(opts.body);
      if (!body.participants || body.participants.length !== 10)
        return err(422, "Maçta tam 10 katılımcı olmalı (5 mavi, 5 kırmızı).");
      const match = {
        id: nextMatchId++,
        source_game_id: body.source_game_id,
        played_at: body.played_at,
        duration_s: body.duration_s,
        winner_team: body.winner_team,
        status: "valid",
        participants: body.participants.map(pt => {
          const p = players.find(x => x.id === pt.player_id);
          const won = pt.team === body.winner_team;
          const delta = won ? 0.8 : -0.8;
          const mu = p ? p.rating.mu : 25;
          const sigma = p ? p.rating.sigma : 8.333;
          return {
            player_id: pt.player_id,
            display_name: p ? p.display_name : "?",
            team: pt.team,
            position: pt.position,
            champion: null,
            stats: { kills: null, deaths: null, assists: null, gold: null,
                     cs: null, damage_to_champs: null, vision_score: null },
            rating_change: {
              mu_before: +mu.toFixed(2),
              sigma_before: +sigma.toFixed(3),
              mu_after: +(mu + delta).toFixed(2),
              sigma_after: +Math.max(0.5, sigma - 0.05).toFixed(3),
            },
          };
        }),
      };
      matches.unshift(match);
      return json({ match_id: match.id, duplicate: false }, 201);
    }

    return err(404, "Böyle bir endpoint yok: " + path);
  };
})();
