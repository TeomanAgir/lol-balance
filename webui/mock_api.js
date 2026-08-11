// mock_api.js — api_contract.md'deki örnek response'ları dönen fetch stub'ı.
// Backend hazır olunca index.html'de USE_MOCK: false yapılır; bu dosya devre dışı kalır.
(function () {
  "use strict";

  // ── Mock roster: 14 kişilik gerçekçi havuz (1 tanesi hiç maç oynamamış) ──
  const players = [
    { id: 1,  display_name: "Teoman", riot_id: "Teoman#TR1",    matches_played: 24, rating: { mu: 29.4, sigma: 3.1, ordinal: 20.1 } },
    { id: 2,  display_name: "Baran",  riot_id: "Baranski#EUW",  matches_played: 22, rating: { mu: 27.8, sigma: 3.3, ordinal: 17.9 } },
    { id: 3,  display_name: "Kaan",   riot_id: "KaanMid#TR1",   matches_played: 25, rating: { mu: 26.9, sigma: 3.0, ordinal: 17.9 } },
    { id: 4,  display_name: "Emir",   riot_id: "Emir#0000",     matches_played: 19, rating: { mu: 26.2, sigma: 3.5, ordinal: 15.7 } },
    { id: 5,  display_name: "Deniz",  riot_id: "DenizJG#TR1",   matches_played: 21, rating: { mu: 25.8, sigma: 3.2, ordinal: 16.2 } },
    { id: 6,  display_name: "Mert",   riot_id: "MertADC#TR1",   matches_played: 17, rating: { mu: 25.1, sigma: 3.6, ordinal: 14.3 } },
    { id: 7,  display_name: "Arda",   riot_id: "ArdaTop#TR1",   matches_played: 15, rating: { mu: 24.6, sigma: 3.8, ordinal: 13.2 } },
    { id: 8,  display_name: "Efe",    riot_id: "EfeSup#TR1",    matches_played: 18, rating: { mu: 24.0, sigma: 3.4, ordinal: 13.8 } },
    { id: 9,  display_name: "Cem",    riot_id: "CemW#TR1",      matches_played: 12, rating: { mu: 23.5, sigma: 4.1, ordinal: 11.2 } },
    { id: 10, display_name: "Ozan",   riot_id: "OzanKral#TR1",  matches_played: 14, rating: { mu: 23.1, sigma: 3.9, ordinal: 11.4 } },
    { id: 11, display_name: "Berk",   riot_id: "Berk#TR2",      matches_played: 9,  rating: { mu: 22.4, sigma: 4.6, ordinal: 8.6 } },
    { id: 12, display_name: "Yigit",  riot_id: "Yigit#TR1",     matches_played: 7,  rating: { mu: 21.8, sigma: 5.0, ordinal: 6.8 } },
    { id: 13, display_name: "Selin",  riot_id: "Selin#SUP",     matches_played: 5,  rating: { mu: 21.0, sigma: 5.5, ordinal: 4.5 } },
    { id: 14, display_name: "Ece",    riot_id: "Ece#NEW",       matches_played: 0,  rating: { mu: 25.0, sigma: 8.333, ordinal: 0.0 } },
  ];

  const CHAMPS = ["Ahri", "Lee Sin", "Jinx", "Thresh", "Darius", "Yasuo", "Lux", "Ezreal", "Vi", "Orianna"];
  const POS = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"];

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
        return {
          player_id: pid,
          display_name: p.display_name,
          team,
          position: POS[i % 5],
          champion: CHAMPS[(pid + m) % CHAMPS.length],
          mu_before: +(p.rating.mu - delta).toFixed(2),
          mu_after: +p.rating.mu.toFixed(2),
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

  function balanceSuggestions(ids) {
    // Mock partisyonlar: gerçek hesap backend'de; burada sadece makul görünen 3 örnek.
    const sorted = [...ids].sort((a, b) => {
      const pa = players.find(p => p.id === a), pb = players.find(p => p.id === b);
      return pb.rating.ordinal - pa.rating.ordinal;
    });
    const snake = [0, 3, 4, 7, 8].map(i => sorted[i]);          // yılan drafta benzer bölme
    const evens = ids.filter((_, i) => i % 2 === 0);
    const half = ids.slice(0, 5);
    const other = (side) => ids.filter(id => !side.includes(id));
    return [
      { team_100: snake, team_200: other(snake), p_win_team_100: 0.508, quality: 0.984 },
      { team_100: evens, team_200: other(evens), p_win_team_100: 0.541, quality: 0.918 },
      { team_100: half,  team_200: other(half),  p_win_team_100: 0.469, quality: 0.938 },
    ].sort((a, b) => b.quality - a.quality);
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
      return json([...players].sort((a, b) => b.rating.ordinal - a.rating.ordinal));

    if (method === "GET" && path.startsWith("/matches")) return json(matches);

    if (method === "POST" && path === "/balance") {
      const body = JSON.parse(opts.body);
      const ids = [...new Set(body.player_ids || [])];
      if (ids.length !== 10) return err(422, "Dengeleme için tam 10 farklı oyuncu seçilmelidir.");
      return json({ engine_version: "openskill-pl-v1", suggestions: balanceSuggestions(ids) });
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
          return {
            player_id: pt.player_id,
            display_name: p ? p.display_name : "?",
            team: pt.team,
            position: pt.position,
            champion: null,
            mu_before: p ? +p.rating.mu.toFixed(2) : 25,
            mu_after: p ? +(p.rating.mu + delta).toFixed(2) : 25,
          };
        }),
      };
      matches.unshift(match);
      return json({ match_id: match.id, duplicate: false }, 201);
    }

    return err(404, "Böyle bir endpoint yok: " + path);
  };
})();
