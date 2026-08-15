"""Canlı mod: gameflow polling → EndOfGame yakalanınca maçı işle.

- Aynı maç için tek tetik: faz kenarı (EndOfGame'e GEÇİŞ) + gameId dedupe
  (bellek + raw_archive dosya varlığı, restart'a dayanıklı).
- Canlı modda roster filtresi YOK; yalnızca custom olmayan ve Sihirdar Vadisi
  dışında oynanan (custom ARAM/URF vb.) maçlar atlanır.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from .archive import archive_path, archive_raw
from .config import Config
from .lcu import LcuClient
from .normalizer import (
    NormalizeError,
    champion_map_from_summary,
    is_custom,
    is_summoners_rift,
    normalize_eog,
    normalize_match_history_game,
)
from .sender import Sender

log = logging.getLogger("collector.live")

END_OF_GAME = "EndOfGame"
_MAX_CONSECUTIVE_FAILURES = 10


class LcuConnectionLost(Exception):
    """LCU art arda çok kez yanıt vermedi — client kapanmış olabilir, yeniden bağlan."""


class LiveRunner:
    def __init__(
        self,
        config: Config,
        lcu: LcuClient,
        sender: Sender,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        should_stop: Optional[Callable[[], bool]] = None,
        on_match: Optional[Callable[[str], None]] = None,
    ):
        self._config = config
        self._lcu = lcu
        self._sender = sender
        self._sleep = sleep
        self._now = now
        # GÖREV 16: arayüzün "Durdur" düğmesi için işbirlikçi kesme + son maç bildirimi.
        # CLI bunları vermez; verilmediğinde davranış birebir eskisi gibidir.
        self._should_stop = should_stop or (lambda: False)
        self._on_match = on_match
        self._processed: set[str] = set()
        self._champion_map: Optional[dict[int, str]] = None
        self._last_heartbeat: Optional[datetime] = None

    # --- yardımcılar ---

    def _maybe_heartbeat(self) -> None:
        """Canlı modda periyodik heartbeat (GÖREV 13, api_contract §6).

        Sayaç `poll_forever` başlangıcında kurulur: bağlantı anındaki heartbeat'i
        CLI atar, ilk periyodik atış ondan `HEARTBEAT_MINUTES` dakika sonradır.
        Gönderim başarısız olsa da sayaç ilerler — hata canlı döngüyü yavaşlatmaz.
        """
        minutes = self._config.heartbeat_minutes
        if minutes <= 0:
            return
        now = self._now()
        if self._last_heartbeat is not None and now - self._last_heartbeat < timedelta(minutes=minutes):
            return
        self._last_heartbeat = now
        self._sender.send_heartbeat("live")

    def _already_processed(self, game_id: str) -> bool:
        return game_id in self._processed or archive_path(self._config, game_id).is_file()

    def _get_champion_map(self) -> Optional[dict[int, str]]:
        if self._champion_map is None:
            try:
                self._champion_map = champion_map_from_summary(self._lcu.get_champion_summary())
            except Exception as exc:
                log.warning("Could not fetch champion list (champion may be sent as null): %s", exc)
                self._champion_map = {}
        return self._champion_map or None

    def _fetch_eog_with_retry(self, tries: int = 5, delay: float = 2.0) -> dict[str, Any]:
        """EOG bloğu faz geçişinden hemen sonra boş dönebilir; birkaç kez dene."""
        for attempt in range(tries):
            try:
                eog = self._lcu.get_eog_stats_block()
            except Exception as exc:
                log.debug("EOG request failed (attempt %d): %s", attempt + 1, exc)
                eog = {}
            if eog.get("gameId"):
                return eog
            self._sleep(delay)
        return {}

    def _process(self, game_id: str, raw: dict[str, Any], payload_dict: dict[str, Any] | None) -> None:
        archive_raw(self._config, game_id, raw)
        self._processed.add(game_id)
        if payload_dict is not None:
            self._sender.send_or_outbox(payload_dict)
            self._notify_match(game_id)

    def _notify_match(self, game_id: str) -> None:
        """Arayüzün durum bandı için: son işlenen maç. Geri çağrı hatası yutulur."""
        if self._on_match is None:
            return
        try:
            self._on_match(game_id)
        except Exception:  # noqa: BLE001 — arayüz hatası toplamayı ASLA durdurmaz
            log.debug("on_match callback failed (ignored)", exc_info=True)

    # --- ana akış ---

    def on_end_of_game(self) -> bool:
        """EndOfGame fazına geçişte bir kez çağrılır. Maç gönderildiyse True."""
        eog = self._fetch_eog_with_retry()

        if eog.get("gameId"):
            game_id = str(eog["gameId"])
            if self._already_processed(game_id):
                log.info("Match already processed, skipping: %s", game_id)
                return False
            if not is_custom(eog):
                log.info("Not a custom game, skipping: %s (gameType=%s, queueId=%s)",
                         game_id, eog.get("gameType"), eog.get("queueId"))
                self._process(game_id, eog, None)
                return False
            if not is_summoners_rift(eog):
                log.info("Not a Summoner's Rift game, skipping: %s (gameMode=%s, mapId=%s)",
                         game_id, eog.get("gameMode"), eog.get("mapId"))
                self._process(game_id, eog, None)
                return False
            try:
                payload = normalize_eog(eog, self._now(), self._get_champion_map())
            except NormalizeError as exc:
                log.error("Could not normalize: %s", exc)
                self._process(game_id, eog, None)
                return False
            self._process(game_id, eog, payload.model_dump())
            return True

        # Fallback: EOG bloğu gelmedi → gameflow session'dan gameId, match history'den detay
        log.warning("Could not fetch EOG block, trying match history fallback")
        try:
            session = self._lcu.get_gameflow_session()
            game_id_raw = (session.get("gameData") or {}).get("gameId")
        except Exception as exc:
            log.error("Could not fetch gameflow session: %s", exc)
            return False
        if not game_id_raw:
            log.error("No gameId found for fallback, match missed (can be recovered with backfill)")
            return False

        game_id = str(game_id_raw)
        if self._already_processed(game_id):
            return False
        try:
            game = self._lcu.get_game(game_id_raw)
        except Exception as exc:
            log.error("Could not fetch match history detail (%s): %s", game_id, exc)
            return False
        if not is_custom(game):
            log.info("Not a custom game (fallback), skipping: %s", game_id)
            self._process(game_id, game, None)
            return False
        if not is_summoners_rift(game):
            log.info("Not a Summoner's Rift game (fallback), skipping: %s (gameMode=%s, mapId=%s)",
                     game_id, game.get("gameMode"), game.get("mapId"))
            self._process(game_id, game, None)
            return False
        try:
            payload = normalize_match_history_game(game, self._get_champion_map())
        except NormalizeError as exc:
            log.error("Could not normalize (fallback): %s", exc)
            self._process(game_id, game, None)
            return False
        self._process(game_id, game, payload.model_dump())
        return True

    def poll_forever(self) -> None:
        """Ana döngü. LCU art arda yanıt vermezse LcuConnectionLost fırlatır.

        `should_stop` verilmişse döngü her turun başında sorar ve istendiğinde
        istisnasız döner (arayüzün "Durdur" düğmesi).
        """
        self._sender.flush_outbox()
        previous_phase: Optional[str] = None
        failures = 0
        self._last_heartbeat = self._now()
        while True:
            if self._should_stop():
                log.info("Live loop stop requested.")
                return
            try:
                phase = self._lcu.get_gameflow_phase()
                failures = 0
            except Exception as exc:
                failures += 1
                log.debug("Could not fetch gameflow phase (%d/%d): %s",
                          failures, _MAX_CONSECUTIVE_FAILURES, exc)
                if failures >= _MAX_CONSECUTIVE_FAILURES:
                    raise LcuConnectionLost() from exc
                self._sleep(self._config.poll_interval_s)
                continue

            if phase == END_OF_GAME and previous_phase != END_OF_GAME:
                try:
                    self.on_end_of_game()
                except Exception:
                    log.exception("Unexpected error while handling EndOfGame")
            previous_phase = phase

            self._sender.flush_outbox()
            self._maybe_heartbeat()
            self._sleep(self._config.poll_interval_s)
