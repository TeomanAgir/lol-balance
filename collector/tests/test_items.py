"""GÖREV 14 — eşya envanteri çıkarımı (ingest_contract "items").

Kaynaklar: canlı EOG bloğunda oyuncunun `items` dizisi, match-history kaydında
`item0..item6` slotları. Ortak kural: ham SIRA korunur, boş slot (`0`) ve bozuk
değerler atılır, en fazla 7 eleman. Kaynakta hiç eşya bilgisi yoksa alan
payload'a KONMAZ (null gönderilmez) — eski exe'lerle aynı davranış.

Doğrulama gerçek fixture'lar üzerinden yapılır (fixture'lar değiştirilmez).
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

import pytest

from collector.models import MAX_ITEMS, Participant
from collector.normalizer import (
    eog_items,
    items_from_raw,
    mh_items,
    normalize_eog,
    normalize_match_history_game,
)

from .conftest import load_fixture

NOW = datetime(2026, 8, 11, 22, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def eog_custom_real():
    return load_fixture("eog_custom_real.json")


@pytest.fixture
def eog_custom_detected():
    return load_fixture("eog_custom_detected.json")


@pytest.fixture
def mh_game_custom_real():
    return load_fixture("mh_game_custom_real.json")


def eog_players(raw):
    """EOG bloğundaki 10 ham oyuncu (takım sırasıyla — normalize ile aynı sıra)."""
    return [p for team in raw["teams"] for p in team["players"]]


def raw_mh_slots(participant):
    """Ham match-history katılımcısının item0..item6 değerleri (sırayla)."""
    return [participant["stats"][f"item{index}"] for index in range(MAX_ITEMS)]


def nonzero(values):
    return [int(v) for v in values if int(v) > 0]


# --------------------------------------------------------------------------- #
# 1. Gerçek fixture'lar — canlı EOG (`items` dizisi)
# --------------------------------------------------------------------------- #


class TestRealEogItems:
    def test_every_participant_carries_raw_order_without_empty_slots(self, eog_custom_real):
        payload = normalize_eog(eog_custom_real, NOW)
        raw_players = eog_players(eog_custom_real)
        assert len(payload.participants) == len(raw_players) == 10
        for participant, raw_player in zip(payload.participants, raw_players):
            assert participant.items == nonzero(raw_player["items"])

    def test_exact_inventory_of_the_first_player(self, eog_custom_real):
        """Ham dizi tam dolu (7/7) → birebir aynı sırayla taşınır."""
        first = eog_players(eog_custom_real)[0]
        assert first["items"] == [3031, 6610, 3111, 2517, 6692, 1038, 3340]
        assert normalize_eog(eog_custom_real, NOW).participants[0].items == [
            3031, 6610, 3111, 2517, 6692, 1038, 3340
        ]

    def test_empty_slot_is_dropped_and_trinket_stays_last(self, eog_custom_real):
        """Ham veride boş slot `0` olarak gelir (ör. 2. oyuncu): atılır, sıra korunur."""
        second = eog_players(eog_custom_real)[1]
        assert second["items"] == [3009, 6697, 6698, 3036, 3031, 0, 3340]
        items = normalize_eog(eog_custom_real, NOW).participants[1].items
        assert items == [3009, 6697, 6698, 3036, 3031, 3340]
        assert 0 not in items

    def test_all_inventories_are_valid_item_ids(self, eog_custom_real):
        for participant in normalize_eog(eog_custom_real, NOW).participants:
            assert participant.items is not None
            assert 0 < len(participant.items) <= MAX_ITEMS
            assert all(isinstance(i, int) and i > 0 for i in participant.items)

    def test_detected_fixture_drops_three_empty_slots(self, eog_custom_detected):
        """Diğer gerçek EOG patch'i: 3 boş slot taşıyan oyuncu 4 eşyayla gider."""
        first = eog_players(eog_custom_detected)[0]
        assert first["items"] == [3111, 3083, 3068, 0, 0, 0, 3340]
        payload = normalize_eog(eog_custom_detected, NOW)
        assert payload.participants[0].items == [3111, 3083, 3068, 3340]
        for participant, raw_player in zip(payload.participants, eog_players(eog_custom_detected)):
            assert participant.items == nonzero(raw_player["items"])


