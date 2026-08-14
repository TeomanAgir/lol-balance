"""Oyuncu rozetleri (api_contract §2 "Rozetler (GÖREV 11+12)").

SALT-OKUR gösterim katmanıdır: hiçbir tablo yazılmaz, hiçbir şema/migration
eklenmez, rating hesabına etkisi yoktur. Her rozet mevcut `matches` /
`match_participants` / `rating_history` satırlarından türetilir; yalnız
`status='valid'` maçlar sayılır.

Determinizm: kronoloji gerektiren rozetler (win_streak_5, bench_3, versatile
ve veteran_* eşiklerinin `last_match_id`'si) maçları `ratings.replay_order_by`
ile sıralar — replay'in sort-key'i burada KOPYALANMAZ, paylaşılır. Bu yüzden
`POST /admin/replay` sonrası yanıt bit-bit aynı kalır.

perf_score bağımlı rozetler (mvp, bench_3) AKTİF engine'in `rating_history`
satırlarını okur (leaderboard / rating tarihçesi hangi version'ı kullanıyorsa
onu); ham (yuvarlanmamış) değerle karşılaştırılır.
"""
from __future__ import annotations

import sqlite3

from rating import ROLES

from .ratings import replay_order_by

# api_contract §2: yanıt sırası SABİT katalog sırasıdır.
BADGE_KEYS = (
    "mvp",
    "vision",
    "damage",
    "cs_per_min",
    "gold",
    "deathless",
    "comeback",
    "win_streak_5",
    "bench_3",
    "versatile",
    "veteran_10",
    "veteran_25",
    "veteran_50",
)

# Rekor rozetleri: rozet anahtarı → match_participants stat kolonu.
# Kural aynı: maçtaki 10 oyuncu içinde en yüksek, NULL aday değil,
# EŞİTLİKTE eşit olan herkes alır.
RECORD_STATS = {
    "vision": "vision_score",
    "damage": "damage_to_champs",
    "gold": "gold",
}

# Blok rozetleri: tamamlanan her N'lik ardışık blok 1 rozet (bloklar ayrık).
WIN_STREAK_BLOCK = 5
BENCH_BLOCK = 3

# Eşik rozetleri: valid maç sayısı; her biri tek seferlik ve bağımsız.
VETERAN_THRESHOLDS = {"veteran_10": 10, "veteran_25": 25, "veteran_50": 50}

TEAM_SIZE = 5

_SECONDS_PER_MINUTE = 60.0


class _Tally:
    """Rozet sayacı: `count` ve rozeti SON kazandıran maç.

    Blok rozetlerinde bloğun son maçı, eşik rozetlerinde eşiği tamamlayan maç
    kaydedilir; `award` kronolojik sırada çağrıldığı için son çağrı doğal
    olarak en son maçtır.
    """

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.last_match: dict[str, int] = {}

    def award(self, key: str, match_id: int) -> None:
        self.counts[key] = self.counts.get(key, 0) + 1
        self.last_match[key] = match_id

    def has(self, key: str) -> bool:
        return key in self.counts

    def to_list(self) -> list[dict]:
        """Katalog sırasında, yalnız count > 0 olan rozetler."""
        return [
            {
                "key": key,
                "count": self.counts[key],
                "last_match_id": self.last_match[key],
            }
            for key in BADGE_KEYS
            if self.counts.get(key, 0) > 0
        ]


def _ordered_matches(conn: sqlite3.Connection, player_id: int) -> list[sqlite3.Row]:
    """Oyuncunun valid maçları, replay sort-key'iyle kronolojik sırada."""
    return conn.execute(
        "SELECT m.id AS match_id, m.duration_s, m.winner_team "
        "FROM matches m "
        "JOIN match_participants mp ON mp.match_id = m.id AND mp.player_id = ? "
        f"WHERE m.status = 'valid' {replay_order_by('m')}",
        (player_id,),
    ).fetchall()


