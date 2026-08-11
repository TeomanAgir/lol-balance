"""Pydantic request/response modelleri (docs/api_contract.md + ingest_contract.md)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Position = Literal["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]


class ParticipantStats(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kills: Optional[int] = None
    deaths: Optional[int] = None
    assists: Optional[int] = None
    gold: Optional[int] = None
    cs: Optional[int] = None
    damage_to_champs: Optional[int] = None
    vision_score: Optional[int] = None


class IngestParticipant(BaseModel):
    model_config = ConfigDict(extra="ignore")

    puuid: Optional[str] = None
    player_id: Optional[int] = None
    riot_id: Optional[str] = None
    team: Literal[100, 200]
    position: Optional[Position] = None
    champion: Optional[str] = None
    stats: Optional[ParticipantStats] = None


class IngestMatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: Literal["lcu_eog", "manual"]
    source_game_id: str = Field(min_length=1)
    played_at: str = Field(min_length=1)  # UTC ISO8601
    duration_s: Optional[int] = None
    winner_team: Literal[100, 200]
    participants: list[IngestParticipant]


class IngestResponse(BaseModel):
    match_id: int
    duplicate: bool


class PlayerCreate(BaseModel):
    display_name: str = Field(min_length=1)
    riot_id: Optional[str] = None


class PlayerPatch(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1)


class RatingOut(BaseModel):
    mu: float
    sigma: float
    ordinal: float


class PlayerOut(BaseModel):
    id: int
    display_name: str
    riot_id: Optional[str]
    puuid: Optional[str]
    matches_played: int
    rating: RatingOut


class BalanceRequest(BaseModel):
    player_ids: list[int]
    top_n: int = 3


class BalanceSuggestionOut(BaseModel):
    team_100: list[int]
    team_200: list[int]
    p_win_team_100: float
    quality: float


class BalanceResponse(BaseModel):
    engine_version: str
    suggestions: list[BalanceSuggestionOut]


class ReplayResponse(BaseModel):
    matches_replayed: int
    engine_version: str
