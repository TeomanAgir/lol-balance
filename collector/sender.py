"""Backend'e gönderim + outbox (at-least-once delivery).

- Ağ hatası / 5xx / 429 → payload `outbox/`'a yazılır, her döngüde yeniden denenir.
- Diğer 4xx (401, 422) → yeniden denemek anlamsız; `outbox/rejected/`'a taşınır,
  insan müdahalesi gerekir (log'da detail gösterilir).
Idempotency backend'de `source_game_id` ile sağlandığından çift gönderim güvenlidir.
"""

from __future__ import annotations

import json
import logging
import re
from enum import Enum
from typing import Any

import httpx

from .config import Config

log = logging.getLogger("collector.sender")

INGEST_PATH = "/api/v1/ingest/match"


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
            log.warning("Backend erişilemedi (%s): %s", game_id, exc)
            return SendOutcome.RETRY

        if 200 <= response.status_code < 300:
            duplicate = False
            try:
                duplicate = bool(response.json().get("duplicate"))
            except Exception:
                pass
            log.info("Gönderildi: %s%s", game_id, " (duplicate)" if duplicate else "")
            return SendOutcome.OK

        if 400 <= response.status_code < 500 and response.status_code != 429:
            log.error(
                "Backend reddetti (%s, HTTP %s): %s",
                game_id, response.status_code, response.text[:500],
            )
            return SendOutcome.REJECTED

        log.warning("Backend hatası (%s, HTTP %s), outbox'tan denenecek", game_id, response.status_code)
        return SendOutcome.RETRY

    def send_or_outbox(self, payload: dict[str, Any]) -> SendOutcome:
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
                log.error("Outbox dosyası okunamadı, atlanıyor: %s (%s)", path.name, exc)
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

    def _write(self, directory, payload: dict[str, Any]) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / _safe_filename(str(payload.get("source_game_id", "unknown")))
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("Payload diske yazıldı: %s", path)

    def close(self) -> None:
        self._client.close()
