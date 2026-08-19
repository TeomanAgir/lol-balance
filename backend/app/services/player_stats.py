"""Oyuncu profil istatistikleri (api_contract §2 "Oyuncu profili").

Tamamı GÖSTERİM istatistiğidir: rating'e hiçbir etkisi yoktur, hiçbir tablo
yazılmaz, şema değişmez — her şey mevcut `matches` / `match_participants` /
`players` satırlarından türetilir. Faz 2 pair-synergy rating modeli AYRIDIR ve
hâlâ kapsam dışıdır (CHANGE_REQUESTS: GÖREV 1, 2026-08-12).

Tüm metrikler yalnız `status='valid'` maçlar üzerinden hesaplanır; void maç
hiçbir metriğe girmez.
"""
from __future__ import annotations

import sqlite3

from rating import ROLES

from .items import load_items

# --------------------------------------------------------------------------
# Sinerji katsayıları (api_contract §2 `synergy`, GÖREV 22 — 2026-08-19)
# --------------------------------------------------------------------------
# Bunlar GÖSTERİM ayarıdır, dondurulmuş rating spec'i DEĞİLDİR: değişmeleri
# replay gerektirmez, yalnız contract güncellemesi ister. Bu yüzden modül
# seviyesinde ADLANDIRILMIŞ sabitlerdir (contract adlarıyla birebir).
SYNERGY_MIN_TOGETHER = 4  # MIN_TOGETHER: aday olma eşiği (n >= 4)
SYNERGY_SHRINKAGE_M = 4.0  # M: küçük örneklemi 0'a çeken shrinkage sabiti
SYNERGY_W_WR = 0.5  # W_WR: winrate lift ağırlığı
SYNERGY_W_PERF = 0.5  # W_PERF: perf lift ağırlığı
SYNERGY_PERF_SCALE = 3.4  # PERF_SCALE: perf farkını winrate ölçeğine getirir
# solo(Z) boşsa (oyuncunun çift dışında hiç maçı yok) wr_solo nötr kabul edilir.
SYNERGY_NEUTRAL_WR_SOLO = 0.5
SYNERGY_LIMIT = 3  # yanıta en fazla 3 kayıt

# Yuvarlama yalnız YANITTA; hesap ve sıralama ham değerle (api_contract §2).
SYNERGY_SCORE_PRECISION = 3
SYNERGY_PERF_DELTA_PRECISION = 2

# api_contract §2 `top_items` (GÖREV 14): en fazla 10 kayıt.
TOP_ITEMS_LIMIT = 10

# Yuvarlama: contract örneğindeki değerler (kills_avg 5.2, ratio 4.06,
# winrate 0.6) 2 basamağa yuvarlanmış hâldedir; float gürültüsünü UI'a
# taşımamak için tüm oran/ortalamalar aynı hassasiyetle döner. Sıralama
# ve eşitlik kırılımları YUVARLANMAMIŞ değerlerle yapılır.
_PRECISION = 2


def _round(value: float) -> float:
    return round(value, _PRECISION)


def _winrate(wins: int, matches: int) -> float:
    return _round(wins / matches)


def _totals(rows: list[sqlite3.Row]) -> dict:
    """Valid maç sayısı + W/L; maçsız oyuncuda winrate null (api_contract §2)."""
    matches = len(rows)
    wins = sum(1 for r in rows if r["team"] == r["winner_team"])
    return {
        "matches": matches,
        "wins": wins,
        "losses": matches - wins,
        "winrate": _winrate(wins, matches) if matches else None,
    }


def _kda(rows: list[sqlite3.Row]) -> dict | None:
    """Yalnız kills/deaths/assists ÜÇÜ DE dolu maçlardan; hiç yoksa None.

    `ratio = (ΣK + ΣA) / max(1, ΣD)` (CHANGE_REQUESTS GÖREV 1 tanımı).
    """
    stat_rows = [
        r
        for r in rows
        if r["kills"] is not None
        and r["deaths"] is not None
        and r["assists"] is not None
    ]
    if not stat_rows:
        return None
    n = len(stat_rows)
    kills = sum(r["kills"] for r in stat_rows)
    deaths = sum(r["deaths"] for r in stat_rows)
    assists = sum(r["assists"] for r in stat_rows)
    return {
        "kills_avg": _round(kills / n),
        "deaths_avg": _round(deaths / n),
        "assists_avg": _round(assists / n),
        "ratio": _round((kills + assists) / max(1, deaths)),
    }


