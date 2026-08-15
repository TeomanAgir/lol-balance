"""`python -m collector backfill-items` testleri (GÖREV 14).

`backfill-positions`'ın birebir deseni: kaynak `raw_archive/`, hedef backend,
LCU yok. Backend HTTP mock'lanır (httpx.MockTransport); doğrulanan şey doğru
endpoint'e doğru gövdeyle istek atıldığı ve `--dry-run`'da atılmadığıdır.
"""

from __future__ import annotations

import copy
import json

import httpx
import pytest

from collector.backfill_items import run_items_backfill
from collector.normalizer import MAX_ITEMS

from .conftest import load_fixture
from .test_backfill_positions import raw_match, write_archive

REAL_EOG_GAME_ID = "1734664864"
REAL_MH_GAME_ID = "1734450310"


def backend(matches, players, put_status=200, calls=None):
    """matches: [{id, source_game_id, participants:[{player_id}]}], players: {puuid: id}"""
    calls = calls if calls is not None else []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        path = request.url.path
        if request.method == "GET" and path == "/api/v1/matches":
            return httpx.Response(200, json=matches)
        if request.method == "GET" and path == "/api/v1/players":
            return httpx.Response(
                200, json=[{"id": pid, "puuid": puuid} for puuid, pid in players.items()]
            )
        if request.method == "PUT" and path.endswith("/items"):
            if put_status >= 400:
                return httpx.Response(put_status, json={"detail": "geçersiz eşya listesi"})
            return httpx.Response(put_status, json={"updated": 10})
        return httpx.Response(404, json={"detail": f"beklenmeyen istek: {path}"})

    return httpx.MockTransport(handler), calls


def put_requests(calls):
    return [c for c in calls if c.method == "PUT"]


def eog_players(raw):
    return [p for team in raw["teams"] for p in team["players"]]


def nonzero(values):
    return [int(v) for v in values if int(v) > 0]


def backend_for(puuids, game_id, match_id=42, **kwargs):
    """Verilen puuid'leri 1..N player_id'leriyle tanıyan backend + tek maç."""
    players = {puuid: index for index, puuid in enumerate(puuids, start=1)}
    matches = [{
        "id": match_id, "source_game_id": str(game_id), "status": "valid",
        "participants": [{"player_id": pid} for pid in players.values()],
    }]
    transport, calls = backend(matches, players, **kwargs)
    return transport, calls, players


def mh_archive(game_id=REAL_MH_GAME_ID, slots=None):
    """`item0..item6` slotları enjekte edilmiş sentetik match-history arşivi."""
    raw = raw_match(game_id=game_id)
    for offset, participant in enumerate(raw["participants"]):
        values = slots if slots is not None else [3031 + offset, 0, 0, 0, 0, 0, 3340]
        participant["stats"] = {f"item{index}": values[index] for index in range(MAX_ITEMS)}
    return raw


# --------------------------------------------------------------------------- #
# 1. Gerçek arşiv formatları
# --------------------------------------------------------------------------- #


def test_sends_items_from_real_eog_archive(config):
    """Canlı EOG arşivi (teams[].players[].items) → 10 envanter gönderilir."""
    raw = load_fixture("eog_custom_real.json")
    write_archive(config, raw)
    transport, calls, players = backend_for(
        [p["puuid"] for p in eog_players(raw)], REAL_EOG_GAME_ID
    )

    stats = run_items_backfill(config, transport=transport)

    puts = put_requests(calls)
    assert len(puts) == 1
    assert puts[0].url.path == "/api/v1/matches/42/items"
    assert puts[0].headers["X-API-Key"] == "test-key"
    body = json.loads(puts[0].content)
    assert set(body) == {"items"}
    assert all(isinstance(k, str) for k in body["items"])  # api_contract §3
    assert body["items"] == {
        str(players[p["puuid"]]): nonzero(p["items"]) for p in eog_players(raw)
    }
    assert stats.matched == 1 and stats.updated == 1 and stats.participants_sent == 10
    assert stats.without_items == 0 and stats.unknown_players == 0
    assert stats.errors == [] and stats.unmatched_matches == []


