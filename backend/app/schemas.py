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
    # mu/sigma/ordinal: W/L çekirdeğinin ham değerleri. perf_avg/score harman
    # engine alanlarıdır (api_contract §2): harman olmayan version'da
    # perf_avg=None, score=ordinal; alanlar her zaman mevcut.
    mu: float
    sigma: float
    ordinal: float
    perf_avg: Optional[float]
    score: float


class RoleRatingOut(BaseModel):
    # Rol evreni (api_contract §2): 5 rolün her biri HER ZAMAN döner.
    # Hiç oynanmamış rol: mu=25, sigma=25/3, perf_avg=1.0, score=0.0, matches=0.
    # Harman olmayan version'da perf_avg=None, score = mu - 3*sigma.
    mu: float
    sigma: float
    perf_avg: Optional[float]
    score: float
    matches: int


class PlayerOut(BaseModel):
    id: int
    display_name: str
    riot_id: Optional[str]
    puuid: Optional[str]
    matches_played: int
    rating: RatingOut
    role_ratings: dict[str, RoleRatingOut]


class StatsPlayerOut(BaseModel):
    id: int
    display_name: str
    riot_id: Optional[str]


class StatsTotalsOut(BaseModel):
    # api_contract §2: maçsız oyuncuda matches=0, wins=0, losses=0, winrate=None.
    matches: int
    wins: int
    losses: int
    winrate: Optional[float]


class StatsKdaOut(BaseModel):
    # Yalnız kills/deaths/assists üçü de dolu valid maçlardan; hiç yoksa
    # PlayerStatsOut.kda tamamen None olur.
    kills_avg: float
    deaths_avg: float
    assists_avg: float
    ratio: float


class FavoriteChampionOut(BaseModel):
    champion: str
    matches: int
    winrate: float


class FavoriteRoleOut(BaseModel):
    role: Position
    matches: int


class SynergyOut(BaseModel):
    # Aynı takımda ≥2 ortak valid maç; yalnız GÖSTERİM (rating'e girmez).
    player_id: int
    display_name: str
    matches_together: int
    wins_together: int
    winrate: float


class PlayerStatsOut(BaseModel):
    # api_contract §2 "Oyuncu profili (GÖREV 1)". kda / favorite_* alanları
    # veri yoksa null; synergy uygun kimse yoksa [].
    player: StatsPlayerOut
    totals: StatsTotalsOut
    kda: Optional[StatsKdaOut]
    favorite_champion: Optional[FavoriteChampionOut]
    favorite_role: Optional[FavoriteRoleOut]
    synergy: list[SynergyOut]


class HighlightsWindowOut(BaseModel):
    # api_contract §2 "Haftanın enleri": UTC ISO8601, `start < played_at <= end`.
    # fallback=True → pencere boştu, end en son valid maça çapalandı.
    start: str
    end: str
    fallback: bool


class HighlightPlayerOut(BaseModel):
    # best_player ve best_by_role kartları: GÜNCEL score + pencere maç sayısı.
    player_id: int
    display_name: str
    score: float
    matches_in_window: int


class HighlightRisingStarOut(BaseModel):
    # "Yıldız rukisi": pencere içi ordinal (mu−3σ) artışı; negatif olabilir.
    player_id: int
    display_name: str
    delta: float
    matches_in_window: int


class WeeklyHighlightsOut(BaseModel):
    # api_contract §2 "Haftanın enleri (GÖREV 2)". best_by_role 5 rolün
    # tamamını içerir; o rolde pencerede kimse oynamadıysa değeri null.
    window: HighlightsWindowOut
    best_player: Optional[HighlightPlayerOut]
    rising_star: Optional[HighlightRisingStarOut]
    best_by_role: dict[str, Optional[HighlightPlayerOut]]


class NemesisPlayerOut(BaseModel):
    # api_contract §2 "Nemesis": pair.players HER ZAMAN küçük player_id önce.
    player_id: int
    display_name: str
    wins: int


class NemesisPairOut(BaseModel):
    # Aday birim (çift, rol) üçlüsüdür: `encounters` yalnız BU roldeki
    # karşılaşmaları sayar. closeness = 1 - 2*|wins[0]/encounters - 0.5|.
    role: Position
    players: list[NemesisPlayerOut]
    encounters: int
    closeness: float


class NemesisOut(BaseModel):
    # active: maç önerisinin kullanacağı çift — weekly > all_time > null.
    all_time: Optional[NemesisPairOut]
    weekly: Optional[NemesisPairOut]
    active: Optional[Literal["weekly", "all_time"]]


class NemesisMatchOut(BaseModel):
    # POST /balance/nemesis yanıtındaki `nemesis` nesnesi; player_ids küçük
    # id önce (pair.players ile aynı sıra).
    source: Literal["weekly", "all_time"]
    role: Position
    player_ids: list[int]


class PositionsUpdate(BaseModel):
    # api_contract §3: anahtarlar bu maçın player_id'leri (JSON nesne anahtarı
    # olduğu için string), değerler rol adı veya null. Kısmi güncelleme serbest.
    # Anahtar/rol doğrulaması router'da yapılır (Türkçe detail üretebilmek için).
    positions: dict[str, Optional[str]]


class PositionsUpdateResponse(BaseModel):
    updated: int
    role_matches_replayed: int


class BalanceRequest(BaseModel):
    player_ids: list[int]
    top_n: int = 3


class TeamSlotOut(BaseModel):
    player_id: int
    position: Position


class BalanceSuggestionOut(BaseModel):
    # Dengeleme HER ZAMAN rol bazlıdır (api_contract §4): takımlar oyuncu id'si
    # değil, (player_id, position) çiftleri döner.
    team_100: list[TeamSlotOut]
    team_200: list[TeamSlotOut]
    p_win_team_100: float
    quality: float


class BalanceResponse(BaseModel):
    engine_version: str
    suggestions: list[BalanceSuggestionOut]


class NemesisBalanceResponse(BalanceResponse):
    # api_contract §4 "Nemesis maçı": /balance yanıtının aynısı + `nemesis`.
    nemesis: NemesisMatchOut


class ReplayResponse(BaseModel):
    matches_replayed: int
    role_matches_replayed: int
    engine_version: str
