"""Oyuncu rating tarihçesi (api_contract §2 "Rating tarihçesi", GÖREV 10).

Salt-okur: hiçbir tablo yazılmaz, rating'e etkisi yoktur. Mu/sigma ve harman
matematiği burada YOK — `score_after`, ratings.effective_score üzerinden rating
paketinin `Engine.effective()` yardımcısıyla hesaplanır (formül backend'e
kopyalanmaz).

GÖREV 18: `GET /matches` yanıtındaki `score_before`/`score_after` da BURADAKİ
tanımı paylaşır — tarihsel efektif score'un tek doğruluk noktası
`historical_score` + önek toplamlarıdır (api_contract §3).
"""
from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from rating import Engine, Rating

from .ratings import effective_score, is_blend, replay_order_by

_PRECISION = 2

# stats nesnesinin alanları; üçü de NULL ise stats tamamen null döner.
_KDA_FIELDS = ("kills", "deaths", "assists")


def _round(value: float) -> float:
    return round(value, _PRECISION)


def _stats(row: sqlite3.Row) -> dict | None:
    kda = {field: row[field] for field in _KDA_FIELDS}
    if all(value is None for value in kda.values()):
        return None
    return kda


def historical_score(
    engine: Engine,
    blend: bool,
    mu: float,
    sigma: float,
    perf_sum: float,
    perf_count: int,
) -> float:
    """Tarihsel efektif score (YUVARLANMAMIŞ) — tek doğruluk noktası.

    `P_avg = perf_sum / perf_count` kümülatif önekten gelir; önekte hiç perf
    yoksa None geçilir ve `effective_score` nötr 1.0 varsayar (rating_contract
    "Harman Engine" §3/§4). Harman dallanması ve formül `effective_score` →
    `Engine.effective()`tadır, burada matematik yoktur.

    Rating tarihçesi (`rating_history`) ve maç listesi score_before/after
    (GÖREV 18, `match_perf_prefixes` ile) bu fonksiyonu ortak kullanır.
    """
    p_avg = perf_sum / perf_count if perf_count else None
    return effective_score(engine, blend, Rating(mu=mu, sigma=sigma), p_avg)


def match_perf_prefixes(
    conn: sqlite3.Connection,
    engine_version: str,
    match_id: int,
    played_at: str,
    player_ids: Sequence[int],
) -> dict[int, tuple[tuple[float, int], tuple[float, int]]]:
    """Oyuncu başına, verilen maça kadarki kronolojik önekin perf toplamları.

    Dönüş: player_id → ((önce_sum, önce_count), (sonra_sum, sonra_count)).
    "sonra" öneki maçı DAHİL eder (rating tarihçesi `score_after` tanımı),
    "önce" HARİÇ tutar (`score_before`, api_contract §3 GÖREV 18). Oyuncunun
    önceki maçı yoksa "önce" (0.0, 0) kalır → historical_score default/nötr
    duruma düşer.

    Önek koşulu replay sort-key'inin (`replay_order_by`: played_at, id) SQL
    WHERE karşılığıdır — `ratings.is_out_of_order`daki çevirinin aynısı; o
    anahtara dokunan değişiklik burayla birlikte düşünülür. Toplama SIRASI da
    `rating_history()` döngüsüyle birebir aynıdır (oyuncu başına kronolojik
    artan), böylece iki endpoint'in score'ları bit-bit tutarlı kalır.
    """
    totals: dict[int, tuple[float, int]] = {pid: (0.0, 0) for pid in player_ids}
    before: dict[int, tuple[float, int]] = {}
    placeholders = ",".join("?" for _ in player_ids)
    rows = conn.execute(
        "SELECT rh.player_id, rh.match_id, rh.perf_score "
        "FROM rating_history rh "
        "JOIN matches m ON m.id = rh.match_id "
        "WHERE rh.engine_version = ? AND m.status = 'valid' "
        f"AND rh.player_id IN ({placeholders}) "
        "AND (m.played_at < ? OR (m.played_at = ? AND m.id <= ?)) "
        f"{replay_order_by('m')}",
        (engine_version, *player_ids, played_at, played_at, match_id),
    )
    for row in rows:
        pid = row["player_id"]
        if row["match_id"] == match_id:
            # Hedef maç önekin SON elemanıdır (sort-key maksimumu); o âna
            # kadarki toplam = "önce" öneki.
            before[pid] = totals[pid]
        if row["perf_score"] is not None:
            perf_sum, perf_count = totals[pid]
            totals[pid] = (perf_sum + row["perf_score"], perf_count + 1)
    return {
        pid: (before.get(pid, totals[pid]), totals[pid]) for pid in player_ids
    }


def rating_history(
    conn: sqlite3.Connection, player_id: int, engine_version: str
) -> dict | None:
    """Oyuncunun maç maç efektif score eğrisi; bilinmeyen oyuncuda None.

    Sıra replay'in sort-key'iyle BİREBİR aynıdır (`replay_order_by`), bu yüzden
    `POST /admin/replay` sonrası yanıt bit-bit korunur.

    `score_after` TARİHSELDİR: o noktaya kadarki (o maç dahil) kronolojik önekte
    biriken perf_score ortalaması P_avg olarak alınır — NULL perf satırları
    ortalamaya girmez, hiç perf yoksa `effective_score` nötr P_avg=1.0 varsayar
    (rating_contract "Harman Engine" §3/§4). Son noktanın P_avg'i tanım gereği
    `ratings.perf_averages`ın tamamıyla aynı kümedir, dolayısıyla son
    `score_after` leaderboard'daki güncel `score`la eşleşir.

    rating_history satırı olmayan maç noktaya dönüşmez (INNER JOIN): score_after
    contract'ta nullable değildir ve aktif engine'de her valid maçın satırı
    vardır (replay tüm valid maçları işler).
    """
    if (
        conn.execute(
            "SELECT 1 FROM players WHERE id = ?", (player_id,)
        ).fetchone()
        is None
    ):
        return None

    engine = Engine(version=engine_version)
    blend = is_blend(engine)

    rows = conn.execute(
        "SELECT m.id AS match_id, m.played_at, m.winner_team,"
        " mp.team, mp.champion, mp.position, mp.kills, mp.deaths, mp.assists,"
        " rh.mu_after, rh.sigma_after, rh.perf_score "
        "FROM match_participants mp "
        "JOIN matches m ON m.id = mp.match_id "
        "JOIN rating_history rh ON rh.match_id = mp.match_id"
        " AND rh.player_id = mp.player_id AND rh.engine_version = ? "
        "WHERE mp.player_id = ? AND m.status = 'valid' "
        f"{replay_order_by('m')}",
        (engine_version, player_id),
    ).fetchall()

    points = []
    perf_sum = 0.0
    perf_count = 0
    for row in rows:
        if row["perf_score"] is not None:
            perf_sum += row["perf_score"]
            perf_count += 1
        # Yuvarlama YALNIZ çıktıda: P_avg ve score ham değerlerle hesaplanır.
        points.append(
            {
                "match_id": row["match_id"],
                "played_at": row["played_at"],
                "win": row["team"] == row["winner_team"],
                "champion": row["champion"],
                "position": row["position"],
                "score_after": _round(
                    historical_score(
                        engine,
                        blend,
                        row["mu_after"],
                        row["sigma_after"],
                        perf_sum,
                        perf_count,
                    )
                ),
                "stats": _stats(row),
            }
        )

    return {
        "player_id": player_id,
        "engine_version": engine_version,
        "points": points,
    }
