"""Backend'e gönderim + outbox (at-least-once delivery) + heartbeat.

- Ağ hatası / 5xx / 429 → payload `outbox/`'a yazılır, her döngüde yeniden denenir.
- Diğer 4xx (401, 422) → yeniden denemek anlamsız; `outbox/rejected/`'a taşınır,
  insan müdahalesi gerekir (log'da detail gösterilir).
Idempotency backend'de `source_game_id` ile sağlandığından çift gönderim güvenlidir.

GÖREV 13:
- `send_or_outbox` gönderilen gövdeye üst seviye `client_id` ekler; outbox'a
  yazılan payload da kimlikli olur. `send`/`flush_outbox` gövdeye DOKUNMAZ, böylece
  GÖREV 13 öncesinden kalmış (alansız) outbox dosyaları olduğu gibi gider.
- `send_heartbeat` ayrı bir uçtur (`/api/v1/health/heartbeat`): HER hatayı yutar ve
  başarısızlıkta outbox'a YAZMAZ — outbox yalnız maç payload'ları içindir.
"""

from __future__ import annotations

import json
import logging
import re
from enum import Enum
from typing import Any

import httpx

from . import __version__
from .config import Config

log = logging.getLogger("collector.sender")

INGEST_PATH = "/api/v1/ingest/match"
HEARTBEAT_PATH = "/api/v1/health/heartbeat"


class SendOutcome(Enum):
    OK = "ok"
    REJECTED = "rejected"  # 4xx — tekrar denenmez
    RETRY = "retry"  # ağ hatası / 5xx / 429 — outbox'tan tekrar denenir


def _safe_filename(source_game_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", source_game_id) + ".json"


class Sender:
    def __init__(self, config: Config, transport: httpx.BaseTransport | None = None):
        self._config = config
        self._client = httpx.Client(
            base_url=config.backend_url,
            headers={"X-API-Key": config.api_key},
            timeout=15.0,
            transport=transport,
        )

    def send(self, payload: dict[str, Any]) -> SendOutcome:
        game_id = payload.get("source_game_id", "?")
        try:
            response = self._client.post(INGEST_PATH, json=payload)
        except httpx.HTTPError as exc:
            log.warning("Backend unreachable (%s): %s", game_id, exc)
            return SendOutcome.RETRY

        if 200 <= response.status_code < 300:
            duplicate = False
            try:
                duplicate = bool(response.json().get("duplicate"))
            except Exception:
                pass
            log.info("Sent: %s%s", game_id, " (duplicate)" if duplicate else "")
            return SendOutcome.OK

        if 400 <= response.status_code < 500 and response.status_code != 429:
            log.error(
                "Backend rejected (%s, HTTP %s): %s",
                game_id, response.status_code, response.text[:500],
            )
            return SendOutcome.REJECTED

        log.warning("Backend error (%s, HTTP %s), will retry from outbox", game_id, response.status_code)
        return SendOutcome.RETRY

    def with_client_id(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Gövdenin kimlikli bir KOPYASI (çağıranın dict'i değişmez).

        Kimlik boşsa alan hiç eklenmez — backend için opsiyonel bir alandır.
        """
        client_id = self._config.client_id
        if not client_id:
            return payload
        return {**payload, "client_id": client_id}

    def send_or_outbox(self, payload: dict[str, Any]) -> SendOutcome:
        payload = self.with_client_id(payload)
        outcome = self.send(payload)
        if outcome is SendOutcome.RETRY:
            self._write(self._config.outbox_dir, payload)
        elif outcome is SendOutcome.REJECTED:
            self._write(self._config.outbox_dir / "rejected", payload)
        return outcome

    def flush_outbox(self) -> None:
        """Outbox'taki her dosyayı dener: 2xx → sil, 4xx → rejected/'a taşı,
        backend hâlâ erişilemiyorsa kalanları sonraki tura bırak."""
        outbox = self._config.outbox_dir
        if not outbox.is_dir():
            return
        for path in sorted(outbox.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                log.error("Could not read outbox file, skipping: %s (%s)", path.name, exc)
                continue
            outcome = self.send(payload)
            if outcome is SendOutcome.OK:
                path.unlink(missing_ok=True)
            elif outcome is SendOutcome.REJECTED:
                rejected_dir = outbox / "rejected"
                rejected_dir.mkdir(parents=True, exist_ok=True)
                path.replace(rejected_dir / path.name)
            else:
                break  # backend erişilemez; kalan dosyaları şimdi denemenin anlamı yok

    # --- heartbeat (GÖREV 13, api_contract §6) ---

    def outbox_pending_count(self) -> int:
        """Bekleyen (henüz gönderilememiş) outbox dosyası sayısı.

        `rejected/` alt dizini sayılmaz: onlar tekrar denenmez, insan işidir.
        """
        try:
            return sum(1 for path in self._config.outbox_dir.glob("*.json") if path.is_file())
        except OSError as exc:
            log.debug("Could not count outbox files: %s", exc)
            return 0

    def send_heartbeat(self, reason: str = "") -> bool:
        """`POST /health/heartbeat`. HER hata yutulur — canlı modu/backfill'i asla durdurmaz.

        Başarısızlıkta outbox'a yazılmaz; bir sonraki heartbeat zaten güncel
        durumu taşır (last_seen sunucuda atanır, gecikmiş bir kopyanın değeri yok).
        """
        client_id = self._config.client_id
        if not client_id:
            log.debug("Heartbeat skipped: no client_id")
            return False
        try:
            body = {
                "client_id": client_id,
                "version": __version__,
                "outbox_pending": self.outbox_pending_count(),
            }
            response = self._client.post(HEARTBEAT_PATH, json=body)
            if 200 <= response.status_code < 300:
                log.debug("Heartbeat sent (%s): %s", reason or "-", body)
                return True
            log.warning(
                "Heartbeat rejected (%s, HTTP %s): %s",
                reason or "-", response.status_code, response.text[:200],
            )
        except Exception as exc:  # noqa: BLE001 — heartbeat asla akışı bozmaz
            log.warning("Heartbeat could not be sent (%s): %s", reason or "-", exc)
        return False

    def _write(self, directory, payload: dict[str, Any]) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / _safe_filename(str(payload.get("source_game_id", "unknown")))
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("Payload written to disk: %s", path)

    def close(self) -> None:
        self._client.close()
