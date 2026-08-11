import json

import httpx

from collector.roster import (
    KnownRoster,
    build_known_roster,
    fetch_backend_roster,
    load_seed_roster,
)


def test_count_known_by_riot_id_case_insensitive():
    roster = KnownRoster(riot_ids={"teoman#tr1", "kaan#tr1"})
    entries = [
        (None, "TEOMAN#TR1"),
        (None, "Kaan#tr1"),
        (None, "Yabanci#EUW"),
        (None, None),
    ]
    assert roster.count_known(entries) == 2


def test_count_known_by_puuid():
    roster = KnownRoster(puuids={"puuid-1"})
    assert roster.count_known([("puuid-1", None), ("puuid-2", None)]) == 1


def test_load_seed_roster(tmp_path):
    path = tmp_path / "seed.json"
    path.write_text(json.dumps(["Teoman#TR1", "  Kaan#TR1  ", ""]), encoding="utf-8")
    assert load_seed_roster(path) == {"teoman#tr1", "kaan#tr1"}


def test_load_seed_roster_missing_file(tmp_path):
    assert load_seed_roster(tmp_path / "yok.json") == set()


def test_fetch_backend_roster(config):
    players = [
        {"id": 1, "riot_id": "Teoman#TR1", "display_name": "Teoman"},
        {"id": 2, "riot_id": None, "display_name": "Misafir"},
        {"id": 3, "riot_id": "Kaan#TR1", "puuid": "puuid-k"},  # puuid ileriye dönük
    ]
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=players))
    roster = fetch_backend_roster(config, transport=transport)
    assert roster.riot_ids == {"teoman#tr1", "kaan#tr1"}
    assert roster.puuids == {"puuid-k"}


def test_fetch_backend_roster_backend_down(config):
    def handler(request):
        raise httpx.ConnectError("bağlanamadı")

    roster = fetch_backend_roster(config, transport=httpx.MockTransport(handler))
    assert roster.is_empty()


def test_build_known_roster_union(config):
    config.seed_roster_path.write_text(json.dumps(["Seed#TR1"]), encoding="utf-8")
    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json=[{"id": 1, "riot_id": "Backend#TR1"}])
    )
    roster = build_known_roster(config, transport=transport)
    assert roster.riot_ids == {"seed#tr1", "backend#tr1"}
