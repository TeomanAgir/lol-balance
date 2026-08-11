"""Kısıt-çözümlü rol tahmini (GÖREV 0) testleri.

Sentetik senaryolar zincirin her adımını ve "belirsizse null bırak" kuralını
sabitler; `TestRealArchive` ise 10 gerçek custom maça karşı koşar.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from collector.role_infer import (
    ParticipantView,
    infer_positions,
    infer_team_positions,
    views_from_eog,
    views_from_match_history,
)

RAW_ARCHIVE_DIR = Path(__file__).resolve().parent.parent / "raw_archive"


def view(key, *, smite=False, lane=None, role=None, team=100) -> ParticipantView:
    return ParticipantView(key=key, team=team, has_smite=smite, lane=lane, role=role)


def standard_team(team=100) -> list[ParticipantView]:
    """Riot etiketlerinin custom'da tipik geldiği hâl: TOP etiketi yok,
    ormancı 'JUNGLE' etiketli ama etiketi taşıyan tek kişi o değil."""
    return [
        view(1, lane="JUNGLE", role="NONE", team=team),  # gerçekte TOP (Riot yanlış etiketledi)
        view(2, smite=True, lane="JUNGLE", role="NONE", team=team),
        view(3, lane="MIDDLE", role="SOLO", team=team),
        view(4, lane="BOTTOM", role="CARRY", team=team),
        view(5, lane="BOTTOM", role="SUPPORT", team=team),
    ]


class TestChain:
    def test_standard_team_fully_resolved(self):
        result = infer_team_positions(standard_team())
        assert result == {1: "TOP", 2: "JUNGLE", 3: "MIDDLE", 4: "BOTTOM", 5: "UTILITY"}

    def test_smite_wins_over_riot_jungle_label(self):
        """Riot iki kişiyi JUNGLE etiketlemişse bile Smite belirleyicidir."""
        result = infer_team_positions(standard_team())
        assert result[2] == "JUNGLE"
        assert result[1] == "TOP"

    def test_two_smites_leaves_jungle_null(self):
        views = standard_team()
        views[0] = view(1, smite=True, lane="JUNGLE", role="NONE")
        result = infer_team_positions(views)
        assert "JUNGLE" not in result.values()
        # Smite'lı ikisi havuzda kalır: MIDDLE/BOTTOM/UTILITY yine çözülür,
        # geriye 2 kişi kaldığı için TOP elemesi yapılamaz → ikisi de null
        assert result[3] == "MIDDLE"
        assert result[4] == "BOTTOM"
        assert result[5] == "UTILITY"
        assert result[1] is None and result[2] is None

    def test_no_smite_leaves_jungle_null_but_others_resolve(self):
        views = standard_team()
        views[1] = view(2, lane="JUNGLE", role="NONE")
        result = infer_team_positions(views)
        assert "JUNGLE" not in result.values()
        assert result[3] == "MIDDLE" and result[4] == "BOTTOM" and result[5] == "UTILITY"
        assert result[1] is None and result[2] is None  # 2 kişi kaldı → TOP elemesi yok

    def test_no_bottom_labels_leaves_bot_roles_null(self):
        views = [
            view(1, lane="TOP", role="SOLO"),
            view(2, smite=True, lane="JUNGLE"),
            view(3, lane="MIDDLE", role="SOLO"),
            view(4, lane="NONE", role="NONE"),
            view(5, lane="NONE", role="NONE"),
        ]
        result = infer_team_positions(views)
        assert result[2] == "JUNGLE"
        assert result[3] == "MIDDLE"
        assert result[1] == "TOP"  # kalanlar içinde tek TOP etiketi
        assert "BOTTOM" not in result.values() and "UTILITY" not in result.values()
        # 2 kişi + 2 boş rol kaldı → eleme yapılamaz
        assert result[4] is None and result[5] is None

    def test_two_supports_leaves_utility_null_and_bottom_falls_back(self):
        """İki SUPPORT etiketi → UTILITY belirsiz; BOTTOM carry etiketiyle yine
        çözülür, geriye kalan iki destek adayı null kalır."""
        views = standard_team()
        views[0] = view(1, lane="BOTTOM", role="SUPPORT")
        result = infer_team_positions(views)
        assert "UTILITY" not in result.values()
        assert result[4] == "BOTTOM"
        assert result[2] == "JUNGLE" and result[3] == "MIDDLE"
        assert result[1] is None and result[5] is None

    def test_bottom_fallback_without_carry_label(self):
        """Bot lane'de CARRY etiketi yoksa (ör. role='SOLO') tek kalan BOTTOM
        etiketli oyuncu yine BOTTOM'a atanır. Burada UTILITY hiç çözülmez ama
        sonda tek kişi + tek boş rol kaldığı için ELEME onu UTILITY'ye eşler
        (eleme yalnızca TOP'a özgü değildir)."""
        views = [
            view(1, lane="TOP", role="SOLO"),
            view(2, smite=True, lane="JUNGLE"),
            view(3, lane="MIDDLE", role="SOLO"),
            view(4, lane="BOTTOM", role="SOLO"),
            view(5, lane="JUNGLE", role="NONE"),
        ]
        result = infer_team_positions(views)
        assert result == {1: "TOP", 2: "JUNGLE", 3: "MIDDLE", 4: "BOTTOM", 5: "UTILITY"}

    def test_top_label_step_resolves_top(self):
        """Kalanlar içinde tam 1 TOP etiketi varsa TOP atanır (adım 5)."""
        views = [
            view(1, lane="TOP", role="SOLO"),
            view(2, smite=True, lane="JUNGLE"),
            view(3, lane="MIDDLE", role="SOLO"),
            view(4, lane="BOTTOM", role="DUO_CARRY"),
            view(5, lane="BOTTOM", role="DUO_SUPPORT"),
        ]
        assert infer_team_positions(views)[1] == "TOP"

    def test_top_assigned_by_elimination_without_top_label(self):
        """TOP etiketi hiç yoksa bile son kalan tek kişi eleme ile TOP olur."""
        result = infer_team_positions(standard_team())  # 1 numara 'JUNGLE' etiketli
        assert result[1] == "TOP"

    def test_two_top_labels_skip_step_and_stay_null(self):
        """Kalanlar içinde 2 TOP etiketi → adım atlanır; ardından 2 kişi + 2 boş
        rol kaldığı için eleme de yapılamaz → ikisi de null (1734450310/200 vakası)."""
        views = [
            view(1, lane="TOP", role="DUO"),
            view(2, lane="TOP", role="DUO"),
            view(3, smite=True, lane="JUNGLE"),
            view(4, lane="BOTTOM", role="CARRY"),
            view(5, lane="BOTTOM", role="SUPPORT"),
        ]
        result = infer_team_positions(views)
        assert result[3] == "JUNGLE" and result[4] == "BOTTOM" and result[5] == "UTILITY"
        assert result[1] is None and result[2] is None
        assert "TOP" not in result.values() and "MIDDLE" not in result.values()

    def test_elimination_needs_exactly_one_person_and_one_role(self):
        """3 kişi + 3 boş rol kaldıysa hiçbir şey atanmaz."""
        views = [
            view(1, lane="NONE"), view(2, lane="NONE"), view(3, lane="NONE"),
            view(4, smite=True, lane="JUNGLE"),
            view(5, lane="BOTTOM", role="CARRY"),
        ]
        result = infer_team_positions(views)
        assert result[4] == "JUNGLE" and result[5] == "BOTTOM"
        assert result[1] is None and result[2] is None and result[3] is None

    def test_duo_role_variants_supported(self):
        views = standard_team()
        views[3] = view(4, lane="BOTTOM", role="DUO_CARRY")
        views[4] = view(5, lane="BOTTOM", role="DUO_SUPPORT")
        result = infer_team_positions(views)
        assert result[4] == "BOTTOM" and result[5] == "UTILITY"

    def test_lane_aliases_and_case(self):
        raw_team = [
            {"participantId": 1, "teamId": 100, "timeline": {"lane": "top", "role": "solo"}},
            {"participantId": 2, "teamId": 100, "spell1Id": 11, "spell2Id": 4},
            {"participantId": 3, "teamId": 100, "timeline": {"lane": "mid", "role": "SOLO"}},
            {"participantId": 4, "teamId": 100, "timeline": {"lane": "bot", "role": "carry"}},
            {"participantId": 5, "teamId": 100, "timeline": {"lane": "BOT", "role": "support"}},
        ]
        result = infer_positions({"participants": raw_team})
        assert result == {1: "TOP", 2: "JUNGLE", 3: "MIDDLE", 4: "BOTTOM", 5: "UTILITY"}

    def test_teams_are_solved_independently(self):
        """Zincir takım başına koşar: bir takımdaki belirsizlik diğerini bozmaz."""
        def raw_p(pid, team, *, smite=False, lane=None, role=None):
            entry = {"participantId": pid, "teamId": team,
                     "timeline": {"lane": lane or "NONE", "role": role or "NONE"}}
            if smite:
                entry["spell1Id"] = 11
            return entry

        raw = {"participants": [
            # takım 100: tam çözülür
            raw_p(1, 100, lane="JUNGLE"), raw_p(2, 100, smite=True, lane="JUNGLE"),
            raw_p(3, 100, lane="MIDDLE", role="SOLO"),
            raw_p(4, 100, lane="BOTTOM", role="CARRY"),
            raw_p(5, 100, lane="BOTTOM", role="SUPPORT"),
            # takım 200: iki Smite → JUNGLE belirsiz
            raw_p(6, 200, smite=True, lane="JUNGLE"), raw_p(7, 200, smite=True, lane="JUNGLE"),
            raw_p(8, 200, lane="MIDDLE", role="SOLO"),
            raw_p(9, 200, lane="BOTTOM", role="CARRY"),
            raw_p(10, 200, lane="BOTTOM", role="SUPPORT"),
        ]}
        result = infer_positions(raw)
        assert result[1] == "TOP" and result[2] == "JUNGLE"
        assert result[6] is None and result[7] is None
        assert result[8] == "MIDDLE" and result[9] == "BOTTOM" and result[10] == "UTILITY"


class TestViewExtraction:
    def test_match_history_uses_puuid_as_key(self):
        raw = {
            "participantIdentities": [
                {"participantId": 1, "player": {"puuid": "p-1"}},
                {"participantId": 2, "player": {"puuid": "p-2"}},
            ],
            "participants": [
                {"participantId": 1, "teamId": 100, "spell1Id": 11,
                 "timeline": {"lane": "JUNGLE", "role": "NONE"}},
                {"participantId": 2, "teamId": 100, "spell1Id": 4, "spell2Id": 7,
                 "timeline": {"lane": "BOTTOM", "role": "CARRY"}},
            ],
        }
        views = views_from_match_history(raw)
        assert [v.key for v in views] == ["p-1", "p-2"]
        assert views[0].has_smite is True and views[1].has_smite is False
        assert views[1].lane == "BOTTOM" and views[1].role == "CARRY"

    def test_match_history_falls_back_to_participant_id(self):
        raw = {"participants": [{"participantId": 3, "teamId": 200, "spell2Id": 11}]}
        views = views_from_match_history(raw)
        assert views[0].key == 3 and views[0].has_smite is True

    def test_eog_views_from_teams_block(self):
        raw = {
            "teams": [
                {
                    "teamId": 100,
                    "players": [
                        {"puuid": "e-1", "teamId": 100, "spell1Id": 11},
                        {"puuid": "e-2", "teamId": 100, "spell1Id": 4, "spell2Id": 14},
                    ],
                }
            ]
        }
        views = views_from_eog(raw)
        assert [v.key for v in views] == ["e-1", "e-2"]
        assert views[0].has_smite is True and views[1].has_smite is False
        assert views[0].lane is None  # EOG'de lane/role yok → yalnızca Smite çözer


def resolved_by_team(raw) -> dict[int, list]:
    """Ham maç → {teamId: [rol veya None, ...]} (5'erli)."""
    result = infer_positions(raw)
    identities = {
        int(i["participantId"]): (i.get("player") or {}).get("puuid")
        for i in raw["participantIdentities"]
    }
    by_team: dict[int, list] = {}
    for p in raw["participants"]:
        key = identities.get(int(p["participantId"])) or int(p["participantId"])
        by_team.setdefault(int(p["teamId"]), []).append(result[key])
    return by_team


@pytest.fixture(scope="module")
def archives():
    """10 gerçek custom maç (raw_archive/). CI'da arşiv olmayabilir → skip."""
    files = sorted(RAW_ARCHIVE_DIR.glob("*.json")) if RAW_ARCHIVE_DIR.is_dir() else []
    if not files:
        pytest.skip("collector/raw_archive/ boş — gerçek maç verisi yok")
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]