# --------------------------------------------------------------------------- #
# 2. Gerçek fixture — match-history (`item0..item6`)
# --------------------------------------------------------------------------- #


class TestRealMatchHistoryItems:
    def test_every_participant_carries_slot_order_without_empty_slots(self, mh_game_custom_real):
        payload = normalize_match_history_game(mh_game_custom_real)
        raw_participants = mh_game_custom_real["participants"]
        assert len(payload.participants) == len(raw_participants) == 10
        for participant, raw_participant in zip(payload.participants, raw_participants):
            assert participant.items == nonzero(raw_mh_slots(raw_participant))

    def test_exact_inventory_of_the_first_participant(self, mh_game_custom_real):
        first = mh_game_custom_real["participants"][0]
        assert raw_mh_slots(first) == [1055, 2031, 3142, 1028, 3047, 1031, 3340]
        assert normalize_match_history_game(mh_game_custom_real).participants[0].items == [
            1055, 2031, 3142, 1028, 3047, 1031, 3340
        ]

    def test_participant_with_three_empty_slots(self, mh_game_custom_real):
        eighth = mh_game_custom_real["participants"][7]
        assert raw_mh_slots(eighth) == [3040, 6653, 0, 0, 0, 3175, 3340]
        assert normalize_match_history_game(mh_game_custom_real).participants[7].items == [
            3040, 6653, 3175, 3340
        ]

    def test_all_inventories_are_valid_item_ids(self, mh_game_custom_real):
        for participant in normalize_match_history_game(mh_game_custom_real).participants:
            assert participant.items is not None
            assert 0 < len(participant.items) <= MAX_ITEMS
            assert all(isinstance(i, int) and i > 0 for i in participant.items)


# --------------------------------------------------------------------------- #
# 3. Boş / eksik / bozuk kaynaklar
# --------------------------------------------------------------------------- #


class TestEogItemExtraction:
    def test_missing_field_is_unknown(self):
        assert eog_items({"puuid": "p"}) is None

    @pytest.mark.parametrize("value", [None, "3031", 3031, {"0": 3031}])
    def test_non_list_field_is_unknown(self, value):
        assert eog_items({"items": value}) is None

    def test_empty_list_is_known_but_empty(self):
        """`[]` "bilgi var, envanter boş" demektir — None ile aynı şey DEĞİLDİR."""
        assert eog_items({"items": []}) == []

    def test_all_slots_empty_is_known_but_empty(self):
        assert eog_items({"items": [0, 0, 0, 0, 0, 0, 0]}) == []

    def test_broken_values_are_dropped_order_preserved(self):
        assert eog_items({"items": [3031, None, "abc", -5, 0, 3340]}) == [3031, 3340]

    def test_numeric_strings_and_floats_are_accepted(self):
        assert eog_items({"items": ["3031", 3340.0]}) == [3031, 3340]

    def test_booleans_are_not_item_ids(self):
        assert eog_items({"items": [True, False, 3340]}) == [3340]

    def test_more_than_seven_entries_are_capped(self):
        raw = list(range(1001, 1012))  # 11 geçerli id
        assert eog_items({"items": raw}) == raw[:MAX_ITEMS]

    def test_cap_counts_only_kept_entries(self):
        """Boş slotlar sayıma girmez: 7 gerçek eşya varsa 7'si de taşınır."""
        raw = [0, 1001, 0, 1002, 1003, 1004, 0, 1005, 1006, 1007]
        assert eog_items({"items": raw}) == [1001, 1002, 1003, 1004, 1005, 1006, 1007]