def _participants(
    conn: sqlite3.Connection, player_id: int, engine_version: str
) -> dict[int, list[sqlite3.Row]]:
    """match_id → o maçın TÜM katılımcıları (stat + aktif engine perf_score).

    Rekor/mvp/bench/comeback rozetleri oyuncuyu takım arkadaşları ve
    rakipleriyle karşılaştırdığı için maçın 10 satırının hepsi gerekir.
    `rating_history` LEFT JOIN'dir: satırı olmayan katılımcının perf'i NULL
    sayılır (aday değildir), maç yine de değerlendirilir.
    """
    rows = conn.execute(
        "SELECT mp.match_id, mp.player_id, mp.team,"
        " mp.kills, mp.deaths, mp.assists, mp.gold, mp.cs,"
        " mp.damage_to_champs, mp.vision_score, rh.perf_score "
        "FROM match_participants mp "
        "JOIN matches m ON m.id = mp.match_id "
        "LEFT JOIN rating_history rh ON rh.match_id = mp.match_id"
        " AND rh.player_id = mp.player_id AND rh.engine_version = ? "
        "WHERE m.status = 'valid' AND mp.match_id IN ("
        "  SELECT match_id FROM match_participants WHERE player_id = ?) "
        "ORDER BY mp.match_id, mp.id",
        (engine_version, player_id),
    ).fetchall()
    by_match: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        by_match.setdefault(row["match_id"], []).append(row)
    return by_match


def _positions(conn: sqlite3.Connection, player_id: int) -> dict[int, str | None]:
    """match_id → oyuncunun o maçtaki position'ı (versatile için)."""
    rows = conn.execute(
        "SELECT mp.match_id, mp.position FROM match_participants mp "
        "JOIN matches m ON m.id = mp.match_id "
        "WHERE mp.player_id = ? AND m.status = 'valid'",
        (player_id,),
    ).fetchall()
    return {row["match_id"]: row["position"] for row in rows}


def _mvp_key(row: sqlite3.Row) -> tuple:
    """MVP kırılımı: perf ↓ → kills ↓ → assists ↓ → deaths ↑ → player_id ↑.

    NULL k/d/a contract'ta kırılım girdisi olarak tanımlı değildir; burada EN
    KÖTÜ değer sayılır (kills/assists için -1'in altı, deaths için sonsuz), son
    anahtar player_id olduğu için sonuç her hâlükârda deterministiktir.
    """
    return (
        -row["perf_score"],
        -(row["kills"] if row["kills"] is not None else -1),
        -(row["assists"] if row["assists"] is not None else -1),
        row["deaths"] if row["deaths"] is not None else float("inf"),
        row["player_id"],
    )


def _is_mvp(participants: list[sqlite3.Row], winner_team: int, player_id: int) -> bool:
    """Kazanan takımın en yüksek perf_score'lusu bu oyuncu mu?

    perf_score'u NULL olan satır aday değildir; kazanan takımda hiç perf yoksa
    o maçta MVP yoktur.
    """
    candidates = [
        row
        for row in participants
        if row["team"] == winner_team and row["perf_score"] is not None
    ]
    if not candidates:
        return False
    return min(candidates, key=_mvp_key)["player_id"] == player_id


def _holds_record(player_id: int, values: dict[int, float]) -> bool:
    """Maçtaki en yüksek değere sahip mi? Eşitlikte HERKES rozeti alır.

    `values` yalnız non-null statlıları içerir; oyuncu içinde yoksa (kendi
    statı NULL) ya da hiç aday yoksa rozet çıkmaz.
    """
    if player_id not in values:
        return False
    return values[player_id] == max(values.values())


def _stat_values(
    participants: list[sqlite3.Row], column: str
) -> dict[int, float]:
    """player_id → stat değeri; NULL statlılar dışarıda (aday değil)."""
    return {
        row["player_id"]: row[column]
        for row in participants
        if row[column] is not None
    }


def _cs_per_min_values(
    participants: list[sqlite3.Row], duration_s: int | None
) -> dict[int, float]:
    """player_id → cs/dk; `duration_s` yok ya da <= 0 ise maç dışıdır.

    Bölen tüm katılımcılarda aynı olduğundan eşitlik karşılaştırması float
    gürültüsünden etkilenmez (eşit cs → bit-bit eşit cs/dk).
    """
    if duration_s is None or duration_s <= 0:
        return {}
    minutes = duration_s / _SECONDS_PER_MINUTE
    return {
        row["player_id"]: row["cs"] / minutes
        for row in participants
        if row["cs"] is not None
    }


