"""Ingest contract'ının (docs/ingest_contract.md) pydantic modelleri.

Bu modeller contract'ın collector tarafındaki garantisidir: 10 katılımcı,
5'e 5 takım dağılımı ve UTC ISO8601 zaman formatı burada doğrulanır.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import (
    BaseModel,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

VALID_POSITIONS = {"TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"}

#: Envanterde en fazla 7 eşya taşınır: 6 slot + trinket (ingest_contract "items").
MAX_ITEMS = 7


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
    #: Maç sonu envanteri (GÖREV 14). `None` = "bilgi yok" → alan gövdeye hiç
    #: konmaz; `[]` = "bilgi var, envanter boş".
    items: Optional[list[int]] = None

    @field_validator("position")
    @classmethod
    def _position_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_POSITIONS:
            raise ValueError(f"Invalid position: {v!r} (allowed: {sorted(VALID_POSITIONS)} or null)")
        return v

    @field_validator("items")
    @classmethod
    def _items_valid(cls, v: Optional[list[int]]) -> Optional[list[int]]:
        if v is None:
            return None
        if len(v) > MAX_ITEMS:
            raise ValueError(f"items can hold at most {MAX_ITEMS} entries, got {len(v)}")
        if any(item_id <= 0 for item_id in v):
            raise ValueError(f"items must contain positive item ids: {v}")
        return v

    @model_serializer(mode="wrap")
    def _omit_unknown_items(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """`items` bilinmiyorsa (None) alan gövdeye HİÇ konmaz — ingest_contract
        "items" maddesi: alanı göndermeyen eski exe'lerle aynı davranış, backend
        `NULL` saklar. Diğer nullable alanlar (position, stats...) eskisi gibi
        `null` olarak gider; davranış yalnız `items` için özeldir."""
        data = handler(self)
        if data.get("items") is None:
            data.pop("items", None)
        return data


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
