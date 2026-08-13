from datetime import datetime, timezone

import pytest

from collector.normalizer import (
    NormalizeError,
    champion_map_from_summary,
    game_creation_datetime,
    is_custom,
    mh_identity_pairs,
    mh_is_remake,
    normalize_eog,
    normalize_match_history_game,
    normalize_position,
)

CAPTURED_AT = datetime(2026, 8, 11, 20, 41, 3, tzinfo=timezone.utc)


class TestNormalizeEog:
    def test_contract_shape(self, eog_custom):
        payload = normalize_eog(eog_custom, CAPTURED_AT)
        assert payload.source == "lcu_eog"
        assert payload.source_game_id == "6874231955"
        assert payload.played_at == "2026-08-11T20:41:03Z"
        assert payload.duration_s == 1874
        assert payload.winner_team == 100
        assert len(payload.participants) == 10
        assert sum(1 for p in payload.participants if p.team == 100) == 5
        assert sum(1 for p in payload.participants if p.team == 200) == 5

    def test_stats_mapping_legacy_upper_keys(self, eog_custom):
        payload = normalize_eog(eog_custom, CAPTURED_AT)
        teoman = next(p for p in payload.participants if p.riot_id == "Teoman#TR1")
        assert teoman.puuid == "puuid-t1"
        assert teoman.champion == "Ahri"
        assert teoman.stats.kills == 7
        assert teoman.stats.deaths == 2
        assert teoman.stats.assists == 9
        assert teoman.stats.gold == 13250
        assert teoman.stats.cs == 201  # 180 lane + 21 neutral
        assert teoman.stats.damage_to_champs == 24810
        assert teoman.stats.vision_score == 21

    def test_stats_mapping_camelcase_keys(self, eog_custom):
        for team in eog_custom["teams"]:
            for player in team["players"]:
                old = player["stats"]
                player["stats"] = {
                    "kills": old["CHAMPIONS_KILLED"],
                    "deaths": old["NUM_DEATHS"],
                    "assists": old["ASSISTS"],
                    "goldEarned": old["GOLD_EARNED"],
                    "totalMinionsKilled": old["MINIONS_KILLED"],
                    "neutralMinionsKilled": old["NEUTRAL_MINIONS_KILLED"],
                    "totalDamageDealtToChampions": old["TOTAL_DAMAGE_DEALT_TO_CHAMPIONS"],
                    "visionScore": old["VISION_SCORE"],
                }
        payload = normalize_eog(eog_custom, CAPTURED_AT)
        teoman = next(p for p in payload.participants if p.riot_id == "Teoman#TR1")
        assert teoman.stats.kills == 7
        assert teoman.stats.cs == 201

    def test_missing_stats_are_null(self, eog_custom):
        eog_custom["teams"][0]["players"][0]["stats"] = {}
        payload = normalize_eog(eog_custom, CAPTURED_AT)
        p = next(p for p in payload.participants if p.puuid == "puuid-t1")
        assert p.stats.kills is None
        assert p.stats.cs is None

    def test_position_none_when_unreliable(self, eog_custom):
        payload = normalize_eog(eog_custom, CAPTURED_AT)
        assert all(p.position is None for p in payload.participants)

    def test_played_at_falls_back_to_captured_at(self, eog_custom):
        """Sentetik blokta `endOfGameTimestamp` yok → yakalama anı kullanılır.
        (Eski LCU sürümleri bu alanı vermeyebilir; fallback korunmalı.)"""
        assert "endOfGameTimestamp" not in eog_custom
        assert normalize_eog(eog_custom, CAPTURED_AT).played_at == "2026-08-11T20:41:03Z"

    def test_end_of_game_timestamp_wins_over_captured_at(self, eog_custom):
        """Alan varsa maçın gerçek bitiş anı kazanır — geç işlemede (retry/outbox)
        played_at kaymaz."""
        eog_custom["endOfGameTimestamp"] = 1786484600652  # 2026-08-11T21:43:20.652Z
        late = datetime(2026, 8, 12, 9, 0, 0, tzinfo=timezone.utc)
        assert normalize_eog(eog_custom, late).played_at == "2026-08-11T21:43:20Z"

    @pytest.mark.parametrize("bad", ["bozuk", None, ""])
    def test_broken_end_of_game_timestamp_falls_back(self, eog_custom, bad):
        eog_custom["endOfGameTimestamp"] = bad
        assert normalize_eog(eog_custom, CAPTURED_AT).played_at == "2026-08-11T20:41:03Z"

    def test_explicit_selected_position_wins_over_inference(self, eog_custom):
        """Gerçek EOG şemasındaki gibi açık alan doldurulursa tahmin ezilir."""
        roles = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]
        for team in eog_custom["teams"]:
            for role, player in zip(roles, team["players"]):
                player["selectedPosition"] = role
        payload = normalize_eog(eog_custom, CAPTURED_AT)
        assert [p.position for p in payload.participants] == roles * 2

    def test_duration_ms_heuristic(self, eog_custom):
        eog_custom["gameLength"] = 1_874_000  # ms dönen patch'ler
        payload = normalize_eog(eog_custom, CAPTURED_AT)
        assert payload.duration_s == 1874

    def test_missing_puuid_raises(self, eog_custom):
        del eog_custom["teams"][0]["players"][0]["puuid"]
        with pytest.raises(NormalizeError, match="puuid"):
            normalize_eog(eog_custom, CAPTURED_AT)

    def test_missing_game_id_raises(self, eog_custom):
        del eog_custom["gameId"]
        with pytest.raises(NormalizeError, match="gameId"):
            normalize_eog(eog_custom, CAPTURED_AT)

    def test_nine_players_rejected(self, eog_custom):
        eog_custom["teams"][1]["players"].pop()
        with pytest.raises(Exception, match="10"):
            normalize_eog(eog_custom, CAPTURED_AT)

    def test_unbalanced_teams_rejected(self, eog_custom):
        # 6'ya 4: team 200'den bir oyuncuyu team 100'e taşı
        player = eog_custom["teams"][1]["players"].pop()
        player["teamId"] = 100
        eog_custom["teams"][0]["players"].append(player)
        with pytest.raises(Exception, match="team=100"):
            normalize_eog(eog_custom, CAPTURED_AT)


