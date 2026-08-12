"""Ingest contract'ının (docs/ingest_contract.md) pydantic modelleri.

Bu modeller contract'ın collector tarafındaki garantisidir: 10 katılımcı,
5'e 5 takım dağılımı ve UTC ISO8601 zaman formatı burada doğrulanır.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

VALID_POSITIONS = {"TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"}


class Stats(BaseModel):
    kills: Optional[int] = None
    deaths: Optional[int] = None
    assists: Optional[int] = None
    gold: Optional[int] = None
    cs: Optional[int] = None
    damage_to_champs: Optional[int] = None
    vision_score: Optional[int] = None


class Participant(BaseModel):
    puuid: str = Field(min_length=1)
    riot_id: Optional[str] = None
    team: Literal[100, 200]
    position: Optional[str] = None
    champion: Optional[str] = None
    stats: Stats = Field(default_factory=Stats)

    @field_validator("position")
    @classmethod
    def _position_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_POSITIONS:
            raise ValueError(f"Invalid position: {v!r} (allowed: {sorted(VALID_POSITIONS)} or null)")
        return v


class MatchPayload(BaseModel):
    source: Literal["lcu_eog"] = "lcu_eog"
    source_game_id: str = Field(min_length=1)
    played_at: str
    duration_s: int = Field(ge=0)
    winner_team: Literal[100, 200]
    participants: list[Participant]

    @field_validator("played_at")
    @classmethod
    def _played_at_utc_iso(cls, v: str) -> str:
        if not v.endswith("Z"):
            raise ValueError("played_at must be UTC ISO8601 and end with 'Z'")
        datetime.fromisoformat(v.replace("Z", "+00:00"))  # parse edilemiyorsa ValueError
        return v

    @model_validator(mode="after")
    def _teams_balanced(self) -> "MatchPayload":
        if len(self.participants) != 10:
            raise ValueError(f"participants must have exactly 10 items, got {len(self.participants)}")
        team_100 = sum(1 for p in self.participants if p.team == 100)
        if team_100 != 5:
            raise ValueError(f"team=100 must be exactly 5, got {team_100} (team=200: {10 - team_100})")
        return self
