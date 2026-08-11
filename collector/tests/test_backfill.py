import copy
import json
from datetime import date

import httpx

from collector.backfill import run_backfill
from collector.roster import KnownRoster
from collector.sender import Sender

from .fakes import FakeLcu

# mh_game_custom fixture'ındaki ilk 6 oyuncu
KNOWN_SIX = {"teoman#tr1", "kaan#tr1", "mert#euw", "ece#tr1", "deniz#tr1", "baran#tr1"}


def capturing_sender(config):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(201, json={"match_id": 1, "duplicate": False})

    return Sender(config, transport=httpx.MockTransport(handler)), sent


def make_lcu(mh_list_page, mh_game_custom, champion_summary):
    games = mh_list_page["games"]["games"]
    old_custom = copy.deepcopy(mh_game_custom)
    old_custom["gameId"] = 6874230000
    old_custom["gameCreationDate"] = "2026-07-01T18:00:00.000Z"
    return FakeLcu(
        summoner={"puuid": "puuid-t1"},
        pages=[games, []],
        games={6874231001: mh_game_custom, 6874230000: old_custom},
        champions=champion_summary,
    )


def test_backfill_sends_roster_matching_customs(
    config, mh_list_page, mh_game_custom, champion_summary
):
    lcu = make_lcu(mh_list_page, mh_game_custom, champion_summary)
    sender, sent = capturing_sender(config)
    roster = KnownRoster(riot_ids=set(KNOWN_SIX))

    stats = run_backfill(config, lcu, sender, roster=roster)

    # listede 3 maç var: 1 ranked (atlanır), 2 custom (ikisi de roster'ı geçer)
    assert stats.scanned == 3
    assert stats.customs == 2
    assert stats.sent == 2
    assert {p["source_game_id"] for p in sent} == {"6874231001", "6874230000"}
    assert stats.errors == []


def test_backfill_since_cutoff(config, mh_list_page, mh_game_custom, champion_summary):
    lcu = make_lcu(mh_list_page, mh_game_custom, champion_summary)
    sender, sent = capturing_sender(config)
    roster = KnownRoster(riot_ids=set(KNOWN_SIX))

    stats = run_backfill(config, lcu, sender, since=date(2026, 7, 15), roster=roster)

    # 2026-07-01 tarihli custom eşikten eski → taranmaz
    assert stats.sent == 1
    assert sent[0]["source_game_id"] == "6874231001"


def test_backfill_roster_threshold(config, mh_list_page, mh_game_custom, champion_summary):
    lcu = make_lcu(mh_list_page, mh_game_custom, champion_summary)
    sender, sent = capturing_sender(config)
    roster = KnownRoster(riot_ids={"teoman#tr1", "kaan#tr1"})  # 2 < MIN_KNOWN=6

    stats = run_backfill(config, lcu, sender, roster=roster)

    assert stats.sent == 0
    assert stats.skipped_roster == 2
    assert sent == []


def test_backfill_empty_roster_aborts(config, mh_list_page, mh_game_custom, champion_summary):
    lcu = make_lcu(mh_list_page, mh_game_custom, champion_summary)
    sender, sent = capturing_sender(config)

    stats = run_backfill(config, lcu, sender, roster=KnownRoster())

    assert stats.scanned == 0
    assert sent == []


def test_backfill_duplicate_send_is_safe(
    config, mh_list_page, mh_game_custom, champion_summary
):
    """İki kez koşmak iki kez gönderir; idempotency backend'de source_game_id ile."""
    lcu = make_lcu(mh_list_page, mh_game_custom, champion_summary)
    sender, sent = capturing_sender(config)
    roster = KnownRoster(riot_ids=set(KNOWN_SIX))

    run_backfill(config, lcu, sender, roster=roster)
    lcu2 = make_lcu(mh_list_page, mh_game_custom, champion_summary)
    stats = run_backfill(config, lcu2, sender, roster=roster)

    assert stats.sent == 2
    assert len(sent) == 4
