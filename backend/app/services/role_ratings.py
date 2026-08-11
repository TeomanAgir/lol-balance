"""Rol rating evreni orkestrasyonu (docs/rating_contract.md "Rol Rating Evreni").

`ratings.py`'nin (player, role) bazlı simetriğidir: aynı Engine, aynı
`engine_version`, aynı formül — evren ayrımı TABLOYLA yapılır
(`role_rating_history`, migration 0003). Ana evren bu modülden asla etkilenmez.

Mu/sigma matematiği burada YOK; tamamı rating paketindedir.
"""
from __future__ import annotations

import sqlite3

from rating import ROLES, Engine, ParticipantStats, Rating

from .ratings import STAT_FIELDS

# (player_id, role) → ...
RoleKey = tuple[int, str]


def is_role_eligible(conn: sqlite3.Connection, match_id: int) -> bool:
    """Maç rol evrenine giriyor mu? (rating_contract "Rol Rating Evreni" §3)

    Koşul: 10 katılımcının 10'unda da `position` dolu VE her takımda 5 farklı
    rolün her birinden tam 1 tane. Deterministik, yan etkisiz.

    Roller HER ZAMAN `match_participants.position`'ın güncel değerinden okunur
    (ham `ingest_events` payload'ından değil — db_schema ilke 5).
    """
    rows = conn.execute(
        "SELECT team, position FROM match_participants WHERE match_id = ?",
        (match_id,),
    ).fetchall()
    if len(rows) != 10:
        return False
    if any(row["position"] is None for row in rows):
        return False
    expected = sorted(ROLES)
    for team in (100, 200):
        got = sorted(row["position"] for row in rows if row["team"] == team)
        if got != expected:
            return False
    return True


def current_role_ratings(
    conn: sqlite3.Connection, engine_version: str
) -> dict[RoleKey, Rating]:
    """(oyuncu id, rol) → güncel rol rating'i (current_role_ratings view'ünden)."""
    rows = conn.execute(
        "SELECT player_id, role, mu, sigma FROM current_role_ratings "
        "WHERE engine_version = ?",
        (engine_version,),
    )
    return {
        (row["player_id"], row["role"]): Rating(mu=row["mu"], sigma=row["sigma"])
        for row in rows
    }


def role_perf_averages(
    conn: sqlite3.Connection, engine_version: str
) -> dict[RoleKey, float]:
    """(oyuncu id, rol) → rol bazlı kariyer performans ortalaması P_avg.

    Yalnız valid maçlar, yalnız verilen engine_version, yalnız o rolün satırları
    (rating_contract "Rol Rating Evreni" §5). Hiç satırı olmayan (oyuncu, rol)
    dict'te YOKTUR — çağıran 1.0 (nötr) varsayar.
    """
    rows = conn.execute(
        "SELECT rrh.player_id, rrh.role, AVG(rrh.perf_score) AS p_avg "
        "FROM role_rating_history rrh "
        "JOIN matches m ON m.id = rrh.match_id "
        "WHERE rrh.engine_version = ? AND m.status = 'valid' "
        "GROUP BY rrh.player_id, rrh.role",
        (engine_version,),
    )
    return {
        (row["player_id"], row["role"]): row["p_avg"]
        for row in rows
        if row["p_avg"] is not None
    }


def role_match_counts(
    conn: sqlite3.Connection, engine_version: str
) -> dict[RoleKey, int]:
    """(oyuncu id, rol) → o rolde oynanan valid maç sayısı (api_contract §2)."""
    rows = conn.execute(
        "SELECT rrh.player_id, rrh.role, COUNT(*) AS n "
        "FROM role_rating_history rrh "
        "JOIN matches m ON m.id = rrh.match_id "
        "WHERE rrh.engine_version = ? AND m.status = 'valid' "
        "GROUP BY rrh.player_id, rrh.role",
        (engine_version,),
    )
    return {(row["player_id"], row["role"]): row["n"] for row in rows}