def _favorite_champion(rows: list[sqlite3.Row]) -> dict | None:
    """EN FAZLA MAÇ KAZANILAN şampiyon (api_contract §2, REVİZE 2026-08-15).

    Ölçüt galibiyet SAYISIDIR, oran değil: az kazançlı ama çok oynanmış bir
    şampiyon, daha çok kazanılmış olanı geçemez. Kırılım: galibiyet çok →
    maç sayısı çok → ad alfabetik küçük. Hiç galibiyeti olmayan bir oyuncuda
    aynı kırılım 0-kazançlılar arasından seçer (yani "en çok oynanan").

    champion NULL olan satırlar hariçtir; hiç kalmazsa None.
    """
    counts: dict[str, list[int]] = {}  # champion -> [matches, wins]
    for r in rows:
        champion = r["champion"]
        if champion is None:
            continue
        entry = counts.setdefault(champion, [0, 0])
        entry[0] += 1
        if r["team"] == r["winner_team"]:
            entry[1] += 1
    if not counts:
        return None
    champion, (matches, wins) = min(
        counts.items(), key=lambda item: (-item[1][1], -item[1][0], item[0])
    )
    return {
        "champion": champion,
        "matches": matches,
        "wins": wins,
        "winrate": _winrate(wins, matches),
    }


def _favorite_role(rows: list[sqlite3.Row]) -> dict | None:
    """En çok oynanan rol; eşitlikte kanonik sıra (TOP<JUNGLE<MIDDLE<BOTTOM<UTILITY).

    position NULL olan satırlar hariçtir; hiç kalmazsa None.
    """
    counts: dict[str, int] = {}
    for r in rows:
        position = r["position"]
        if position is None:
            continue
        counts[position] = counts.get(position, 0) + 1
    if not counts:
        return None
    role, matches = min(
        counts.items(), key=lambda item: (-item[1], ROLES.index(item[0]))
    )
    return {"role": role, "matches": matches}


