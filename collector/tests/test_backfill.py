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


class RepeatingPageLcu(FakeLcu):
    """Gerçek LCU'nun gözlenen davranışı: begIndex/endIndex yok sayılır, her
    çağrıda aynı (son ~21 maçlık) liste döner."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.list_calls = 0
        self.game_calls: list = []

    def get_match_list(self, puuid, beg_index, end_index):
        self.list_calls += 1
        return self._pages[0]

    def get_game(self, game_id):
        self.game_calls.append(game_id)
        return super().get_game(game_id)


def make_remake_game(mh_game_custom, game_id=6874233333):
    """185 sn süren, iki takımın da win='Fail' olduğu gerçek remake şekli."""
    remake = copy.deepcopy(mh_game_custom)
    remake["gameId"] = game_id
    remake["gameDuration"] = 185
    remake["gameCreationDate"] = "2026-08-03T20:00:00.000Z"
    for team in remake["teams"]:
        team["win"] = "Fail"
    return remake


def remake_summary(game_id=6874233333):
    return {
        "gameId": game_id,
        "gameCreationDate": "2026-08-03T20:00:00.000Z",
        "gameDuration": 185,
        "queueId": 0,
        "gameType": "CUSTOM_GAME",
        "gameMode": "CLASSIC",
    }


def custom_summary(game_id, **overrides):
    """Liste sayfasındaki bir custom maç özeti (varsayılan: SR/CLASSIC)."""
    summary = {
        "gameId": game_id,
        "gameCreationDate": "2026-08-05T20:00:00.000Z",
        "gameDuration": 1500,
        "queueId": 0,
        "gameType": "CUSTOM_GAME",
        "gameMode": "CLASSIC",
        "mapId": 11,
    }
    summary.update(overrides)
    return summary


class DetailTrackingLcu(FakeLcu):
    """Hangi maçların DETAYININ çekildiğini kaydeder (filtre detaydan önce mi?)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.game_calls: list = []

    def get_game(self, game_id):
        self.game_calls.append(game_id)
        return super().get_game(game_id)


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
    # liste yeniden-eskiye gelir ama gönderim ESKİDEN-YENİYE olmalı
    # (incremental rating doğru sırayla işlesin diye)
    assert [p["source_game_id"] for p in sent] == ["6874230000", "6874231001"]
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


def test_backfill_stops_when_pagination_does_not_advance(
    config, mh_list_page, mh_game_custom, champion_summary
):
    """LCU indeksleri yok sayıp hep aynı listeyi dönerse: her maç bir kez işlenir,
    ikinci (yeni maç içermeyen) sayfada tarama biter — 500 sayfa dönülmez."""
    games = mh_list_page["games"]["games"]
    old_custom = copy.deepcopy(mh_game_custom)
    old_custom["gameId"] = 6874230000
    old_custom["gameCreationDate"] = "2026-07-01T18:00:00.000Z"
    lcu = RepeatingPageLcu(
        summoner={"puuid": "puuid-t1"},
        pages=[games],
        games={6874231001: mh_game_custom, 6874230000: old_custom},
        champions=champion_summary,
    )
    sender, sent = capturing_sender(config)
    roster = KnownRoster(riot_ids=set(KNOWN_SIX))

    stats = run_backfill(config, lcu, sender, roster=roster)

    assert lcu.list_calls == 2  # 1. sayfa + "ilerlemiyor" tespiti, sonra dur
    assert stats.scanned == 3  # her maç yalnızca bir kez sayıldı
    assert stats.sent == 2
    assert len(lcu.game_calls) == len(set(lcu.game_calls)) == 2  # detay tek kez çekildi
    assert len(sent) == 2


def test_backfill_skips_remake_without_error(
    config, mh_list_page, mh_game_custom, champion_summary
):
    """Kazananı olmayan 185 sn'lik maç remake'tir: gönderilmez, hata da sayılmaz."""
    remake_id = 6874233333
    games = [remake_summary(remake_id)] + mh_list_page["games"]["games"]
    old_custom = copy.deepcopy(mh_game_custom)
    old_custom["gameId"] = 6874230000
    old_custom["gameCreationDate"] = "2026-07-01T18:00:00.000Z"
    lcu = FakeLcu(
        summoner={"puuid": "puuid-t1"},
        pages=[games, []],
        games={
            remake_id: make_remake_game(mh_game_custom, remake_id),
            6874231001: mh_game_custom,
            6874230000: old_custom,
        },
        champions=champion_summary,
    )
    sender, sent = capturing_sender(config)
    roster = KnownRoster(riot_ids=set(KNOWN_SIX))

    stats = run_backfill(config, lcu, sender, roster=roster)

    assert stats.skipped_remake == 1
    assert stats.errors == []
    assert stats.sent == 2
    assert str(remake_id) not in {p["source_game_id"] for p in sent}


