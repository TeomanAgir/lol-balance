"""Oyuncu rating tarihçesi (api_contract §2 "Rating tarihçesi", GÖREV 10).

Salt-okur: hiçbir tablo yazılmaz, rating'e etkisi yoktur. Mu/sigma ve harman
matematiği burada YOK — `score_after`, ratings.effective_score üzerinden rating
paketinin `Engine.effective()` yardımcısıyla hesaplanır (formül backend'e
kopyalanmaz).
"""
from __future__ import annotations

import sqlite3

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
        p_avg = perf_sum / perf_count if perf_count else None
        rating = Rating(mu=row["mu_after"], sigma=row["sigma_after"])
        # Yuvarlama YALNIZ çıktıda: p_avg ve score ham değerlerle hesaplanır.
        points.append(
            {
                "match_id": row["match_id"],
                "played_at": row["played_at"],
                "win": row["team"] == row["winner_team"],
                "champion": row["champion"],
                "position": row["position"],
                "score_after": _round(
                    effective_score(engine, blend, rating, p_avg)
                ),
                "stats": _stats(row),
            }
        )

    return {
        "player_id": player_id,
        "engine_version": engine_version,
        "points": points,
    }
