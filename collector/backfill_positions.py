"""Geçmiş maçların rollerini backend'e yazan tek seferlik backfill (GÖREV 0).

`python -m collector backfill-positions [--dry-run]`

Akış:
1. `raw_archive/*.json` içindeki her ham maç için `role_infer` zinciri koşulur.
2. `GET /api/v1/matches` ile `source_game_id → match.id` eşlenir.
3. `GET /api/v1/players` ile `puuid → player_id` eşlenir (api_contract §2).
4. `PUT /api/v1/matches/{id}/positions` ile `{"positions": {"<player_id>": "ROL"}}`
   gönderilir. `None` kalan roller GÖNDERİLMEZ (kısmi güncelleme serbesttir;
   böylece daha önce elle düzeltilmiş bir rol tahminle ezilmez).

Eşleşmeyen maç/oyuncu ölümcül değildir: uyarı yazılır, tarama devam eder.
Komut idempotenttir; istenildiği kadar tekrar koşturulabilir.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx

from .config import Config
from .role_infer import infer_positions

log = logging.getLogger("collector.backfill_positions")

MATCHES_PATH = "/api/v1/matches"
PLAYERS_PATH = "/api/v1/players"
POSITIONS_PATH = "/api/v1/matches/{match_id}/positions"

#: Backend `GET /matches` limitini 200'de sınırlar (api_contract §3 / Query le=200)
MATCH_LIST_LIMIT = 200


@dataclass
class PositionBackfillStats:
    archives: int = 0  # okunan ham maç dosyası
    matched: int = 0  # backend'de karşılığı bulunan maç
    updated: int = 0  # PUT gönderilen (dry-run'da gönderilecek olan) maç
    positions_sent: int = 0  # gönderilen rol sayısı
    unresolved: int = 0  # tahmin zinciri çözemedi → gönderilmedi
    unmatched_matches: list[str] = field(default_factory=list)
    unknown_players: int = 0
    errors: list[str] = field(default_factory=list)


def _client(config: Config, transport: httpx.BaseTransport | None) -> httpx.Client:
    return httpx.Client(
        base_url=config.backend_url,
        headers={"X-API-Key": config.api_key},
        timeout=30.0,
        transport=transport,
    )


def fetch_match_index(client: httpx.Client, limit: int = MATCH_LIST_LIMIT) -> dict[str, dict]:
    """`source_game_id → {"id": int, "player_ids": set[int], "status": str}`."""
    response = client.get(MATCHES_PATH, params={"limit": limit})
    response.raise_for_status()
    index: dict[str, dict] = {}
    for match in response.json() or []:
        source_game_id = match.get("source_game_id")
        if source_game_id is None:
            continue
        index[str(source_game_id)] = {
            "id": match.get("id"),
            "status": match.get("status"),
            "player_ids": {
                p.get("player_id") for p in match.get("participants") or []
            },
        }
    return index


def fetch_player_index(client: httpx.Client) -> dict[str, int]:
    """`puuid → player_id` (puuid'i olmayan oyuncular atlanır)."""
    response = client.get(PLAYERS_PATH)
    response.raise_for_status()
    index: dict[str, int] = {}
    for player in response.json() or []:
        puuid, player_id = player.get("puuid"), player.get("id")
        if puuid and player_id is not None:
            index[str(puuid)] = int(player_id)
    return index


def _archive_files(config: Config, archive_dir: Optional[Path]) -> list[Path]:
    directory = archive_dir or config.raw_archive_dir
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.json"))


def _load_raw(path: Path) -> Optional[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.error("Ham maç dosyası okunamadı, atlanıyor: %s (%s)", path.name, exc)
        return None
    return data if isinstance(data, dict) else None


def run_position_backfill(
    config: Config,
    *,
    dry_run: bool = False,
    transport: httpx.BaseTransport | None = None,
    archive_dir: Optional[Path] = None,
    limit: int = MATCH_LIST_LIMIT,
) -> PositionBackfillStats:
    stats = PositionBackfillStats()
    files = _archive_files(config, archive_dir)
    if not files:
        log.warning(
            "Ham maç arşivi boş (%s): backfill-positions yapacak iş bulamadı",
            archive_dir or config.raw_archive_dir,
        )
        return stats

    with _client(config, transport) as client:
        try:
            matches = fetch_match_index(client, limit=min(limit, MATCH_LIST_LIMIT))
            players = fetch_player_index(client)
        except (httpx.HTTPError, ValueError) as exc:
            log.error("Backend'den maç/oyuncu listesi alınamadı: %s", exc)
            stats.errors.append(f"backend listesi: {exc}")
            return stats

        log.info(
            "Backend'de %d maç, %d puuid'li oyuncu; %d ham maç dosyası taranacak%s",
            len(matches), len(players), len(files), " (DRY-RUN)" if dry_run else "",
        )

        for path in files:
            raw = _load_raw(path)
            if raw is None:
                continue
            stats.archives += 1
            source_game_id = str(raw.get("gameId") or path.stem)

            match = matches.get(source_game_id)
            if match is None:
                stats.unmatched_matches.append(source_game_id)
                log.warning(
                    "Maç backend'de bulunamadı, atlanıyor: %s "
                    "(ingest edilmemiş ya da liste limitinin dışında olabilir)",
                    source_game_id,
                )
                continue
            stats.matched += 1

            positions: dict[str, str] = {}
            for key, role in infer_positions(raw).items():
                if role is None:
                    stats.unresolved += 1
                    continue
                player_id = players.get(str(key))
                if player_id is None:
                    stats.unknown_players += 1
                    log.warning(
                        "Oyuncu eşleşmedi (maç %s): puuid=%s — backend'de puuid'li kaydı yok",
                        source_game_id, key,
                    )
                    continue
                if match["player_ids"] and player_id not in match["player_ids"]:
                    stats.unknown_players += 1
                    log.warning(
                        "Oyuncu %s bu maçın (%s) katılımcısı değil, atlanıyor",
                        player_id, source_game_id,
                    )
                    continue
                positions[str(player_id)] = role

            if not positions:
                log.warning("Gönderilecek rol yok: %s", source_game_id)
                continue

            if dry_run:
                log.info(
                    "[dry-run] PUT %s ← %s",
                    POSITIONS_PATH.format(match_id=match["id"]),
                    json.dumps(positions, ensure_ascii=False, sort_keys=True),
                )
                stats.updated += 1
                stats.positions_sent += len(positions)
                continue

            try:
                response = client.put(
                    POSITIONS_PATH.format(match_id=match["id"]),
                    json={"positions": positions},
                )
            except httpx.HTTPError as exc:
                stats.errors.append(f"{source_game_id}: {exc}")
                log.error("Rol güncellemesi gönderilemedi (%s): %s", source_game_id, exc)
                continue

            if 200 <= response.status_code < 300:
                stats.updated += 1
                stats.positions_sent += len(positions)
                log.info(
                    "Roller güncellendi: maç %s (id=%s), %d rol",
                    source_game_id, match["id"], len(positions),
                )
            else:
                stats.errors.append(
                    f"{source_game_id}: HTTP {response.status_code} {response.text[:300]}"
                )
                log.error(
                    "Backend rol güncellemesini reddetti (%s, HTTP %s): %s",
                    source_game_id, response.status_code, response.text[:300],
                )

    log.info(
        "backfill-positions bitti%s: %d ham maç, %d eşleşti, %d maç güncellendi, "
        "%d rol gönderildi, %d rol çözülemedi, %d maç backend'de yok, "
        "%d oyuncu eşleşmedi, %d hata",
        " (DRY-RUN — hiçbir şey gönderilmedi)" if dry_run else "",
        stats.archives, stats.matched, stats.updated, stats.positions_sent,
        stats.unresolved, len(stats.unmatched_matches), stats.unknown_players,
        len(stats.errors),
    )
    return stats