def test_backfill_no_winner_long_game_is_still_error(
    config, mh_list_page, mh_game_custom, champion_summary
):
    """Kazanan yok ama süre >= 300 sn: remake değil, gerçek anormallik → hata."""
    broken_id = 6874234444
    broken = copy.deepcopy(mh_game_custom)
    broken["gameId"] = broken_id
    broken["gameCreationDate"] = "2026-08-04T20:00:00.000Z"
    for team in broken["teams"]:
        team["win"] = "Fail"  # gameDuration 2011 sn kalır
    summary = remake_summary(broken_id)
    summary["gameDuration"] = 2011
    summary["gameCreationDate"] = "2026-08-04T20:00:00.000Z"
    lcu = FakeLcu(
        summoner={"puuid": "puuid-t1"},
        pages=[[summary], []],
        games={broken_id: broken},
        champions=champion_summary,
    )
    sender, sent = capturing_sender(config)
    roster = KnownRoster(riot_ids=set(KNOWN_SIX))

    stats = run_backfill(config, lcu, sender, roster=roster)

    assert stats.skipped_remake == 0
    assert len(stats.errors) == 1
    assert "Could not determine the winning team" in stats.errors[0]
    assert sent == []


def test_backfill_skips_non_summoners_rift_custom(
    config, mh_list_page, mh_game_custom, champion_summary
):
    """Custom ARAM (SR değil) sessizce atlanır: detayı bile çekilmez, hata sayılmaz
    (Teoman, 2026-08-13)."""
    aram_id = 6874235555
    games = [custom_summary(aram_id, gameMode="ARAM", mapId=12)] + mh_list_page["games"]["games"]
    old_custom = copy.deepcopy(mh_game_custom)
    old_custom["gameId"] = 6874230000
    old_custom["gameCreationDate"] = "2026-07-01T18:00:00.000Z"
    lcu = DetailTrackingLcu(
        summoner={"puuid": "puuid-t1"},
        pages=[games, []],
        games={6874231001: mh_game_custom, 6874230000: old_custom},
        champions=champion_summary,
    )
    sender, sent = capturing_sender(config)
    roster = KnownRoster(riot_ids=set(KNOWN_SIX))

    stats = run_backfill(config, lcu, sender, roster=roster)

    assert stats.scanned == 4
    assert stats.customs == 3  # ARAM da bir custom'dır, ama SR olmadığı için elenir
    assert stats.skipped_non_sr == 1
    assert stats.errors == []
    assert aram_id not in lcu.game_calls  # filtre detay çekiminden ÖNCE
    assert [p["source_game_id"] for p in sent] == ["6874230000", "6874231001"]


def test_backfill_skips_non_sr_map_id_with_classic_mode(
    config, mh_game_custom, champion_summary
):
    """Kemer-askı: gameMode CLASSIC ama mapId 11 değilse yine elenir."""
    tt_id = 6874236666
    lcu = DetailTrackingLcu(
        summoner={"puuid": "puuid-t1"},
        pages=[[custom_summary(tt_id, mapId=10)], []],
        games={tt_id: mh_game_custom},
        champions=champion_summary,
    )
    sender, sent = capturing_sender(config)

    stats = run_backfill(config, lcu, sender, roster=KnownRoster(riot_ids=set(KNOWN_SIX)))

    assert stats.skipped_non_sr == 1
    assert stats.sent == 0 and sent == []
    assert lcu.game_calls == []


def test_backfill_processes_custom_without_game_mode(
    config, mh_game_custom, champion_summary
):
    """Eski şema toleransı: özet `gameMode` taşımıyorsa maç ATLANMAZ."""
    game_id = 6874231001
    summary = custom_summary(game_id)
    del summary["gameMode"], summary["mapId"]
    lcu = DetailTrackingLcu(
        summoner={"puuid": "puuid-t1"},
        pages=[[summary], []],
        games={game_id: mh_game_custom},
        champions=champion_summary,
    )
    sender, sent = capturing_sender(config)

    stats = run_backfill(config, lcu, sender, roster=KnownRoster(riot_ids=set(KNOWN_SIX)))

    assert stats.skipped_non_sr == 0
    assert stats.sent == 1
    assert [p["source_game_id"] for p in sent] == [str(game_id)]


def test_backfill_sends_chronologically(
    config, mh_list_page, mh_game_custom, champion_summary
):
    """Liste yeniden-eskiye gelir; gönderim played_at'e göre eskiden-yeniye olmalı."""
    lcu = make_lcu(mh_list_page, mh_game_custom, champion_summary)
    sender, sent = capturing_sender(config)
    roster = KnownRoster(riot_ids=set(KNOWN_SIX))

    run_backfill(config, lcu, sender, roster=roster)

    played_ats = [p["played_at"] for p in sent]
    assert played_ats == sorted(played_ats)
    assert [p["source_game_id"] for p in sent] == ["6874230000", "6874231001"]
