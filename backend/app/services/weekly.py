"""Haftanın enleri (api_contract §2 "Haftanın enleri (GÖREV 2)").

SALT-OKUR gösterim endpoint'idir: hiçbir tablo yazılmaz, rating hesabına
etkisi yoktur, şema değişmez. Tüm metrikler yalnız `status='valid'` maçlardan
ve AKTİF `engine_version`'ın rating satırlarından türetilir.

Score hesabı burada YENİDEN YAZILMAZ: `ratings.effective_score` ile players
router'ın kullandığı yolun aynısından geçer (harman/harman-olmayan dallanması
tek yerdedir).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from rating import ROLES, Engine, Rating

from .ratings import current_ratings, effective_score, is_blend, perf_averages
from .role_ratings import current_role_ratings, role_perf_averages

# api_contract §2: pencere = son 7 gün, `start < played_at <= end`.
WINDOW_DAYS = 7

# Örnek payload'daki değerler (score 5.5, delta 2.31) 2 basamağa
# yuvarlanmış hâldedir; contract delta için 2 ondalığı açıkça şart koşar.
# Sıralama ve eşitlik kırılımları YUVARLANMAMIŞ değerlerle yapılır.
_PRECISION = 2


def _as_utc(dt: datetime) -> datetime:
    """Naive datetime UTC kabul edilir; aware olan UTC'ye çevrilir."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_played_at(text: str | None) -> datetime | None:
    """`matches.played_at` (UTC ISO8601 TEXT) → aware datetime; bozuksa None.

    Kolon TEXT olduğu için 'Z' son eki, offset'li ve offset'siz biçimler
    gelebilir; hepsi UTC'ye normalize edilir. Ayrıştırılamayan satır pencere
    hesabına giremez (sessizce dışarıda kalır — endpoint salt-okur olduğu için
    tek etkisi o maçın enlerde görünmemesidir).
    """
    if not text:
        return None
    s = text.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        return _as_utc(datetime.fromisoformat(s))
    except ValueError:
        return None


