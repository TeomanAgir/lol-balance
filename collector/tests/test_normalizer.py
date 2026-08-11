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

    def test_timeline_lane_not_guessed(self, mh_game_custom):
        payload = normalize_match_history_game(mh_game_custom)
        assert all(p.position is None for p in payload.participants)

    def test_identity_pairs(self, mh_game_custom):
        pairs = mh_identity_pairs(mh_game_custom)
        assert len(pairs) == 10
        assert ("puuid-t1", "Teoman#TR1") in pairs


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
        with pytest.raises(NormalizeError, match="Kazanan"):
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
