"""Rating orkestrasyonu: incremental update ve replay.

Mu/sigma matematiği burada YOK — tamamı rating paketinde (Agent 3).
Bu modül yalnızca DB'den okur, Engine'i çağırır, sonucu rating_history'ye yazar.
"""
from __future__ import annotations

import sqlite3

from rating import Engine, ParticipantStats, Rating

# match_participants'taki stat kolonları — ParticipantStats alanlarıyla birebir.
# Rol evreni (role_ratings.py) aynı kolonları okur, bu yüzden public.
STAT_FIELDS = (
    "kills",
    "deaths",
    "assists",
    "gold",
    "cs",
    "damage_to_champs",
    "vision_score",
)


def current_ratings(
    conn: sqlite3.Connection, engine_version: str
) -> dict[int, Rating]:
    """Oyuncu id → güncel rating (current_ratings view'ünden)."""
    rows = conn.execute(
        "SELECT player_id, mu, sigma FROM current_ratings WHERE engine_version = ?",
        (engine_version,),
    )
    return {
        row["player_id"]: Rating(mu=row["mu"], sigma=row["sigma"]) for row in rows
    }


def perf_averages(
    conn: sqlite3.Connection, engine_version: str
) -> dict[int, float]:
    """Oyuncu id → kariyer performans ortalaması P_avg (harman engine girdisi).

    Yalnız valid maçların, yalnız verilen engine_version'ın satırları sayılır
    (rating_contract "Harman Engine" §3). AVG, NULL perf_score satırlarını
    zaten atlar; hiç satırı olmayan oyuncu dict'te YOKTUR — çağıran 1.0
    (nötr) varsayar.
    """
    rows = conn.execute(
        "SELECT rh.player_id, AVG(rh.perf_score) AS p_avg "
        "FROM rating_history rh "
        "JOIN matches m ON m.id = rh.match_id "
        "WHERE rh.engine_version = ? AND m.status = 'valid' "
        "GROUP BY rh.player_id",
        (engine_version,),
    )
    return {
        row["player_id"]: row["p_avg"]
        for row in rows
        if row["p_avg"] is not None
    }


def effective_score(
    engine: Engine, blend: bool, rating: Rating, p_avg: float | None
) -> float:
    """Gösterilecek `score` (api_contract §2) — TEK doğruluk noktası.

    Harman version'da efektif rating (`mu_eff - 3σ`), harman olmayanda
    `ordinal`. `p_avg` None ise nötr (1.0) sayılır: hiç perf satırı olmayan
    oyuncu/rol için harman engine 1.0 varsayar.

    players router (ana + rol rating listesi) ve haftanın enleri bu fonksiyonu
    ortak kullanır; blend dallanması hiçbir çağıranda kopyalanmaz.
    """
    if not blend:
        return rating.ordinal
    return engine.effective(
        rating.mu, rating.sigma, 1.0 if p_avg is None else p_avg
    ).score


def is_blend(engine: Engine) -> bool:
    """Engine harman (efektif rating) destekliyor mu?

    Rating paketi bunu yalnızca `effective()`ın ValueError'ıyla bildirir;
    private alana bakmak yerine nötr girdiyle probe edilir (saf fonksiyon,
    yan etkisiz).
    """
    try:
        engine.effective(25.0, 25.0 / 3.0, 1.0)
    except ValueError:
        return False
    return True


