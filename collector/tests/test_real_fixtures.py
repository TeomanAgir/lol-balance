"""Gerçek LCU client'ından alınmış fixture'lara karşı regresyon testleri.

Sentetik fixture'lar (`mh_game_custom.json` vb.) yapıyı belgeler; buradaki
`*_real.json` fixture'ları gerçek şemayı belgeler:

- `mh_game_custom_real.json`: 10 kişilik gerçek custom maç (gameId 1734450310).
  Statlar camelCase, açık position alanı yok, puuid'ler participantIdentities'te.
- `mh_list_page_real.json`: gerçek match-history liste sayfası (21 maç).
  Custom'larda queueId 0 DEĞİL (3110/3100/3130 geliyor) — custom tespiti
  gameType=="CUSTOM_GAME" yoluyla yapılmalı, queueId==0 fallback'ine güvenilemez.
- `champion_summary_real.json`: gerçek champion-summary (id=-1 "Yok" girdisi dahil).
"""

from __future__ import annotations

import pytest

from collector.normalizer import (
    champion_map_from_summary,
    is_custom,
    normalize_match_history_game,
)

from .conftest import load_fixture

STAT_FIELDS = ("kills", "deaths", "assists", "gold", "cs", "damage_to_champs", "vision_score")


@pytest.fixture
def mh_game_custom_real():
    return load_fixture("mh_game_custom_real.json")


@pytest.fixture
def mh_list_page_real():
    return load_fixture("mh_list_page_real.json")


@pytest.fixture
def champion_summary_real():
    return load_fixture("champion_summary_real.json")


@pytest.fixture
def real_champion_map(champion_summary_real):
    return champion_map_from_summary(champion_summary_real)


class TestNormalizeRealMatchHistoryGame:
    def test_contract_shape(self, mh_game_custom_real, real_champion_map):
        payload = normalize_match_history_game(
            mh_game_custom_real, champion_map=real_champion_map
        )
        assert payload.source_game_id == "1734450310"
        assert payload.duration_s == 1352
        assert payload.winner_team == 100
        assert len(payload.participants) == 10
        assert sum(1 for p in payload.participants if p.team == 100) == 5
        assert sum(1 for p in payload.participants if p.team == 200) == 5

    def test_all_participants_have_puuid(self, mh_game_custom_real, real_champion_map):
        payload = normalize_match_history_game(
            mh_game_custom_real, champion_map=real_champion_map
        )
        for p in payload.participants:
            assert p.puuid, f"puuid boş: {p.riot_id!r}"

    def test_all_stats_populated_from_camelcase_keys(
        self, mh_game_custom_real, real_champion_map
    ):
        """Gerçek match-history statları camelCase gelir; hiçbir alan None kalmamalı."""
        payload = normalize_match_history_game(
            mh_game_custom_real, champion_map=real_champion_map
        )
        for p in payload.participants:
            for field in STAT_FIELDS:
                assert getattr(p.stats, field) is not None, (
                    f"{field} None kaldı ({p.riot_id!r}) — camelCase stat eşlemesi kırılmış"
                )

    def test_all_champions_resolved_via_champion_map(
        self, mh_game_custom_real, real_champion_map
    ):
        payload = normalize_match_history_game(
            mh_game_custom_real, champion_map=real_champion_map
        )
        for p in payload.participants:
            assert p.champion, f"champion çözülemedi ({p.riot_id!r})"

    def test_positions_are_none_in_real_custom(self, mh_game_custom_real, real_champion_map):
        """Gerçek custom kaydında açık position alanı yok; timeline.lane Riot
        tahminidir ve kullanılmamalı → tüm position'lar None beklenir."""
        payload = normalize_match_history_game(
            mh_game_custom_real, champion_map=real_champion_map
        )
        for p in payload.participants:
            assert p.position is None, (
                f"position {p.position!r} geldi ({p.riot_id!r}) — custom'da tahmin yasak"
            )


class TestIsCustomOnRealListPage:
    def test_gametype_decides_not_queue_id(self, mh_list_page_real):
        """Gerçek liste sayfasında custom'lar queueId 3110/3100/3130 ile gelir
        (0 DEĞİL). queueId==0 fallback'i bunları yakalayamazdı; is_custom
        gameType=="CUSTOM_GAME" yolu sayesinde doğru sınıflandırmalı."""
        games = mh_list_page_real["games"]["games"]
        assert len(games) == 21  # fixture bütünlüğü

        seen_nonzero_custom_queue = False
        for game in games:
            game_type = game["gameType"]
            assert game_type in ("CUSTOM_GAME", "MATCHED_GAME")
            expected = game_type == "CUSTOM_GAME"
            assert is_custom(game) is expected, (
                f"gameId={game.get('gameId')} gameType={game_type} "
                f"queueId={game.get('queueId')}"
            )
            if expected and game.get("queueId") != 0:
                seen_nonzero_custom_queue = True

        # Tuzağın gerçekten fixture'da var olduğunu kanıtla: en az bir custom
        # maç sıfırdan farklı queueId taşıyor.
        assert seen_nonzero_custom_queue


class TestRealChampionSummary:
    def test_map_size_and_validity(self, real_champion_map):
        assert len(real_champion_map) >= 200
        for cid, name in real_champion_map.items():
            assert isinstance(cid, int) and cid > 0
            assert name

    def test_invalid_placeholder_entry_dropped(self, champion_summary_real, real_champion_map):
        """Gerçek summary id=-1 ('Yok') placeholder girdisi içerir; map'e girmemeli."""
        assert any(e.get("id") == -1 for e in champion_summary_real)
        assert -1 not in real_champion_map
