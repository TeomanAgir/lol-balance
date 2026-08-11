"""LCU API erişim katmanı.

Tüm LCU bağımlılığı `LcuClient` protokolünün arkasında; testler fixture tabanlı
sahte client kullanır, canlıda `HttpLcuClient` kullanılır.

Endpoint yolları patch'lerde değişebilir — canlı client'ta ilk iş doğrulamak
(bkz. README "Canlı doğrulama").
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from .lockfile import LockfileInfo

GAMEFLOW_PHASE = "/lol-gameflow/v1/gameflow-phase"
GAMEFLOW_SESSION = "/lol-gameflow/v1/session"
EOG_STATS_BLOCK = "/lol-end-of-game/v1/eog-stats-block"
CURRENT_SUMMONER = "/lol-summoner/v1/current-summoner"
MATCH_LIST = "/lol-match-history/v1/products/lol/{puuid}/matches"
MATCH_DETAIL = "/lol-match-history/v1/games/{game_id}"
CHAMPION_SUMMARY = "/lol-game-data/assets/v1/champion-summary.json"


class LcuClient(Protocol):
    def get_gameflow_phase(self) -> str: ...
    def get_gameflow_session(self) -> dict[str, Any]: ...
    def get_eog_stats_block(self) -> dict[str, Any]: ...
    def get_current_summoner(self) -> dict[str, Any]: ...
    def get_match_list(self, puuid: str, beg_index: int, end_index: int) -> list[dict[str, Any]]: ...
    def get_game(self, game_id: int | str) -> dict[str, Any]: ...
    def get_champion_summary(self) -> list[dict[str, Any]]: ...


class HttpLcuClient:
    """Gerçek LCU client'ı. Self-signed sertifika nedeniyle TLS doğrulaması kapalı;
    bağlantı yalnızca 127.0.0.1'e gittiği için kabul edilebilir."""

    def __init__(self, info: LockfileInfo, timeout: float = 10.0):
        self._client = httpx.Client(
            base_url=info.base_url,
            auth=("riot", info.password),
            verify=False,
            timeout=timeout,
        )

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self._client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    def get_gameflow_phase(self) -> str:
        # Endpoint çıplak JSON string döner, ör. "EndOfGame"
        return str(self._get_json(GAMEFLOW_PHASE))

    def get_gameflow_session(self) -> dict[str, Any]:
        return self._get_json(GAMEFLOW_SESSION)

    def get_eog_stats_block(self) -> dict[str, Any]:
        data = self._get_json(EOG_STATS_BLOCK)
        return data if isinstance(data, dict) else {}

    def get_current_summoner(self) -> dict[str, Any]:
        return self._get_json(CURRENT_SUMMONER)

    def get_match_list(self, puuid: str, beg_index: int, end_index: int) -> list[dict[str, Any]]:
        data = self._get_json(
            MATCH_LIST.format(puuid=puuid),
            params={"begIndex": beg_index, "endIndex": end_index},
        )
        # Patch'e göre {"games": {"games": [...]}} ya da doğrudan liste dönebilir
        games = data.get("games", data) if isinstance(data, dict) else data
        if isinstance(games, dict):
            games = games.get("games", [])
        return games or []

    def get_game(self, game_id: int | str) -> dict[str, Any]:
        return self._get_json(MATCH_DETAIL.format(game_id=game_id))

    def get_champion_summary(self) -> list[dict[str, Any]]:
        data = self._get_json(CHAMPION_SUMMARY)
        return data if isinstance(data, list) else []

    def close(self) -> None:
        self._client.close()