def _is_comeback(
    participants: list[sqlite3.Row], winner_team: int, team: int
) -> bool:
    """Kazanan takımda + iki takımın da 5 gold'u dolu + kazananın toplamı KÜÇÜK."""
    if team != winner_team:
        return False
    totals = {100: 0, 200: 0}
    sizes = {100: 0, 200: 0}
    for row in participants:
        if row["team"] not in totals:
            return False
        if row["gold"] is None:
            return False
        totals[row["team"]] += row["gold"]
        sizes[row["team"]] += 1
    if sizes[100] != TEAM_SIZE or sizes[200] != TEAM_SIZE:
        return False
    loser_team = 200 if winner_team == 100 else 100
    return totals[winner_team] < totals[loser_team]


def _is_bench(participants: list[sqlite3.Row], player_id: int, team: int) -> bool:
    """Oyuncu KENDİ takımının TEK BAŞINA en düşük perf_score'lusu mu?

    Karşılaştırılabilirlik şartı: kendi takımının 5 oyuncusunun da perf'i
    non-null olmalı. Şart sağlanmıyorsa ya da en düşükte eşitlik varsa maç
    bench SAYILMAZ (çağıran için seriyi kıran durum ile aynı sonuç).
    """
    own = [row for row in participants if row["team"] == team]
    if len(own) != TEAM_SIZE:
        return False
    if any(row["perf_score"] is None for row in own):
        return False
    lowest = min(row["perf_score"] for row in own)
    at_lowest = [row["player_id"] for row in own if row["perf_score"] == lowest]
    if len(at_lowest) > 1:
        return False
    return at_lowest[0] == player_id


def player_badges(
    conn: sqlite3.Connection, player_id: int, engine_version: str
) -> dict | None:
    """Oyuncunun rozetleri (api_contract §2); bilinmeyen oyuncuda None.

    Tek geçişte kronolojik olarak yürünür: maç bazlı rozetler o maçta
    değerlendirilir, blok rozetleri sayaçla, eşik/tek-seferlik rozetler ilk
    tamamlandıkları maçla kaydedilir.
    """
    if (
        conn.execute(
            "SELECT 1 FROM players WHERE id = ?", (player_id,)
        ).fetchone()
        is None
    ):
        return None

    matches = _ordered_matches(conn, player_id)
    by_match = _participants(conn, player_id, engine_version)
    positions = _positions(conn, player_id)

    tally = _Tally()
    win_streak = 0
    bench_streak = 0
    played_roles: set[str] = set()

    for played, match in enumerate(matches, start=1):
        match_id = match["match_id"]
        participants = by_match.get(match_id, [])
        me = next(
            (row for row in participants if row["player_id"] == player_id), None
        )
        if me is None:  # savunma amaçlı; _ordered_matches zaten katılımı şart koşar
            continue
        team = me["team"]
        winner_team = match["winner_team"]

        # --- Maç bazlı rozetler ---
        if _is_mvp(participants, winner_team, player_id):
            tally.award("mvp", match_id)

        for key, column in RECORD_STATS.items():
            if _holds_record(player_id, _stat_values(participants, column)):
                tally.award(key, match_id)

        if _holds_record(
            player_id, _cs_per_min_values(participants, match["duration_s"])
        ):
            tally.award("cs_per_min", match_id)

        if me["deaths"] == 0:
            tally.award("deathless", match_id)

        if _is_comeback(participants, winner_team, team):
            tally.award("comeback", match_id)

        # --- Blok rozetleri (ayrık bloklar; kronoloji şart) ---
        if team == winner_team:
            win_streak += 1
            if win_streak == WIN_STREAK_BLOCK:
                tally.award("win_streak_5", match_id)
                win_streak = 0
        else:
            win_streak = 0

        if _is_bench(participants, player_id, team):
            bench_streak += 1
            if bench_streak == BENCH_BLOCK:
                tally.award("bench_3", match_id)
                bench_streak = 0
        else:
            bench_streak = 0

        # --- Tek seferlik / eşik rozetleri ---
        position = positions.get(match_id)
        if position is not None:
            played_roles.add(position)
        if len(played_roles) == len(ROLES) and not tally.has("versatile"):
            tally.award("versatile", match_id)

        for key, threshold in VETERAN_THRESHOLDS.items():
            if played == threshold:
                tally.award(key, match_id)

    return {"player_id": player_id, "badges": tally.to_list()}
