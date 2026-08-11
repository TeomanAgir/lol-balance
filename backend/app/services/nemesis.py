"""Nemesis çifti (api_contract §2 "Nemesis (GÖREV 3)").

SALT-OKUR gösterim + öneri katmanıdır: hiçbir tablo yazılmaz, şema değişmez,
rating modeline dokunmaz (nemesis maçı normal maç olarak rating'e girer, özel
ağırlık YOKTUR — CHANGE_REQUESTS GÖREV 3).

Aday birim (çift, rol) ÜÇLÜSÜDÜR: aynı iki oyuncunun farklı rollerdeki
karşılaşmaları ayrı adaylardır. Haftalık pencere kuralı burada YENİDEN
YAZILMAZ: `weekly.weekly_window` ile haftanın enleriyle birebir aynı yoldan
geçer.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from rating import ROLES

from .weekly import weekly_window

# api_contract §2: aday olabilmek için o rolde en az 3 karşılaşma.
MIN_ENCOUNTERS = 3

# closeness 2 ondalığa yuvarlanır; SIRALAMA ham değerle yapılır.
_PRECISION = 2

# Eşitlik kırılımında kanonik rol sırası (TOP < JUNGLE < MIDDLE < BOTTOM < UTILITY).
_ROLE_ORDER = {role: i for i, role in enumerate(ROLES)}

# Karşılaşma: valid bir maçta KARŞI takımlarda ve İKİSİ DE AYNI (non-null)
# position. `b.player_id > a.player_id` çifti tekilleştirir ve aynı zamanda
# `a` tarafını "küçük player_id" yapar (contract'ın players sırası).
# `b.position = a.position` NULL'ları zaten eler (NULL = NULL → NULL); `a` için
# de açıkça IS NOT NULL denir.
_ENCOUNTER_SQL = """
SELECT a.player_id AS low_id,
       b.player_id AS high_id,
       a.position  AS role,
       COUNT(*)    AS encounters,
       SUM(CASE WHEN m.winner_team = a.team THEN 1 ELSE 0 END) AS low_wins
FROM match_participants a
JOIN match_participants b
  ON b.match_id  = a.match_id
 AND b.team     <> a.team
 AND b.position  = a.position
 AND b.player_id > a.player_id
JOIN matches m ON m.id = a.match_id
WHERE m.status = 'valid'
  AND a.position IS NOT NULL
{extra}
GROUP BY a.player_id, b.player_id, a.position
"""


def _closeness(low_wins: int, encounters: int) -> float:
    """1 - 2*|wins[0]/encounters - 0.5|; 1.0 = tam başa baş (api_contract §2)."""
    return 1.0 - 2.0 * abs(low_wins / encounters - 0.5)


def encounter_candidates(
    conn: sqlite3.Connection, match_ids: list[int] | None = None
) -> list[sqlite3.Row]:
    """Eşiği geçen (çift, rol) adayları. `match_ids=None` → tüm valid maçlar.

    Satır alanları: low_id, high_id, role, encounters, low_wins
    (low_id < high_id; low_wins küçük id'li oyuncunun galibiyet sayısı).
    """
    if match_ids is None:
        sql, params = _ENCOUNTER_SQL.format(extra=""), ()
    elif not match_ids:
        return []  # boş pencere: `IN ()` yazmadan kısa devre
    else:
        placeholders = ",".join("?" * len(match_ids))
        sql = _ENCOUNTER_SQL.format(extra=f"  AND a.match_id IN ({placeholders})")
        params = tuple(match_ids)
    return [
        row
        for row in conn.execute(sql, params)
        if row["encounters"] >= MIN_ENCOUNTERS
    ]


def _display_names(conn: sqlite3.Connection, *player_ids: int) -> dict[int, str]:
    rows = conn.execute(
        "SELECT id, display_name FROM players WHERE id IN (?, ?)", player_ids
    )
    return {row["id"]: row["display_name"] for row in rows}


def _best_pair(
    conn: sqlite3.Connection, match_ids: list[int] | None = None
) -> dict | None:
    """En "başa baş" (çift, rol) adayı; aday yoksa None.

    Sıralama (api_contract §2): closeness azalan → encounters azalan → rol
    kanonik sıra → (küçük player_id, büyük player_id) artan. `min` ile tek
    geçişte seçilir; anahtar tamamen deterministiktir.
    """
    candidates = encounter_candidates(conn, match_ids)
    if not candidates:
        return None

    best = min(
        candidates,
        key=lambda r: (
            -_closeness(r["low_wins"], r["encounters"]),
            -r["encounters"],
            _ROLE_ORDER.get(r["role"], len(ROLES)),
            r["low_id"],
            r["high_id"],
        ),
    )

    low_id, high_id = best["low_id"], best["high_id"]
    encounters, low_wins = best["encounters"], best["low_wins"]
    # Her karşılaşmada iki oyuncu KARŞI takımlardadır → tam biri kazanır.
    high_wins = encounters - low_wins
    names = _display_names(conn, low_id, high_id)
    return {
        "role": best["role"],
        "players": [
            {
                "player_id": low_id,
                "display_name": names.get(low_id, ""),
                "wins": low_wins,
            },
            {
                "player_id": high_id,
                "display_name": names.get(high_id, ""),
                "wins": high_wins,
            },
        ],
        "encounters": encounters,
        "closeness": round(_closeness(low_wins, encounters), _PRECISION),
    }


def nemesis_pairs(
    conn: sqlite3.Connection, now: datetime | None = None
) -> dict:
    """`GET /nemesis` gövdesi (api_contract §2). `now` enjekte edilebilir (test).

    `active`: weekly doluysa "weekly", değilse all_time doluysa "all_time",
    ikisi de boşsa None — maç önerisinin (`POST /balance/nemesis`) kullanacağı
    çifti bu alan belirler.
    """
    all_time = _best_pair(conn)
    _, window_match_ids = weekly_window(conn, now)
    weekly = _best_pair(conn, window_match_ids)

    if weekly is not None:
        active = "weekly"
    elif all_time is not None:
        active = "all_time"
    else:
        active = None

    return {"all_time": all_time, "weekly": weekly, "active": active}