class TestMatchHistoryItemExtraction:
    def test_no_slot_fields_is_unknown(self, mh_game_custom):
        """Sentetik fixture item0..item6 taşımaz → bilgi yok."""
        assert mh_items(mh_game_custom["participants"][0]) is None
        assert mh_items({"stats": {"kills": 3}}) is None

    def test_all_slots_zero_is_known_but_empty(self):
        stats = {f"item{index}": 0 for index in range(MAX_ITEMS)}
        assert mh_items({"stats": stats}) == []

    def test_partial_slot_fields_keep_order(self):
        assert mh_items({"stats": {"item0": 3031, "item3": 3340}}) == [3031, 3340]

    def test_slots_on_the_participant_itself_are_read(self):
        """Bazı LCU sürümleri slotları `stats` yerine katılımcıda taşır."""
        assert mh_items({"item0": 3031, "item6": 3340}) == [3031, 3340]

    def test_stats_wins_over_participant_level_duplicate(self):
        assert mh_items({"item0": 111, "stats": {"item0": 3031}}) == [3031]

    def test_broken_values_are_dropped(self):
        assert mh_items({"stats": {"item0": "x", "item1": -1, "item2": 3340}}) == [3340]


# --------------------------------------------------------------------------- #
# 4. Payload şekli — bilgi yoksa alan KONMAZ
# --------------------------------------------------------------------------- #


class TestPayloadShape:
    def test_field_absent_when_source_has_no_item_data(self, eog_custom):
        """Sentetik EOG (items alanı yok) → gövdede `items` anahtarı HİÇ yok."""
        dumped = normalize_eog(eog_custom, NOW).model_dump()
        for participant in dumped["participants"]:
            assert "items" not in participant
        assert '"items"' not in json.dumps(dumped)

    def test_field_absent_for_match_history_without_slots(self, mh_game_custom):
        dumped = normalize_match_history_game(mh_game_custom).model_dump()
        assert all("items" not in p for p in dumped["participants"])

    def test_empty_inventory_is_sent_as_empty_list(self, eog_custom):
        """"Bilgi var, envanter boş" hâli gövdeye `[]` olarak GİRER."""
        raw = copy.deepcopy(eog_custom)
        eog_players(raw)[0]["items"] = [0, 0, 0, 0, 0, 0, 0]
        dumped = normalize_eog(raw, NOW).model_dump()
        assert dumped["participants"][0]["items"] == []
        assert all("items" not in p for p in dumped["participants"][1:])

    def test_mixed_participants_keep_their_own_state(self, eog_custom):
        raw = copy.deepcopy(eog_custom)
        eog_players(raw)[3]["items"] = [3031, 0, 3340]
        dumped = normalize_eog(raw, NOW).model_dump()
        assert dumped["participants"][3]["items"] == [3031, 3340]
        assert [("items" in p) for p in dumped["participants"]] == [
            i == 3 for i in range(10)
        ]

    def test_other_nullable_fields_are_still_sent_as_null(self, eog_custom):
        """Regresyon: alan atlama davranışı YALNIZ items'a özeldir."""
        dumped = normalize_eog(eog_custom, NOW).model_dump()
        participant = dumped["participants"][0]
        assert "position" in participant and "champion" in participant
        assert set(participant["stats"]) == {
            "kills", "deaths", "assists", "gold", "cs", "damage_to_champs", "vision_score"
        }

    def test_model_rejects_more_than_seven_items(self):
        with pytest.raises(ValueError, match="at most 7"):
            Participant(puuid="p", team=100, items=list(range(1001, 1009)))

    def test_model_rejects_non_positive_item_ids(self):
        with pytest.raises(ValueError, match="positive item ids"):
            Participant(puuid="p", team=100, items=[3031, 0])


# --------------------------------------------------------------------------- #
# 5. items_from_raw — backfill-items ile aynı anahtarlama
# --------------------------------------------------------------------------- #


