"""Testler için LcuClient sahtesi — LCU bağımlılığı interface arkasında olduğundan
tüm akışlar client'sız test edilebilir."""

from __future__ import annotations

from typing import Any


class FakeLcu:
    def __init__(
        self,
        *,
        phases: list[str] | None = None,
        eog: dict[str, Any] | None = None,
        session: dict[str, Any] | None = None,
        summoner: dict[str, Any] | None = None,
        pages: list[list[dict[str, Any]]] | None = None,
        games: dict[Any, dict[str, Any]] | None = None,
        champions: list[dict[str, Any]] | None = None,
    ):
        self._phases = iter(phases or [])
        self._eog = eog if eog is not None else {}
        self._session = session or {}
        self._summoner = summoner or {}
        self._pages = pages or []
        self._games = games or {}
        self._champions = champions or []

    def get_gameflow_phase(self) -> str:
        try:
            return next(self._phases)
        except StopIteration:
            raise KeyboardInterrupt  # testte döngüden çıkış

    def get_gameflow_session(self) -> dict[str, Any]:
        return self._session

    def get_eog_stats_block(self) -> dict[str, Any]:
        return self._eog

    def get_current_summoner(self) -> dict[str, Any]:
        return self._summoner

    def get_match_list(self, puuid: str, beg_index: int, end_index: int) -> list[dict[str, Any]]:
        page = beg_index // max(end_index - beg_index, 1)
        return self._pages[page] if page < len(self._pages) else []

    def get_game(self, game_id) -> dict[str, Any]:
        return self._games[game_id]

    def get_champion_summary(self) -> list[dict[str, Any]]:
        return self._champions
