"""Custom maçlarda rol (position) tahmini — kısıt çözümü, deterministik.

Neden gerekli: LCU custom maçlarda gerçek rol atamasını hiç vermez. Ham veride
`timeline.lane` alanı Riot'un TAHMİNİDİR ve custom'larda bozuktur (10 gerçek maçta
100 katılımcının 36'sı "JUNGLE" etiketli, oysa gerçek ormancı 20; "TOP" etiketi
yalnızca 7 kez geçiyor). Buna karşılık **Smite** (spellId 11) kusursuz sinyaldir:
10 maçta tam 20 taşıyıcı = takım başına tam 1 ormancı.

Bu yüzden tek bir alana güvenmek yerine takım başına (5 oyuncu) kısıt zinciri
koşulur; her adım TAM BİR aday bulursa atar, 0 veya 2+ aday varsa o rol `None`
kalır ve adaylar havuzda kalır. **Tahmin ZORLANMAZ**: kısmi sonuç geçerlidir,
eksik kalanı insan `PUT /matches/{id}/positions` ile düzeltir (api_contract §3).

Zincir (bkz. docs/ingest_contract.md "Rol tahmini (GÖREV 0)", zincir revizyonu
CHANGE_REQUESTS lcu-collector 2026-08-11):
1. JUNGLE  — Smite taşıyan
2. UTILITY — kalanlar içinde lane=BOTTOM ve role destek türevi
3. BOTTOM  — kalanlar içinde lane=BOTTOM ve role carry türevi; olmazsa tek kalan BOTTOM
4. MIDDLE  — kalanlar içinde lane=MIDDLE
5. TOP     — kalanlar içinde lane=TOP etiketli tam 1 kişi
6. Eleme   — atanmamış tam 1 kişi ve boş tam 1 rol kaldıysa eşle

Hem match-history (`participants[] + timeline`) hem EOG (`teams[].players[]`)
formatı desteklenir; EOG'de lane/role çoğu sürümde yoktur, o durumda yalnızca
Smite adımı çözülür ve gerisi `None` kalır — bu beklenen davranıştır.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

SMITE_SPELL_ID = 11

#: Zincirin çözüm sırası (rapor/test'ler bu sırayı kullanır)
ROLE_CHAIN = ("JUNGLE", "UTILITY", "BOTTOM", "MIDDLE", "TOP")

_SPELL_KEYS = ("spell1Id", "spell2Id", "summoner1Id", "summoner2Id")
_LANE_ALIASES = {"MID": "MIDDLE", "BOT": "BOTTOM"}
_SUPPORT_ROLES = {"SUPPORT", "DUO_SUPPORT"}
_CARRY_ROLES = {"CARRY", "DUO_CARRY"}


@dataclass(frozen=True)
class ParticipantView:
    """Rol tahmini için gereken asgari görünüm (formattan bağımsız)."""

    key: Any  # puuid varsa puuid, yoksa participantId/index
    team: int
    has_smite: bool
    lane: Optional[str] = None
    role: Optional[str] = None


def _normalized(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    upper = value.strip().upper()
    if not upper or upper == "NONE":
        return None
    return _LANE_ALIASES.get(upper, upper)


def _has_smite(raw: dict[str, Any]) -> bool:
    for key in _SPELL_KEYS:
        value = raw.get(key)
        if value is None:
            continue
        try:
            if int(value) == SMITE_SPELL_ID:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _lane_role(raw: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    timeline = raw.get("timeline")
    if isinstance(timeline, dict):
        lane, role = timeline.get("lane"), timeline.get("role")
    else:
        lane, role = raw.get("lane"), raw.get("role")
    return _normalized(lane), _normalized(role)


def views_from_match_history(raw: dict[str, Any]) -> list[ParticipantView]:
    """`/lol-match-history/v1/games/{id}` kaydından görünümler.

    puuid `participantIdentities` altında durur; yoksa participantId anahtar olur.
    """
    identities: dict[int, dict[str, Any]] = {}
    for identity in raw.get("participantIdentities") or []:
        try:
            identities[int(identity.get("participantId", -1))] = identity.get("player") or {}
        except (TypeError, ValueError):
            continue

    views: list[ParticipantView] = []
    for index, p in enumerate(raw.get("participants") or []):
        try:
            participant_id = int(p.get("participantId", index))
        except (TypeError, ValueError):
            participant_id = index
        player = identities.get(participant_id, {})
        lane, role = _lane_role(p)
        try:
            team = int(p.get("teamId"))
        except (TypeError, ValueError):
            continue  # takımı bilinmeyen katılımcı zincire alınamaz
        views.append(
            ParticipantView(
                key=player.get("puuid") or p.get("puuid") or participant_id,
                team=team,
                has_smite=_has_smite(p),
                lane=lane,
                role=role,
            )
        )
    return views


def views_from_eog(raw: dict[str, Any]) -> list[ParticipantView]:
    """`/lol-end-of-game/v1/eog-stats-block` bloğundan görünümler.

    EOG'de lane/role alanı çoğu sürümde yoktur → yalnızca Smite adımı çözülür.
    """
    views: list[ParticipantView] = []
    index = 0
    for team in raw.get("teams") or []:
        for player in team.get("players") or []:
            lane, role = _lane_role(player)
            try:
                team_id = int(player.get("teamId") or team.get("teamId"))
            except (TypeError, ValueError):
                index += 1
                continue
            views.append(
                ParticipantView(
                    key=player.get("puuid") or index,
                    team=team_id,
                    has_smite=_has_smite(player),
                    lane=lane,
                    role=role,
                )
            )
            index += 1
    return views


def views_from_raw(raw: dict[str, Any]) -> list[ParticipantView]:
    """Format tespiti: match-history mi EOG mi olduğunu şekilden anlar."""
    if raw.get("participants"):
        return views_from_match_history(raw)
    return views_from_eog(raw)


def infer_team_positions(views: list[ParticipantView]) -> dict[Any, Optional[str]]:
    """Tek bir takımın kısıt zincirini koşar → {key: rol veya None}."""
    remaining: dict[Any, ParticipantView] = {v.key: v for v in views}
    result: dict[Any, Optional[str]] = {v.key: None for v in views}

    def assign(role: str, candidates: list[Any]) -> None:
        """Yalnızca TEK aday varsa atar; 0 veya 2+ ise rol boş kalır ve adaylar
        havuzda durur (sonraki adımlar onları hâlâ değerlendirebilir)."""
        if len(candidates) == 1:
            key = candidates[0]
            result[key] = role
            remaining.pop(key, None)

    # 1) JUNGLE: Smite kusursuz sinyal
    assign("JUNGLE", [k for k, v in remaining.items() if v.has_smite])

    # 2) UTILITY: bot lane + destek rolü
    assign(
        "UTILITY",
        [k for k, v in remaining.items() if v.lane == "BOTTOM" and v.role in _SUPPORT_ROLES],
    )

    # 3) BOTTOM: bot lane + carry rolü; carry etiketi yoksa tek kalan BOTTOM'a düş
    carries = [k for k, v in remaining.items() if v.lane == "BOTTOM" and v.role in _CARRY_ROLES]
    if len(carries) != 1:
        carries = [k for k, v in remaining.items() if v.lane == "BOTTOM"]
    assign("BOTTOM", carries)

    # 4) MIDDLE
    assign("MIDDLE", [k for k, v in remaining.items() if v.lane == "MIDDLE"])

    # 5) TOP: kalanlar içinde TOP etiketli tam 1 kişi
    assign("TOP", [k for k, v in remaining.items() if v.lane == "TOP"])

    # 6) Eleme: geriye tam 1 kişi ve tam 1 boş rol kaldıysa eşleşme zorunludur.
    #    (Boş rol her zaman TOP olmak zorunda değil: önceki adımlardan biri
    #    belirsiz kalmışsa geriye kalan rol ör. UTILITY de olabilir.)
    unassigned_roles = [r for r in ROLE_CHAIN if r not in set(result.values())]
    if len(remaining) == 1 and len(unassigned_roles) == 1:
        assign(unassigned_roles[0], list(remaining))

    return result


def infer_positions(raw: dict[str, Any]) -> dict[Any, Optional[str]]:
    """Ham maçtaki tüm katılımcılar için {key: rol veya None}.

    `key` = puuid (varsa), yoksa participantId/index. Zincir takım başına koşar.
    """
    views = views_from_raw(raw)
    teams: dict[int, list[ParticipantView]] = {}
    for view in views:
        teams.setdefault(view.team, []).append(view)

    result: dict[Any, Optional[str]] = {}
    for team_views in teams.values():
        result.update(infer_team_positions(team_views))
    return result


def position_for(
    inferred: dict[Any, Optional[str]], puuid: Optional[str], fallback_key: Any
) -> Optional[str]:
    """Normalizer'ın kullandığı arama: önce puuid, yoksa index/participantId."""
    if puuid is not None and puuid in inferred:
        return inferred[puuid]
    return inferred.get(fallback_key)
