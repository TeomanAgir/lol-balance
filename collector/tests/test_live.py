import json
from datetime import datetime, timezone

import httpx

from collector.live import LiveRunner
from collector.sender import Sender

from .conftest import load_fixture
from .fakes import FakeLcu

NOW = lambda: datetime(2026, 8, 11, 20, 41, 3, tzinfo=timezone.utc)
NO_SLEEP = lambda s: None


def capturing_sender(config, status=201):
    sent = []

    def handler(request):
        if request.url.path == "/api/v1/ingest/match":
            sent.append(json.loads(request.content))
            return httpx.Response(status, json={"match_id": 1, "duplicate": False})
        return httpx.Response(404)

    return Sender(config, transport=httpx.MockTransport(handler)), sent


def make_runner(config, lcu, sender):
    return LiveRunner(config, lcu, sender, sleep=NO_SLEEP, now=NOW)


def test_eog_processed_once(config, eog_custom, champion_summary):
    lcu = FakeLcu(eog=eog_custom, champions=champion_summary)
    sender, sent = capturing_sender(config)
    runner = make_runner(config, lcu, sender)

    assert runner.on_end_of_game() is True
    assert len(sent) == 1
    payload = sent[0]
    assert payload["source_game_id"] == "6874231955"
    assert payload["winner_team"] == 100
    assert len(payload["participants"]) == 10
    # ham payload arşivlendi
    assert (config.raw_archive_dir / "6874231955.json").is_file()

    # aynı maç ikinci kez tetiklenmez (gameId dedupe)
    assert runner.on_end_of_game() is False
    assert len(sent) == 1


def test_dedupe_survives_restart(config, eog_custom, champion_summary):
    """raw_archive'de dosyası olan maç, yeni runner'da da tekrar gönderilmez."""
    lcu = FakeLcu(eog=eog_custom, champions=champion_summary)
    sender, sent = capturing_sender(config)
    make_runner(config, lcu, sender).on_end_of_game()
    assert len(sent) == 1

    fresh_runner = make_runner(config, lcu, sender)
    assert fresh_runner.on_end_of_game() is False
    assert len(sent) == 1


def test_played_at_is_game_end_not_processing_time(config, champion_summary):
    """Geç işleme senaryosu: proses gecikmesi/retry yüzünden maç bitiminden saatler
    sonra işlenen bir EOG'de bile played_at maçın GERÇEK bitiş anını taşımalı
    (payload'daki endOfGameTimestamp), yakalama anını değil."""
    eog = load_fixture("eog_custom_real.json")  # endOfGameTimestamp: 2026-08-11T21:43:20.652Z
    lcu = FakeLcu(eog=eog, champions=champion_summary)
    sender, sent = capturing_sender(config)
    much_later = lambda: datetime(2026, 8, 12, 9, 0, 0, tzinfo=timezone.utc)
    runner = LiveRunner(config, lcu, sender, sleep=NO_SLEEP, now=much_later)

    assert runner.on_end_of_game() is True
    assert sent[0]["source_game_id"] == "1734664864"
    assert sent[0]["played_at"] == "2026-08-11T21:43:20Z"


def test_played_at_falls_back_to_now_without_timestamp(config, eog_custom, champion_summary):
    """Alan taşımayan (eski/sentetik) blokta yakalama anı kullanılmaya devam eder."""
    lcu = FakeLcu(eog=eog_custom, champions=champion_summary)
    sender, sent = capturing_sender(config)

    assert make_runner(config, lcu, sender).on_end_of_game() is True
    assert sent[0]["played_at"] == "2026-08-11T20:41:03Z"


def test_non_custom_skipped(config, eog_custom):
    eog_custom["gameType"] = "MATCHED_GAME"
    eog_custom["queueId"] = 420
    lcu = FakeLcu(eog=eog_custom)
    sender, sent = capturing_sender(config)
    runner = make_runner(config, lcu, sender)

    assert runner.on_end_of_game() is False
    assert sent == []
    # yine de arşivlenir ve işlenmiş sayılır
    assert (config.raw_archive_dir / "6874231955.json").is_file()