def test_sends_items_from_real_match_history_archive(config):
    """Backfill arşivi (participants[].stats.item0..6) → 10 envanter gönderilir."""
    raw = load_fixture("mh_game_custom_real.json")
    write_archive(config, raw)
    identities = {
        identity["participantId"]: identity["player"]["puuid"]
        for identity in raw["participantIdentities"]
    }
    transport, calls, players = backend_for(identities.values(), REAL_MH_GAME_ID)

    stats = run_items_backfill(config, transport=transport)

    body = json.loads(put_requests(calls)[0].content)
    assert body["items"] == {
        str(players[identities[p["participantId"]]]): nonzero(
            [p["stats"][f"item{index}"] for index in range(MAX_ITEMS)]
        )
        for p in raw["participants"]
    }
    assert stats.participants_sent == 10 and stats.errors == []


def test_empty_slots_are_dropped_not_sent_as_zero(config):
    """Ham veride boş slot `0`'dır; gövdeye asla girmez (ingest_contract "items")."""
    raw = load_fixture("eog_custom_real.json")
    write_archive(config, raw)
    transport, calls, _ = backend_for([p["puuid"] for p in eog_players(raw)], REAL_EOG_GAME_ID)

    run_items_backfill(config, transport=transport)

    body = json.loads(put_requests(calls)[0].content)
    assert any(0 in p["items"] for p in eog_players(raw))  # kaynakta boş slot VAR
    for inventory in body["items"].values():
        assert 0 < len(inventory) <= MAX_ITEMS
        assert all(item_id > 0 for item_id in inventory)


# --------------------------------------------------------------------------- #
# 2. Eksik / boş eşya bilgisi
# --------------------------------------------------------------------------- #


def test_archive_without_item_data_sends_nothing(config):
    """Eşya bilgisi olmayan arşiv (eski maçlar) → PUT yok, uyarı + sayaç."""
    write_archive(config, raw_match(game_id=REAL_MH_GAME_ID))
    transport, calls, _ = backend_for([f"p-{pid}" for pid in range(1, 11)], REAL_MH_GAME_ID)

    stats = run_items_backfill(config, transport=transport)

    assert put_requests(calls) == []
    assert stats.matched == 1 and stats.updated == 0
    assert stats.without_items == 10 and stats.errors == []


def test_participants_without_item_data_are_skipped_rest_sent(config):
    """Kısmi güncelleme: bilgisi olmayan katılımcı gövdeye girmez (üzerine yazılmaz)."""
    raw = mh_archive()
    for participant in raw["participants"][:4]:
        participant.pop("stats")
    write_archive(config, raw)
    transport, calls, _ = backend_for([f"p-{pid}" for pid in range(1, 11)], REAL_MH_GAME_ID)

    stats = run_items_backfill(config, transport=transport)

    body = json.loads(put_requests(calls)[0].content)
    assert set(body["items"]) == {"5", "6", "7", "8", "9", "10"}
    assert stats.without_items == 4 and stats.participants_sent == 6


def test_empty_inventory_is_sent_as_empty_list(config):
    """Tüm slotları boş katılımcı `[]` ile gider — "bilgi var, envanter boş"."""
    raw = mh_archive(slots=[0] * MAX_ITEMS)
    write_archive(config, raw)
    transport, calls, _ = backend_for([f"p-{pid}" for pid in range(1, 11)], REAL_MH_GAME_ID)

    stats = run_items_backfill(config, transport=transport)

    body = json.loads(put_requests(calls)[0].content)
    assert body["items"] == {str(pid): [] for pid in range(1, 11)}
    assert stats.without_items == 0 and stats.participants_sent == 10


# --------------------------------------------------------------------------- #
# 3. dry-run + eşleşme / hata yolları
# --------------------------------------------------------------------------- #


def test_dry_run_sends_nothing(config):
    write_archive(config, mh_archive())
    transport, calls, _ = backend_for([f"p-{pid}" for pid in range(1, 11)], REAL_MH_GAME_ID)

    stats = run_items_backfill(config, transport=transport, dry_run=True)

    assert put_requests(calls) == []
    assert stats.updated == 1 and stats.participants_sent == 10  # ne gönderileceği raporlanır


def test_unmatched_archive_is_warned_and_skipped(config):
    write_archive(config, mh_archive(game_id=999))
    transport, calls, _ = backend_for([f"p-{pid}" for pid in range(1, 11)], REAL_MH_GAME_ID)

    stats = run_items_backfill(config, transport=transport)

    assert put_requests(calls) == []
    assert stats.unmatched_matches == ["999"]
    assert stats.matched == 0 and stats.errors == []


