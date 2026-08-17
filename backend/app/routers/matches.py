"""Maç listesi ve void işlemi (api_contract §3)."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query
from rating import ROLES, Engine

from ..config import Settings, get_settings
from ..deps import get_db
from ..schemas import (
    ItemsUpdate,
    ItemsUpdateResponse,
    PositionsUpdate,
    PositionsUpdateResponse,
    RouletteUnlinkResponse,
)
from ..services.items import dump_items, load_items, validate_items
from ..services.rating_history import historical_score, match_perf_prefixes
from ..services.ratings import is_blend, replay
from ..services.role_ratings import replay_roles
from ..services.roulette import match_roulette, unlink_match

router = APIRouter()


_MATCH_COLUMNS = (
    "id, source_game_id, played_at, duration_s, winner_team, status"
)


def _rating_change(
    row: sqlite3.Row,
    engine: Engine,
    blend: bool,
    prefixes: dict[int, tuple[tuple[float, int], tuple[float, int]]],
) -> dict | None:
    """`rating_change` nesnesi (api_contract §3); rating satırı yoksa None.

    `score_before`/`score_after` (GÖREV 18) rating tarihçesi endpoint'iyle
    BİREBİR aynı tanımdır: kümülatif önek P_avg'li tarihsel efektif score,
    hesap `rating_history.historical_score` üzerinden (formül kopyalanmaz).
    "önce" öneki maçı hariç tutar; oyuncunun önceki maçı yoksa default durum
    (rh.mu_before/sigma_before zaten default + boş önek → nötr P_avg).
    """
    if row["mu_after"] is None:
        return None
    (before_sum, before_count), (after_sum, after_count) = prefixes[
        row["player_id"]
    ]
    return {
        "mu_before": row["mu_before"],
        "sigma_before": row["sigma_before"],
        "mu_after": row["mu_after"],
        "sigma_after": row["sigma_after"],
        # Hassasiyet: 2 ondalık, yuvarlama yalnız çıktıda (api_contract §3).
        "score_before": round(
            historical_score(
                engine, blend, row["mu_before"], row["sigma_before"],
                before_sum, before_count,
            ),
            2,
        ),
        "score_after": round(
            historical_score(
                engine, blend, row["mu_after"], row["sigma_after"],
                after_sum, after_count,
            ),
            2,
        ),
    }


def _serialize_match(
    conn: sqlite3.Connection, match: sqlite3.Row, engine_version: str
) -> dict:
    """Tek maçın yanıt şekli — liste ve tekil endpoint TEK bu fonksiyonu kullanır
    (api_contract §3: `GET /matches/{id}` liste elemanıyla BİREBİR aynı şekil).
    """
    engine = Engine(version=engine_version)
    blend = is_blend(engine)
    participants = conn.execute(
        "SELECT mp.player_id, p.display_name, mp.team, mp.position, mp.champion,"
        " mp.kills, mp.deaths, mp.assists, mp.gold, mp.cs,"
        " mp.damage_to_champs, mp.vision_score, mp.items_json,"
        " rh.mu_before, rh.sigma_before, rh.mu_after, rh.sigma_after,"
        " rh.perf_score "
        "FROM match_participants mp "
        "JOIN players p ON p.id = mp.player_id "
        "LEFT JOIN rating_history rh ON rh.match_id = mp.match_id"
        " AND rh.player_id = mp.player_id AND rh.engine_version = ? "
        "WHERE mp.match_id = ? ORDER BY mp.team, mp.id",
        (engine_version, match["id"]),
    ).fetchall()
    # Önek toplamları yalnız rating satırı olan katılımcılar için gerekir;
    # void maçta (replay satırları silmiştir) hiç sorgu atılmaz.
    scored_ids = [
        row["player_id"] for row in participants if row["mu_after"] is not None
    ]
    prefixes = (
        match_perf_prefixes(
            conn, engine_version, match["id"], match["played_at"], scored_ids
        )
        if scored_ids
        else {}
    )
    return {
        **dict(match),
        # api_contract §3 (GÖREV 23): maça bağlı rulet oturumu yoksa null;
        # liste + detay aynı şekil (serializasyon paylaşıldığı için otomatik).
        "roulette": match_roulette(conn, match["id"], match["winner_team"]),
        "participants": [
            {
                "player_id": row["player_id"],
                "display_name": row["display_name"],
                "team": row["team"],
                "position": row["position"],
                "champion": row["champion"],
                "stats": {
                    "kills": row["kills"],
                    "deaths": row["deaths"],
                    "assists": row["assists"],
                    "gold": row["gold"],
                    "cs": row["cs"],
                    "damage_to_champs": row["damage_to_champs"],
                    "vision_score": row["vision_score"],
                },
                # api_contract §3 (GÖREV 14): null = "bilinmiyor" (eski exe/maç),
                # [] = "bilgi var, envanter boş".
                "items": load_items(row["items_json"]),
                "rating_change": _rating_change(row, engine, blend, prefixes),
            }
            for row in participants
        ],
    }


@router.get("/matches")
def list_matches(
    limit: int = Query(default=20, ge=1, le=200),
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    matches = conn.execute(
        f"SELECT {_MATCH_COLUMNS} "
        "FROM matches ORDER BY played_at DESC, id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        _serialize_match(conn, m, settings.engine_version) for m in matches
    ]


@router.get("/matches/{match_id}")
def get_match(
    match_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Tek maç (api_contract §3, GÖREV 10: profil grafiğinden maç detayına atlama).

    Şekil liste elemanıyla birebir aynıdır — serializasyon paylaşılır.
    """
    match = conn.execute(
        f"SELECT {_MATCH_COLUMNS} FROM matches WHERE id = ?", (match_id,)
    ).fetchone()
    if match is None:
        raise HTTPException(404, detail=f"Maç bulunamadı: {match_id}.")
    return _serialize_match(conn, match, settings.engine_version)