def _top_items(rows: list[sqlite3.Row]) -> list[dict]:
    """items bilgisi DOLU valid maçlardaki eşya sayımları (api_contract §2).

    `items_json` NULL olan maç ("bilinmiyor") hiç sayılmaz; `[]` sayılır ama
    katkısı yoktur. AYNI maçta aynı eşya (ör. iki iksir slotu) BİR kez sayılır.
    Sıralama: sayım azalan → item_id artan; en fazla 10 kayıt. Eşya adı/tags
    burada BİLİNMEZ — trinket/tüketilebilir ayıklaması web UI'dadır.
    """
    counts: dict[int, int] = {}
    for r in rows:
        items = load_items(r["items_json"])
        if items is None:
            continue
        for item_id in set(items):
            counts[item_id] = counts.get(item_id, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [
        {"item_id": item_id, "matches": matches}
        for item_id, matches in ordered[:TOP_ITEMS_LIMIT]
    ]


def _mean(values: list[float]) -> float | None:
    """Ortalama; hiç değer yoksa None ("hesaplanamıyor" ayrı bir durumdur)."""
    if not values:
        return None
    return sum(values) / len(values)


def _perf_lift(
    matches: dict[int, tuple[bool, float | None]], together: set[int]
) -> float:
    """`ort(perf | together) − ort(perf | solo)` (api_contract §2 `perf_lift`).

    `perf_score`'u NULL olan maç hiçbir ortalamaya girmez. Taraflardan biri
    hesaplanamıyorsa (o kümede hiç perf'li maç yok) lift 0 sayılır — yokluk
    "kötü oynadı" demek değildir.

    Toplama SIRASI match_id artan olarak sabittir; replay perf_score'ları
    bit-bit yeniden ürettiği için yanıt da bit-bit korunur.
    """
    together_perfs: list[float] = []
    solo_perfs: list[float] = []
    for match_id in sorted(matches):
        perf = matches[match_id][1]
        if perf is None:
            continue
        (together_perfs if match_id in together else solo_perfs).append(perf)
    together_avg = _mean(together_perfs)
    solo_avg = _mean(solo_perfs)
    if together_avg is None or solo_avg is None:
        return 0.0
    return together_avg - solo_avg


def _wr_solo(
    matches: dict[int, tuple[bool, float | None]], together: set[int]
) -> float:
    """Çiftin DIŞINDAKİ maçların winrate'i; solo küme boşsa nötr 0.5."""
    solo = [win for match_id, (win, _) in matches.items() if match_id not in together]
    if not solo:
        return SYNERGY_NEUTRAL_WR_SOLO
    return sum(1 for win in solo if win) / len(solo)


def synergy_score(
    n: int,
    wins_together: int,
    wr_solo_x: float,
    wr_solo_y: float,
    perf_lift_x: float,
    perf_lift_y: float,
) -> tuple[float, float]:
    """(score, perf_delta) — api_contract §2 `synergy` formülünün TAMAMI.

    `score = n/(n+M) * (W_WR * wr_lift + W_PERF * PERF_SCALE * perf_delta)`
    `wr_lift = wins(together)/n − (wr_solo(X) + wr_solo(Y))/2`
    `perf_delta = (perf_lift(X) + perf_lift(Y)) / 2`

    Saf fonksiyondur (DB bilmez): formülün her parçası tek başına sınanabilsin
    diye ayrı durur. Yuvarlama YOKTUR — o yalnız yanıt katmanındadır.
    """
    perf_delta = (perf_lift_x + perf_lift_y) / 2
    wr_lift = wins_together / n - (wr_solo_x + wr_solo_y) / 2
    shrinkage = n / (n + SYNERGY_SHRINKAGE_M)
    score = shrinkage * (
        SYNERGY_W_WR * wr_lift + SYNERGY_W_PERF * SYNERGY_PERF_SCALE * perf_delta
    )
    return score, perf_delta


def synergy_sort_key(item: tuple[float, dict]) -> tuple:
    """(ham score, yanıt kaydı) → sıralama anahtarı (api_contract §2).

    `score` azalan → `matches_together` azalan → `display_name` alfabetik.
    Karşılaştırma HAM score iledir; yanıttaki yuvarlanmış değer sıralamayı
    etkilemez.
    """
    score, entry = item
    return (-score, -entry["matches_together"], entry["display_name"])


def _player_matches(
    conn: sqlite3.Connection, player_ids: list[int], engine_version: str
) -> dict[int, dict[int, tuple[bool, float | None]]]:
    """player_id → {match_id: (kazandı mı, perf_score)} (yalnız valid maçlar).

    `perf_score` AKTİF engine'in `rating_history` satırından okunur; backend
    perf'i KENDİ hesaplamaz (rating paketinin yazdığı değer tek kaynaktır —
    badges/MVP ile birebir aynı yol). LEFT JOIN: satırı olmayan katılımcının
    perf'i NULL'dır, maçın kendisi yine sayılır (W/L tarafına girer).
    """
    placeholders = ",".join("?" for _ in player_ids)
    rows = conn.execute(
        "SELECT mp.player_id, mp.match_id,"
        " CASE WHEN mp.team = m.winner_team THEN 1 ELSE 0 END AS win,"
        " rh.perf_score "
        "FROM match_participants mp "
        "JOIN matches m ON m.id = mp.match_id "
        "LEFT JOIN rating_history rh ON rh.match_id = mp.match_id"
        " AND rh.player_id = mp.player_id AND rh.engine_version = ? "
        f"WHERE m.status = 'valid' AND mp.player_id IN ({placeholders}) "
        "ORDER BY mp.match_id, mp.id",
        (engine_version, *player_ids),
    ).fetchall()
    by_player: dict[int, dict[int, tuple[bool, float | None]]] = {
        pid: {} for pid in player_ids
    }
    for row in rows:
        by_player[row["player_id"]][row["match_id"]] = (
            bool(row["win"]),
            row["perf_score"],
        )
    return by_player


def _synergy(
    conn: sqlite3.Connection, player_id: int, engine_version: str
) -> list[dict]:
    """Birlikte EN İYİ OYNANAN takım arkadaşları (api_contract §2, GÖREV 22).

    Eski tanım (salt birlikte-winrate, eşik 2) canlı veride gürültü olduğu
    ÖLÇÜLEREK terk edildi (CHANGE_REQUESTS 2026-08-19). Yeni ölçüt lift'tir:
    çift birlikteyken normalinden ne kadar iyi oynuyor/kazanıyor.

    Aday: aynı takımda `n >= MIN_TOGETHER` valid maç. Yanıta yalnız
    `score > 0` girer (pozitif sinerji yoksa sahte birinci gösterilmez);
    sıralama ham `score` azalan → `matches_together` azalan → `display_name`
    alfabetik; en fazla 3 kayıt.
    """
    rows = conn.execute(
        "SELECT o.player_id AS player_id, p.display_name AS display_name,"
        " me.match_id AS match_id "
        "FROM match_participants me "
        "JOIN matches m ON m.id = me.match_id "
        "JOIN match_participants o ON o.match_id = me.match_id"
        "  AND o.team = me.team AND o.player_id <> me.player_id "
        "JOIN players p ON p.id = o.player_id "
        "WHERE me.player_id = ? AND m.status = 'valid' "
        "ORDER BY o.player_id, me.match_id",
        (player_id,),
    ).fetchall()

    together: dict[int, set[int]] = {}
    names: dict[int, str] = {}
    for row in rows:
        together.setdefault(row["player_id"], set()).add(row["match_id"])
        names[row["player_id"]] = row["display_name"]
    candidates = sorted(
        pid for pid, shared in together.items()
        if len(shared) >= SYNERGY_MIN_TOGETHER
    )
    if not candidates:
        return []

    matches = _player_matches(conn, [player_id, *candidates], engine_version)
    mine = matches[player_id]

    scored: list[tuple[float, dict]] = []
    for pid in candidates:
        shared = together[pid]
        n = len(shared)
        theirs = matches[pid]
        wins_together = sum(1 for match_id in shared if mine[match_id][0])
        score, perf_delta = synergy_score(
            n,
            wins_together,
            _wr_solo(mine, shared),
            _wr_solo(theirs, shared),
            _perf_lift(mine, shared),
            _perf_lift(theirs, shared),
        )
        if score <= 0:
            continue
        scored.append(
            (
                score,
                {
                    "player_id": pid,
                    "display_name": names[pid],
                    "matches_together": n,
                    "wins_together": wins_together,
                    "winrate": _winrate(wins_together, n),
                    "score": round(score, SYNERGY_SCORE_PRECISION),
                    # `+ 0.0`: çok küçük negatif fark yuvarlanınca IEEE -0.0
                    # üretir ve JSON'a "-0.0" diye düşerdi; işaret sıfırlanır
                    # (değer aynı, yalnız gösterim).
                    "perf_delta": round(perf_delta, SYNERGY_PERF_DELTA_PRECISION) + 0.0,
                },
            )
        )
    scored.sort(key=synergy_sort_key)
    return [entry for _, entry in scored[:SYNERGY_LIMIT]]


def player_stats(
    conn: sqlite3.Connection, player_id: int, engine_version: str
) -> dict | None:
    """Oyuncu profil istatistikleri; oyuncu yoksa None (router 404 üretir).

    `engine_version` yalnız sinerjinin perf tarafı içindir: `perf_score` AKTİF
    engine'in `rating_history` satırlarından okunur (badges/MVP ile aynı yol).
    """
    player = conn.execute(
        "SELECT id, display_name, riot_id FROM players WHERE id = ?", (player_id,)
    ).fetchone()
    if player is None:
        return None

    rows = conn.execute(
        "SELECT mp.team, mp.position, mp.champion,"
        " mp.kills, mp.deaths, mp.assists, mp.items_json, m.winner_team "
        "FROM match_participants mp "
        "JOIN matches m ON m.id = mp.match_id "
        "WHERE mp.player_id = ? AND m.status = 'valid' "
        "ORDER BY mp.match_id, mp.id",
        (player_id,),
    ).fetchall()

    return {
        "player": {
            "id": player["id"],
            "display_name": player["display_name"],
            "riot_id": player["riot_id"],
        },
        "totals": _totals(rows),
        "kda": _kda(rows),
        "favorite_champion": _favorite_champion(rows),
        "favorite_role": _favorite_role(rows),
        "synergy": _synergy(conn, player_id, engine_version),
        "top_items": _top_items(rows),
    }