class TestRealArchive:
    def test_every_smite_carrier_is_jungle(self, archives):
        jungles = 0
        for raw in archives:
            result = infer_positions(raw)
            identities = {
                int(i["participantId"]): (i.get("player") or {}).get("puuid")
                for i in raw["participantIdentities"]
            }
            for p in raw["participants"]:
                key = identities.get(int(p["participantId"])) or int(p["participantId"])
                if 11 in (p.get("spell1Id"), p.get("spell2Id")):
                    assert result[key] == "JUNGLE", f"Smite taşıyan JUNGLE değil: {key}"
                else:
                    assert result[key] != "JUNGLE"
            jungles += sum(1 for v in result.values() if v == "JUNGLE")
        # 10 maç × 2 takım × 1 ormancı
        assert jungles == 20

    def test_no_duplicate_role_within_team(self, archives):
        for raw in archives:
            for team_id, roles in resolved_by_team(raw).items():
                assigned = [r for r in roles if r]
                assert len(assigned) == len(set(assigned)), f"{team_id} takımında rol tekrarı"

    def test_resolution_rate_is_documented(self, archives):
        """Belgelenen sonuç (2026-08-11, revize zincir, 10 gerçek maç):
        20 takımın 19'u 5/5, toplam 98/100 pozisyon çözülür.
        Tek istisna 1734450310 / 200: kalan iki oyuncunun İKİSİ de 'TOP/DUO'
        etiketli → ayırt edilemez, MIDDLE ve TOP null kalır (insan düzeltir).
        Bu bir ölçüm sabitidir: sayı DÜŞERSE tahmin zinciri bozulmuş demektir."""
        fully_resolved, total_teams, filled, unresolved = 0, 0, 0, []
        for raw in archives:
            for team_id, roles in resolved_by_team(raw).items():
                total_teams += 1
                assigned = [r for r in roles if r]
                filled += len(assigned)
                if len(assigned) == 5:
                    fully_resolved += 1
                else:
                    unresolved.append((raw.get("gameId"), team_id, sorted(assigned)))

        assert total_teams == 20
        assert fully_resolved == 19, f"çözünürlük değişti: {fully_resolved}/20 — {unresolved}"
        assert filled == 98, f"dolu pozisyon sayısı değişti: {filled}/100"
        assert [(g, t) for g, t, _ in unresolved] == [(1734450310, 200)]

    def test_only_ambiguous_team_is_the_double_top_duo_one(self, archives):
        """1734163932'nin iki takımı da (revize zincirden önce 3/5 kalıyordu)
        artık tam çözülür; 1734450310 / 200 hâlâ 3/5 — iki TOP/DUO ayırt edilemez."""
        by_game = {raw["gameId"]: resolved_by_team(raw) for raw in archives}

        for team_id in (100, 200):
            roles = sorted(r for r in by_game[1734163932][team_id] if r)
            assert roles == ["BOTTOM", "JUNGLE", "MIDDLE", "TOP", "UTILITY"]

        assert sorted(r for r in by_game[1734450310][100] if r) == [
            "BOTTOM", "JUNGLE", "MIDDLE", "TOP", "UTILITY"
        ]
        ambiguous = by_game[1734450310][200]
        assert sorted(r for r in ambiguous if r) == ["BOTTOM", "JUNGLE", "UTILITY"]
        assert sum(1 for r in ambiguous if r is None) == 2
