// advisor.js — Seçim danışmanı ANALİZ MOTORU (GÖREV 21). Saf istemci tarafı,
// DOM'suz ve metinsiz: girdiler veri dosyalarından gelir, çıktı yapısal bir
// sonuç nesnesidir; rozetler {type, kind, params} TANIMLAYICILARIDIR — görünen
// metni app.js i18n sözlüğünden kurar (docs/i18n_contract.md).
//
// Sinyaller (CHANGE_REQUESTS GÖREV 21 kaydı):
//   1) Meta tier + win_rate — assets/meta/tiers.json. YENİ şema tier listeleri
//      [{name, win_rate, pick_rate}] taşır; ESKİ düz-string biçimi de okunur
//      (geriye uyum contract gereği: dosya tazelenene dek win_rate bilinmez).
//   2) Kompozisyon açıkları — Data Dragon champions.json `tags` + `info`
//      alanlarından (paralel veri işi ekler; alanlar yoksa sinyal ATLANIR):
//      AD/AP dengesi, öncü (Tank/Fighter) ve taşıyıcı (Marksman) eksikleri.
//   3) Counter — assets/meta/counters.json. Karşı koridor rakibi biliniyorsa:
//      1-3 gerçek kayıt (veri) + TERS YÖN taraması (rakip başka bir şampiyonun
//      listesinde DÜŞÜK winrate ile geçiyorsa o şampiyon rakibe karşı iyidir)
//      + sınıf sezgiseli + tier dolgusu → ~10 kart.
//   4) Early/late — SEZGİSEL (tags/info kuralları); rozeti "sezgisel" işaretli.
//   5) Grup rozeti — GET /matches'tan şampiyon×oyuncu W-L sayımı. SIRALAMAYI
//      ETKİLEMEZ (Teoman kararı): yalnız bilgi rozetidir, skora katılmaz.
//
// Rozet kind sözleşmesi: "data" = gerçek veriye dayalı (dolu kenar),
// "gut" = sezgisel (kesikli kenar), "info" = grup bilgi rozeti.
// Veri dosyalarının HERHANGİ biri yoksa/şema dışıysa ilgili sinyal sessizce
// atlanır; motor hiçbir girişte throw etmez (ekran KIRILMAZ kuralı).
(function () {
  "use strict";

  const ROLES = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"];
  const ROLE_KEY = {
    TOP: "top", JUNGLE: "jungle", MIDDLE: "middle", BOTTOM: "bottom", UTILITY: "utility",
  };
  const TIERS = ["S", "A", "B"];

  // ── Skor sabitleri (version'suz UI sezgiseli — rating motoru DEĞİLDİR) ──
  // Ağırlıklar yalnız kart SIRASINI belirler; sayı ekranda gösterilmez.
  const W_TIER = { S: 3, A: 2, B: 1 };     // meta kademesi
  const W_WR = 20;                          // (win_rate - 0.5) çarpanı
  const W_COUNTER_DIRECT = 2.5;             // gerçek counter kaydı tabanı
  const W_COUNTER_REVERSE = 2.0;            // ters yön taraması tabanı
  const W_COUNTER_WR = 10;                  // counter winrate sapması çarpanı
  const W_CLASS = 1.0;                      // sınıf sezgiseli
  const W_GAP = 1.5;                        // kapattığı açık başına
  const W_TEMPO = 0.25;                     // early/late sezgiseli (küçük itki)
  const AD_AP_GAP_PCT = 25;                 // taraf payı bu yüzdenin altındaysa açık
  const MIN_PICKS_FOR_GAPS = 2;             // açık analizi için asgari seçim
  const DECK_DEFAULT = 8;                   // öneri kartı (5-8 bandının üstü)
  const DECK_COUNTER = 10;                  // bilinen koridor rakibi varsa ~10

  // Sınıf sezgiseli: anahtar sınıf, değeri "karşısında avantajlı olduğu" sınıflar.
  // Koridor bağlamında kaba bir el kuralıdır — rozeti her zaman "sezgisel" çıkar.
  const CLASS_EDGE = {
    Assassin: ["Mage", "Marksman"],
    Tank: ["Assassin"],
    Mage: ["Fighter", "Tank"],
    Marksman: ["Tank"],
    Fighter: ["Assassin"],
  };

  const isStr = (x) => typeof x === "string" && x.trim() !== "";
  const isNum = (x) => typeof x === "number" && isFinite(x);
  const lower = (x) => String(x).toLocaleLowerCase("en");

  // ── Tier verisi (sinyal 1) ────────────────────────────────────
  // Tek girdiyi normalize eder: eski şema düz string, yeni şema {name, win_rate,
  // pick_rate}. Şema dışı değer null döner ve sessizce elenir.
  function normTierEntry(x) {
    if (isStr(x)) return { name: x.trim(), win_rate: null, pick_rate: null };
    if (x && typeof x === "object" && isStr(x.name)) {
      return {
        name: x.name.trim(),
        win_rate: isNum(x.win_rate) ? x.win_rate : null,
        pick_rate: isNum(x.pick_rate) ? x.pick_rate : null,
      };
    }
    return null;
  }

  // tiers.tiers[roleKey] → Map(ad → {tier, win_rate, pick_rate}). Aynı ad iki
  // kademede geçerse İYİ olan kazanır (dosya sırası deterministik).
  function tierIndex(tiers, roleKey) {
    const out = new Map();
    const cell = tiers && typeof tiers === "object" ? tiers[roleKey] : null;
    if (!cell || typeof cell !== "object") return out;
    TIERS.forEach(tier => {
      const arr = Array.isArray(cell[tier]) ? cell[tier] : [];
      arr.forEach(raw => {
        const e = normTierEntry(raw);
        if (!e) return;
        if (!out.has(e.name)) out.set(e.name, { tier, win_rate: e.win_rate, pick_rate: e.pick_rate });
      });
    });
    return out;
  }

  // Rolü bilinmeyen şampiyonun TÜM rollerdeki en iyi kademesi (tehdit tespiti).
  function bestTierAnyRole(tiers, name) {
    let best = null;
    ROLES.forEach(role => {
      const e = tierIndex(tiers, ROLE_KEY[role]).get(name);
      if (e && (!best || TIERS.indexOf(e.tier) < TIERS.indexOf(best.tier))) best = e;
    });
    return best;
  }

  // ── Şampiyon meta verisi (sinyal 2/4) ─────────────────────────
  const champTags = (champInfo, name) => {
    const c = champInfo && name ? champInfo[name] : null;
    return c && Array.isArray(c.tags) ? c.tags.filter(isStr) : [];
  };
  const champInfoOf = (champInfo, name) => {
    const c = champInfo && name ? champInfo[name] : null;
    return c && c.info && typeof c.info === "object" ? c.info : null;
  };

  // ── AD/AP dengesi ─────────────────────────────────────────────
  // DD info.attack / info.magic (0-10) toplanır; pay yüzdedir. `known` = info'su
  // bilinen seçim sayısı — 0 ise çubuk çizilmez (veri yok, sıfır uydurulmaz).
  function damageProfile(picks, champInfo) {
    let ad = 0, ap = 0, known = 0;
    picks.forEach(p => {
      const info = champInfoOf(champInfo, p.champ);
      if (!info || (!isNum(info.attack) && !isNum(info.magic))) return;
      known++;
      ad += isNum(info.attack) ? info.attack : 0;
      ap += isNum(info.magic) ? info.magic : 0;
    });
    const sum = ad + ap;
    return {
      known,
      ad_pct: sum > 0 ? Math.round((ad / sum) * 100) : 0,
      ap_pct: sum > 0 ? Math.round((ap / sum) * 100) : 0,
    };
  }

  // ── Kompozisyon açıkları (kendi takımı) ───────────────────────
  // Her açık {key, kind:"data"} döner: tags/info GERÇEK DD verisidir (sezgisel
  // değil). Bilgi yoksa (info'suz/etiketsiz seçimler) o açık hiç üretilmez.
  function teamGaps(picks, champInfo) {
    const gaps = [];
    const withChamp = picks.filter(p => isStr(p.champ));
    const dmg = damageProfile(withChamp, champInfo);
    if (dmg.known >= MIN_PICKS_FOR_GAPS) {
      if (dmg.ap_pct < AD_AP_GAP_PCT) gaps.push({ key: "ap", kind: "data" });
      if (dmg.ad_pct < AD_AP_GAP_PCT) gaps.push({ key: "ad", kind: "data" });
    }
    const tagged = withChamp.filter(p => champTags(champInfo, p.champ).length);
    if (tagged.length >= MIN_PICKS_FOR_GAPS) {
      const hasTag = (t) => tagged.some(p => champTags(champInfo, p.champ).indexOf(t) !== -1);
      if (!hasTag("Tank") && !hasTag("Fighter")) gaps.push({ key: "front", kind: "data" });
      if (!hasTag("Marksman")) gaps.push({ key: "carry", kind: "data" });
    }
    return { gaps, damage: dmg };
  }

  // Aday bir açığı kapatıyor mu? (rozet + skor)
  function closesGap(gapKey, name, champInfo) {
    const tags = champTags(champInfo, name);
    const info = champInfoOf(champInfo, name);
    switch (gapKey) {
      case "ap": return !!info && isNum(info.magic) && info.magic > (isNum(info.attack) ? info.attack : 0);
      case "ad": return !!info && isNum(info.attack) && info.attack > (isNum(info.magic) ? info.magic : 0);
      case "front": return tags.indexOf("Tank") !== -1 || tags.indexOf("Fighter") !== -1;
      case "carry": return tags.indexOf("Marksman") !== -1;
      default: return false;
    }
  }

  // ── Early/late sezgiseli (sinyal 4) ───────────────────────────
  // Kaba kurallar; sayısal kaynak v2 araştırması (CHANGE_REQUESTS). null dönebilir.
  function tempoOf(name, champInfo) {
    const tags = champTags(champInfo, name);
    const info = champInfoOf(champInfo, name);
    if (tags.indexOf("Assassin") !== -1) return "early";
    if (tags.indexOf("Marksman") !== -1) return "late";
    if (info && isNum(info.attack) && isNum(info.defense) && info.attack >= 8 && info.defense <= 4
        && tags.indexOf("Fighter") !== -1) return "early";
    if (info && isNum(info.magic) && info.magic >= 9) return "late";
    return null;
  }

  // ── Counter verisi (sinyal 3) ─────────────────────────────────
  // counters[roleKey][rakip] → [{champion, games, win_rate_against}] (kayıttaki
  // şampiyonun RAKİBE karşı winrate'i; yüksek = iyi counter).
  function counterRecords(counters, roleKey, enemyName) {
    const cell = counters && typeof counters === "object" ? counters[roleKey] : null;
    const arr = cell && typeof cell === "object" && Array.isArray(cell[enemyName])
      ? cell[enemyName] : [];
    return arr.filter(r => r && isStr(r.champion) && isNum(r.win_rate_against));
  }

  // TERS YÖN: rakip E, K'nin counter listesinde DÜŞÜK winrate ile geçiyorsa
  // (E, K'ye karşı kötü) → K, E'ye karşı iyidir; pct = 1 - win_rate_against.
  function reverseCounters(counters, roleKey, enemyName) {
    const cell = counters && typeof counters === "object" ? counters[roleKey] : null;
    if (!cell || typeof cell !== "object") return [];
    const out = [];
    Object.keys(cell).forEach(key => {
      if (key === enemyName || !Array.isArray(cell[key])) return;
      cell[key].forEach(r => {
        if (r && r.champion === enemyName && isNum(r.win_rate_against) && r.win_rate_against < 0.5) {
          out.push({ champion: key, win_rate_against: 1 - r.win_rate_against });
        }
      });
    });
    return out;
  }

  // ── Grup rozeti (sinyal 5 — SIRALAMAYA GİRMEZ) ───────────────
  // GET /matches yanıtından şampiyon×oyuncu W-L sayımı. Şampiyon başına EN ÇOK
  // maçlı oyuncunun satırı rozetlik seçilir (eşitlikte galibiyet, sonra ad).
  function buildGroupIndex(matches) {
    const byChamp = new Map(); // ad -> Map(oyuncu -> {wins, losses})
    (Array.isArray(matches) ? matches : []).forEach(m => {
      if (!m || m.status !== "valid" || !Array.isArray(m.participants)) return;
      m.participants.forEach(p => {
        if (!p || !isStr(p.champion) || !isStr(p.display_name)) return;
        if (!byChamp.has(p.champion)) byChamp.set(p.champion, new Map());
        const perPlayer = byChamp.get(p.champion);
        if (!perPlayer.has(p.display_name)) perPlayer.set(p.display_name, { wins: 0, losses: 0 });
        const row = perPlayer.get(p.display_name);
        if (p.team === m.winner_team) row.wins++; else row.losses++;
      });
    });
    const out = {}; // ad -> {name, wins, losses}
    byChamp.forEach((perPlayer, champ) => {
      let best = null;
      perPlayer.forEach((row, name) => {
        const cand = { name, wins: row.wins, losses: row.losses };
        const tot = (x) => x.wins + x.losses;
        if (!best || tot(cand) > tot(best) || (tot(cand) === tot(best) &&
            (cand.wins > best.wins || (cand.wins === best.wins && cand.name < best.name))))
          best = cand;
      });
      if (best) out[champ] = best;
    });
    return out;
  }

  // ── Ana analiz ────────────────────────────────────────────────
  // input: {mine: [{champ, role}], enemy: [{champ, role|null}], myIndex,
  //         champInfo, tiers, counters, group, sampleSize}
  // Tüm veri alanları null/eksik olabilir; ilgili sinyal atlanır.
  function analyze(input) {
    const mine = Array.isArray(input.mine) ? input.mine : [];
    const enemy = Array.isArray(input.enemy) ? input.enemy : [];
    const champInfo = input.champInfo && typeof input.champInfo === "object" ? input.champInfo : {};
    const tiers = input.tiers && typeof input.tiers === "object" ? input.tiers : null;
    const counters = input.counters && typeof input.counters === "object" ? input.counters : null;
    const group = input.group && typeof input.group === "object" ? input.group : {};

    const my = teamGaps(mine, champInfo);
    const them = damageProfile(enemy.filter(p => isStr(p.champ)), champInfo);

    // Tehditler: rakip seçimlerinden rolünde (rol bilinmiyorsa herhangi bir rolde)
    // S kademesinde olanlar. Rolü bilinmeyenler ayrıca raporlanır (counter notu).
    const threats = [];
    const unknownRoles = [];
    enemy.forEach(p => {
      if (!isStr(p.champ)) return;
      if (!p.role) unknownRoles.push(p.champ);
      if (!tiers) return;
      const e = p.role ? tierIndex(tiers, ROLE_KEY[p.role]).get(p.champ)
        : bestTierAnyRole(tiers, p.champ);
      if (e && e.tier === "S") threats.push({ name: p.champ, role: p.role || null });
    });

    // ── Öneriler: BEN işaretli satırın rolü için ──
    const meIdx = Number.isInteger(input.myIndex) ? input.myIndex : null;
    const myRole = meIdx != null && mine[meIdx] && ROLES.indexOf(mine[meIdx].role) !== -1
      ? mine[meIdx].role : null;
    const result = {
      damage: { us: my.damage, them },
      gaps: my.gaps,
      threats,
      unknownRoles,
      myRole,
      counterContext: null,
      suggestions: [],
    };
    if (!myRole) return result;

    const roleKey = ROLE_KEY[myRole];
    const tIndex = tiers ? tierIndex(tiers, roleKey) : new Map();

    // Karşı koridor rakibi: rakip listesinde rolü benimkiyle aynı VE şampiyonu
    // seçilmiş satır (ilk eşleşen). Rol "Bilinmiyor" ise koridor eşleşmez.
    const laneFoe = enemy.find(p => p.role === myRole && isStr(p.champ)) || null;
    result.counterContext = laneFoe ? laneFoe.champ : null;

    // Seçilmiş her şampiyon aday havuzundan düşer (iki taraf birden).
    const taken = new Set();
    mine.concat(enemy).forEach(p => { if (isStr(p.champ)) taken.add(lower(p.champ)); });

    // Aday havuzu: rolün tier listesi + (varsa) counter kayıtlarındaki adlar.
    const scores = new Map(); // ad -> {score, badges:[]}
    const ensure = (name) => {
      if (!scores.has(name)) scores.set(name, { name, score: 0, badges: [] });
      return scores.get(name);
    };

    tIndex.forEach((e, name) => {
      if (taken.has(lower(name))) return;
      const c = ensure(name);
      c.score += W_TIER[e.tier] || 0;
      c.badges.push({ type: "tier", kind: "data", params: { tier: e.tier } });
      if (isNum(e.win_rate)) {
        c.score += (e.win_rate - 0.5) * W_WR;
        c.badges.push({ type: "wr", kind: "data", params: { n: Math.round(e.win_rate * 100) } });
      }
    });

    if (laneFoe && counters) {
      // Gerçek kayıtlar (1-3, dosya kadar): "%X counter (veri)".
      counterRecords(counters, roleKey, laneFoe.champ).forEach(r => {
        if (taken.has(lower(r.champion)) || r.win_rate_against < 0.5) return;
        const c = ensure(r.champion);
        c.score += W_COUNTER_DIRECT + (r.win_rate_against - 0.5) * W_COUNTER_WR;
        c.badges.push({ type: "counter", kind: "data",
          params: { name: laneFoe.champ, n: Math.round(r.win_rate_against * 100) } });
      });
      // Ters yön taraması — aynı rozet tipi, pct ters kayıttan türetilir.
      reverseCounters(counters, roleKey, laneFoe.champ).forEach(r => {
        if (taken.has(lower(r.champion))) return;
        const c = ensure(r.champion);
        if (c.badges.some(b => b.type === "counter")) return; // doğrudan kayıt üstündür
        c.score += W_COUNTER_REVERSE + (r.win_rate_against - 0.5) * W_COUNTER_WR;
        c.badges.push({ type: "counter", kind: "data",
          params: { name: laneFoe.champ, n: Math.round(r.win_rate_against * 100) } });
      });
    }

    // Sınıf sezgiseli yalnız koridor rakibi bilinirken anlamlıdır.
    const foeTags = laneFoe ? champTags(champInfo, laneFoe.champ) : [];
    scores.forEach(c => {
      if (foeTags.length) {
        const myTags = champTags(champInfo, c.name);
        const edge = myTags.some(tg =>
          (CLASS_EDGE[tg] || []).some(victim => foeTags.indexOf(victim) !== -1));
        if (edge) {
          c.score += W_CLASS;
          c.badges.push({ type: "classadv", kind: "gut", params: {} });
        }
      }
      my.gaps.forEach(g => {
        if (closesGap(g.key, c.name, champInfo)) {
          c.score += W_GAP;
          c.badges.push({ type: "gap_" + g.key, kind: "data", params: {} });
        }
      });
      const tempo = tempoOf(c.name, champInfo);
      if (tempo) {
        c.score += W_TEMPO;
        c.badges.push({ type: tempo, kind: "gut", params: {} });
      }
      const g = group[c.name];
      if (g && isStr(g.name)) // bilgi rozeti — skora BİLEREK katılmaz
        c.badges.push({ type: "group", kind: "info",
          params: { name: g.name, w: g.wins, l: g.losses } });
    });

    const deck = laneFoe ? DECK_COUNTER : DECK_DEFAULT;
    result.suggestions = [...scores.values()]
      .sort((a, b) => b.score - a.score || (a.name < b.name ? -1 : 1))
      .slice(0, deck)
      .map((c, i) => ({ name: c.name, role: myRole, badges: c.badges, best: i === 0 }));
    return result;
  }

  // tierIndex/counterRecords GÖREV 21-FIX'te dışa açıldı (Eşleşme ekranı, app.js):
  // ikisi de zaten SAF fonksiyondu (yalnız parametre alır, kapsanan state'e
  // dokunmaz) — dışa açmak analyze()/buildGroupIndex()'in davranışını DEĞİŞTİRMEZ,
  // S3 "Seçim" ekranı aynı iki fonksiyonu aynı şekilde çağırmaya devam eder.
  window.PickAdvisor = { analyze, buildGroupIndex, tierIndex, counterRecords };
})();