def test_partially_matching_archives_continue(config):
    """Bir arşiv backend'de var, biri yok → eşleşen gönderilir, diğeri atlanır."""
    write_archive(config, mh_archive(game_id=REAL_MH_GAME_ID))
    write_archive(config, mh_archive(game_id=999))
    transport, calls, _ = backend_for([f"p-{pid}" for pid in range(1, 11)], REAL_MH_GAME_ID)

    stats = run_items_backfill(config, transport=transport)

    assert len(put_requests(calls)) == 1
    assert stats.archives == 2 and stats.matched == 1 and stats.updated == 1
    assert stats.unmatched_matches == ["999"] and stats.errors == []


def test_unknown_player_is_skipped_but_rest_sent(config):
    write_archive(config, mh_archive())
    matches = [{
        "id": 42, "source_game_id": REAL_MH_GAME_ID, "status": "valid",
        "participants": [{"player_id": pid} for pid in range(1, 11)],
    }]
    players = {f"p-{pid}": pid for pid in range(2, 11)}  # p-1 backend'de yok
    transport, calls = backend(matches, players)

    stats = run_items_backfill(config, transport=transport)

    body = json.loads(put_requests(calls)[0].content)
    assert "1" not in body["items"] and len(body["items"]) == 9
    assert stats.unknown_players == 1 and stats.errors == []


def test_player_not_in_that_match_is_skipped(config):
    write_archive(config, mh_archive())
    matches = [{
        "id": 42, "source_game_id": REAL_MH_GAME_ID, "status": "valid",
        "participants": [{"player_id": pid} for pid in range(1, 10)],  # 10 eksik
    }]
    players = {f"p-{pid}": pid for pid in range(1, 11)}
    transport, calls = backend(matches, players)

    stats = run_items_backfill(config, transport=transport)

    assert "10" not in json.loads(put_requests(calls)[0].content)["items"]
    assert stats.unknown_players == 1


def test_backend_rejection_is_recorded_and_scan_continues(config):
    write_archive(config, mh_archive(game_id=1))
    write_archive(config, mh_archive(game_id=2))
    matches = [
        {"id": 41, "source_game_id": "1", "participants": [{"player_id": p} for p in range(1, 11)]},
        {"id": 42, "source_game_id": "2", "participants": [{"player_id": p} for p in range(1, 11)]},
    ]
    players = {f"p-{pid}": pid for pid in range(1, 11)}
    transport, calls = backend(matches, players, put_status=422)

    stats = run_items_backfill(config, transport=transport)

    assert len(put_requests(calls)) == 2  # ilk hata taramayı durdurmaz
    assert len(stats.errors) == 2 and stats.updated == 0
    assert "422" in stats.errors[0]


def test_empty_archive_does_no_requests(config):
    transport, calls, _ = backend_for([f"p-{pid}" for pid in range(1, 11)], REAL_MH_GAME_ID)
    stats = run_items_backfill(config, transport=transport)
    assert calls == [] and stats.archives == 0


def test_backend_unreachable_is_error_not_crash(config):
    write_archive(config, mh_archive())

    def handler(request):
        raise httpx.ConnectError("bağlanamadı")

    stats = run_items_backfill(config, transport=httpx.MockTransport(handler))

    assert stats.errors and stats.updated == 0


def test_corrupt_archive_file_is_skipped(config):
    write_archive(config, mh_archive())
    config.raw_archive_dir.joinpath("bozuk.json").write_text("{ değil json", encoding="utf-8")
    transport, calls, _ = backend_for([f"p-{pid}" for pid in range(1, 11)], REAL_MH_GAME_ID)

    stats = run_items_backfill(config, transport=transport)

    assert stats.archives == 1 and len(put_requests(calls)) == 1


def test_match_list_limit_capped_at_200(config):
    """api_contract §3: limit üst sınırı 200; aşarsak backend 422 döner."""
    write_archive(config, mh_archive())
    transport, calls, _ = backend_for([f"p-{pid}" for pid in range(1, 11)], REAL_MH_GAME_ID)

    run_items_backfill(config, transport=transport, limit=10_000)

    get_matches = next(c for c in calls if c.method == "GET" and c.url.path == "/api/v1/matches")
    assert get_matches.url.params["limit"] == "200"


def test_rerun_is_idempotent(config):
    """Ham arşiv otoritedir: aynı komut ikinci kez aynı gövdeyi yazar."""
    write_archive(config, mh_archive())
    puuids = [f"p-{pid}" for pid in range(1, 11)]
    bodies = []
    for _ in range(2):
        transport, calls, _ = backend_for(puuids, REAL_MH_GAME_ID)
        run_items_backfill(config, transport=transport)
        bodies.append(json.loads(put_requests(calls)[0].content))
    assert bodies[0] == bodies[1]


