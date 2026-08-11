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

  // Tek katılımcı üretici (ana geçmiş + nemesis senaryosu ortak kullanır).
  // seed yalnız istatistikleri çeşitlendirir; hepsi deterministiktir.
  function mkParticipant(pid, team, position, winner, seed) {
    const p = players.find(x => x.id === pid);
    const won = team === winner;
    const delta = (won ? 1 : -1) * (0.4 + ((pid * 7 + seed * 3) % 10) / 12);
    return {
      player_id: pid,
      display_name: p ? p.display_name : "?",
      team,
      position,
      // Her oyuncu iki şampiyon arasında gidip gelir → profildeki "favori karakter"
      // birden çok maça dayanır (tek maçlık beraberlik yerine anlamlı bir favori).
      champion: CHAMPS[(pid * 3 + (seed % 2)) % CHAMPS.length],
      stats: {
        kills: (pid + seed) % 12,
        deaths: (pid * 3 + seed) % 9,
        assists: (pid * 5 + seed) % 15,
        gold: 8000 + ((pid * 911 + seed * 137) % 8000),
        cs: 90 + ((pid * 37 + seed * 11) % 160),
        damage_to_champs: 9000 + ((pid * 1723 + seed * 431) % 22000),
        vision_score: 5 + ((pid * 3 + seed) % 40),
      },
      rating_change: {
        mu_before: +((p ? p.rating.mu : 25) - delta).toFixed(2),
        sigma_before: +((p ? p.rating.sigma : 8.333) + 0.05).toFixed(3),
        mu_after: +(p ? p.rating.mu : 25).toFixed(2),
        sigma_after: +(p ? p.rating.sigma : 8.333).toFixed(3),
      },
    };
  }

  // Maçsız oyuncu (Ece) hiçbir maça girmez: matches_played ile maç geçmişi tutarlı kalsın,
  // profil ekranında (GÖREV 1) boş/null senaryosu gerçekten boş görünsün.
  const matchPool = players.filter(p => p.matches_played).map(p => p.id);
  for (let m = 0; m < 8; m++) {
    // Her maçta havuz bir kaydırılır, ilk 10 kişi oynar.
    const uniq = matchPool.map((_, i, all) => all[(i + m) % all.length]).slice(0, 10);
    const winner = m % 2 === 0 ? 100 : 200;
    matches.push({
      id: nextMatchId++,
      source_game_id: "687423" + (1900 + m),
      played_at: `2026-08-${String(2 + m).padStart(2, "0")}T2${m % 3}:1${m}:00Z`,
      duration_s: 1500 + m * 137,
      winner_team: winner,
      status: "valid",
      participants: uniq.map((pid, i) => {
        const part = mkParticipant(pid, i < 5 ? 100 : 200, POS[i % 5], winner, m);
        // m === 1 maçında iki katılımcının rolü boş: UI'ın "—" gösterimi ve rol
        // düzeltme akışı denenebilsin (bu maç rol evrenine girmez).
        if (m === 1 && (i === 1 || i === 6)) part.position = null;
        // m === 0 maçında iki katılımcıda rating_change null: UI'ın "—" yolu test edilebilsin.
        if (m === 0 && (i === 2 || i === 7)) part.rating_change = null;
        return part;
      }),
    });
  }

  // ── Nemesis senaryosu (GÖREV 3) ──
  // Ana geçmişte her (çift, rol) yalnız 1 kez karşılaşıyor; nemesis eşiği ise
  // encounters >= 3. Bu yüzden sabit kadrolu, tekrar eden 6 maç eklenir.
  // Taban kadro: [rol, mavi oyuncu, kırmızı oyuncu]; "swap" o maçta taraf değiştirenler.
  const RIVAL_BASE = [
    ["TOP", 2, 4], ["JUNGLE", 5, 7], ["MIDDLE", 1, 3], ["BOTTOM", 6, 9], ["UTILITY", 8, 10],
  ];
  // İlk iki maç 7 günlük pencerenin DIŞINDA kalır → weekly çift all_time'dan farklı
  // çıkar (UI'daki "Bu haftanın çifti" notu bu senaryoyla test edilir).
  // Beklenen: all_time = Teoman–Kaan (Orta, 3–3, %100), weekly = Baran–Emir (Üst, 2–2, %100).
  const RIVAL_MATCHES = [
    { at: "2026-07-30T19:05:00Z", winner: 100, swap: ["BOTTOM"] },
    { at: "2026-07-31T20:10:00Z", winner: 100, swap: [] },
    { at: "2026-08-06T19:40:00Z", winner: 100, swap: [] },
    { at: "2026-08-07T20:05:00Z", winner: 200, swap: [] },
    { at: "2026-08-08T19:20:00Z", winner: 200, swap: ["JUNGLE"] },
    { at: "2026-08-09T21:00:00Z", winner: 200, swap: ["JUNGLE", "TOP", "UTILITY"] },
  ];
  RIVAL_MATCHES.forEach((r, i) => {
    const parts = [];
    for (const [role, blue, red] of RIVAL_BASE) {
      const flip = r.swap.includes(role);
      parts.push(mkParticipant(flip ? red : blue, 100, role, r.winner, 20 + i));
      parts.push(mkParticipant(flip ? blue : red, 200, role, r.winner, 20 + i));
    }
    matches.push({
      id: nextMatchId++,
      source_game_id: "687424" + (2000 + i),
      played_at: r.at,
      duration_s: 1620 + i * 94,
      winner_team: r.winner,
      status: "valid",
      participants: parts,
    });
  });

  matches.sort((a, b) => Date.parse(b.played_at) - Date.parse(a.played_at)); // en yeni başta

  // ── Yardımcılar ──
  const json = (obj, status = 200) =>
    new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });
  const err = (status, detail) => json({ detail }, status);
  const delay = (ms) => new Promise((r) => setTimeout(r, ms));

  // Takıma rol atar: açgözlü (en yüksek rol skoru önce), eşitlikte ilk bulunan kalır.
  // Gerçek atama backend'de (126 ayrım × 120 atama); burada sadece şekil doğru olsun diye.
  // fixed = {player_id, position} verilirse o oyuncu o role sabitlenir (nemesis maçı).
  function assignRoles(teamIds, fixed) {
    const free = POS.filter(r => !fixed || r !== fixed.position);
    const rest = teamIds.filter(id => !fixed || id !== fixed.player_id);
    const out = fixed ? [{ player_id: fixed.player_id, position: fixed.position }] : [];
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

  // ── Oyuncu profili (GÖREV 1) ──
  // api_contract §2 "Oyuncu profili": tüm istatistikler yalnız status='valid' maçlardan.
  // Mock bunları maç geçmişinden TÜRETİR → void işlemi profili de tutarlı etkiler.
  const emptyStats = (p) => ({
    player: { id: p.id, display_name: p.display_name, riot_id: p.riot_id },
    totals: { matches: 0, wins: 0, losses: 0, winrate: null },
    kda: null,
    favorite_champion: null,
    favorite_role: null,
    synergy: [],
  });

  function playerStats(id) {
    const p = players.find(x => x.id === id);
    if (!p) return null;
    // Ece (matches_played: 0) → contract'taki tüm null/boş yolları temsil eden senaryo.
    if (!p.matches_played) return emptyStats(p);

    const mine = [];
    for (const m of matches) {
      if (m.status !== "valid") continue;
      const part = m.participants.find(x => x.player_id === id);
      if (part) mine.push({ m, part });
    }
    if (!mine.length) return emptyStats(p);

    const wins = mine.filter(({ m, part }) => m.winner_team === part.team).length;
    const totals = {
      matches: mine.length, wins, losses: mine.length - wins,
      winrate: +(wins / mine.length).toFixed(3),
    };

    // kda: yalnız kills/deaths/assists ÜÇÜ DE dolu maçlar; hiç yoksa null.
    const statted = mine.filter(({ part }) => part.stats &&
      part.stats.kills != null && part.stats.deaths != null && part.stats.assists != null);
    let kda = null;
    if (statted.length) {
      const sum = (f) => statted.reduce((a, { part }) => a + part.stats[f], 0);
      const K = sum("kills"), D = sum("deaths"), A = sum("assists");
      kda = {
        kills_avg: +(K / statted.length).toFixed(2),
        deaths_avg: +(D / statted.length).toFixed(2),
        assists_avg: +(A / statted.length).toFixed(2),
        ratio: +((K + A) / Math.max(1, D)).toFixed(2),
      };
    }

    // favorite_champion: champion null hariç en çok oynanan; eşitlikte ad alfabetik küçük.
    const champs = new Map();
    for (const { m, part } of mine) {
      if (!part.champion) continue;
      const c = champs.get(part.champion) || { champion: part.champion, matches: 0, wins: 0 };
      c.matches++;
      if (m.winner_team === part.team) c.wins++;
      champs.set(part.champion, c);
    }
    const favC = [...champs.values()]
      .sort((a, b) => b.matches - a.matches || a.champion.localeCompare(b.champion))[0];
    const favorite_champion = favC
      ? { champion: favC.champion, matches: favC.matches, winrate: +(favC.wins / favC.matches).toFixed(3) }
      : null;

    // favorite_role: position null hariç en çok oynanan; eşitlikte kanonik rol sırası.
    const roles = new Map();
    for (const { part } of mine) {
      if (!part.position) continue;
      roles.set(part.position, (roles.get(part.position) || 0) + 1);
    }
    const favR = [...roles.entries()]
      .sort((a, b) => b[1] - a[1] || POS.indexOf(a[0]) - POS.indexOf(b[0]))[0];
    const favorite_role = favR ? { role: favR[0], matches: favR[1] } : null;

    // synergy: AYNI TAKIMDA oynanan valid maçlar, en az 2 ortak maç, en fazla 3 kayıt.
    const mates = new Map();
    for (const { m, part } of mine) {
      const won = m.winner_team === part.team;
      for (const other of m.participants) {
        if (other.player_id === id || other.team !== part.team) continue;
        const e = mates.get(other.player_id) || {
          player_id: other.player_id, display_name: other.display_name,
          matches_together: 0, wins_together: 0,
        };
        e.matches_together++;
        if (won) e.wins_together++;
        mates.set(other.player_id, e);
      }
    }
    const synergy = [...mates.values()]
      .filter(e => e.matches_together >= 2)
      .map(e => ({ ...e, winrate: +(e.wins_together / e.matches_together).toFixed(3) }))
      .sort((a, b) => b.winrate - a.winrate ||
                      b.matches_together - a.matches_together ||
                      a.display_name.localeCompare(b.display_name))
      .slice(0, 3);

    return {
      player: { id: p.id, display_name: p.display_name, riot_id: p.riot_id },
      totals, kda, favorite_champion, favorite_role, synergy,
    };
  }

  // ── Haftanın enleri (GÖREV 2) ──
  // api_contract §2 "Haftanın enleri": pencere = son 7 gün; o pencerede hiç valid maç
  // yoksa end = en son valid maçın zamanı olur ve fallback: true döner.
  //
  // SENARYO BAYRAKLARI (test için elle değiştir):
  //   HL_FORCE_FALLBACK = true → pencereyi zorla son maç haftasına kaydırır (fallback: true).
  //     (Mock maçlar 2026-08-02..09 tarihli; bu tarihler 7 günden eskiyince bu yol
  //      zaten kendiliğinden devreye girer.)
  //   HL_EMPTY = true → hiç valid maç yokmuş gibi davranır: üç alan da null, UI boş durum.
  const HL_FORCE_FALLBACK = false;
  const HL_EMPTY = false;

  const DAY7_MS = 7 * 24 * 60 * 60 * 1000;
  const playedAt = (m) => Date.parse(m.played_at);
  const ordinalOf = (mu, sigma) => mu - 3 * sigma;
  const emptyRoles = () => POS.reduce((o, r) => (o[r] = null, o), {});

  // Pencere hesabı tek yerde: haftanın enleri ve nemesis.weekly AYNI kuralı kullanır
  // (contract: "weekly, GET /highlights/weekly pencere kuralının AYNISI ile").
  function weeklyWindow() {
    const valid = matches.filter(m => m.status === "valid");
    if (HL_EMPTY || !valid.length) {
      const end = Date.now();
      return {
        valid, inWindow: [],
        win: { start: new Date(end - DAY7_MS).toISOString(), end: new Date(end).toISOString(), fallback: false },
      };
    }
    let end = Date.now();
    let fallback = false;
    let inWindow = valid.filter(m => playedAt(m) > end - DAY7_MS && playedAt(m) <= end);
    if (HL_FORCE_FALLBACK || !inWindow.length) {
      end = Math.max(...valid.map(playedAt));           // en son valid maç
      inWindow = valid.filter(m => playedAt(m) > end - DAY7_MS && playedAt(m) <= end);
      fallback = true;
    }
    return {
      valid, inWindow,
      win: {  // global window'u gölgelememek için "win"
        start: new Date(end - DAY7_MS).toISOString(),
        end: new Date(end).toISOString(),
        fallback,
      },
    };
  }

  function weeklyHighlights() {
    const { valid, inWindow, win } = weeklyWindow();
    if (HL_EMPTY || !valid.length) {
      return { window: win, best_player: null, rising_star: null, best_by_role: emptyRoles() };
    }

    // Oyuncu bazında topla: pencere maç sayısı, rol bazlı maç sayısı ve
    // ordinal'in pencere içi ilk "önce" / son "sonra" değerleri (rising_star için).
    const agg = new Map();
    for (const m of [...inWindow].sort((a, b) => playedAt(a) - playedAt(b))) {
      for (const part of m.participants) {
        let e = agg.get(part.player_id);
        if (!e) { e = { matches: 0, first: null, last: null, roles: new Map() }; agg.set(part.player_id, e); }
        e.matches++;
        if (part.position) e.roles.set(part.position, (e.roles.get(part.position) || 0) + 1);
        const rc = part.rating_change;   // null olabilir → o maç rating'e girmemiş
        if (rc) {
          if (e.first === null) e.first = ordinalOf(rc.mu_before, rc.sigma_before);
          e.last = ordinalOf(rc.mu_after, rc.sigma_after);
        }
      }
    }

    const rows = [...agg.entries()]
      .map(([id, e]) => ({ id, e, p: players.find(x => x.id === id) }))
      .filter(x => x.p);
    if (!rows.length) return { window: win, best_player: null, rising_star: null, best_by_role: emptyRoles() };

    // Eşitlik kırılımı (contract): değer azalan → pencere maç sayısı azalan → ad alfabetik.
    const best = (list, valueOf, countOf) => [...list].sort((a, b) =>
      valueOf(b) - valueOf(a) ||
      countOf(b) - countOf(a) ||
      a.p.display_name.localeCompare(b.p.display_name, "tr"))[0];

    const winCount = (x) => x.e.matches;
    const topScore = best(rows, x => x.p.rating.score, winCount);
    const best_player = {
      player_id: topScore.id, display_name: topScore.p.display_name,
      score: topScore.p.rating.score, matches_in_window: topScore.e.matches,
    };

    const risers = rows.filter(x => x.e.first !== null);
    const deltaOf = (x) => +(x.e.last - x.e.first).toFixed(2);
    const topRise = risers.length ? best(risers, deltaOf, winCount) : null;
    const rising_star = topRise ? {
      player_id: topRise.id, display_name: topRise.p.display_name,
      delta: deltaOf(topRise), matches_in_window: topRise.e.matches,
    } : null;

    const best_by_role = {};
    for (const role of POS) {
      const cand = rows.filter(x => x.e.roles.get(role));
      const roleCount = (x) => x.e.roles.get(role);
      const roleScore = (x) => ((x.p.role_ratings || {})[role] || {}).score || 0;
      const w = cand.length ? best(cand, roleScore, roleCount) : null;
      best_by_role[role] = w ? {
        player_id: w.id, display_name: w.p.display_name,
        score: roleScore(w), matches_in_window: roleCount(w),
      } : null;
    }

    return { window: win, best_player, rising_star, best_by_role };
  }

  // ── Nemesis (GÖREV 3) ──
  // api_contract §2 "Nemesis": aday birim (çift, rol). Karşılaşma = valid maçta KARŞI
  // takımlarda ve İKİSİ DE aynı non-null position. Eşik encounters >= 3.
  //
  // SENARYO BAYRAKLARI (test için elle değiştir):
  //   NEM_NONE = true       → all_time ve weekly null, active null (UI boş durumu + düğme yok).
  //   NEM_WEEKLY_OFF = true → weekly bastırılır; active "all_time" olur (haftalık not çizilmez).
  const NEM_NONE = false;
  const NEM_WEEKLY_OFF = false;

  // Verilen maç listesindeki en iyi (çift, rol) adayını döner; yoksa null.
  // Sıralama: closeness ↓ → encounters ↓ → rol kanonik → (küçük id, büyük id) ↑.
  function nemesisBest(list) {
    const cand = new Map();
    for (const m of list) {
      if (m.status !== "valid") continue;
      const parts = m.participants.filter(p => p.position);
      for (let i = 0; i < parts.length; i++) {
        for (let j = i + 1; j < parts.length; j++) {
          const a = parts[i], b = parts[j];
          if (a.team === b.team || a.position !== b.position) continue;
          const lo = a.player_id < b.player_id ? a : b;
          const hi = lo === a ? b : a;
          const key = `${a.position}|${lo.player_id}|${hi.player_id}`;
          let e = cand.get(key);
          if (!e) {
            e = { role: a.position, lo: lo.player_id, hi: hi.player_id, encounters: 0, loWins: 0, hiWins: 0 };
            cand.set(key, e);
          }
          e.encounters++;
          if (m.winner_team === lo.team) e.loWins++;
          else if (m.winner_team === hi.team) e.hiWins++;
        }
      }
    }
    return [...cand.values()]
      .filter(e => e.encounters >= 3)
      .map(e => ({ ...e, closeness: 1 - 2 * Math.abs(e.loWins / e.encounters - 0.5) }))
      .sort((x, y) =>
        y.closeness - x.closeness ||
        y.encounters - x.encounters ||
        POS.indexOf(x.role) - POS.indexOf(y.role) ||
        x.lo - y.lo || x.hi - y.hi)[0] || null;
  }

  const nemName = (id) => (players.find(p => p.id === id) || {}).display_name || ("#" + id);
  const nemPair = (e) => e ? {
    role: e.role,
    players: [
      { player_id: e.lo, display_name: nemName(e.lo), wins: e.loWins },
      { player_id: e.hi, display_name: nemName(e.hi), wins: e.hiWins },
    ],
    encounters: e.encounters,
    closeness: +e.closeness.toFixed(2),
  } : null;

  function nemesisPayload() {
    if (NEM_NONE) return { all_time: null, weekly: null, active: null };
    const all_time = nemPair(nemesisBest(matches));
    const weekly = NEM_WEEKLY_OFF ? null : nemPair(nemesisBest(weeklyWindow().inWindow));
    return { all_time, weekly, active: weekly ? "weekly" : all_time ? "all_time" : null };
  }

  // Nemesis maçı: çift KARŞI takımlara ayrılır ve İKİSİ DE nemesis rolüne sabitlenir;
  // kalan 8 oyuncu normal (mock: açgözlü) atamayla dağıtılır.
  function nemesisSuggestions(ids, pair) {
    const [a, b] = pair.players.map(x => x.player_id);
    const scoreOfId = (id) => ((players.find(p => p.id === id) || {}).rating || {}).score || 0;
    const rest = ids.filter(id => id !== a && id !== b).sort((x, y) => scoreOfId(y) - scoreOfId(x));
    return [
      { blue: [rest[0], rest[3], rest[4], rest[7]], p_win_team_100: 0.506, quality: 0.988 },
      { blue: [rest[0], rest[1], rest[6], rest[7]], p_win_team_100: 0.532, quality: 0.936 },
      { blue: [rest[2], rest[3], rest[4], rest[5]], p_win_team_100: 0.474, quality: 0.948 },
    ].map(s => ({
      team_100: assignRoles([a, ...s.blue], { player_id: a, position: pair.role }),
      team_200: assignRoles([b, ...rest.filter(id => !s.blue.includes(id))], { player_id: b, position: pair.role }),
      p_win_team_100: s.p_win_team_100,
      quality: s.quality,
    })).sort((x, y) => y.quality - x.quality);
  }

  // ── fetch stub ──
  window.mockFetch = async function (url, opts = {}) {
    await delay(250); // ağ hissi
    const method = (opts.method || "GET").toUpperCase();
    const key = (opts.headers || {})["X-API-Key"];
    const path = url.replace(/^.*\/api\/v1/, "");

    if (!key) return err(401, "API anahtarı eksik veya hatalı.");

    if (method === "GET" && path === "/players") return json(players);

    const statsPath = path.match(/^\/players\/(\d+)\/stats$/);
    if (method === "GET" && statsPath) {
      const s = playerStats(Number(statsPath[1]));
      return s ? json(s) : err(404, "Oyuncu bulunamadı.");
    }

    if (method === "GET" && path === "/leaderboard")
      return json([...players].sort((a, b) => b.rating.score - a.rating.score));

    if (method === "GET" && path === "/highlights/weekly") return json(weeklyHighlights());

    if (method === "GET" && path === "/nemesis") return json(nemesisPayload());

    if (method === "GET" && path.startsWith("/matches")) return json(matches);

    if (method === "POST" && path === "/balance") {
      const body = JSON.parse(opts.body);
      const ids = [...new Set(body.player_ids || [])];
      if (ids.length !== 10) return err(422, "Dengeleme için tam 10 farklı oyuncu seçilmelidir.");
      return json({ engine_version: "openskill-pl-blend50-v1", suggestions: balanceSuggestions(ids) });
    }

    // Nemesis maçı (GÖREV 3): /balance ile aynı yanıt + "nemesis" nesnesi.
    // 409 = aktif çift yok, 422 = 10 seçim hatalı ya da çift seçimin dışında.
    if (method === "POST" && path === "/balance/nemesis") {
      const body = JSON.parse(opts.body);
      const ids = [...new Set(body.player_ids || [])];
      if (ids.length !== 10) return err(422, "Dengeleme için tam 10 farklı oyuncu seçilmelidir.");
      const nem = nemesisPayload();
      if (!nem.active)
        return err(409, "Aktif nemesis çifti yok: aynı koridorda en az 3 karşılaşma gerekiyor.");
      const pair = nem[nem.active];
      const pids = pair.players.map(x => x.player_id);
      const missing = pair.players.filter(x => !ids.includes(x.player_id));
      if (missing.length)
        return err(422, `Nemesis çifti seçimin dışında: ${missing.map(x => x.display_name).join(" ve ")} de seçilmeli.`);
      return json({
        engine_version: "openskill-pl-blend50-v1",
        suggestions: nemesisSuggestions(ids, pair),
        nemesis: { source: nem.active, role: pair.role, player_ids: pids },
      });
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
