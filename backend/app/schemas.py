"""Pydantic request/response modelleri (docs/api_contract.md + ingest_contract.md)."""
from __future__ import annotations

from typing import Any, Literal, Optional

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
    # GÖREV 14 (ingest_contract "items"): maç sonu envanteri, OPSİYONEL —
    # eski exe'ler alanı hiç göndermez (alan yok/None → NULL "bilinmiyor").
    # 0-7 eleman + int kuralının tanımı services/items.validate_items'tadır
    # (detail Türkçe ve tek-string olsun diye pydantic'e bırakılmaz).
    items: Optional[Any] = None


class IngestMatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: Literal["lcu_eog", "manual"]
    source_game_id: str = Field(min_length=1)
    played_at: str = Field(min_length=1)  # UTC ISO8601
    duration_s: Optional[int] = None
    winner_team: Literal[100, 200]
    participants: list[IngestParticipant]
    # GÖREV 13 (ingest_contract "client_id"): gönderen cihazın kimliği.
    # OPSİYONEL — eski exe'ler alanı hiç göndermez. Trim/uzunluk kuralı
    # services/health.normalize_optional_client_id'dedir.
    client_id: Optional[str] = None


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
    # api_contract §2 [REVİZE 2026-08-15]: seçim ölçütü galibiyet SAYISI;
    # `wins` bu yüzden yanıtta açıkça döner (winrate tek başına yetmez).
    champion: str
    matches: int
    wins: int
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


class TopItemOut(BaseModel):
    # api_contract §2 `top_items` (GÖREV 14): yalnız SAYIM taşınır — eşya adı /
    # ikonu / tags backend'de TUTULMAZ, "favori eşya" seçimi web UI'dadır.
    item_id: int
    matches: int


class PlayerStatsOut(BaseModel):
    # api_contract §2 "Oyuncu profili (GÖREV 1)". kda / favorite_* alanları
    # veri yoksa null; synergy uygun kimse yoksa [].
    player: StatsPlayerOut
    totals: StatsTotalsOut
    kda: Optional[StatsKdaOut]
    favorite_champion: Optional[FavoriteChampionOut]
    favorite_role: Optional[FavoriteRoleOut]
    synergy: list[SynergyOut]
    top_items: list[TopItemOut]


class RatingHistoryStatsOut(BaseModel):
    # api_contract §2 "Rating tarihçesi": k/d/a nullable; ÜÇÜ DE null ise
    # RatingHistoryPointOut.stats tamamen None olur.
    kills: Optional[int]
    deaths: Optional[int]
    assists: Optional[int]


class RatingHistoryPointOut(BaseModel):
    # score_after = o maç SONRASI efektif score (leaderboard `score` tanımı),
    # o ana kadarki kümülatif P_avg ile; 2 ondalığa yuvarlanmış.
    match_id: int
    played_at: str
    win: bool
    champion: Optional[str]
    position: Optional[Position]
    score_after: float
    stats: Optional[RatingHistoryStatsOut]


class RatingHistoryOut(BaseModel):
    # Tam tarihçe döner: zaman aralığı filtresi SUNUCUDA YOKTUR (api_contract §2).
    player_id: int
    engine_version: str
    points: list[RatingHistoryPointOut]


class BadgeOut(BaseModel):
    # api_contract §2 "Rozetler": yalnız `key` taşınır — rozet adı/açıklaması
    # backend'de TUTULMAZ, çeviri web UI i18n sözlüklerindedir.
    # last_match_id: rozeti son kazandıran maç (blok rozetinde bloğun son maçı,
    # eşik rozetinde eşiği tamamlayan maç).
    key: str
    count: int
    last_match_id: int


class PlayerBadgesOut(BaseModel):
    # Yalnız count > 0 rozetler, SABİT katalog sırasında; rozetsiz oyuncuda [].
    player_id: int
    badges: list[BadgeOut]


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


class ItemsUpdate(BaseModel):
    # api_contract §3 (GÖREV 14): anahtarlar bu maçın player_id'leri (JSON
    # nesne anahtarı olduğu için string), değerler 0-7 elemanlı int dizisi
    # (`[]` = "bilgi var, envanter boş"). Kısmi güncelleme serbest; mevcut
    # değerin ÜZERİNE yazar. Doğrulama router + services/items'tadır
    # (Türkçe detail üretebilmek için).
    items: dict[str, Any]


class ItemsUpdateResponse(BaseModel):
    # Rating'e etkisi YOK: replay alanı bilinçli olarak yoktur.
    updated: int


class RouletteAssignmentIn(BaseModel):
    # api_contract §4.5 (GÖREV 23): tip/enum kontrolü burada; sayısal/küme
    # kuralları (10 kayıt, 5/5 takım, rol/champion benzersizliği, item_ids
    # tam 2 farklı pozitif int) services/roulette.validate_assignments'tadır
    # (detail Türkçe ve tek-string olsun diye pydantic'e bırakılmaz).
    model_config = ConfigDict(extra="ignore")

    player_id: int
    team: Literal[100, 200]
    position: Position
    champion: str
    item_ids: Any = None


class RouletteCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    assignments: list[RouletteAssignmentIn]


class RouletteCreateResponse(BaseModel):
    session_id: int
    created_at: str


class RouletteAssignmentOut(BaseModel):
    # GET /roulette/current: POST gövdesindeki 10 kayıt aynen döner.
    player_id: int
    team: Literal[100, 200]
    position: Position
    champion: str
    item_ids: list[int]


class RouletteSessionOut(BaseModel):
    session_id: int
    created_at: str
    assignments: list[RouletteAssignmentOut]


class RouletteCurrentResponse(BaseModel):
    # Açık oturum yoksa {"session": null} (api_contract §4.5).
    session: Optional[RouletteSessionOut]


class RouletteUnlinkResponse(BaseModel):
    # api_contract §4.5: başarıda maç valid olur ve HER İKİ evren replay koşar.
    status: Literal["valid"]
    matches_replayed: int
    role_matches_replayed: int


class RouletteClearResponse(BaseModel):
    # api_contract §4.5 (Teoman, 2026-08-19): silinen (match_id IS NULL) oturum sayısı.
    deleted: int


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


class HeartbeatIn(BaseModel):
    # api_contract §6: client_id zorunlu (trim sonrası boş olamaz, ≤64) — bu
    # kontrol router'da yapılır ki detail Türkçe ve tek-string olsun.
    # version/outbox_pending opsiyonel/nullable.
    model_config = ConfigDict(extra="ignore")

    client_id: Optional[str] = None
    version: Optional[str] = None
    outbox_pending: Optional[int] = None


class HeartbeatResponse(BaseModel):
    ok: bool


class CollectorHealthOut(BaseModel):
    # api_contract §6. last_seen SUNUCUDA atanır (UTC Z). last_ingest_* o
    # cihazın `matches.client_id` izinden son maçı; iz yoksa null (void dahil).
    client_id: str
    last_seen: str
    version: Optional[str]
    outbox_pending: Optional[int]
    last_ingest_at: Optional[str]
    last_ingest_game_id: Optional[str]