class TestNormalizeMatchHistory:
    def test_contract_shape(self, mh_game_custom, champion_summary):
        cmap = champion_map_from_summary(champion_summary)
        payload = normalize_match_history_game(mh_game_custom, cmap)
        assert payload.source_game_id == "6874231001"
        assert payload.winner_team == 200
        assert payload.duration_s == 2011
        # played_at = gameCreationDate + duration
        assert payload.played_at == "2026-08-01T19:46:15Z"
        assert len(payload.participants) == 10
        assert sum(1 for p in payload.participants if p.team == 100) == 5

    def test_champion_resolved_from_map(self, mh_game_custom, champion_summary):
        cmap = champion_map_from_summary(champion_summary)
        payload = normalize_match_history_game(mh_game_custom, cmap)
        teoman = next(p for p in payload.participants if p.puuid == "puuid-t1")
        assert teoman.champion == "Ahri"
        assert teoman.riot_id == "Teoman#TR1"

    def test_champion_null_without_map(self, mh_game_custom):
        payload = normalize_match_history_game(mh_game_custom, None)
        assert all(p.champion is None for p in payload.participants)

    def test_stats_camelcase(self, mh_game_custom):
        payload = normalize_match_history_game(mh_game_custom)
        teoman = next(p for p in payload.participants if p.puuid == "puuid-t1")
        assert teoman.stats.kills == 7
        assert teoman.stats.gold == 13250
        assert teoman.stats.cs == 201
        assert teoman.stats.vision_score == 21

    def test_ambiguous_signals_stay_null(self, mh_game_custom):
        """Sentetik fixture'da lane/role hep NONE ve Smite yok → zincir hiçbir
        rolü çözemez; tahmin ZORLANMAZ, hepsi null kalır."""
        payload = normalize_match_history_game(mh_game_custom)
        assert all(p.position is None for p in payload.participants)

    def test_identity_pairs(self, mh_game_custom):
        pairs = mh_identity_pairs(mh_game_custom)
        assert len(pairs) == 10
        assert ("puuid-t1", "Teoman#TR1") in pairs


