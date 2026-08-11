"""Gerçek LCU client'ından alınmış fixture'lara karşı regresyon testleri.

Sentetik fixture'lar (`mh_game_custom.json` vb.) yapıyı belgeler; buradaki
`*_real.json` fixture'ları gerçek şemayı belgeler:

- `eog_custom_real.json`: canlı LCU'dan yakalanmış gerçek EOG bloğu
  (gameId 1734664864, 2026-08-11 gecesi oynandı, `raw_archive/1734664864.json`
  kopyası). Statlar UPPER_SNAKE, `selectedPosition` + `detectedTeamPosition`
  İKİSİ DE dolu ve tutarlı, `championName` payload'ın içinde (champion_map
  gerekmez), `queueId` alanı HİÇ YOK ve `queueType` "NORMAL" — custom tespiti
  yalnızca `gameType == "CUSTOM_GAME"` ile mümkün.
- `mh_game_custom_real.json`: 10 kişilik gerçek custom maç (gameId 1734450310).
  Statlar camelCase, açık position alanı yok, puuid'ler participantIdentities'te.
- `mh_list_page_real.json`: gerçek match-history liste sayfası (21 maç).
  Custom'larda queueId 0 DEĞİL (3110/3100/3130 geliyor) — custom tespiti
  gameType=="CUSTOM_GAME" yoluyla yapılmalı, queueId==0 fallback'ine güvenilemez.
- `champion_summary_real.json`: gerçek champion-summary (id=-1 "Yok" girdisi dahil).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from collector.normalizer import (
    champion_map_from_summary,
    is_custom,
    normalize_eog,
    normalize_match_history_game,
    to_utc_z,
)
from collector.role_infer import SMITE_SPELL_ID

from .conftest import load_fixture

STAT_FIELDS = ("kills", "deaths", "assists", "gold", "cs", "damage_to_champs", "vision_score")

#: Gerçek EOG bloğundaki `endOfGameTimestamp` (1786484600652 ms) → maçın bitiş anı.
#: `normalize_eog` played_at'i ÖNCE bu alandan üretir; `captured_at` yalnızca alan
#: yoksa devreye girer (CHANGE_REQUESTS, 2026-08-11).
REAL_EOG_END_TS_MS = 1786484600652

#: Bilerek maç bitişinden ~1 gün sonrası: played_at'in yakalama anından DEĞİL,
#: payload'daki bitiş anından geldiğini kanıtlar.
REAL_EOG_CAPTURED_AT = datetime(2026, 8, 12, 9, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def eog_custom_real():
    return load_fixture("eog_custom_real.json")


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


#: gameId 1734664864'ün gerçek kadrosu: riot_id → (team, selectedPosition, championName)
REAL_EOG_ROSTER = {
    "YANSIMA#TR1": (100, "TOP", "Riven"),
    "II RYUKEN II#PNTHR": (100, "JUNGLE", "Quinn"),
    "SauronunAgzi#3791": (100, "MIDDLE", "Hwei"),
    "Śhade#TR1": (100, "BOTTOM", "Jhin"),
    "Kati#TR22": (100, "UTILITY", "Vex"),
    "DEPRESSED THUGG#1616": (200, "TOP", "Renekton"),
    "kimsesiz34#7823": (200, "JUNGLE", "Viego"),
    "Konna Netlaka#1703": (200, "MIDDLE", "Aurelion Sol"),
    "Çizgi Hükümdarı#PNTHR": (200, "BOTTOM", "Caitlyn"),
    "YETİ VE PİÇİ#TR1": (200, "UTILITY", "Seraphine"),
}


class TestNormalizeRealEog:
    """Canlı yakalanmış gerçek EOG bloğuna karşı regresyon (gameId 1734664864).

    Bu maç canlı sistemde uçtan uca doğru işlendi (pozisyonlar + 7 stat alanı DB'de
    dolu); buradaki testler o davranışı gerçek şemaya karşı KİLİTLER.
    """

    def test_contract_shape(self, eog_custom_real):
        payload = normalize_eog(eog_custom_real, REAL_EOG_CAPTURED_AT)
        assert payload.source == "lcu_eog"
        assert payload.source_game_id == "1734664864"
        assert payload.duration_s == 2070  # gameLength saniye cinsinden geliyor
        assert payload.winner_team == 100
        assert len(payload.participants) == 10
        assert sum(1 for p in payload.participants if p.team == 100) == 5
        assert sum(1 for p in payload.participants if p.team == 200) == 5

    def test_played_at_from_end_of_game_timestamp(self, eog_custom_real):
        """played_at, payload'daki `endOfGameTimestamp`'ten gelir (ms → saniye,
        UTC 'Z'). Yakalama anı burada bilerek ~11 saat sonrası verildi: sonuç
        değişmiyorsa zaman gerçekten maçın bitişinden okunuyor demektir."""
        assert eog_custom_real["endOfGameTimestamp"] == REAL_EOG_END_TS_MS
        payload = normalize_eog(eog_custom_real, REAL_EOG_CAPTURED_AT)
        assert payload.played_at == "2026-08-11T21:43:20Z"
        assert payload.played_at != to_utc_z(REAL_EOG_CAPTURED_AT)

    def test_is_custom_despite_normal_queue_type(self, eog_custom_real):
        """Gerçek EOG bloğunda `queueId` alanı HİÇ YOK ve `queueType` "NORMAL"
        geliyor; custom tespiti yalnızca gameType üzerinden yürümek zorunda."""
        assert "queueId" not in eog_custom_real
        assert eog_custom_real["queueType"] == "NORMAL"
        assert eog_custom_real["gameType"] == "CUSTOM_GAME"
        assert is_custom(eog_custom_real) is True

    def test_all_positions_match_selected_position(self, eog_custom_real):
        """10 pozisyonun TAMAMI dolu ve ham `selectedPosition` ile birebir aynı —
        açık alan tahmini ezer (GÖREV 0 kuralı)."""
        payload = normalize_eog(eog_custom_real, REAL_EOG_CAPTURED_AT)
        actual = {p.riot_id: p.position for p in payload.participants}
        expected = {rid: pos for rid, (_, pos, _) in REAL_EOG_ROSTER.items()}
        assert actual == expected
        assert all(p.position is not None for p in payload.participants)

    def test_selected_and_detected_position_agree_in_raw(self, eog_custom_real):
        """Gerçek şema iki position alanı taşıyor ve ikisi de dolu/tutarlı.
        Normalizer `selectedPosition`'ı okur; bu test ikisinin ayrışmadığını,
        yani seçilen alanın doğru alan olduğunu belgeler."""
        for team in eog_custom_real["teams"]:
            for player in team["players"]:
                selected = player["selectedPosition"]
                detected = player["detectedTeamPosition"]
                assert selected and detected
                assert selected == detected, player.get("riotIdGameName")

    def test_smite_carriers_are_jungle(self, eog_custom_real):
        """Smite (spellId 11) kusursuz sinyal: tam 2 taşıyıcı, ikisi de JUNGLE."""
        carriers = {
            f"{p['riotIdGameName']}#{p['riotIdTagLine']}"
            for team in eog_custom_real["teams"]
            for p in team["players"]
            if SMITE_SPELL_ID in (p["spell1Id"], p["spell2Id"])
        }
        assert carriers == {"II RYUKEN II#PNTHR", "kimsesiz34#7823"}
        payload = normalize_eog(eog_custom_real, REAL_EOG_CAPTURED_AT)
        for p in payload.participants:
            if p.riot_id in carriers:
                assert p.position == "JUNGLE"

    def test_all_stats_populated_from_upper_snake_keys(self, eog_custom_real):
        """Gerçek EOG statları UPPER_SNAKE gelir; 7 alanın 7'si de dolmalı."""
        payload = normalize_eog(eog_custom_real, REAL_EOG_CAPTURED_AT)
        for p in payload.participants:
            for field in STAT_FIELDS:
                assert getattr(p.stats, field) is not None, (
                    f"{field} None kaldı ({p.riot_id!r}) — UPPER_SNAKE stat eşlemesi kırılmış"
                )

    def test_exact_stats_for_yansima(self, eog_custom_real):
        """Fixture'dan okunan gerçek değerler (kaymayı yakalamak için elle sabit)."""
        payload = normalize_eog(eog_custom_real, REAL_EOG_CAPTURED_AT)
        p = next(p for p in payload.participants if p.riot_id == "YANSIMA#TR1")
        assert p.team == 100
        assert p.champion == "Riven"
        assert p.position == "TOP"
        assert p.stats.kills == 13
        assert p.stats.deaths == 9
        assert p.stats.assists == 7
        assert p.stats.gold == 18254
        assert p.stats.cs == 236  # 224 lane (MINIONS_KILLED) + 12 neutral
        assert p.stats.damage_to_champs == 35600
        assert p.stats.vision_score == 36

    def test_exact_stats_for_zero_kill_support(self, eog_custom_real):
        """0 değeri None'a düşmemeli (falsy tuzağı) — bu maçta destek 0/9/17."""
        payload = normalize_eog(eog_custom_real, REAL_EOG_CAPTURED_AT)
        p = next(p for p in payload.participants if p.riot_id == "YETİ VE PİÇİ#TR1")
        assert p.stats.kills == 0
        assert p.stats.deaths == 9
        assert p.stats.assists == 17
        assert p.stats.gold == 10014
        assert p.stats.cs == 44  # 44 lane + 0 neutral
        assert p.stats.damage_to_champs == 18216
        assert p.stats.vision_score == 91

    def test_champions_come_from_payload_without_champion_map(self, eog_custom_real):
        """EOG bloğu `championName` taşır → champion_map olmadan da hepsi çözülür."""
        payload = normalize_eog(eog_custom_real, REAL_EOG_CAPTURED_AT)
        actual = {p.riot_id: p.champion for p in payload.participants}
        expected = {rid: champ for rid, (_, _, champ) in REAL_EOG_ROSTER.items()}
        assert actual == expected

    def test_identities_are_complete(self, eog_custom_real):
        """puuid dolu; riot_id "Ad#TAG" biçiminde (gerçek şemada `summonerName`
        BOŞ string geliyor — fallback'e düşülseydi kimlik kaybolurdu)."""
        assert all(
            p["summonerName"] == ""
            for team in eog_custom_real["teams"]
            for p in team["players"]
        )
        payload = normalize_eog(eog_custom_real, REAL_EOG_CAPTURED_AT)
        for p in payload.participants:
            assert p.puuid, f"puuid boş: {p.riot_id!r}"
            assert p.riot_id and "#" in p.riot_id
            name, _, tag = p.riot_id.partition("#")
            assert name and tag
        assert {p.riot_id for p in payload.participants} == set(REAL_EOG_ROSTER)
        assert len({p.puuid for p in payload.participants}) == 10

    def test_teams_assigned_from_player_team_id(self, eog_custom_real):
        payload = normalize_eog(eog_custom_real, REAL_EOG_CAPTURED_AT)
        actual = {p.riot_id: p.team for p in payload.participants}
        expected = {rid: team for rid, (team, _, _) in REAL_EOG_ROSTER.items()}
        assert actual == expected


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

    def test_positions_come_from_constraint_solver(
        self, mh_game_custom_real, real_champion_map
    ):
        """Gerçek custom kaydında açık position alanı yok (GÖREV 0 öncesi hepsi
        None kalıyordu). Artık kısıt zinciri koşar: takım 100 tam çözülür; takım
        200'de iki oyuncu da 'TOP/DUO' etiketli olduğundan MIDDLE ve TOP
        belirsizdir → o iki slot None kalır (tahmin ZORLANMAZ)."""
        payload = normalize_match_history_game(
            mh_game_custom_real, champion_map=real_champion_map
        )
        team_100 = {p.riot_id: p.position for p in payload.participants if p.team == 100}
        assert sorted(v for v in team_100.values() if v) == [
            "BOTTOM", "JUNGLE", "MIDDLE", "TOP", "UTILITY"
        ]
        assert team_100["SoSiSwithSaLaM#TR1"] == "JUNGLE"  # Smite taşıyan

        team_200 = {p.riot_id: p.position for p in payload.participants if p.team == 200}
        assert team_200["YANSIMANIN OĞLU#4634"] == "JUNGLE"
        assert team_200["Fugori#3818"] == "BOTTOM"
        assert team_200["Çizgi Hükümdarı#PNTHR"] == "UTILITY"
        # belirsiz kalan iki oyuncu — null gider, insan UI'dan düzeltir
        assert team_200["ıııııMMAMMıııııı#TR1"] is None
        assert team_200["Śhade#TR1"] is None

    def test_no_duplicate_position_within_team(self, mh_game_custom_real):
        """Zincir aynı rolü bir takımda iki kez atamamalı."""
        payload = normalize_match_history_game(mh_game_custom_real)
        for team_id in (100, 200):
            assigned = [
                p.position
                for p in payload.participants
                if p.team == team_id and p.position
            ]
            assert len(assigned) == len(set(assigned))


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
