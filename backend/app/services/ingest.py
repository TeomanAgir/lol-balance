"""Ingest iş kuralları (docs/ingest_contract.md + db_schema.md kenar durumları)."""
from __future__ import annotations

import logging
import sqlite3

from fastapi import HTTPException

from ..schemas import IngestMatch, IngestParticipant
from . import ratings as rating_service
from . import role_ratings as role_rating_service

VOID_THRESHOLD_S = 300

logger = logging.getLogger(__name__)


def validate_rules(body: IngestMatch) -> None:
    """Pydantic'in tip kontrolü sonrası contract'ın sayısal kurallarını doğrular."""
    n = len(body.participants)
    if n != 10:
        raise HTTPException(
            422, detail=f"participants tam 10 eleman içermeli, geldi: {n}."
        )
    n100 = sum(1 for p in body.participants if p.team == 100)
    if n100 != 5:
        raise HTTPException(
            422,
            detail=f"Her takımda tam 5 oyuncu olmalı (team=100 için {n100} geldi).",
        )
    for i, p in enumerate(body.participants):
        if p.puuid is None and p.player_id is None:
            raise HTTPException(
                422,
                detail=f"participants[{i}]: puuid veya player_id'den en az biri zorunlu.",
            )


def _display_name_from(participant: IngestParticipant) -> str:
    if participant.riot_id:
        return participant.riot_id.split("#", 1)[0]
    assert participant.puuid is not None
    return participant.puuid[:12]


def resolve_player(conn: sqlite3.Connection, p: IngestParticipant, index: int) -> int:
    """Participant'ı bir players satırına bağlar; gerekirse oluşturur.

    Sıra (db_schema "Yeni oyuncu"): player_id → puuid → riot_id (puuid'siz kayıt,
    case-insensitive) → auto-create. Aynı kişi için asla ikinci satır açılmaz.
    """
    if p.player_id is not None:
        row = conn.execute(
            "SELECT id, puuid FROM players WHERE id = ?", (p.player_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(
                422, detail=f"participants[{index}]: player_id {p.player_id} bulunamadı."
            )
        if p.puuid and row["puuid"] is None:
            conn.execute(
                "UPDATE players SET puuid = ? WHERE id = ?", (p.puuid, row["id"])
            )
        return row["id"]

    row = conn.execute(
        "SELECT id FROM players WHERE puuid = ?", (p.puuid,)
    ).fetchone()
    if row is not None:
        return row["id"]

    if p.riot_id:
        row = conn.execute(
            "SELECT id FROM players "
            "WHERE puuid IS NULL AND riot_id IS NOT NULL "
            "AND lower(riot_id) = lower(?) ORDER BY id LIMIT 1",
            (p.riot_id,),
        ).fetchone()
        if row is not None:
            conn.execute(
                "UPDATE players SET puuid = ? WHERE id = ?", (p.puuid, row["id"])
            )
            return row["id"]

    cur = conn.execute(
        "INSERT INTO players (puuid, riot_id, display_name) VALUES (?, ?, ?)",
        (p.puuid, p.riot_id, _display_name_from(p)),
    )
    return cur.lastrowid


def ingest_match(
    conn: sqlite3.Connection,
    body: IngestMatch,
    raw_payload: str,
    engine_version: str,
) -> tuple[int, bool]:
    """Maçı işler; (match_id, duplicate) döner. Tek transaction'da koşar."""
    validate_rules(body)

    existing = conn.execute(
        "SELECT id FROM matches WHERE source_game_id = ?", (body.source_game_id,)
    ).fetchone()
    if existing is not None:
        return existing["id"], True

    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO ingest_events (source, source_game_id, payload_json) "
                "VALUES (?, ?, ?)",
                (body.source, body.source_game_id, raw_payload),
            )
            ingest_event_id = cur.lastrowid

            player_ids = [
                resolve_player(conn, p, i) for i, p in enumerate(body.participants)
            ]
            if len(set(player_ids)) != len(player_ids):
                raise HTTPException(
                    422, detail="Aynı oyuncu birden fazla participant'ta yer alamaz."
                )

            is_void = (
                body.duration_s is not None and body.duration_s < VOID_THRESHOLD_S
            )
            cur = conn.execute(
                "INSERT INTO matches (ingest_event_id, source_game_id, played_at,"
                " duration_s, winner_team, status) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    ingest_event_id,
                    body.source_game_id,
                    body.played_at,
                    body.duration_s,
                    body.winner_team,
                    "void" if is_void else "valid",
                ),
            )
            match_id = cur.lastrowid

            for p, player_id in zip(body.participants, player_ids):
                stats = p.stats
                conn.execute(
                    "INSERT INTO match_participants (match_id, player_id, team,"
                    " position, champion, kills, deaths, assists, gold, cs,"
                    " damage_to_champs, vision_score)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        match_id,
                        player_id,
                        p.team,
                        p.position,
                        p.champion,
                        stats.kills if stats else None,
                        stats.deaths if stats else None,
                        stats.assists if stats else None,
                        stats.gold if stats else None,
                        stats.cs if stats else None,
                        stats.damage_to_champs if stats else None,
                        stats.vision_score if stats else None,
                    ),
                )

            if not is_void:
                # Sıra-dışı geliş (api_contract §5): maç, replay sırasında sona
                # düşmüyorsa incremental "son maçı üste uygula" varsayımı çöker.
                # O durumda tek maç yerine HER İKİ evren baştan kurulur; replay
                # servisleri aynen kullanılır (mantık kopyalanmaz).
                if rating_service.is_out_of_order(conn, match_id, body.played_at):
                    logger.info(
                        "Sıra-dışı ingest: match_id=%s source_game_id=%s "
                        "played_at=%s mevcut valid maçların sonunda değil; "
                        "incremental yerine her iki evren replay ediliyor.",
                        match_id,
                        body.source_game_id,
                        body.played_at,
                    )
                    # Not: replay/replay_roles kendi `with conn:` bloklarını
                    # açar; iç içe sqlite3 context manager'ı dıştaki açık
                    # transaction'ı commit eder — yani maç + replay birlikte
                    # kalıcı olur, replay patlarsa maç da geri alınır.
                    rating_service.replay(conn, engine_version)
                    role_rating_service.replay_roles(conn, engine_version)
                else:
                    rating_service.apply_match_incremental(
                        conn, match_id, body.winner_team, engine_version
                    )
                    # Rol evreni ayrı state uzayıdır; uygunluk kontrolü içeride
                    # yapılır, uygun değilse sessizce atlanır (GÖREV 0).
                    role_rating_service.apply_match_incremental_roles(
                        conn, match_id, body.winner_team, engine_version
                    )
    except sqlite3.IntegrityError as exc:
        # Eşzamanlı çift gönderim: UNIQUE(source_game_id) yarışı kaybedildi.
        if "source_game_id" in str(exc):
            row = conn.execute(
                "SELECT id FROM matches WHERE source_game_id = ?",
                (body.source_game_id,),
            ).fetchone()
            if row is not None:
                return row["id"], True
        raise

    return match_id, False