def _iso(dt: datetime) -> str:
    """Contract'ın window biçimi: '2026-08-05T21:00:00Z'."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _round(value: float) -> float:
    return round(value, _PRECISION)


def _valid_matches(conn: sqlite3.Connection) -> list[tuple[int, datetime]]:
    """(match_id, played_at) — valid maçlar, kronolojik (replay ile aynı sıra)."""
    rows = conn.execute(
        "SELECT id, played_at FROM matches WHERE status = 'valid'"
    ).fetchall()
    parsed = [
        (row["id"], dt)
        for row in rows
        if (dt := _parse_played_at(row["played_at"])) is not None
    ]
    parsed.sort(key=lambda item: (item[1], item[0]))
    return parsed


def _window(
    matches: list[tuple[int, datetime]], now: datetime
) -> tuple[datetime, datetime, bool, list[tuple[int, datetime]]]:
    """Pencereyi ve içindeki maçları döner (api_contract §2 "Pencere").

    Rolling pencere boşsa `end` en son valid maça çapalanır (`fallback=True`)
    — ekran veri varken boş kalmaz. Hiç valid maç yoksa rolling pencere
    aynen döner (çapalanacak maç yoktur → fallback=False, içi boş).
    """

    def slice_at(end: datetime) -> tuple[datetime, list[tuple[int, datetime]]]:
        start = end - timedelta(days=WINDOW_DAYS)
        return start, [m for m in matches if start < m[1] <= end]

    end = now
    start, in_window = slice_at(end)
    if not in_window and matches:
        end = matches[-1][1]
        start, in_window = slice_at(end)
        return start, end, True, in_window
    return start, end, False, in_window


def _pick(rows: list[dict], value_key: str) -> dict | None:
    """Eşitlik kırılımı (api_contract §2): değer ↓ → pencere maç sayısı ↓ →
    display_name alfabetik. Aday yoksa None."""
    if not rows:
        return None
    best = min(
        rows,
        key=lambda r: (-r["value"], -r["matches_in_window"], r["display_name"]),
    )
    return {
        "player_id": best["player_id"],
        "display_name": best["display_name"],
        value_key: _round(best["value"]),
        "matches_in_window": best["matches_in_window"],
    }


def _placeholders(n: int) -> str:
    return ",".join("?" * n)


def _window_participation(
    conn: sqlite3.Connection, match_ids: list[int]
) -> dict[int, tuple[str, int]]:
    """player_id → (display_name, penceredeki valid maç sayısı)."""
    rows = conn.execute(
        "SELECT mp.player_id AS player_id, p.display_name AS display_name,"
        " COUNT(*) AS n "
        "FROM match_participants mp "
        "JOIN players p ON p.id = mp.player_id "
        f"WHERE mp.match_id IN ({_placeholders(len(match_ids))}) "
        "GROUP BY mp.player_id, p.display_name",
        match_ids,
    ).fetchall()
    return {r["player_id"]: (r["display_name"], r["n"]) for r in rows}


def _best_player(
    participation: dict[int, tuple[str, int]],
    engine: Engine,
    blend: bool,
    default: Rating,
    ratings: dict[int, Rating],
    p_avgs: dict[int, float],
) -> dict | None:
    """Pencerede ≥1 maç oynayanlar arasında GÜNCEL score'u en yüksek olan.

    Score güncel değerdir (leaderboard ile aynı): pencerede oynamamış yüksek
    score'lu oyuncu ADAY DEĞİLDİR.
    """
    rows = [
        {
            "player_id": pid,
            "display_name": name,
            "value": effective_score(
                engine,
                blend,
                ratings.get(pid, default),
                p_avgs.get(pid, 1.0) if blend else None,
            ),
            "matches_in_window": n,
        }
        for pid, (name, n) in participation.items()
    ]
    return _pick(rows, "score")


def _rising_star(
    conn: sqlite3.Connection,
    engine_version: str,
    match_ids: list[int],
    order: dict[int, int],
    participation: dict[int, tuple[str, int]],
) -> dict | None:
    """Pencere içi ordinal artışı en yüksek olan (api_contract §2).

    `delta = (mu−3σ) son pencere maçı SONRASI − (mu−3σ) ilk pencere maçı
    ÖNCESİ`; ana evren `rating_history`, aktif engine_version. Negatif olabilir
    — yine en yükseği döner. Pencere maçları için (aktif version'da) rating
    satırı olmayan oyuncu delta üretemez, aday olmaz.
    """
    rows = conn.execute(
        "SELECT player_id, match_id, mu_before, sigma_before, mu_after, sigma_after "
        "FROM rating_history "
        f"WHERE engine_version = ? AND match_id IN ({_placeholders(len(match_ids))})",
        (engine_version, *match_ids),
    ).fetchall()

    by_player: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        by_player.setdefault(row["player_id"], []).append(row)

    candidates = []
    for player_id, player_rows in by_player.items():
        if player_id not in participation:
            continue
        player_rows.sort(key=lambda r: order[r["match_id"]])
        first, last = player_rows[0], player_rows[-1]
        before = first["mu_before"] - 3.0 * first["sigma_before"]
        after = last["mu_after"] - 3.0 * last["sigma_after"]
        name, n = participation[player_id]
        candidates.append(
            {
                "player_id": player_id,
                "display_name": name,
                "value": after - before,
                "matches_in_window": n,
            }
        )
    return _pick(candidates, "delta")


def _best_by_role(
    conn: sqlite3.Connection,
    engine: Engine,
    engine_version: str,
    blend: bool,
    default: Rating,
    match_ids: list[int],
) -> dict[str, dict | None]:
    """Her rol için: pencerede O ROLDE ≥1 maç oynayanlar arasında GÜNCEL rol
    score'u en yüksek olan; kimse oynamadıysa None.

    Rolde oynama kaydı `role_rating_history`'dendir (contract): rol evrenine
    uygun olmayan maçlar orada satır üretmez, dolayısıyla enlere de girmez.
    """
    rows = conn.execute(
        "SELECT rrh.player_id AS player_id, rrh.role AS role,"
        " p.display_name AS display_name, COUNT(*) AS n "
        "FROM role_rating_history rrh "
        "JOIN players p ON p.id = rrh.player_id "
        "WHERE rrh.engine_version = ? "
        f"AND rrh.match_id IN ({_placeholders(len(match_ids))}) "
        "GROUP BY rrh.player_id, rrh.role, p.display_name",
        (engine_version, *match_ids),
    ).fetchall()

    role_ratings = current_role_ratings(conn, engine_version)
    role_p_avgs = role_perf_averages(conn, engine_version) if blend else {}

    per_role: dict[str, list[dict]] = {role: [] for role in ROLES}
    for row in rows:
        key = (row["player_id"], row["role"])
        per_role.setdefault(row["role"], []).append(
            {
                "player_id": row["player_id"],
                "display_name": row["display_name"],
                "value": effective_score(
                    engine,
                    blend,
                    role_ratings.get(key, default),
                    role_p_avgs.get(key, 1.0) if blend else None,
                ),
                "matches_in_window": row["n"],
            }
        )
    return {role: _pick(per_role.get(role, []), "score") for role in ROLES}


def weekly_highlights(
    conn: sqlite3.Connection,
    engine_version: str,
    now: datetime | None = None,
) -> dict:
    """Haftanın enleri (api_contract §2). `now` enjekte edilebilir (test).

    `now` verilmezse gerçek UTC şimdi kullanılır; her iki hâlde saniyeye
    yuvarlanır ki dönen `window` ile filtreleme birebir aynı anı ifade etsin.
    """
    now = _as_utc(now if now is not None else datetime.now(timezone.utc))
    now = now.replace(microsecond=0)

    matches = _valid_matches(conn)
    start, end, fallback, in_window = _window(matches, now)
    window_out = {"start": _iso(start), "end": _iso(end), "fallback": fallback}

    if not in_window:
        # Hiç valid maç yok (ya da hepsi ayrıştırılamadı) → çapalanacak veri de
        # yok: contract gereği üç alan da null döner.
        return {
            "window": window_out,
            "best_player": None,
            "rising_star": None,
            "best_by_role": {role: None for role in ROLES},
        }

    match_ids = [m[0] for m in in_window]
    order = {mid: i for i, mid in enumerate(match_ids)}  # kronolojik sıra

    engine = Engine(version=engine_version)
    blend = is_blend(engine)
    default = engine.default_rating()
    ratings = current_ratings(conn, engine_version)
    p_avgs = perf_averages(conn, engine_version) if blend else {}

    participation = _window_participation(conn, match_ids)

    return {
        "window": window_out,
        "best_player": _best_player(
            participation, engine, blend, default, ratings, p_avgs
        ),
        "rising_star": _rising_star(
            conn, engine_version, match_ids, order, participation
        ),
        "best_by_role": _best_by_role(
            conn, engine, engine_version, blend, default, match_ids
        ),
    }