def _match_teams(
    conn: sqlite3.Connection, match_id: int
) -> tuple[
    list[int],
    list[int],
    list[ParticipantStats],
    list[ParticipantStats],
    int | None,
]:
    """Maçın katılımcılarını (id + stat) takım bazında, deterministik sırada
    ve maç süresiyle birlikte döner.

    Stat kolonları null olabilir; ParticipantStats null alanları nötr sayar,
    bu yüzden stats her zaman kurulur ve Engine'e her version'da geçilir.
    """
    team100: list[int] = []
    team200: list[int] = []
    stats100: list[ParticipantStats] = []
    stats200: list[ParticipantStats] = []
    rows = conn.execute(
        "SELECT player_id, team, kills, deaths, assists, gold, cs,"
        " damage_to_champs, vision_score FROM match_participants "
        "WHERE match_id = ? ORDER BY id",
        (match_id,),
    )
    for row in rows:
        stats = ParticipantStats(**{f: row[f] for f in STAT_FIELDS})
        if row["team"] == 100:
            team100.append(row["player_id"])
            stats100.append(stats)
        else:
            team200.append(row["player_id"])
            stats200.append(stats)
    duration_s = conn.execute(
        "SELECT duration_s FROM matches WHERE id = ?", (match_id,)
    ).fetchone()["duration_s"]
    return team100, team200, stats100, stats200, duration_s


def _apply_and_record(
    conn: sqlite3.Connection,
    engine: Engine,
    match_id: int,
    winner_team: int,
    ratings: dict[int, Rating],
) -> None:
    """Tek maçı engine'den geçirir; ratings dict'ini günceller ve
    rating_history'ye before/after satırlarını yazar."""
    team100, team200, stats100, stats200, duration_s = _match_teams(conn, match_id)
    before100 = [ratings.get(p, engine.default_rating()) for p in team100]
    before200 = [ratings.get(p, engine.default_rating()) for p in team200]
    # Stats her version'da geçilir: perf'siz version'larda etkisizdir
    # (rating paketinin testlerinde kanıtlı), perf'li version'da çarpanı besler.
    after100, after200 = engine.update(
        before100,
        before200,
        winner=winner_team,
        stats100=stats100,
        stats200=stats200,
        duration_s=duration_s,
    )
    # perf_score her version'da yazılır (kolon nullable, tanımı version'dan
    # bağımsız); harman engine P_avg'i bu kolondan türetir. Statsız katılımcı
    # rating paketinde 1.0 (nötr) alır.
    perf100, perf200 = engine.perf_scores(stats100, stats200, duration_s)

    for player_id, before, after, perf in zip(
        team100 + team200,
        before100 + before200,
        after100 + after200,
        perf100 + perf200,
    ):
        ratings[player_id] = after
        conn.execute(
            "INSERT INTO rating_history "
            "(player_id, match_id, engine_version,"
            " mu_before, sigma_before, mu_after, sigma_after, perf_score) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                player_id,
                match_id,
                engine.version,
                before.mu,
                before.sigma,
                after.mu,
                after.sigma,
                perf,
            ),
        )


def apply_match_incremental(
    conn: sqlite3.Connection, match_id: int, winner_team: int, engine_version: str
) -> None:
    """Valid bir ingest sonrası son rating'lerin üstüne tek maç uygular.

    Çağıranın transaction'ı içinde koşar; commit çağıranındır.
    """
    engine = Engine(version=engine_version)
    ratings = current_ratings(conn, engine_version)
    _apply_and_record(conn, engine, match_id, winner_team, ratings)


def replay(conn: sqlite3.Connection, engine_version: str) -> int:
    """Aktif engine_version'ın rating_history'sini siler ve valid maçları
    played_at sırasıyla yeniden işler. İşlenen maç sayısını döner.

    Diğer engine_version'ların satırlarına dokunulmaz (db_schema ilke 3).
    """
    engine = Engine(version=engine_version)
    with conn:
        conn.execute(
            "DELETE FROM rating_history WHERE engine_version = ?", (engine_version,)
        )
        matches = conn.execute(
            "SELECT id, winner_team FROM matches "
            "WHERE status = 'valid' ORDER BY played_at, id"
        ).fetchall()
        ratings: dict[int, Rating] = {}
        for match in matches:
            _apply_and_record(
                conn, engine, match["id"], match["winner_team"], ratings
            )
    return len(matches)