def test_positions_endpoint_is_never_called(config):
    """Eşya backfill'i rolleri (ve dolayısıyla rol evreni replay'ini) tetiklemez."""
    write_archive(config, mh_archive())
    transport, calls, _ = backend_for([f"p-{pid}" for pid in range(1, 11)], REAL_MH_GAME_ID)

    run_items_backfill(config, transport=transport)

    assert all(not c.url.path.endswith("/positions") for c in calls)


# --------------------------------------------------------------------------- #
# 4. CLI
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("dry_run", [True, False])
def test_cli_wiring(config, monkeypatch, dry_run):
    """`python -m collector backfill-items [--dry-run]` doğru fonksiyonu çağırır."""
    from collector import __main__ as cli

    seen = {}

    def fake_run(cfg, *, dry_run):
        seen["dry_run"] = dry_run
        return type("S", (), {"errors": []})()

    monkeypatch.setattr(cli, "load_config", lambda: config)
    monkeypatch.setattr(cli, "run_items_backfill", fake_run)
    monkeypatch.setattr(cli, "_ensure_env", lambda force_setup=False: None)
    monkeypatch.setattr(cli, "report_backend_check", lambda url, key: None)

    argv = ["backfill-items"] + (["--dry-run"] if dry_run else [])
    assert cli.main(argv) == 0
    assert seen["dry_run"] is dry_run


def test_cli_reports_errors_with_exit_code_1(config, monkeypatch):
    from collector import __main__ as cli

    monkeypatch.setattr(cli, "load_config", lambda: config)
    monkeypatch.setattr(cli, "_ensure_env", lambda force_setup=False: None)
    monkeypatch.setattr(cli, "report_backend_check", lambda url, key: None)
    monkeypatch.setattr(
        cli, "run_items_backfill",
        lambda cfg, *, dry_run: type("S", (), {"errors": ["boom"]})(),
    )

    assert cli.main(["backfill-items"]) == 1


def test_cli_banner_shows_item_backfill_mode(config, monkeypatch, capsys):
    """Mod etiketi i18n'den gelir (tr varsayılan) ve dry-run eki korunur."""
    from collector import __main__ as cli

    monkeypatch.setattr(cli, "load_config", lambda: config)
    monkeypatch.setattr(cli, "_ensure_env", lambda force_setup=False: None)
    monkeypatch.setattr(cli, "report_backend_check", lambda url, key: None)
    monkeypatch.setattr(
        cli, "run_items_backfill", lambda cfg, *, dry_run: type("S", (), {"errors": []})()
    )

    cli.main(["backfill-items", "--dry-run"])

    assert "eşya backfill (dry-run)" in capsys.readouterr().out


def test_backfill_items_does_not_disturb_positional_backfill_alias(config, monkeypatch):
    """`backfill` pozisyonel komutu eşya moduna kaymaz (regresyon)."""
    from collector import __main__ as cli
    from collector import commands

    called = {}
    monkeypatch.setattr(cli, "load_config", lambda: config)
    monkeypatch.setattr(cli, "_ensure_env", lambda force_setup=False: None)
    monkeypatch.setattr(cli, "report_backend_check", lambda url, key: None)
    monkeypatch.setattr(
        cli, "run_items_backfill",
        lambda cfg, *, dry_run: called.setdefault("items", True),
    )
    monkeypatch.setattr(commands, "read_lockfile", lambda lol_dir: (_ for _ in ()).throw(
        cli.LockfileNotFound("yok")
    ))

    assert cli.main(["backfill"]) == 1  # lockfile yok → 1, ama items yolu çalışmadı
    assert "items" not in called


def test_unknown_command_is_rejected(config):
    from collector import __main__ as cli

    with pytest.raises(SystemExit):
        cli.main(["backfill-esya"])


def test_archive_copy_is_not_modified(config):
    """Backfill ham arşivi OKUR, asla değiştirmez (ingest immutable)."""
    raw = mh_archive()
    path = write_archive(config, raw)
    before = path.read_text(encoding="utf-8")
    transport, _, _ = backend_for([f"p-{pid}" for pid in range(1, 11)], REAL_MH_GAME_ID)

    run_items_backfill(config, transport=transport)

    assert path.read_text(encoding="utf-8") == before
    assert json.loads(before) == json.loads(json.dumps(copy.deepcopy(raw)))