class TestPositionInferenceIntegration:
    """GÖREV 0: açık position alanı VARSA kazanır, yoksa kısıt-çözümlü tahmin
    payload'a yazılır. Her iki normalize yolu için de geçerlidir."""

    LANES = [
        ("JUNGLE", "NONE"), ("JUNGLE", "NONE"),  # 1: aslında TOP (Riot yanlış etiketi)
        ("MIDDLE", "SOLO"), ("BOTTOM", "CARRY"), ("BOTTOM", "SUPPORT"),
    ]

    def _label(self, mh_game_custom):
        """Her takımın 2. oyuncusuna Smite, kalanlara tipik Riot etiketleri ver."""
        for p in mh_game_custom["participants"]:
            index = (int(p["participantId"]) - 1) % 5
            lane, role = self.LANES[index]
            p["timeline"] = {"lane": lane, "role": role}
            p["spell1Id"] = 11 if index == 1 else 4
            p["spell2Id"] = 14
        return mh_game_custom

    def test_mh_inferred_positions_written_to_payload(self, mh_game_custom):
        payload = normalize_match_history_game(self._label(mh_game_custom))
        for team in (100, 200):
            roles = sorted(p.position for p in payload.participants if p.team == team)
            assert roles == ["BOTTOM", "JUNGLE", "MIDDLE", "TOP", "UTILITY"]

    def test_mh_explicit_position_overrides_inference(self, mh_game_custom):
        """Smite taşıyan oyuncuya açık 'MIDDLE' verilirse tahmin ezilir."""
        raw = self._label(mh_game_custom)
        smite_player = next(p for p in raw["participants"] if p["participantId"] == 2)
        smite_player["selectedPosition"] = "MID"  # alias da çözülmeli
        payload = normalize_match_history_game(raw)
        puuid = next(
            i["player"]["puuid"]
            for i in raw["participantIdentities"]
            if i["participantId"] == 2
        )
        assert next(p for p in payload.participants if p.puuid == puuid).position == "MIDDLE"

    def test_mh_invalid_explicit_position_falls_back_to_inference(self, mh_game_custom):
        raw = self._label(mh_game_custom)
        for p in raw["participants"]:
            p["selectedPosition"] = "NONE"  # geçersiz/boş → tahmine düşer
        payload = normalize_match_history_game(raw)
        assert all(p.position is not None for p in payload.participants)

    def test_eog_smite_resolves_jungle_others_null(self, eog_custom):
        """Gerçek EOG bloğunda lane/role yoktur → yalnızca Smite adımı çözülür."""
        for team in eog_custom["teams"]:
            for index, player in enumerate(team["players"]):
                player["spell1Id"] = 11 if index == 1 else 4
                player["spell2Id"] = 14
        payload = normalize_eog(eog_custom, CAPTURED_AT)
        assert sum(1 for p in payload.participants if p.position == "JUNGLE") == 2
        assert sum(1 for p in payload.participants if p.position is None) == 8

    def test_eog_with_lane_hints_resolves_full_team(self, eog_custom):
        """LCU bir sürümde lane/role verirse (timeline bloğu) zincir tam çözer."""
        for team in eog_custom["teams"]:
            for index, player in enumerate(team["players"]):
                lane, role = TestPositionInferenceIntegration.LANES[index]
                player["timeline"] = {"lane": lane, "role": role}
                player["spell1Id"] = 11 if index == 1 else 4
        payload = normalize_eog(eog_custom, CAPTURED_AT)
        for team in (100, 200):
            roles = sorted(p.position for p in payload.participants if p.team == team)
            assert roles == ["BOTTOM", "JUNGLE", "MIDDLE", "TOP", "UTILITY"]

    def test_eog_explicit_position_overrides_inference(self, eog_custom):
        for team in eog_custom["teams"]:
            for index, player in enumerate(team["players"]):
                player["spell1Id"] = 11 if index == 1 else 4
            team["players"][1]["selectedPosition"] = "TOP"
        payload = normalize_eog(eog_custom, CAPTURED_AT)
        assert sum(1 for p in payload.participants if p.position == "TOP") == 2
        assert all(p.position != "JUNGLE" for p in payload.participants)


