"""Collector sağlığı (api_contract §6 "Collector sağlığı (GÖREV 13)").

Heartbeat ingest'ten BAĞIMSIZ yaşar: `collector_health` upsert'tir, rating'e
hiçbir etkisi yoktur. `client_id` kuralının (trim + ≤64) TEK tanımı burasıdır —
ingest de heartbeat de bu yardımcılardan geçer, kural iki yerde kopyalanmaz.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

CLIENT_ID_MAX_LEN = 64


def utc_now_z(now: datetime | None = None) -> str:
    """SUNUCU saati, UTC "…Z" biçiminde (client saatine güvenilmez).

    `now` yalnız deterministik test için enjekte edilir (weekly_window deseni).
    """
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _trim(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    trimmed = raw.strip()
    return trimmed or None


def _check_length(client_id: str) -> str:
    if len(client_id) > CLIENT_ID_MAX_LEN:
        raise HTTPException(
            422,
            detail=(
                f"client_id en fazla {CLIENT_ID_MAX_LEN} karakter olabilir, "
                f"geldi: {len(client_id)}."
            ),
        )
    return client_id


def normalize_optional_client_id(raw: Optional[str]) -> Optional[str]:
    """Ingest gövdesindeki opsiyonel `client_id` (ingest_contract "client_id").

    Trim'lenir; boş/boşluk-yalnızca değer alan hiç gönderilmemiş sayılır (None)
    — eski exe'lerle geriye uyumluluk, bir izleme alanı yüzünden maç reddedilmez.
    64'ten uzun değer ise şema ihlalidir → 422.
    """
    client_id = _trim(raw)
    return None if client_id is None else _check_length(client_id)


def require_client_id(raw: Optional[str]) -> str:
    """Heartbeat'in zorunlu `client_id`'si (api_contract §6): boşsa/uzunsa 422."""
    client_id = _trim(raw)
    if client_id is None:
        raise HTTPException(
            422, detail="client_id zorunlu (boş olmayan bir metin gönderin)."
        )
    return _check_length(client_id)


def record_heartbeat(
    conn: sqlite3.Connection,
    client_id: str,
    version: Optional[str] = None,
    outbox_pending: Optional[int] = None,
    now: datetime | None = None,
) -> str:
    """Cihazın sağlık kaydını upsert eder; atanan `last_seen`'i döner.

    Upsert semantiği "son heartbeat kazanır"dır: version/outbox_pending
    gönderilmediyse kayıttaki değer de NULL'a döner (alanlar o anki durumu
    gösterir, tarihçe tutulmaz).
    """
    last_seen = utc_now_z(now)
    with conn:
        conn.execute(
            "INSERT INTO collector_health"
            " (client_id, last_seen, version, outbox_pending)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(client_id) DO UPDATE SET"
            "   last_seen = excluded.last_seen,"
            "   version = excluded.version,"
            "   outbox_pending = excluded.outbox_pending",
            (client_id, last_seen, version, outbox_pending),
        )
    return last_seen


def list_collectors(conn: sqlite3.Connection) -> list[dict]:
    """Sağlık listesi: `last_seen` azalan (eşitlikte client_id artan, determinizm).

    `last_ingest_*` cihazın `matches.client_id` izinden en son maçıdır; VOID
    maçlar DAHİLDİR — bu operasyonel izdir, rating süzgeci değil.
    """
    rows = conn.execute(
        "SELECT ch.client_id, ch.last_seen, ch.version, ch.outbox_pending,"
        "       m.played_at AS last_ingest_at,"
        "       m.source_game_id AS last_ingest_game_id "
        "FROM collector_health ch "
        "LEFT JOIN matches m ON m.id = ("
        "    SELECT id FROM matches WHERE client_id = ch.client_id"
        "    ORDER BY played_at DESC, id DESC LIMIT 1) "
        "ORDER BY ch.last_seen DESC, ch.client_id ASC"
    ).fetchall()
    return [dict(row) for row in rows]