def _match_role_teams(
    conn: sqlite3.Connection, match_id: int
) -> tuple[
    list[RoleKey],
    list[RoleKey],
    list[ParticipantStats],
    list[ParticipantStats],
    int | None,
]:
    """Maçın katılımcılarını (player_id, rol) + stat olarak takım bazında,
    deterministik sırada ve maç süresiyle birlikte döner.

    Yalnızca uygun (is_role_eligible) maçlarda çağrılır; bu yüzden her
    katılımcının position'ı doludur.
    """
    team100: list[RoleKey] = []
    team200: list[RoleKey] = []
    stats100: list[ParticipantStats] = []
    stats200: list[ParticipantStats] = []
    rows = conn.execute(
        "SELECT player_id, team, position, kills, deaths, assists, gold, cs,"
        " damage_to_champs, vision_score FROM match_participants "
        "WHERE match_id = ? ORDER BY id",
        (match_id,),
    )
    for row in rows:
        stats = ParticipantStats(**{f: row[f] for f in STAT_FIELDS})
        key = (row["player_id"], row["position"])
        if row["team"] == 100:
            team100.append(key)
            stats100.append(stats)
        else:
            team200.append(key)
            stats200.append(stats)
    duration_s = conn.execute(
        "SELECT duration_s FROM matches WHERE id = ?", (match_id,)
    ).fetchone()["duration_s"]
    return team100, team200, stats100, stats200, duration_s


def _apply_and_record_roles(
    conn: sqlite3.Connection,
    engine: Engine,
    match_id: int,
    winner_team: int,
    ratings: dict[RoleKey, Rating],
) -> None:
    """Uygun tek maçı engine'den geçirir; ratings dict'ini günceller ve
    role_rating_history'ye before/after satırlarını yazar.

    Ana evrenle aynı mekanik: aynı 5v5 yapısı, aynı winner, aynı stats/duration.
    Fark yalnızca state anahtarıdır: (player_id, role).
    """
    team100, team200, stats100, stats200, duration_s = _match_role_teams(
        conn, match_id
    )
    before100 = [ratings.get(k, engine.default_rating()) for k in team100]
    before200 = [ratings.get(k, engine.default_rating()) for k in team200]
    after100, after200 = engine.update(
        before100,
        before200,
        winner=winner_team,
        stats100=stats100,
        stats200=stats200,
        duration_s=duration_s,
    )
    # perf_score ana evrendeki maç perf değeriyle AYNIDIR (aynı stats, aynı
    # fonksiyon) — rating_contract "Rol Rating Evreni" §4.
    perf100, perf200 = engine.perf_scores(stats100, stats200, duration_s)

    for key, before, after, perf in zip(
        team100 + team200,
        before100 + before200,
        after100 + after200,
        perf100 + perf200,
    ):
        ratings[key] = after
        player_id, role = key
        conn.execute(
            "INSERT INTO role_rating_history "
            "(player_id, match_id, role, engine_version,"
            " mu_before, sigma_before, mu_after, sigma_after, perf_score) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                player_id,
                match_id,
                role,
                engine.version,
                before.mu,
                before.sigma,
                after.mu,
                after.sigma,
                perf,
            ),
        )


def apply_match_incremental_roles(
    conn: sqlite3.Connection, match_id: int, winner_team: int, engine_version: str
) -> bool:
    """Valid bir ingest sonrası rol evrenine tek maç uygular.

    Maç uygun değilse SESSİZCE hiçbir şey yapmaz (ana evren yine işlenmiştir).
    Uygunluk içeride kontrol edilir; çağıranın bilmesi gerekmez.
    İşlendiyse True döner. Çağıranın transaction'ı içinde koşar.
    """
    if not is_role_eligible(conn, match_id):
        return False
    engine = Engine(version=engine_version)
    ratings = current_role_ratings(conn, engine_version)
    _apply_and_record_roles(conn, engine, match_id, winner_team, ratings)
    return True


def replay_roles(conn: sqlite3.Connection, engine_version: str) -> int:
    """Aktif engine_version'ın role_rating_history'sini siler ve valid maçları
    played_at sırasıyla yeniden işler. İşlenen (UYGUN) maç sayısını döner.

    Uygun olmayan maçlar atlanır ve sayılmaz. Roller her zaman
    match_participants'ın GÜNCEL position değerinden okunur, bu yüzden
    `PUT /matches/{id}/positions` düzeltmeleri replay'de kaybolmaz.
    """
    engine = Engine(version=engine_version)
    processed = 0
    with conn:
        conn.execute(
            "DELETE FROM role_rating_history WHERE engine_version = ?",
            (engine_version,),
        )
        matches = conn.execute(
            "SELECT id, winner_team FROM matches "
            "WHERE status = 'valid' ORDER BY played_at, id"
        ).fetchall()
        ratings: dict[RoleKey, Rating] = {}
        for match in matches:
            if not is_role_eligible(conn, match["id"]):
                continue
            _apply_and_record_roles(
                conn, engine, match["id"], match["winner_team"], ratings
            )
            processed += 1
    return processed
