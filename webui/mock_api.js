// mock_api.js — api_contract.md'deki örnek response'ları dönen fetch stub'ı.
// Backend hazır olunca index.html'de USE_MOCK: false yapılır; bu dosya devre dışı kalır.
(function () {
  "use strict";

  // ── Mock roster: 14 kişilik gerçekçi havuz (1 tanesi hiç maç oynamamış) ──
  // rating: harman engine (openskill-pl-blend20-v1) şekli {mu, sigma, ordinal, perf_avg, score}.
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

  // Contract formülü (rating_contract.md "Harman Engine — blend20"): W=0.8, MU_0=25, K=20.
  // perf_avg null → harman-dışı version: score = ordinal.
  const scoreOf = (r) =>
    r.perf_avg == null
      ? r.ordinal
      : +(0.2 * r.mu + 0.8 * (25 + 20 * (r.perf_avg - 1)) - 3 * r.sigma).toFixed(1);
  players.forEach(p => { p.rating.score = scoreOf(p.rating); });

  // GÖREV 18: maç önü/sonu EFEKTİF score (api_contract §3 rating_change
  // score_before/score_after). scoreOf ile aynı harman formülü, nokta değerlerle
  // çağrılır; contract gereği 2 ondalığa yuvarlanır.
  const effScoreAt = (mu, sigma, pavg) =>
    +(0.2 * mu + 0.8 * (25 + 20 * (pavg - 1)) - 3 * sigma).toFixed(2);

  // Sıra değişimi (api_contract §5): YALNIZ /leaderboard'da döner, /players'ta
  // yoktur. Oyuncu id → rank_delta; listede dört hâlin dördü de bulunsun diye
  // sabit bir örnek dağılım: yükselen (+), düşen (−), değişmeyen (0) ve
  // karşılaştırılamayan (null: 14'ün hiç maçı yok — önceki anda rating satırı
  // olmayan oyuncuda sahte yükseliş gösterilmez; panelden eklenen yeni oyuncu da
  // haritada bulunmadığı için null alır).
  const RANK_DELTA = {
    1: 0, 2: 2, 3: -1, 4: 1, 5: -2, 6: 3, 7: 0,
    8: -1, 9: 0, 10: 1, 11: -3, 12: 0, 13: 1, 14: null,
  };

  const CHAMPS = ["Ahri", "Lee Sin", "Jinx", "Thresh", "Darius", "Yasuo", "Lux", "Ezreal", "Vi", "Orianna"];
  const POS = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"];

  // ── Rol rating evreni (GÖREV 0) ──
  // Contract §2: 5 anahtar HER ZAMAN mevcut; hiç oynanmamış rol default prior döner.
  // Mock'ta her oyuncunun bir ana + bir ikincil rolü maç görmüş, kalan 3 rol default.
  const defaultRole = () => ({ mu: 25.0, sigma: 8.333, perf_avg: 1.0, score: 0.0, matches: 0 });
  const roleScoreOf = (mu, sigma, perf) =>
    +(0.2 * mu + 0.8 * (25 + 20 * (perf - 1)) - 3 * sigma).toFixed(1);

  // SENARYO BAYRAĞI (GÖREV 4): bu rolde HİÇ kimsenin maçı yokmuş gibi davranılır
  // (5 anahtar yine döner, hepsi default prior). Harita ekranındaki soluk "—"
  // baloncuğu ve rol sıralaması pop-up'ının boş mesajı bu yolla test edilir.
  // null yaparsan beş rol de dolu olur.
  const EMPTY_ROLE = "UTILITY";

  players.forEach(p => {
    const rr = {};
    POS.forEach((role, i) => {
      if (role === EMPTY_ROLE) { rr[role] = defaultRole(); return; }
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

  // KALABALIK ROL (profil rol sıralaması penceresi, 2026-08-19): pencere
  // "lider → ayraç → ±3 komşuluk → ayraç → sonuncu" düzenindedir, yani TAM
  // hâlini görebilmek için o rolde EN AZ 10 oyuncu gerekir (9 satır sığar).
  // Yukarıdaki ana/ikincil dağılım role başına ~6 kişi bırakıyor; bu yüzden
  // ORTA koridoru bilerek doldurulur: maçı olan HER oyuncunun (13 kişi) orada
  // birkaç maçı olur → biri 1., biri sonuncu, çoğu ortalarda. Diğer roller
  // seyrek kalır, böylece "az oyuncu → tam liste, ayraç yok" hâli de görülür;
  // EMPTY_ROLE ise hiç oynanmamış rolün (tıklanamaz simge) örneğidir.
  const CROWD_ROLE = "MIDDLE";
  players.forEach(p => {
    if (CROWD_ROLE === EMPTY_ROLE) return; // iki senaryo bayrağı çakışmasın
    if (!p.matches_played || p.role_ratings[CROWD_ROLE].matches) return;
    const matches = 2 + (p.id % 4);
    const mu = +(p.rating.mu - 1.4).toFixed(2);
    const sigma = +Math.max(1.5, p.rating.sigma + 2.2).toFixed(3);
    const perf = +((p.rating.perf_avg == null ? 1.0 : p.rating.perf_avg) - 0.09).toFixed(2);
    p.role_ratings[CROWD_ROLE] = {
      mu, sigma, perf_avg: perf, score: roleScoreOf(mu, sigma, perf), matches,
    };
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

  // ── Eşya envanterleri (GÖREV 14) ──
  // api_contract §3: `items` HAM sıradır (son slot totem), 0-7 eleman; NULL =
  // "bilinmiyor" (eski exe/eski maç), [] = "bilgi var, envanter boş".
  // Roller gerçekçi build'ler taşır; 5. slot seed'e göre değişir → top_items
  // sayımları oyuncudan oyuncuya farklılaşır. Totem her build'in SON slotudur:
  // profildeki favori eşya süzgeci (Trinket/Consumable atlanır) böylece görünür
  // bir yol izler — sayımda en tepede totem çıkar, kart ilk gerçek eşyayı gösterir.
  const BUILDS = {
    TOP:     [3068, 3075, 3047, 3065, 3143, 1031, 3340],
    JUNGLE:  [6692, 3142, 3814, 3047, 3036, 1037, 3340],
    MIDDLE:  [6655, 3157, 3020, 4645, 3135, 1058, 3340],
    BOTTOM:  [3031, 3094, 3006, 3072, 3036, 1055, 3340],
    UTILITY: [3877, 3011, 3222, 3504, 2055, 3107, 3364],
  };
  const ALT_ITEMS = [3033, 3026, 3156, 3053, 3742, 3115];

  function mkItems(pid, position, seed) {
    const base = BUILDS[position] || BUILDS.MIDDLE;
    const build = base.slice();
    build[4] = ALT_ITEMS[(pid + seed) % ALT_ITEMS.length];
    return build;
  }

  // Tek katılımcı üretici (ana geçmiş + nemesis senaryosu ortak kullanır).
  // seed yalnız istatistikleri çeşitlendirir; hepsi deterministiktir.
  function mkParticipant(pid, team, position, winner, seed) {
    const p = players.find(x => x.id === pid);
    const won = team === winner;
    const delta = (won ? 1 : -1) * (0.4 + ((pid * 7 + seed * 3) % 10) / 12);
    // GÖREV 18: efektif score alanları — kümülatif P_avg taklidi. O maçın perf'i
    // kariyer ortalamasını 1/n ağırlıkla oynatır (kronolojik önek ortalaması
    // gibi). Kazananın perf'i ortalamanın üstüne, kaybedeninki altına eğilimli;
    // seed sapmasıyla İYİ OYNAYAN KAYBEDEN pozitif score delta'sı alabilir
    // (blend'in kabul edilen ödünleşimi — UI'da yeşil "+" iki yönde de görünsün).
    const muAfter = p ? p.rating.mu : 25;
    const muBefore = +(muAfter - delta).toFixed(2);
    const sigmaAfter = +(p ? p.rating.sigma : 8.333).toFixed(3);
    const sigmaBefore = +(sigmaAfter + 0.05).toFixed(3);
    const pavgBefore = p && p.rating.perf_avg != null ? p.rating.perf_avg : 1.0;
    const n = Math.max(1, p ? p.matches_played : 1);
    const perfGame = pavgBefore + (won ? 0.15 : -0.35) + (((pid * 7 + seed * 5) % 12) / 12 - 0.3);
    const pavgAfter = pavgBefore + (perfGame - pavgBefore) / n;
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
      items: mkItems(pid, position, seed),
      rating_change: {
        mu_before: muBefore,
        sigma_before: sigmaBefore,
        mu_after: +muAfter.toFixed(2),
        sigma_after: sigmaAfter,
        score_before: effScoreAt(muBefore, sigmaBefore, pavgBefore),
        score_after: effScoreAt(muAfter, sigmaAfter, pavgAfter),
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
        // m === 2 maçında bazı stat alanları null (contract: stats alanları nullable) —
        // maç detayındaki (GÖREV 8) "—" + 0 genişlikte bar yolu denenebilsin.
        if (m === 2 && i === 4) part.stats.vision_score = null;
        // GÖREV 19: k/d/a'dan yalnız BİRİ null → o satırda KDA HİÇ görünmemeli
        // (kısmi "7/—/9" da "—" da yok). Geçmiş kartı + maç detayı bu maçla denenir.
        if (m === 2 && i === 4) part.stats.kills = null;
        if (m === 2 && i === 9) { part.stats.gold = null; part.stats.damage_to_champs = null; }
        // m === 3 maçında mavi takımda MÜKERRER rol (iki ORMAN, TOP yok) — maç
        // detayının rol eşleştirmesi artakalanları "?" satırına düşürmeli.
        if (m === 3 && i === 0) part.position = "JUNGLE";
        // Eşya senaryoları (GÖREV 14) — BUILD sekmesinin üç yolu da denenebilsin:
        //   null = bilinmiyor ("eşya bilgisi yok"), [] = boş slotlar,
        //   kısa dizi = dolu + boş slot karışımı, 9999 = kaldırılmış/bilinmeyen
        //   id (yer tutucu kutuya düşer).
        if (m === 0 && i === 3) part.items = null;
        if (m === 0 && i === 8) part.items = [];
        if (m === 2 && i === 5) part.items = [3031, 1055];
        if (m === 4 && i === 1) part.items[2] = 9999;
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

  // ── Rulet maçı (GÖREV 23) ──
  // status='roulette' + `roulette` alanı (api_contract §3): Geçmiş'teki RULET
  // rozeti, maç detayındaki görev bölümü ve unlink akışı mock ile denenebilsin.
  // Contract: rulet maçı HİÇBİR rating evrenine girmez → rating_change null;
  // valid süzgeçli tüm türetimlerin (profil, enler, nemesis, rozet, tarihçe)
  // dışında kalır — mock zaten her yerde status === "valid" süzer.
  // Senaryolar: [0] iki eşya da envanterde + takımı kazandı (bought/won true),
  // [5] iki eşya da envanterde ama takım kaybetti (won false), [2] items null →
  // bought null ("doğrulanamadı"), kalanlar bought false.
  (function addRouletteMatch() {
    const ids = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
    const parts = ids.map((pid, i) => {
      const part = mkParticipant(pid, i < 5 ? 100 : 200, POS[i % 5], 100, 40);
      part.rating_change = null;
      return part;
    });
    parts[2].items = null;
    const assignments = parts.map((p, i) => {
      // Atama kaydı contract §3 şeklidir (team YOK; detay ekranı takımı
      // participants'tan çözer). bought=true satırlarda item_ids gerçekten
      // envanterin ilk iki eşyasıdır (küme bazlı karşılaştırmayla tutarlı).
      const item_ids = i === 0 || i === 5 ? [p.items[0], p.items[1]]
        : i === 2 ? [3031, 3026]
        : [3157, 3033];
      const bought = i === 0 || i === 5 ? true : i === 2 ? null : false;
      return {
        player_id: p.player_id, champion: p.champion, position: p.position,
        item_ids, bought, won: bought === true && p.team === 100,
      };
    });
    matches.push({
      id: nextMatchId++,
      source_game_id: "6874242100",
      played_at: "2026-08-10T20:30:00Z",
      duration_s: 1780,
      winner_team: 100,
      status: "roulette",
      participants: parts,
      roulette: { session_id: 4, assignments },
    });
  })();

  // api_contract §3: `roulette` alanı HER maçta bulunur — bağlı oturum yoksa
  // null. Tek yerden tamamlanır ki her maç kurucusuna elle eklenmesin.
  matches.forEach(m => { if (m.roulette === undefined) m.roulette = null; });

  matches.sort((a, b) => Date.parse(b.played_at) - Date.parse(a.played_at)); // en yeni başta

  // ── Yardımcılar ──
  const json = (obj, status = 200) =>
    new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });
  const err = (status, detail) => json({ detail }, status);
  const delay = (ms) => new Promise((r) => setTimeout(r, ms));

  // ── İdari anahtar (fix-2, api_contract "Admin anahtarı") ──
  // Mock'ta SABİT SAHTE bir anahtar kullanılır; gerçek şifreyle ilgisi yoktur
  // ve olamaz (repo public). Kontrol Paneli'ni mock modunda denemek için
  // giriş ekranına bu değer yazılır.
  const MOCK_ADMIN_KEY = "mock-admin-key";
  // Gerçek backend'de ADMIN_KEY yapılandırılmamışsa uçlar 503 döner; mock'ta
  // bu yolu denemek için aşağıdaki bayrak konsoldan true yapılabilir.
  window.MOCK_ADMIN_KEY_MISSING = false;
  const adminGuard = (opts) => {
    if (window.MOCK_ADMIN_KEY_MISSING)
      return err(503, "Yönetim anahtarı sunucuda yapılandırılmamış (ADMIN_KEY); idari uçlar kapalı.");
    const given = (opts.headers || {})["X-Admin-Key"];
    if (given !== MOCK_ADMIN_KEY) return err(403, "Yönetim anahtarı eksik veya hatalı.");
    return null;
  };

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
    top_items: [],
  });

  // Oyuncunun tüm valid maçlarını (m, kendi participant satırı) döner — playerStats
  // ("mine") ve GÖREV 22 sinerji hesabı (aday arkadaşın KENDİ solo maçları için) ortak kullanır.
  function validMatchesFor(pid) {
    const list = [];
    for (const m of matches) {
      if (m.status !== "valid") continue;
      const part = m.participants.find(x => x.player_id === pid);
      if (part) list.push({ m, part });
    }
    return list;
  }

  function playerStats(id) {
    const p = players.find(x => x.id === id);
    if (!p) return null;
    // Ece (matches_played: 0) → contract'taki tüm null/boş yolları temsil eden senaryo.
    if (!p.matches_played) return emptyStats(p);

    const mine = validMatchesFor(id);
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

    // favorite_champion [REVİZE 2026-08-15]: champion null hariç EN FAZLA MAÇ
    // KAZANILAN şampiyon (galibiyet sayısı, oran değil); kırılım galibiyet çok →
    // maç sayısı çok → ad alfabetik küçük. Hiç galibiyet yoksa kural kendiliğinden
    // en çok oynanana düşer.
    const champs = new Map();
    for (const { m, part } of mine) {
      if (!part.champion) continue;
      const c = champs.get(part.champion) || { champion: part.champion, matches: 0, wins: 0 };
      c.matches++;
      if (m.winner_team === part.team) c.wins++;
      champs.set(part.champion, c);
    }
    const favC = [...champs.values()]
      .sort((a, b) => b.wins - a.wins || b.matches - a.matches ||
                      a.champion.localeCompare(b.champion))[0];
    const favorite_champion = favC
      ? {
          champion: favC.champion, matches: favC.matches, wins: favC.wins,
          winrate: +(favC.wins / favC.matches).toFixed(3),
        }
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

    // synergy [YENİDEN TANIMLANDI — GÖREV 22, api_contract §2]: "birlikteyken diğer
    // maçlarına göre ne kadar iyi oynadınız" (winrate-lift + perf-lift harmanı).
    // perf_score gerçek formülü backend/rating paketindedir; burada YALNIZ şekli
    // doğrulamak için deterministik bir vekil (perfProxy) kullanılır — sayılar
    // backend'le birebir eşleşmek zorunda değil (mock kuralı).
    const SYN_MIN_TOGETHER = 4, SYN_M = 4, SYN_W_WR = 0.5, SYN_W_PERF = 0.5, SYN_PERF_SCALE = 3.4;
    const togetherByMate = new Map(); // player_id -> [{m, part: mine-satırı}]
    for (const row of mine) {
      const { m, part } = row;
      for (const other of m.participants) {
        if (other.player_id === id || other.team !== part.team) continue;
        if (!togetherByMate.has(other.player_id)) togetherByMate.set(other.player_id, []);
        togetherByMate.get(other.player_id).push(row);
      }
    }
    const winrateOf = (list) => {
      if (!list.length) return 0.5; // solo(Z) boşsa contract: 0.5
      const w = list.filter(({ m, part }) => m.winner_team === part.team).length;
      return w / list.length;
    };
    // perfProxy ham birimleri (kill*3+... büyüklüğünde) gerçek perf_score'un
    // ~1.0 ortalamalı ölçeğinden çok büyük — badges (mvp/bench) yalnız SIRALAMA
    // kullandığı için sorun değil, ama burada FARK (perf_delta) doğrudan gösterime
    // gidiyor. /100 ölçeklemesi contract örneğindeki büyüklüğe (score≈0.25,
    // perf_delta≈0.2) yaklaştırır — yalnız GÖRÜNÜM gerçekçiliği, hesap etkilenmez.
    const perfAvgOf = (list) => {
      const vals = list.map(({ part }) => perfProxy(part)).filter(v => typeof v === "number");
      return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length / 100 : null;
    };
    const synergy = [...togetherByMate.entries()]
      .map(([matePid, together]) => {
        const n = together.length;
        const mate = players.find(x => x.id === matePid);
        const wins_together = together.filter(({ m, part }) => m.winner_team === part.team).length;
        const togetherIds = new Set(together.map(({ m }) => m.id));
        const soloXlist = mine.filter(({ m }) => !togetherIds.has(m.id));
        const soloYlist = validMatchesFor(matePid).filter(({ m }) => !togetherIds.has(m.id));
        const wrLift = wins_together / n - (winrateOf(soloXlist) + winrateOf(soloYlist)) / 2;
        const perfXTogether = perfAvgOf(together);
        const perfYTogether = perfAvgOf(together.map(({ m }) => ({ part: m.participants.find(x => x.player_id === matePid) })));
        const perfXSolo = perfAvgOf(soloXlist);
        const perfYSolo = perfAvgOf(soloYlist);
        const liftX = (perfXTogether != null && perfXSolo != null) ? perfXTogether - perfXSolo : 0;
        const liftY = (perfYTogether != null && perfYSolo != null) ? perfYTogether - perfYSolo : 0;
        const perf_delta = (liftX + liftY) / 2;
        const shrink = n / (n + SYN_M);
        const score = shrink * (SYN_W_WR * wrLift + SYN_W_PERF * SYN_PERF_SCALE * perf_delta);
        return {
          player_id: matePid, display_name: mate ? mate.display_name : `#${matePid}`,
          matches_together: n, wins_together,
          winrate: +(wins_together / n).toFixed(3),
          score: +score.toFixed(3), perf_delta: +perf_delta.toFixed(2),
        };
      })
      .filter(e => e.matches_together >= SYN_MIN_TOGETHER && e.score > 0)
      .sort((a, b) => b.score - a.score ||
                      b.matches_together - a.matches_together ||
                      a.display_name.localeCompare(b.display_name))
      .slice(0, 3);
    // GÖREV 22 SENARYO: Selin (13, en az maçlı — 5) doğal hesapta eşiği zar zor
    // geçen tek bir aday buluyor (score sıfıra çok yakın). "Kayda değer sinerji
    // yok" boş-durum yolunun mock'ta GÜVENİLİR biçimde denenebilmesi için burada
    // bilerek boşaltılır (dosyadaki diğer SENARYO BAYRAKLARI ile aynı desen —
    // ör. m===1'de position null). UI: profil.synergy_empty, toplam maç sayısıyla
    // ("5 maç") bağlam verir.
    if (id === 13) synergy.length = 0;

    // top_items (GÖREV 14): yalnız items DOLU maçlar (null olanlar atlanır);
    // aynı maçta aynı eşya BİR KEZ sayılır; sıra sayım azalan → item_id artan;
    // en fazla 10 kayıt. Totem/tüketilebilir ELEMESİ BURADA YOKTUR — contract
    // gereği o seçim web UI'dadır (backend eşya meta verisi bilmez).
    const itemCounts = new Map();
    for (const { part } of mine) {
      if (!Array.isArray(part.items)) continue;
      for (const id of new Set(part.items)) itemCounts.set(id, (itemCounts.get(id) || 0) + 1);
    }
    const top_items = [...itemCounts.entries()]
      .map(([item_id, n]) => ({ item_id, matches: n }))
      .sort((a, b) => b.matches - a.matches || a.item_id - b.item_id)
      .slice(0, 10);

    return {
      player: { id: p.id, display_name: p.display_name, riot_id: p.riot_id },
      totals, kda, favorite_champion, favorite_role, synergy, top_items,
    };
  }

  // ── Rating tarihçesi (GÖREV 10) ──
  // api_contract §2 "Rating tarihçesi": yalnız valid maçlar, KRONOLOJİK ARTAN sıra,
  // sunucuda zaman aralığı filtresi YOK (tam tarihçe döner, aralık seçimi UI'da).
  // Gerçek değerler backend'de rating paketiyle hesaplanır; burada yalnız ŞEKİL
  // doğru olsun diye deterministik bir yürüyüş üretilir (Date.now/random yok).
  //
  // SENARYO BAYRAKLARI (test için elle değiştir):
  //   HIST_SINGLE_PLAYER = <id> → o oyuncunun tarihçesi İLK maçıyla sınırlanır.
  //     Selin (13) en son 2026-08-05'te oynadı → aynı anda İKİ kenar durumu verir:
  //     "tek nokta, çizgi yok" ve "7 gün" aralığında "bu aralıkta maç yok".
  //     (null yaparsan kapanır.)
  //   HIST_NULL_STATS_PLAYER = <id> → o oyuncunun 2. maçında stats null döner
  //     (contract: k/d/a'nın üçü de null ise stats null) → popup'ta K/D/A "—".
  // Ece (14) hiç maç oynamadı → points: [] (grafik yerine boş durum metni).
  // Teoman (1) 12 maçlık seri → aralık filtresi anlamlı biçimde denenebilir.
  const HIST_SINGLE_PLAYER = 13;
  const HIST_NULL_STATS_PLAYER = 3;

  function ratingHistory(id) {
    const p = players.find(x => x.id === id);
    if (!p) return null;
    const mine = matches
      .filter(m => m.status === "valid" && m.participants.some(x => x.player_id === id))
      .sort((a, b) => Date.parse(a.played_at) - Date.parse(b.played_at));

    // mu W/L ile yürür, sigma yavaşça daralır, P_avg kümülatif ortalamadır —
    // score = 0.2*mu + 0.8*(25 + 20*(P_avg-1)) - 3*sigma (rating_contract harman/blend20).
    let mu = 25, sigma = 8.333, perfSum = 0;
    const points = [];
    mine.forEach((m, i) => {
      const part = m.participants.find(x => x.player_id === id);
      const win = m.winner_team === part.team;
      mu += win ? 1.7 - ((id + i) % 3) * 0.25 : -1.4 + ((id + i) % 4) * 0.2;
      sigma = Math.max(p.rating.sigma, sigma - 0.42);
      perfSum += 1 + (((id * 7 + i * 13) % 25) - 12) / 100;   // 0.88 .. 1.13
      const pAvg = perfSum / (i + 1);
      const noStats = id === HIST_NULL_STATS_PLAYER && i === 1;
      points.push({
        match_id: m.id,
        played_at: m.played_at,
        win,
        champion: part.champion,
        position: part.position,
        score_after: +(0.2 * mu + 0.8 * (25 + 20 * (pAvg - 1)) - 3 * sigma).toFixed(2),
        stats: noStats ? null : {
          kills: part.stats.kills, deaths: part.stats.deaths, assists: part.stats.assists,
        },
      });
    });

    return {
      player_id: id,
      engine_version: "openskill-pl-blend20-v1",
      points: id === HIST_SINGLE_PLAYER ? points.slice(0, 1) : points,
    };
  }

  // ── Rozetler (GÖREV 11+12; katalog GÖREV 24'te 27 rozet) ──
  // api_contract §2 "Rozetler": yanıt `key` + sayısal alanları taşır (ad/açıklama
  // web UI sözlüğünde), sıra SABİT katalog sırasıdır (ID = sıradaki konum),
  // `include_locked=false` iken yalnız count > 0 rozetler döner.
  //
  // Gerçek hesapta perf temelli rozetler rating satırındaki perf_score'a bakar;
  // mock'ta perf_score yok, bu yüzden deterministik bir VEKİL kullanılır — şekil ve
  // kenar durumları doğru olsun diye, sayılar backend'le aynı olmak zorunda değil.
  // Mock fixture'ı küçük olduğu için bazı rozetler (kill_20, role_record…) doğal
  // olarak hiç düşmez; onlar KİLİTLİ yolu (include_locked) besler.
  //
  // SENARYO BAYRAĞI (test için elle değiştir):
  //   BADGES_FULL_PLAYER = <id> → o oyuncuda eksik katalog rozetleri deterministik
  //     sayılarla tamamlanır (27 rozetlik profil + ALTI KADEMENİN hepsi bir
  //     bakışta görülebilsin: mvp STELLAR (görev tamam), gold DIAMOND (görev 2/3),
  //     cs_per_min PLATINUM, vision GOLD, role_duel SILVER, damage BRONZE — vitrine
  //     bu sırayla mvp/gold/cs_per_min girer) ve sona BİLİNMEYEN bir anahtar
  //     eklenir: UI'ın "tanımadığın key'i
  //     sessizce atla" ileri uyumluluk yolu böyle denenir. null yaparsan yalnız
  //     gerçek rozetler döner.
  // Ece (14) hiç maç oynamadı → include_locked=false ile badges: [] (boş durum
  // metni), include_locked=true ile 27 kilitli rozet + ilerleme (0/10 …).
  //
  // class / source / tiered / one_time alanları GET /badges kataloğunun
  // (api_contract §2 "Rozet kataloğu ucu") alanlarıdır; sıra ID sırasıdır.
  const BADGE_CATALOG = [
    { key: "mvp", cls: "record", src: "valid", tiered: true, one: false },
    { key: "vision", cls: "record", src: "valid", tiered: true, one: false },
    { key: "damage", cls: "record", src: "valid", tiered: true, one: false },
    { key: "cs_per_min", cls: "record", src: "valid", tiered: true, one: false },
    { key: "gold", cls: "record", src: "valid", tiered: true, one: false },
    { key: "role_duel", cls: "role", src: "valid", tiered: true, one: false },
    { key: "role_record", cls: "role", src: "valid", tiered: false, one: false },
    { key: "pr_perf", cls: "personal", src: "valid", tiered: false, one: false },
    { key: "pr_damage", cls: "personal", src: "valid", tiered: false, one: false },
    { key: "kill_20", cls: "narrative", src: "valid", tiered: false, one: false },
    { key: "kda_10", cls: "narrative", src: "valid", tiered: false, one: false },
    { key: "deathless", cls: "narrative", src: "valid", tiered: false, one: false },
    { key: "comeback", cls: "narrative", src: "valid", tiered: false, one: false },
    { key: "tragic_hero", cls: "narrative", src: "valid", tiered: false, one: false },
    { key: "marathon_5", cls: "narrative", src: "valid", tiered: false, one: false },
    { key: "win_streak_3", cls: "streak", src: "valid", tiered: false, one: false },
    { key: "lose_streak_3", cls: "streak", src: "valid", tiered: false, one: false },
    { key: "bench_2", cls: "streak", src: "valid", tiered: false, one: false },
    { key: "nemesis_6", cls: "relational", src: "valid", tiered: false, one: true },
    { key: "duo_6", cls: "relational", src: "valid", tiered: false, one: true },
    { key: "versatile", cls: "identity", src: "valid", tiered: false, one: true },
    { key: "veteran_10", cls: "milestone", src: "valid", tiered: false, one: true },
    { key: "veteran_20", cls: "milestone", src: "valid", tiered: false, one: true },
    { key: "veteran_50", cls: "milestone", src: "valid", tiered: false, one: true },
    { key: "roulette_complete", cls: "roulette", src: "roulette", tiered: false, one: false },
    { key: "roulette_winner", cls: "roulette", src: "roulette", tiered: false, one: false },
    { key: "gambler", cls: "roulette", src: "roulette", tiered: false, one: true },
    // ID 28 (Teoman 2026-08-19): katalog SONUNA eklendi. Tek NADİR ölçekli
    // kademeli rozet (eşikler seyrek olay için daha düşük).
    { key: "perfect_quad", cls: "record", src: "valid", tiered: true, scale: "rare", one: false },
  ];
  const BADGES_FULL_PLAYER = 1;

  // Kademe eşikleri (api_contract §2 "Kademe — ALTI SEVİYE").
  // [REVİZE — Teoman, 2026-08-19] Kademe KÜMÜLATİF SAYAÇLADIR ve ASLA DÜŞMEZ:
  // ölçüt `count`, ORAN KULLANILMAZ (oran paydaya bağlı olduğu için kötü bir gece
  // kademeyi düşürebiliyordu). İki ölçek var: STANDART (her maçta ~1 dağılan
  // rozetler) ve NADİR (yalnız `perfect_quad`). `matches_played >= 8` şartı
  // KALDIRILDI. `rate` yanıtta SALT BİLGİ olarak kalır, kademeyi etkilemez.
  //
  // `stellar` SAYAÇLA KAZANILMAZ: elmas eşiği + o rozeti ARDIŞIK 3 valid maçta
  // kazanma GÖREVİ. Bu yüzden elmasta next_tier_count NULL'dur (sıradaki basamak
  // sayaçla değil görevle açılır) ve yanıt `stellar_quest` alanını taşır.
  const TIER_STEPS = {
    standard: { silver: 3, gold: 5, platinum: 8, diamond: 12 },
    rare: { silver: 2, gold: 3, platinum: 4, diamond: 6 },
  };
  const TIER_BRONZE = 1, STELLAR_TARGET = 3;

  function tierOf(count, played, scale, questBest) {
    const step = TIER_STEPS[scale] || TIER_STEPS.standard;
    const rate = played > 0 ? count / played : 0;
    let tier = "bronze";
    if (count >= step.diamond) tier = "diamond";
    else if (count >= step.platinum) tier = "platinum";
    else if (count >= step.gold) tier = "gold";
    else if (count >= step.silver) tier = "silver";
    const best = Math.max(0, Number(questBest) || 0);
    const met = best >= STELLAR_TARGET;
    if (tier === "diamond" && met) tier = "stellar";
    const next = count < TIER_BRONZE ? TIER_BRONZE
      : tier === "bronze" ? step.silver
        : tier === "silver" ? step.gold
          : tier === "gold" ? step.platinum
            : tier === "platinum" ? step.diamond
              : null;
    return {
      tier, rate: +rate.toFixed(2), next_tier_count: next,
      stellar_quest: { target: STELLAR_TARGET, best, met },
    };
  }

  // perf_score vekili: NULL stat varsa perf de NULL sayılır (contract: perf_score
  // NULL satır mvp/bench için aday değildir).
  function perfProxy(part) {
    const s = part.stats;
    if (!s) return null;
    const need = [s.kills, s.deaths, s.assists, s.gold, s.damage_to_champs];
    if (need.some(v => typeof v !== "number")) return null;
    return s.kills * 3 + s.assists * 1.5 - s.deaths * 2 + s.gold / 4000 + s.damage_to_champs / 9000;
  }

  function playerBadges(id, includeLocked) {
    if (!players.some(x => x.id === id)) return null;
    const mine = matches
      .filter(m => m.status === "valid" && m.participants.some(x => x.player_id === id))
      .sort((a, b) => Date.parse(a.played_at) - Date.parse(b.played_at));

    // key -> {count, last_match_id, best_match_id, best_value, run, best_run}
    // val verilirse "en iyi an" izlenir (rekor/rol/kişisel sınıfları).
    // best_run = kariyerdeki EN UZUN ARDIŞIK kazanım serisi (stellar görevi):
    // rozet, kronolojik sırada bir önceki maçta da kazanıldıysa seri uzar, aksi
    // hâlde 1'e döner (arada kazanılmayan/kapsam dışı maç seriyi KIRAR).
    const acc = new Map();
    let curIdx = -1;
    const add = (key, mid, val) => {
      const e = acc.get(key) ||
        { count: 0, last_match_id: null, best_match_id: null, best_value: null,
          run: 0, best_run: 0, runEnd: -2 };
      e.count++; e.last_match_id = mid;
      if (typeof val === "number" && (e.best_value === null || val > e.best_value)) {
        e.best_value = +val.toFixed(2); e.best_match_id = mid;
      }
      e.run = e.runEnd === curIdx - 1 ? e.run + 1 : 1;
      e.runEnd = curIdx;
      if (e.run > e.best_run) e.best_run = e.run;
      acc.set(key, e);
    };

    const roles = new Set();
    const nights = new Map();     // gece anahtarı -> {n, last}
    const foeWins = new Map();    // rakip player_id -> galibiyet
    const mateWins = new Map();   // arkadaş player_id -> birlikte galibiyet
    let winRun = 0, loseRun = 0, benchRun = 0, played = 0;
    let bestPerf = null, bestDpm = null, perfSeen = 0, dpmSeen = 0;

    for (const m of mine) {
      curIdx++;                   // kronolojik sıra: ardışıklık sayımının temeli
      played++;
      const me = m.participants.find(x => x.player_id === id);
      const win = m.winner_team === me.team;
      if (me.position) roles.add(me.position);
      if (roles.size === 5 && !acc.has("versatile")) add("versatile", m.id);
      [10, 20, 50].forEach(n => { if (played === n) add("veteran_" + n, m.id); });

      // Oyun gecesi: played_at (UTC) − 6 saat → tarih (sabaha kadar süren
      // oturum tek gece sayılır, api_contract §2 "marathon_5").
      const nk = new Date(Date.parse(m.played_at) - 6 * 3600 * 1000)
        .toISOString().slice(0, 10);
      const nb = nights.get(nk) || { n: 0, last: null };
      nb.n++; nb.last = m.id;
      nights.set(nk, nb);
      if (nb.n === 5) add("marathon_5", nb.last);

      // İlişkisel rozetler: aynı rakibe / aynı arkadaşla 6 galibiyet (tek seferlik).
      if (win) {
        for (const other of m.participants) {
          if (other.player_id === id) continue;
          const tally = other.team === me.team ? mateWins : foeWins;
          const key = other.team === me.team ? "duo_6" : "nemesis_6";
          const v = (tally.get(other.player_id) || 0) + 1;
          tally.set(other.player_id, v);
          if (v === 6 && !acc.has(key)) add(key, m.id);
        }
      }

      // Maçın en'leri: NULL aday değil, EŞİTLİKTE eşit olan herkes alır.
      // Rekor sınıfında best_value = o maçtaki metrik değeri (contract §2).
      // Dönüş değeri `perfect_quad` için gerekir: dört bileşenin AYNI maçta
      // birden alınıp alınmadığı buradan bilinir.
      const statBadge = (key, fn) => {
        const nums = m.participants.map(fn).filter(v => typeof v === "number");
        const v = fn(me);
        const top = nums.length > 0 && typeof v === "number" && v === Math.max(...nums);
        if (top) add(key, m.id, v);
        return top;
      };
      statBadge("vision", x => (x.stats ? x.stats.vision_score : null));
      const gotDamage = statBadge("damage", x => (x.stats ? x.stats.damage_to_champs : null));
      const gotGold = statBadge("gold", x => (x.stats ? x.stats.gold : null));
      const gotCs = statBadge("cs_per_min", x =>
        m.duration_s > 0 && x.stats && typeof x.stats.cs === "number"
          ? x.stats.cs / (m.duration_s / 60) : null);

      // MVP: kazanan takımın en yüksek perf'lisi; kırılım perf → kills → assists
      // → az deaths → küçük player_id.
      const winners = m.participants
        .filter(x => x.team === m.winner_team && perfProxy(x) !== null)
        .sort((a, b) =>
          perfProxy(b) - perfProxy(a) ||
          b.stats.kills - a.stats.kills ||
          b.stats.assists - a.stats.assists ||
          a.stats.deaths - b.stats.deaths ||
          a.player_id - b.player_id);
      const gotMvp = winners.length > 0 && winners[0].player_id === id;
      if (gotMvp) add("mvp", m.id);
      // Kusursuz Dörtlük (ID 28): MVP + en yüksek hasar + en çok gold + en
      // yüksek CS/dk AYNI maçta. Bileşenler kendi rozetlerinin kuralıyla ölçülür,
      // biri hesaplanamıyorsa (statBadge false döner) o maç bu rozetin dışındadır.
      if (gotMvp && gotDamage && gotGold && gotCs) add("perfect_quad", m.id);

      if (me.stats && me.stats.deaths === 0) add("deathless", m.id);

      // Anlatısal eşikler: bir maçta 20+ kill, KDA >= 10.
      if (me.stats && typeof me.stats.kills === "number" && me.stats.kills >= 20)
        add("kill_20", m.id);
      if (me.stats && ["kills", "deaths", "assists"].every(f => typeof me.stats[f] === "number")
        && (me.stats.kills + me.stats.assists) / Math.max(1, me.stats.deaths) >= 10)
        add("kda_10", m.id);

      // Comeback: kazandı + 10 gold'un hepsi non-null + kazananın toplamı küçük.
      const golds = m.participants.map(x => (x.stats ? x.stats.gold : null));
      if (win && golds.every(g => typeof g === "number")) {
        const sum = (team) => m.participants
          .filter(x => x.team === team).reduce((a, x) => a + x.stats.gold, 0);
        if (sum(m.winner_team) < sum(m.winner_team === 100 ? 200 : 100)) add("comeback", m.id);
      }

      // Koridor hâkimi: aynı rolde KARŞI takımda tam 1 rakip + perf oranı >= 1.5.
      // best_value = oran (contract §2 "role_duel").
      const mineP = perfProxy(me);
      if (me.position && mineP !== null) {
        const foes = m.participants.filter(x => x.team !== me.team && x.position === me.position);
        const foeP = foes.length === 1 ? perfProxy(foes[0]) : null;
        if (foeP !== null && foeP > 0 && mineP / foeP >= 1.5) add("role_duel", m.id, mineP / foeP);
      }

      // Talihsiz kahraman: kaybeden takımın TEK BAŞINA en yüksek perf'lisi
      // (bench_2'nin aynası; eşitlikte rozet yok).
      const loseTeam = m.winner_team === 100 ? 200 : 100;
      if (!win) {
        const lp = m.participants.filter(x => x.team === loseTeam).map(perfProxy);
        const top = lp.every(v => v !== null) ? Math.max(...lp) : null;
        if (top !== null && lp.filter(v => v === top).length === 1 && mineP === top)
          add("tragic_hero", m.id);
      }

      // Kişisel rekorlar: en az 5 ÖNCEKİ karşılaştırılabilir maç + kesin aşma.
      if (mineP !== null) {
        if (perfSeen >= 5 && mineP > bestPerf) add("pr_perf", m.id, mineP);
        perfSeen++;
        if (bestPerf === null || mineP > bestPerf) bestPerf = mineP;
      }
      const dpm = m.duration_s > 0 && me.stats && typeof me.stats.damage_to_champs === "number"
        ? me.stats.damage_to_champs / (m.duration_s / 60) : null;
      if (dpm !== null) {
        if (dpmSeen >= 5 && dpm > bestDpm) add("pr_damage", m.id, dpm);
        dpmSeen++;
        if (bestDpm === null || dpm > bestDpm) bestDpm = dpm;
      }

      // Ayrık bloklar: 3 galibiyet / 3 mağlubiyet / 2 bench maçı tamamlanınca
      // sayaç sıfırlanır (GÖREV 24 eşikleri).
      winRun = win ? winRun + 1 : 0;
      if (winRun === 3) { add("win_streak_3", m.id); winRun = 0; }
      loseRun = win ? 0 : loseRun + 1;
      if (loseRun === 3) { add("lose_streak_3", m.id); loseRun = 0; }

      const team = m.participants.filter(x => x.team === me.team);
      const perfs = team.map(perfProxy);
      const comparable = perfs.every(v => v !== null) && mineP !== null;
      const lowest = comparable && perfs.filter(v => v === Math.min(...perfs)).length === 1
        && mineP === Math.min(...perfs);
      benchRun = lowest ? benchRun + 1 : 0;
      if (benchRun === 2) { add("bench_2", m.id); benchRun = 0; }
    }

    // Rulet üçlüsü: katalogdaki TEK istisna — status='roulette' maçlardan
    // türetilir (contract §2). Mock'ta atama kaydındaki bought/won bayrakları
    // "iki eşya da envanterde" / "+ takım kazandı" anlamını taşır.
    let rouletteWins = 0;
    curIdx = -1;                  // rulet maçları ayrı bir kronoloji (seri sayacı sıfırlanır)
    for (const m of matches.filter(x => x.status === "roulette" && x.roulette)
      .sort((a, b) => Date.parse(a.played_at) - Date.parse(b.played_at))) {
      curIdx++;
      const a = (m.roulette.assignments || []).filter(x => x.player_id === id)[0];
      if (!a) continue;
      if (a.bought === true) add("roulette_complete", m.id);
      if (a.won === true) {
        add("roulette_winner", m.id);
        rouletteWins++;
        if (rouletteWins === 5) add("gambler", m.id);
      }
    }

    // İlerleme (contract §2): kilometre, kimlik, ilişkisel, AÇIK seri, gambler.
    const maxOf = (map) => (map.size ? Math.max(...map.values()) : 0);
    const prog = {
      veteran_10: { current: played, target: 10 },
      veteran_20: { current: played, target: 20 },
      veteran_50: { current: played, target: 50 },
      versatile: { current: roles.size, target: 5 },
      nemesis_6: { current: maxOf(foeWins), target: 6 },
      duo_6: { current: maxOf(mateWins), target: 6 },
      win_streak_3: { current: winRun, target: 3 },
      lose_streak_3: { current: loseRun, target: 3 },
      bench_2: { current: benchRun, target: 2 },
      gambler: { current: rouletteWins, target: 5 },
    };

    // SENARYO: tam vitrin + kademe yolları. Sentetik sayaçlar acc'ye YAZILIR ki
    // kademe hesabı gerçek yolun aynısından (tierOf) geçsin.
    if (id === BADGES_FULL_PLAYER && mine.length) {
      const lastId = mine[mine.length - 1].id;
      // Hedef SAYAÇLAR altı kademenin hepsini tek profilde gösterir (eşikler:
      // standart 1/3/5/8/12, nadir 1/2/3/4/6):
      //   mvp 12 + görev TAMAM (3 seri)  = STELLAR
      //   gold 12 + görev 2/3            = DIAMOND (göreve 1 kaldı)
      //   cs_per_min 8 = PLATINUM · vision 5 = GOLD · role_duel 3 = SILVER
      //   damage 1 = BRONZE · perfect_quad 4 = PLATINUM (NADİR ölçek)
      const COUNTS = {
        mvp: 12, gold: 12, cs_per_min: 8, vision: 5, role_duel: 3, damage: 1,
        perfect_quad: 4,
      };
      BADGE_CATALOG.forEach((c, i) => {
        const want = COUNTS[c.key];
        const cur = acc.get(c.key);
        if (want != null) {
          // KADEMELİ rozetlerde sayaç sentetik değere SABİTLENİR (gerçek sayı
          // daha büyük olsa bile): amaç altı kademenin HEPSİNİ tek profilde
          // göstermek; gerçek sayı bırakılsa bazı rozetler aynı kademede
          // yığılıp gümüş/bronz yolu hiç denenmezdi.
          const best = cur && cur.best_match_id != null ? cur : null;
          acc.set(c.key, {
            count: want, last_match_id: lastId,
            best_match_id: best ? best.best_match_id : lastId,
            best_value: best ? best.best_value : +(1.4 + i / 10).toFixed(2),
            run: 0, best_run: cur ? cur.best_run : 0, runEnd: -2,
          });
        } else if (!cur) {
          const measurable = c.cls === "record" || c.cls === "role" || c.cls === "personal";
          acc.set(c.key, {
            count: c.one ? 1 : 1 + (i % 3), last_match_id: lastId,
            best_match_id: measurable ? lastId : null,
            best_value: measurable ? +(1.2 + i / 10).toFixed(2) : null,
            run: 0, best_run: 0, runEnd: -2,
          });
        }
      });
      // Stellar GÖREVİ yolları (iki yol da denenebilsin): mvp'de görev
      // TAMAMLANMIŞ (ardışık 3 → stellar), gold'da göreve 1 KALMIŞ (2/3 →
      // elmasta kalır ve baloncukta görev satırı görünür).
      const RUNS = {
        mvp: 3, gold: 2, cs_per_min: 2, vision: 1, role_duel: 1, damage: 1,
        perfect_quad: 1,
      };
      Object.keys(RUNS).forEach(k => {
        const e = acc.get(k);
        if (e) e.best_run = RUNS[k];
      });
    }

    const rows = BADGE_CATALOG.map(c => {
      const e = acc.get(c.key) ||
        { count: 0, last_match_id: null, best_match_id: null, best_value: null };
      // Kilitli kademeli rozet (count: 0): tier null, rate 0.0 (hiç maç yoksa
      // null), next_tier_count = bronz eşiği (1).
      const tier = !c.tiered ? { tier: null, rate: null, next_tier_count: null, stellar_quest: null }
        : e.count > 0 ? tierOf(e.count, played, c.scale, e.best_run)
          : { tier: null, rate: played > 0 ? 0 : null, next_tier_count: TIER_BRONZE, stellar_quest: null };
      const p = prog[c.key] || null;
      return {
        key: c.key,
        count: e.count,
        last_match_id: e.last_match_id,
        best_match_id: e.best_match_id,
        best_value: e.best_value,
        tier: tier.tier,
        rate: tier.rate,
        next_tier_count: tier.next_tier_count,
        stellar_quest: tier.stellar_quest,
        progress: p ? { current: p.current, target: p.target } : null,
      };
    }).filter(r => includeLocked || r.count > 0);

    // İleri uyumluluk yolu: UI tanımadığı anahtarı sessizce atlar.
    if (id === BADGES_FULL_PLAYER && mine.length) {
      rows.push({
        key: "future_badge_unknown", count: 2, last_match_id: mine[mine.length - 1].id,
        best_match_id: null, best_value: null, tier: null, rate: null,
        next_tier_count: null, stellar_quest: null, progress: null,
      });
    }
    return { player_id: id, matches_played: played, badges: rows };
  }

  // ── Rozet kataloğu (GÖREV 24) ──
  // GET /badges: salt-okur, global. holders = o rozetten en az 1 taşıyan oyuncu
  // sayısı; roster_size = en az 1 valid maçı olan oyuncu sayısı (hiç oynamamış
  // kayıt nadirliği şişirmesin). Per-player hesapların saf toplamıdır.
  function badgeCatalogPayload() {
    const roster = players.filter(p => matches.some(m =>
      m.status === "valid" && m.participants.some(x => x.player_id === p.id)));
    const holders = new Map();
    for (const p of roster) {
      const b = playerBadges(p.id, false);
      for (const row of (b ? b.badges : [])) {
        if (row.count > 0) holders.set(row.key, (holders.get(row.key) || 0) + 1);
      }
    }
    const size = roster.length;
    return {
      roster_size: size,
      badges: BADGE_CATALOG.map((c, i) => {
        const n = holders.get(c.key) || 0;
        return {
          id: i + 1, key: c.key, class: c.cls, source: c.src,
          tiered: c.tiered, tier_scale: c.tiered ? (c.scale || "standard") : null,
          one_time: c.one,
          holders: n, holders_pct: size > 0 ? +((n / size) * 100).toFixed(1) : 0,
        };
      }),
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
      // Aday = pencerede o rolde oynamış VE rol evreninde o rolde rating'i olan
      // (contract: role_rating_history). İkinci koşul EMPTY_ROLE bayrağıyla mock'un
      // kendi içinde tutarlı kalmasını sağlar (rol boşsa Enler kartı da boş çıkar).
      const cand = rows.filter(x => x.e.roles.get(role) &&
        (((x.p.role_ratings || {})[role] || {}).matches > 0));
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

  // ── Rulet oturumu (GÖREV 23) ──
  // api_contract §4.5: en fazla 1 açık oturum — başarılı POST öncekini iptal
  // eder (mock'ta üzerine yazmak aynı kapıya çıkar). GET /roulette/current
  // yalnız AÇIK oturumu döner; yukarıdaki bağlı (linked) maçın oturumu (id 4)
  // kapalıdır, burada görünmez.
  let rouletteSession = null;   // {session_id, created_at, assignments}
  let nextSessionId = 5;

  // Contract'taki şekil doğrulaması (tamamı 422 + Türkçe detail). "Tamamlanmış
  // eşya" kontrolü BİLEREK yok: havuz süzgeci istemcidedir, backend ham id saklar.
  function validateRoulette(body) {
    const asg = body && body.assignments;
    if (!Array.isArray(asg) || asg.length !== 10)
      return "Rulet oturumu tam 10 atama içermeli.";
    const pids = new Set(), champs = new Set();
    for (const a of asg) {
      if (!a || typeof a !== "object") return "Atama kaydı geçersiz.";
      if (!players.some(p => p.id === a.player_id))
        return `Bilinmeyen oyuncu: ${a.player_id}`;
      if (pids.has(a.player_id)) return "Oyuncular birbirinden farklı olmalı.";
      pids.add(a.player_id);
      if (a.team !== 100 && a.team !== 200) return "team 100 ya da 200 olmalı.";
      if (!POS.includes(a.position)) return `Geçersiz rol: ${a.position}`;
      if (typeof a.champion !== "string" || !a.champion.trim())
        return "champion boş olmayan bir metin olmalı.";
      if (champs.has(a.champion)) return "Şampiyonlar 10 kayıtta birbirinden farklı olmalı.";
      champs.add(a.champion);
      if (!Array.isArray(a.item_ids) || a.item_ids.length !== 2 ||
          a.item_ids[0] === a.item_ids[1] ||
          a.item_ids.some(x => !Number.isInteger(x) || x <= 0))
        return "item_ids tam 2 farklı pozitif tam sayı olmalı.";
    }
    for (const team of [100, 200]) {
      const side = asg.filter(a => a.team === team);
      if (side.length !== 5 || new Set(side.map(a => a.position)).size !== 5)
        return "Her takımda 5 oyuncu ve 5 rolün her biri tam 1 kez olmalı.";
    }
    return null;
  }

  // ── Collector sağlığı (GÖREV 13) ──
  // api_contract §6: liste last_seen AZALAN sıralıdır; version / outbox_pending /
  // last_ingest_at / last_ingest_game_id nullable'dır. Zaman damgaları İSTEK
  // ANINA göre üretilir: UI göreli metin gösterdiği için ("3 dk önce") sabit
  // tarihler senaryoyu birkaç gün sonra anlamsız kılardı.
  //
  // Senaryo (3 cihaz): (1) çevrimiçi ve outbox temiz, (2) bugün görülmüş ama
  // outbox birikmiş, (3) 3 gündür sinyal yok + sürüm bilinmiyor + hiç maç izi yok.
  const MIN = 60 * 1000, HOUR = 60 * MIN, DAY = 24 * HOUR;
  const agoIso = (ms) => new Date(Date.now() - ms).toISOString().replace(/\.\d+Z$/, "Z");
  const collectorHealth = () => [
    {
      client_id: "Teoman-PC", last_seen: agoIso(3 * MIN), version: "1.5.0",
      outbox_pending: 0, last_ingest_at: agoIso(14 * HOUR), last_ingest_game_id: "6874240007",
    },
    {
      client_id: "Baran-Laptop", last_seen: agoIso(2 * HOUR), version: "1.4.2",
      outbox_pending: 3, last_ingest_at: agoIso(2 * HOUR + 5 * MIN), last_ingest_game_id: "6874240012",
    },
    {
      client_id: "Kaan-PC", last_seen: agoIso(3 * DAY + 2 * HOUR), version: null,
      outbox_pending: null, last_ingest_at: null, last_ingest_game_id: null,
    },
  ];

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

    // Rating tarihçesi (GÖREV 10) — profil grafiğinin verisi.
    const histPath = path.match(/^\/players\/(\d+)\/rating-history$/);
    if (method === "GET" && histPath) {
      const h = ratingHistory(Number(histPath[1]));
      return h ? json(h) : err(404, "Oyuncu bulunamadı.");
    }

    // Rozetler (GÖREV 11+12) — profil vitrininin verisi. GÖREV 24: kilitliler
    // ?include_locked=true ile gelir (varsayılan false = yalnız kazanılmışlar).
    const badgePath = path.match(/^\/players\/(\d+)\/badges(?:\?(.*))?$/);
    if (method === "GET" && badgePath) {
      const locked = /(^|&)include_locked=(true|1)(&|$)/.test(badgePath[2] || "");
      const b = playerBadges(Number(badgePath[1]), locked);
      return b ? json(b) : err(404, "Oyuncu bulunamadı.");
    }

    // Rozet kataloğu (GÖREV 24) — nadirlik göstergesinin kaynağı.
    if (method === "GET" && path === "/badges") return json(badgeCatalogPayload());

    if (method === "GET" && path === "/leaderboard")
      return json(
        [...players]
          .sort((a, b) => b.rating.score - a.rating.score)
          .map(p => ({ ...p, rank_delta: RANK_DELTA[p.id] === undefined ? null : RANK_DELTA[p.id] }))
      );

    if (method === "GET" && path === "/highlights/weekly") return json(weeklyHighlights());

    if (method === "GET" && path === "/nemesis") return json(nemesisPayload());

    // Collector sağlığı (GÖREV 13). Heartbeat'i UI atmaz (collector atar), yine de
    // contract §6 ile senkron kalsın diye stub'ta duruyor.
    if (method === "GET" && path === "/health/collectors") return json(collectorHealth());

    if (method === "POST" && path === "/health/heartbeat") {
      let body = {};
      try { body = JSON.parse(opts.body); } catch { /* gövde JSON değil */ }
      const cid = typeof body.client_id === "string" ? body.client_id.trim() : "";
      if (!cid || cid.length > 64) return err(422, "client_id zorunlu (en fazla 64 karakter).");
      return json({ ok: true });
    }

    // Tek maç (GÖREV 10): liste elemanıyla BİREBİR aynı şekil. Bu dal listeden
    // ÖNCE gelmeli — aşağıdaki startsWith("/matches") /matches/{id}'yi de yakalar.
    const oneMatch = path.match(/^\/matches\/(\d+)$/);
    if (method === "GET" && oneMatch) {
      const m = matches.find(x => x.id === Number(oneMatch[1]));
      return m ? json(m) : err(404, "Maç bulunamadı.");
    }

    if (method === "GET" && path.startsWith("/matches")) return json(matches);

    if (method === "POST" && path === "/balance") {
      const body = JSON.parse(opts.body);
      const ids = [...new Set(body.player_ids || [])];
      if (ids.length !== 10) return err(422, "Dengeleme için tam 10 farklı oyuncu seçilmelidir.");
      return json({ engine_version: "openskill-pl-blend20-v1", suggestions: balanceSuggestions(ids) });
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
        engine_version: "openskill-pl-blend20-v1",
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

    // ── Rulet uçları (GÖREV 23, api_contract §4.5) ──
    if (method === "POST" && path === "/roulette") {
      let body = {};
      try { body = JSON.parse(opts.body); } catch { /* gövde JSON değil */ }
      const bad = validateRoulette(body);
      if (bad) return err(422, bad);
      // Önceki açık oturum(lar) iptal olur: üzerine yazmak mock'ta yeterli.
      rouletteSession = {
        session_id: nextSessionId++,
        created_at: new Date().toISOString().replace(/\.\d+Z$/, "Z"),
        assignments: body.assignments,
      };
      return json({
        session_id: rouletteSession.session_id,
        created_at: rouletteSession.created_at,
      }, 201);
    }

    if (method === "GET" && path === "/roulette/current")
      return json({ session: rouletteSession });

    // Liste temizleme (Teoman, 2026-08-19): mock'ta tek açık oturum değişkeni
    // var (linked'e karşılık gelen önceden gömülü rulet maçı ayrı, `matches`
    // fixture'ında sabit — dokunulmaz); açık oturum varsa 1 silinir, yoksa 0.
    if (method === "POST" && path === "/roulette/clear") {
      const deleted = rouletteSession ? 1 : 0;
      rouletteSession = null;
      return json({ deleted });
    }

    // fix-3: unlink İDARİ uç oldu (api_contract §4.5 + "Korunan uçların TAM
    // listesi") — arayüzü de maç detayından Kontrol Paneli'ne taşındı.
    const unlinkMatch = path.match(/^\/matches\/(\d+)\/roulette\/unlink$/);
    if (method === "POST" && unlinkMatch) {
      const denied = adminGuard(opts);
      if (denied) return denied;
      const match = matches.find(m => m.id === Number(unlinkMatch[1]));
      if (!match) return err(404, "Maç bulunamadı.");
      if (match.status !== "roulette") return err(409, "Bu maç rulet maçına bağlı değil.");
      match.status = "valid";
      match.roulette = null;
      // Gerçekte HER İKİ evren auto-replay koşar ve maç rating'e girer; mock'ta
      // rating_change null kalır (UI "—" yolunu zaten bilir), yalnız sayaç döner.
      const replayed = matches.filter(m => m.status === "valid").length;
      return json({ status: "valid", matches_replayed: replayed, role_matches_replayed: replayed });
    }

    // İdari uçlar (fix-2): X-API-Key'e EK olarak X-Admin-Key ister.
    // adminGuard null dönerse anahtar geçerlidir, aksi halde hazır hata yanıtı.
    const voidMatch = path.match(/^\/matches\/(\d+)\/void$/);
    if (method === "POST" && voidMatch) {
      const denied = adminGuard(opts);
      if (denied) return denied;
      const match = matches.find(m => m.id === Number(voidMatch[1]));
      if (!match) return err(404, "Maç bulunamadı.");
      // api_contract §3 (Teoman, 2026-08-19): rulet maçı zaten rating dışıdır,
      // void anlamsız → 409 (gerçek backend'le parite; unlink 409'uyla aynı kalıp).
      if (match.status === "roulette")
        return err(409, "Maç bir rulet maçı; rulet maçları zaten rating'e katılmıyor, void edilemez.");
      if (match.status === "void") return err(422, "Bu maç zaten void işaretli.");
      match.status = "void";
      // fix-3: yanıt contract §3'teki TAM şekli taşır (rol evreni sayacı +
      // engine_version); eksik alanlar UI'da sessizce "undefined" oluyordu.
      const valid = matches.filter(m => m.status === "valid");
      return json({
        match_id: match.id, status: "void",
        matches_replayed: valid.length,
        role_matches_replayed: valid.filter(roleEligible).length,
        engine_version: "openskill-pl-blend20-v1",
      });
    }

    // Void'un simetriği (api_contract §3, fix-2): yalnız void maçta çalışır.
    const unvoidMatch = path.match(/^\/matches\/(\d+)\/unvoid$/);
    if (method === "POST" && unvoidMatch) {
      const denied = adminGuard(opts);
      if (denied) return denied;
      const match = matches.find(m => m.id === Number(unvoidMatch[1]));
      if (!match) return err(404, "Maç bulunamadı.");
      if (match.status !== "void")
        return err(409, `Maç void değil (durum: ${match.status}); unvoid yalnız void maçlarda çalışır.`);
      match.status = "valid";
      const valid = matches.filter(m => m.status === "valid");
      return json({
        match_id: match.id, status: "valid",
        matches_replayed: valid.length,
        role_matches_replayed: valid.filter(roleEligible).length,
        engine_version: "openskill-pl-blend20-v1",
      });
    }

    // Admin anahtarı doğrulama ucu (api_contract §5): 204, yan etkisiz.
    if (method === "GET" && path === "/admin/ping") {
      const denied = adminGuard(opts);
      if (denied) return denied;
      return new Response(null, { status: 204 });
    }

    if (method === "POST" && path === "/admin/replay") {
      const denied = adminGuard(opts);
      if (denied) return denied;
      const valid = matches.filter(m => m.status === "valid");
      return json({
        matches_replayed: valid.length,
        role_matches_replayed: valid.filter(roleEligible).length,
        engine_version: "openskill-pl-blend20-v1",
      });
    }

    // Oyuncu ekleme (api_contract §2): fix-3'te İDARİ uç oldu. Web UI'da
    // arayüzü henüz yok; mock'ta contract paritesi için duruyor.
    if (method === "POST" && path === "/players") {
      const denied = adminGuard(opts);
      if (denied) return denied;
      let body = {};
      try { body = JSON.parse(opts.body); } catch { /* gövde JSON değil */ }
      const name = String(body.display_name == null ? "" : body.display_name).trim();
      if (!name) return err(422, "display_name zorunlu.");
      const p = {
        id: Math.max(...players.map(x => x.id)) + 1,
        display_name: name,
        riot_id: body.riot_id || null,
        puuid: null,
        matches_played: 0,
        rating: { mu: 25.0, sigma: 8.333, ordinal: 0.0, perf_avg: 1.0, score: 0.0 },
        role_ratings: POS.reduce((acc, r) => { acc[r] = defaultRole(); return acc; }, {}),
      };
      players.push(p);
      return json({ id: p.id }, 201);
    }

    // Oyuncu adı düzeltme (Kontrol Paneli): fix-3'te İDARİ uç oldu — normal
    // X-API-Key artık YETMEZ, X-Admin-Key de gerekir (gerçek backend'le parite).
    const patchPlayer = path.match(/^\/players\/(\d+)$/);
    if (method === "PATCH" && patchPlayer) {
      const denied = adminGuard(opts);
      if (denied) return denied;
      const p = players.find(x => x.id === Number(patchPlayer[1]));
      if (!p) return err(404, "Oyuncu bulunamadı.");
      let body = {};
      try { body = JSON.parse(opts.body); } catch { /* gövde JSON değil */ }
      if (body.display_name !== undefined && body.display_name !== null) {
        const name = String(body.display_name).trim();
        if (!name) return err(422, "display_name boş olamaz.");
        p.display_name = name;
      }
      return json({ id: p.id, display_name: p.display_name, riot_id: p.riot_id });
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
        // Elle girilen maç rulet oturumuna bağlanmaz (api_contract §3: null).
        roulette: null,
        participants: body.participants.map(pt => {
          const p = players.find(x => x.id === pt.player_id);
          const won = pt.team === body.winner_team;
          const delta = won ? 0.8 : -0.8;
          const mu = p ? p.rating.mu : 25;
          const sigma = p ? p.rating.sigma : 8.333;
          const sigmaAfter = +Math.max(0.5, sigma - 0.05).toFixed(3);
          // GÖREV 18: manuel girişte stat yok → perf_score NULL → P_avg oynamaz;
          // score farkı yalnız mu/sigma hareketinden gelir (contract'la tutarlı).
          const pavg = p && p.rating.perf_avg != null ? p.rating.perf_avg : 1.0;
          return {
            player_id: pt.player_id,
            display_name: p ? p.display_name : "?",
            team: pt.team,
            position: pt.position,
            champion: null,
            stats: { kills: null, deaths: null, assists: null, gold: null,
                     cs: null, damage_to_champs: null, vision_score: null },
            // Manuel girişte envanter bilinmez (GÖREV 14): contract'ta NULL bunu anlatır.
            items: null,
            rating_change: {
              mu_before: +mu.toFixed(2),
              sigma_before: +sigma.toFixed(3),
              mu_after: +(mu + delta).toFixed(2),
              sigma_after: sigmaAfter,
              score_before: effScoreAt(mu, sigma, pavg),
              score_after: effScoreAt(mu + delta, sigmaAfter, pavg),
            },
          };
        }),
      };
      matches.unshift(match);
      return json({ match_id: match.id, duplicate: false }, 201);
    }

    return err(404, "Böyle bir endpoint yok: " + path);
  };

  // ── Seçim danışmanı mock verisi (GÖREV 21) ──
  // Canlıda bu veriler STATİK DOSYALARDAN gelir (assets/meta/tiers.json +
  // counters.json + champions.json tags/info — api_contract §8); mock modunda
  // dosyalar olmayabilir diye makul sahteleri buradan verilir (app.js USE_MOCK
  // iken doğrudan window.MOCK_ADVISOR okur, fetch yolu hiç koşmaz).
  // tiers YENİ şemadadır ({name, win_rate, pick_rate}); MIDDLE B kademesi eski
  // düz-string biçimi taşır → geriye uyum yolu mock'ta da görünür/denenebilir.
  // Adlar bilerek maç geçmişindeki CHAMPS havuzuyla kesişir: grup rozeti
  // ("Teoman: 3W-1L") önerilerde gerçekten belirir.
  window.MOCK_ADVISOR = {
    tiers: {
      top: {
        S: [{ name: "Darius", win_rate: 0.531, pick_rate: 0.082 },
            { name: "Garen", win_rate: 0.524, pick_rate: 0.071 }],
        A: [{ name: "Malphite", win_rate: 0.517, pick_rate: 0.055 },
            { name: "Sett", win_rate: 0.512, pick_rate: 0.049 }],
        B: [{ name: "Teemo", win_rate: 0.498, pick_rate: 0.038 }],
      },
      jungle: {
        S: [{ name: "Vi", win_rate: 0.528, pick_rate: 0.077 },
            { name: "Warwick", win_rate: 0.535, pick_rate: 0.064 }],
        A: [{ name: "Lee Sin", win_rate: 0.489, pick_rate: 0.118 }],
        B: [{ name: "Master Yi", win_rate: 0.505, pick_rate: 0.042 }],
      },
      middle: {
        S: [{ name: "Ahri", win_rate: 0.521, pick_rate: 0.096 },
            { name: "Orianna", win_rate: 0.514, pick_rate: 0.058 }],
        A: [{ name: "Galio", win_rate: 0.526, pick_rate: 0.034 },
            { name: "Vladimir", win_rate: 0.508, pick_rate: 0.041 }],
        B: ["Yasuo", "Lux", "Pantheon"],
      },
      bottom: {
        S: [{ name: "Jinx", win_rate: 0.533, pick_rate: 0.124 }],
        A: [{ name: "Ezreal", win_rate: 0.492, pick_rate: 0.147 },
            { name: "Ashe", win_rate: 0.515, pick_rate: 0.066 }],
        B: [{ name: "Caitlyn", win_rate: 0.501, pick_rate: 0.088 }],
      },
      utility: {
        S: [{ name: "Thresh", win_rate: 0.512, pick_rate: 0.101 },
            { name: "Leona", win_rate: 0.527, pick_rate: 0.079 }],
        A: [{ name: "Lulu", win_rate: 0.519, pick_rate: 0.062 }],
        B: [{ name: "Morgana", win_rate: 0.503, pick_rate: 0.057 }],
      },
    },
    counters: {
      top: {
        Darius: [{ champion: "Malphite", games: 412, win_rate_against: 0.547 },
                 { champion: "Teemo", games: 388, win_rate_against: 0.521 }],
        Garen: [{ champion: "Darius", games: 356, win_rate_against: 0.538 }],
      },
      jungle: {
        "Lee Sin": [{ champion: "Warwick", games: 290, win_rate_against: 0.552 }],
      },
      middle: {
        Yasuo: [{ champion: "Ahri", games: 512, win_rate_against: 0.543 },
                { champion: "Lux", games: 301, win_rate_against: 0.518 }],
        // Ters yön senaryosu: Yasuo, Vladimir'in listesinde DÜŞÜK winrate ile
        // geçer → motor "Vladimir, Yasuo'ya karşı iyi" çıkarımını buradan yapar.
        Vladimir: [{ champion: "Yasuo", games: 264, win_rate_against: 0.462 }],
      },
      bottom: {
        Jinx: [{ champion: "Caitlyn", games: 433, win_rate_against: 0.529 }],
      },
      utility: {
        Thresh: [{ champion: "Morgana", games: 377, win_rate_against: 0.541 }],
      },
    },
    // champions.json'a paralel veri işinin ekleyeceği tags/info alanlarının
    // taklidi (DD şeması: tags sınıf listesi, info 0-10 skalası).
    champ_info: {
      Ahri: { tags: ["Mage", "Assassin"], info: { attack: 3, defense: 4, magic: 8, difficulty: 5 } },
      Orianna: { tags: ["Mage", "Support"], info: { attack: 4, defense: 3, magic: 9, difficulty: 7 } },
      Galio: { tags: ["Tank", "Mage"], info: { attack: 1, defense: 10, magic: 6, difficulty: 5 } },
      Vladimir: { tags: ["Mage"], info: { attack: 2, defense: 6, magic: 8, difficulty: 7 } },
      Yasuo: { tags: ["Fighter", "Assassin"], info: { attack: 8, defense: 4, magic: 4, difficulty: 10 } },
      Lux: { tags: ["Mage", "Support"], info: { attack: 2, defense: 4, magic: 9, difficulty: 5 } },
      Pantheon: { tags: ["Fighter", "Assassin"], info: { attack: 9, defense: 4, magic: 3, difficulty: 4 } },
      Darius: { tags: ["Fighter", "Tank"], info: { attack: 9, defense: 5, magic: 1, difficulty: 2 } },
      Garen: { tags: ["Fighter", "Tank"], info: { attack: 7, defense: 7, magic: 1, difficulty: 5 } },
      Malphite: { tags: ["Tank", "Fighter"], info: { attack: 5, defense: 9, magic: 7, difficulty: 2 } },
      Sett: { tags: ["Fighter", "Tank"], info: { attack: 8, defense: 5, magic: 1, difficulty: 2 } },
      Teemo: { tags: ["Marksman", "Assassin"], info: { attack: 5, defense: 3, magic: 7, difficulty: 6 } },
      Vi: { tags: ["Fighter", "Assassin"], info: { attack: 8, defense: 5, magic: 3, difficulty: 4 } },
      Warwick: { tags: ["Fighter", "Tank"], info: { attack: 9, defense: 5, magic: 3, difficulty: 3 } },
      "Lee Sin": { tags: ["Fighter", "Assassin"], info: { attack: 8, defense: 5, magic: 3, difficulty: 6 } },
      "Master Yi": { tags: ["Assassin", "Fighter"], info: { attack: 10, defense: 4, magic: 2, difficulty: 4 } },
      Jinx: { tags: ["Marksman"], info: { attack: 9, defense: 2, magic: 4, difficulty: 6 } },
      Ezreal: { tags: ["Marksman", "Mage"], info: { attack: 7, defense: 2, magic: 6, difficulty: 7 } },
      Ashe: { tags: ["Marksman", "Support"], info: { attack: 7, defense: 3, magic: 2, difficulty: 4 } },
      Caitlyn: { tags: ["Marksman"], info: { attack: 8, defense: 2, magic: 2, difficulty: 6 } },
      Thresh: { tags: ["Support", "Fighter"], info: { attack: 5, defense: 6, magic: 6, difficulty: 7 } },
      Leona: { tags: ["Tank", "Support"], info: { attack: 4, defense: 8, magic: 3, difficulty: 4 } },
      Lulu: { tags: ["Support", "Mage"], info: { attack: 4, defense: 5, magic: 7, difficulty: 5 } },
      Morgana: { tags: ["Mage", "Support"], info: { attack: 1, defense: 6, magic: 8, difficulty: 1 } },
    },
  };
})();