class TestDetectedTeamPositionTier:
    """Rol önceliğinin orta katmanı (2026-08-13, gameId 1734940206 vakası):
    açık seçim (boş olmayan) > `detectedTeamPosition` (boş olmayan) > zincir.
    Boş string hiçbir katmanda değer değildir."""

    ROLES = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]

    def test_eog_detected_wins_when_selected_is_empty_string(self, eog_custom):
        """Olayın birebir şekli: selectedPosition="" + detected dolu → tespit
        kazanır, 10/10 rol dolar."""
        for team in eog_custom["teams"]:
            for role, player in zip(self.ROLES, team["players"]):
                player["selectedPosition"] = ""
                player["detectedTeamPosition"] = role
        payload = normalize_eog(eog_custom, CAPTURED_AT)
        assert [p.position for p in payload.participants] == self.ROLES * 2

    def test_eog_explicit_beats_conflicting_detected(self, eog_custom):
        """1. katman > 2. katman: dolu selectedPosition, çelişen tespiti ezer."""
        for team in eog_custom["teams"]:
            for player in team["players"]:
                player["selectedPosition"] = "TOP"
                player["detectedTeamPosition"] = "MIDDLE"
        payload = normalize_eog(eog_custom, CAPTURED_AT)
        assert all(p.position == "TOP" for p in payload.participants)

    def test_eog_both_empty_falls_through_to_chain(self, eog_custom):
        """2. katman da boşsa 3. katman (zincir) aynen çalışır: EOG'de
        lane/role yok → yalnız Smite taşıyanlar JUNGLE olur."""
        for team in eog_custom["teams"]:
            for index, player in enumerate(team["players"]):
                player["selectedPosition"] = ""
                player["detectedTeamPosition"] = ""
                player["spell1Id"] = 11 if index == 1 else 4
                player["spell2Id"] = 14
        payload = normalize_eog(eog_custom, CAPTURED_AT)
        assert sum(1 for p in payload.participants if p.position == "JUNGLE") == 2
        assert sum(1 for p in payload.participants if p.position is None) == 8

    @pytest.mark.parametrize("garbage", ["NONE", "", "MID", "FILL", 5])
    def test_eog_garbage_detected_falls_through_to_chain(self, eog_custom, garbage):
        """Tanınmayan tespit değeri olduğu gibi YAYILMAZ (alias çözümü de
        yapılmaz — "MID" bile geçersizdir): zincire düşülür."""
        for team in eog_custom["teams"]:
            for index, player in enumerate(team["players"]):
                player["selectedPosition"] = ""
                player["detectedTeamPosition"] = garbage
                player["spell1Id"] = 11 if index == 1 else 4
                player["spell2Id"] = 14
        payload = normalize_eog(eog_custom, CAPTURED_AT)
        assert sum(1 for p in payload.participants if p.position == "JUNGLE") == 2
        assert sum(1 for p in payload.participants if p.position is None) == 8

    def test_eog_missing_detected_field_behaves_like_before(self, eog_custom):
        """Alanın hiç olmaması (eski patch şekli) boş olmasıyla aynıdır: sentetik
        fixture'da açık alan NONE ve tespit alanı yok → tüm roller null kalır."""
        assert all(
            "detectedTeamPosition" not in p
            for t in eog_custom["teams"] for p in t["players"]
        )
        payload = normalize_eog(eog_custom, CAPTURED_AT)
        assert all(p.position is None for p in payload.participants)

    def test_mh_detected_wins_when_no_explicit_field(self, mh_game_custom):
        """Orta katman match-history formatında da geçerlidir (alan bir gün
        orada da görünürse aynı öncelik uygulanır)."""
        for p in mh_game_custom["participants"]:
            index = (int(p["participantId"]) - 1) % 5
            p["detectedTeamPosition"] = self.ROLES[index]
        payload = normalize_match_history_game(mh_game_custom)
        for team in (100, 200):
            roles = sorted(p.position for p in payload.participants if p.team == team)
            assert roles == sorted(self.ROLES)


class TestMhIsRemake:
    def test_no_winner_short_game_is_remake(self, mh_game_custom):
        mh_game_custom["gameDuration"] = 185
        for team in mh_game_custom["teams"]:
            team["win"] = "Fail"
        assert mh_is_remake(mh_game_custom) is True

    def test_no_winner_long_game_is_not_remake(self, mh_game_custom):
        for team in mh_game_custom["teams"]:
            team["win"] = "Fail"  # gameDuration 2011 kalır
        assert mh_is_remake(mh_game_custom) is False
        with pytest.raises(NormalizeError, match="winning team"):
            normalize_match_history_game(mh_game_custom)

    def test_short_game_with_winner_is_not_remake(self, mh_game_custom):
        mh_game_custom["gameDuration"] = 185
        assert mh_is_remake(mh_game_custom) is False


class TestIsCustom:
    def test_custom_by_game_type(self, eog_custom):
        assert is_custom(eog_custom) is True

    def test_custom_by_queue_id_only(self):
        assert is_custom({"queueId": 0}) is True

    def test_ranked_not_custom(self):
        assert is_custom({"gameType": "MATCHED_GAME", "queueId": 420}) is False

    def test_unknown_fields_not_custom(self):
        assert is_custom({}) is False


class TestHelpers:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("MIDDLE", "MIDDLE"), ("mid", "MIDDLE"), ("BOT", "BOTTOM"),
            ("SUPPORT", "UTILITY"), ("UTILITY", "UTILITY"), ("TOP", "TOP"),
            ("NONE", None), ("", None), (None, None), ("FILL", None), (5, None),
        ],
    )
    def test_normalize_position(self, raw, expected):
        assert normalize_position(raw) == expected

    def test_game_creation_from_iso(self):
        dt = game_creation_datetime({"gameCreationDate": "2026-08-01T19:12:44.000Z"})
        assert dt == datetime(2026, 8, 1, 19, 12, 44, tzinfo=timezone.utc)

    def test_game_creation_from_epoch_ms(self):
        dt = game_creation_datetime({"gameCreation": 1754075564000})
        assert dt is not None and dt.tzinfo is not None

    def test_champion_map_skips_none_entry(self, champion_summary):
        cmap = champion_map_from_summary(champion_summary)
        assert -1 not in cmap
        assert cmap[103] == "Ahri"
        assert cmap[64] == "Lee Sin"