def test_non_summoners_rift_custom_skipped(config, eog_custom):
    """Custom ARAM (gameMode != CLASSIC) custom-olmayanlar gibi sessizce atlanır
    (Teoman, 2026-08-13): gönderilmez ama arşivlenip işlenmiş sayılır."""
    eog_custom["gameMode"] = "ARAM"
    lcu = FakeLcu(eog=eog_custom)
    sender, sent = capturing_sender(config)
    runner = make_runner(config, lcu, sender)

    assert runner.on_end_of_game() is False
    assert sent == []
    assert (config.raw_archive_dir / "6874231955.json").is_file()
    # ikinci tetikte de gönderilmez (dedupe)
    assert make_runner(config, lcu, sender).on_end_of_game() is False
    assert sent == []


def test_eog_without_game_mode_is_still_processed(config, eog_custom, champion_summary):
    """Eski şema toleransı: `gameMode` alanı hiç yoksa maç ATLANMAZ."""
    eog_custom.pop("gameMode")
    lcu = FakeLcu(eog=eog_custom, champions=champion_summary)
    sender, sent = capturing_sender(config)

    assert make_runner(config, lcu, sender).on_end_of_game() is True
    assert [p["source_game_id"] for p in sent] == ["6874231955"]


def test_fallback_to_match_history(config, mh_game_custom, champion_summary):
    """EOG bloğu boş dönerse gameflow session'daki gameId ile match history'den alınır."""
    lcu = FakeLcu(
        eog={},
        session={"gameData": {"gameId": 6874231001}},
        games={6874231001: mh_game_custom},
        champions=champion_summary,
    )
    sender, sent = capturing_sender(config)
    runner = make_runner(config, lcu, sender)

    assert runner.on_end_of_game() is True
    assert sent[0]["source_game_id"] == "6874231001"
    assert sent[0]["winner_team"] == 200


def test_fallback_skips_non_summoners_rift(config, mh_game_custom, champion_summary):
    """EOG fallback yolu (match-history kaydı) da SR filtresini uygular."""
    mh_game_custom["gameMode"] = "URF"
    mh_game_custom["mapId"] = 11  # mod SR olmasa da mapId 11 gelebilir: mod kazanır
    lcu = FakeLcu(
        eog={},
        session={"gameData": {"gameId": 6874231001}},
        games={6874231001: mh_game_custom},
        champions=champion_summary,
    )
    sender, sent = capturing_sender(config)

    assert make_runner(config, lcu, sender).on_end_of_game() is False
    assert sent == []
    assert (config.raw_archive_dir / "6874231001.json").is_file()


def test_fallback_skips_non_sr_map_id(config, mh_game_custom, champion_summary):
    """Kemer-askı: gameMode CLASSIC ama mapId 11 değilse (ör. Twisted Treeline) atlanır."""
    mh_game_custom["mapId"] = 12
    lcu = FakeLcu(
        eog={},
        session={"gameData": {"gameId": 6874231001}},
        games={6874231001: mh_game_custom},
        champions=champion_summary,
    )
    sender, sent = capturing_sender(config)

    assert make_runner(config, lcu, sender).on_end_of_game() is False
    assert sent == []


def test_fallback_processes_summoners_rift_with_map_id(
    config, mh_game_custom, champion_summary
):
    mh_game_custom["mapId"] = 11
    lcu = FakeLcu(
        eog={},
        session={"gameData": {"gameId": 6874231001}},
        games={6874231001: mh_game_custom},
        champions=champion_summary,
    )
    sender, sent = capturing_sender(config)

    assert make_runner(config, lcu, sender).on_end_of_game() is True
    assert [p["source_game_id"] for p in sent] == ["6874231001"]


def test_send_failure_goes_to_outbox(config, eog_custom, champion_summary):
    lcu = FakeLcu(eog=eog_custom, champions=champion_summary)
    sender, _ = capturing_sender(config, status=500)
    runner = make_runner(config, lcu, sender)

    runner.on_end_of_game()
    assert (config.outbox_dir / "6874231955.json").is_file()


def test_poll_forever_triggers_on_phase_edge(config, eog_custom, champion_summary):
    """EndOfGame'e geçişte tek tetik; fazda kalınca tekrar tetiklenmez."""
    lcu = FakeLcu(
        phases=["Lobby", "InProgress", "EndOfGame", "EndOfGame", "None"],
        eog=eog_custom,
        champions=champion_summary,
    )
    sender, sent = capturing_sender(config)
    runner = make_runner(config, lcu, sender)

    try:
        runner.poll_forever()
    except KeyboardInterrupt:
        pass  # FakeLcu fazlar bitince döngüyü kırar
    assert len(sent) == 1