@router.post("/matches/{match_id}/void")
def void_match(
    match_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    row = conn.execute(
        "SELECT id, status FROM matches WHERE id = ?", (match_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, detail=f"Maç bulunamadı: {match_id}.")
    with conn:
        conn.execute(
            "UPDATE matches SET status = 'void' WHERE id = ?", (match_id,)
        )
    # Void, geçmişi değiştirir → HER İKİ evrende otomatik replay
    # (api_contract §5; rol evreni GÖREV 0).
    matches_replayed = replay(conn, settings.engine_version)
    role_matches_replayed = replay_roles(conn, settings.engine_version)
    return {
        "match_id": match_id,
        "status": "void",
        "matches_replayed": matches_replayed,
        "role_matches_replayed": role_matches_replayed,
        "engine_version": settings.engine_version,
    }


@router.post("/matches/{match_id}/roulette/unlink")
def unlink_roulette(
    match_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RouletteUnlinkResponse:
    """Yanlış otomatik eşleşmeyi çözer (api_contract §4.5, GÖREV 23).

    Maç `valid` olur, oturum `cancelled` olur ve HER İKİ evren replay koşar
    (maç rating'e girer — sıra-dışı ingest replay'iyle aynı mekanizma).
    Ters yönde manuel bağlama (valid → roulette) YOKTUR.
    """
    row = conn.execute(
        "SELECT id, status FROM matches WHERE id = ?", (match_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, detail=f"Maç bulunamadı: {match_id}.")
    if row["status"] != "roulette":
        raise HTTPException(
            409,
            detail=(
                f"Maç bir rulet maçı değil (durum: {row['status']}); "
                "unlink yalnız roulette maçlarda çalışır."
            ),
        )
    unlink_match(conn, match_id)
    matches_replayed = replay(conn, settings.engine_version)
    role_matches_replayed = replay_roles(conn, settings.engine_version)
    return RouletteUnlinkResponse(
        status="valid",
        matches_replayed=matches_replayed,
        role_matches_replayed=role_matches_replayed,
    )


def _match_participant_ids(conn: sqlite3.Connection, match_id: int) -> set[int]:
    return {
        r["player_id"]
        for r in conn.execute(
            "SELECT player_id FROM match_participants WHERE match_id = ?",
            (match_id,),
        )
    }


@router.put("/matches/{match_id}/items")
def update_items(
    match_id: int,
    body: ItemsUpdate,
    conn: sqlite3.Connection = Depends(get_db),
) -> ItemsUpdateResponse:
    """Katılımcı envanterlerini yazar (api_contract §3, GÖREV 14).

    Collector `backfill-items` ham arşivden çağırır; ham arşiv OTORİTEDİR, bu
    yüzden mevcut değerin ÜZERİNE yazılır. `items_json` küratörlü alandır
    (position deseni): ham `ingest_events` DEĞİŞMEZ. Rating'e etkisi yoktur —
    hiçbir replay tetiklenmez.
    """
    row = conn.execute(
        "SELECT id FROM matches WHERE id = ?", (match_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, detail=f"Maç bulunamadı: {match_id}.")

    participants = _match_participant_ids(conn, match_id)

    # Önce TÜM girdi doğrulanır, sonra yazılır (positions deseni): hata
    # durumunda DB'ye hiç dokunulmaz, kısmen uygulanmış güncelleme olmaz.
    updates: list[tuple[int, str]] = []
    for raw_key, value in body.items.items():
        try:
            player_id = int(raw_key)
        except (TypeError, ValueError):
            raise HTTPException(
                422,
                detail=f"items anahtarı oyuncu id'si olmalı, geldi: {raw_key!r}.",
            ) from None
        if player_id not in participants:
            raise HTTPException(
                422,
                detail=f"Oyuncu {player_id} bu maçta yer almıyor (maç {match_id}).",
            )
        updates.append(
            (player_id, dump_items(validate_items(value, f"Oyuncu {player_id}")))
        )

    updated = 0
    with conn:
        for player_id, value in updates:
            cur = conn.execute(
                "UPDATE match_participants SET items_json = ? "
                "WHERE match_id = ? AND player_id = ?",
                (value, match_id, player_id),
            )
            updated += cur.rowcount

    return ItemsUpdateResponse(updated=updated)


@router.put("/matches/{match_id}/positions")
def update_positions(
    match_id: int,
    body: PositionsUpdate,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PositionsUpdateResponse:
    """Katılımcı rollerini günceller (api_contract §3).

    `match_participants.position` küratörlü alandır (db_schema ilke 5): ham
    `ingest_events` DEĞİŞMEZ. Yalnız rol evreni replay edilir; ana rating
    bit-bit korunur.
    """
    row = conn.execute(
        "SELECT id FROM matches WHERE id = ?", (match_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, detail=f"Maç bulunamadı: {match_id}.")

    participants = _match_participant_ids(conn, match_id)

    # Önce TÜM girdi doğrulanır, sonra yazılır: kısmen uygulanmış güncelleme
    # olmaz (hata durumunda DB'ye hiç dokunulmaz).
    updates: list[tuple[int, str | None]] = []
    for raw_key, value in body.positions.items():
        try:
            player_id = int(raw_key)
        except (TypeError, ValueError):
            raise HTTPException(
                422,
                detail=f"positions anahtarı oyuncu id'si olmalı, geldi: {raw_key!r}.",
            ) from None
        if player_id not in participants:
            raise HTTPException(
                422,
                detail=f"Oyuncu {player_id} bu maçta yer almıyor (maç {match_id}).",
            )
        if value is not None and value not in ROLES:
            raise HTTPException(
                422,
                detail=(
                    f"Geçersiz rol: {value!r}. "
                    f"Geçerli roller: {', '.join(ROLES)} veya null."
                ),
            )
        updates.append((player_id, value))

    updated = 0
    with conn:
        for player_id, value in updates:
            cur = conn.execute(
                "UPDATE match_participants SET position = ? "
                "WHERE match_id = ? AND player_id = ?",
                (value, match_id, player_id),
            )
            updated += cur.rowcount

    # Rol düzeltmesi rol evreninde replay tetikler; ana evren ETKİLENMEZ.
    role_matches_replayed = replay_roles(conn, settings.engine_version)
    return PositionsUpdateResponse(
        updated=updated, role_matches_replayed=role_matches_replayed
    )