class TestItemsFromRaw:
    def test_eog_keyed_by_puuid(self, eog_custom_real):
        resolved = items_from_raw(eog_custom_real)
        raw_players = eog_players(eog_custom_real)
        assert set(resolved) == {p["puuid"] for p in raw_players}
        for raw_player in raw_players:
            assert resolved[raw_player["puuid"]] == nonzero(raw_player["items"])

    def test_match_history_keyed_by_identity_puuid(self, mh_game_custom_real):
        resolved = items_from_raw(mh_game_custom_real)
        identities = {
            identity["participantId"]: identity["player"]["puuid"]
            for identity in mh_game_custom_real["participantIdentities"]
        }
        assert set(resolved) == set(identities.values())
        for participant in mh_game_custom_real["participants"]:
            puuid = identities[participant["participantId"]]
            assert resolved[puuid] == nonzero(raw_mh_slots(participant))

    def test_keys_match_positions_from_raw(self, eog_custom_real, mh_game_custom_real):
        """Rol ve eşya sözlükleri aynı anahtar uzayını kullanır (backfill eşlemesi)."""
        from collector.normalizer import positions_from_raw

        for raw in (eog_custom_real, mh_game_custom_real):
            assert set(items_from_raw(raw)) == set(positions_from_raw(raw))

    def test_unknown_when_source_has_no_item_data(self, eog_custom, mh_game_custom):
        assert set(items_from_raw(eog_custom).values()) == {None}
        assert set(items_from_raw(mh_game_custom).values()) == {None}


# --------------------------------------------------------------------------- #
# 6. Mevcut gönderim yolları (canlı + backfill) envanteri taşır
# --------------------------------------------------------------------------- #


class TestLivePathCarriesItems:
    def _run(self, config, eog, champion_summary):
        from collector.live import LiveRunner

        from .fakes import FakeLcu
        from .test_live import NO_SLEEP, capturing_sender

        sender, sent = capturing_sender(config)
        runner = LiveRunner(
            config, FakeLcu(eog=eog, champions=champion_summary), sender,
            sleep=NO_SLEEP, now=lambda: NOW,
        )
        assert runner.on_end_of_game() is True
        return sent[0]

    def test_real_eog_payload_carries_inventories(self, config, eog_custom_real, champion_summary):
        payload = self._run(config, eog_custom_real, champion_summary)
        expected = [nonzero(p["items"]) for p in eog_players(eog_custom_real)]
        assert [p["items"] for p in payload["participants"]] == expected

    def test_payload_without_item_data_has_no_field(self, config, eog_custom, champion_summary):
        payload = self._run(config, eog_custom, champion_summary)
        assert all("items" not in p for p in payload["participants"])


class TestBackfillPathCarriesItems:
    def _run(self, config, mh_list_page, game, champion_summary):
        from collector.backfill import run_backfill
        from collector.roster import KnownRoster

        from .test_backfill import KNOWN_SIX, capturing_sender, make_lcu

        lcu = make_lcu(mh_list_page, game, champion_summary)
        sender, sent = capturing_sender(config)
        run_backfill(config, lcu, sender, roster=KnownRoster(riot_ids=set(KNOWN_SIX)))
        return sent

    def test_item_slots_reach_the_payload(
        self, config, mh_list_page, mh_game_custom, champion_summary
    ):
        game = copy.deepcopy(mh_game_custom)
        for offset, participant in enumerate(game["participants"]):
            participant["stats"].update(
                {f"item{index}": 0 for index in range(MAX_ITEMS)}
            )
            participant["stats"]["item0"] = 3031 + offset
            participant["stats"]["item6"] = 3340

        sent = self._run(config, mh_list_page, game, champion_summary)

        assert sent, "backfill hiç maç göndermedi"
        for payload in sent:
            assert [p["items"] for p in payload["participants"]] == [
                [3031 + offset, 3340] for offset in range(10)
            ]

    def test_payload_without_item_slots_has_no_field(
        self, config, mh_list_page, mh_game_custom, champion_summary
    ):
        sent = self._run(config, mh_list_page, mh_game_custom, champion_summary)

        assert sent
        for payload in sent:
            assert all("items" not in p for p in payload["participants"])
