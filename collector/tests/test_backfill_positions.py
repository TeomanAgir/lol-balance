"""`python -m collector backfill-positions` testleri (GÖREV 0).

Backend HTTP mock'lanır (httpx.MockTransport); doğrulanan şey: doğru
endpoint'lere doğru gövdelerle istek atıldığı ve `--dry-run`'da atılmadığı.
"""

from __future__ import annotations

import json

import httpx
import pytest

from collector.backfill_positions import run_position_backfill

from .conftest import load_fixture

# Riot'un custom'da tipik etiketleri: TOP etiketi yok, ormancı Smite ile bulunur
LANES = [
    ("JUNGLE", "NONE"), ("JUNGLE", "NONE"), ("MIDDLE", "SOLO"),
    ("BOTTOM", "CARRY"), ("BOTTOM", "SUPPORT"),
]
EXPECTED_ROLES = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]


def raw_match(game_id=1734450310, puuid_prefix="p"):
    """10 kişilik ham match-history kaydı: her takım tam çözülür."""
    participants, identities = [], []
    for pid in range(1, 11):
        index = (pid - 1) % 5
        lane, role = LANES[index]
        participants.append({
            "participantId": pid,
            "teamId": 100 if pid <= 5 else 200,
            "spell1Id": 11 if index == 1 else 4,
            "spell2Id": 14,
            "timeline": {"lane": lane, "role": role},
        })
        identities.append({"participantId": pid, "player": {"puuid": f"{puuid_prefix}-{pid}"}})
    return {"gameId": game_id, "participants": participants,
            "participantIdentities": identities}


def write_archive(config, raw):
    config.raw_archive_dir.mkdir(parents=True, exist_ok=True)
    path = config.raw_archive_dir / f"{raw['gameId']}.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


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
        if request.method == "PUT" and path.endswith("/positions"):
            if put_status >= 400:
                return httpx.Response(put_status, json={"detail": "geçersiz rol"})
            return httpx.Response(put_status, json={"updated": 5, "role_matches_replayed": 1})
        return httpx.Response(404, json={"detail": f"beklenmeyen istek: {path}"})

    return httpx.MockTransport(handler), calls


def default_backend(game_id=1734450310, **kwargs):
    matches = [{
        "id": 42, "source_game_id": str(game_id), "status": "valid",
        "participants": [{"player_id": pid} for pid in range(1, 11)],
    }]
    players = {f"p-{pid}": pid for pid in range(1, 11)}
    return backend(matches, players, **kwargs)


def put_requests(calls):
    return [c for c in calls if c.method == "PUT"]


def test_sends_inferred_positions(config):
    write_archive(config, raw_match())
    transport, calls = default_backend()

    stats = run_position_backfill(config, transport=transport)

    puts = put_requests(calls)
    assert len(puts) == 1
    assert puts[0].url.path == "/api/v1/matches/42/positions"
    assert puts[0].headers["X-API-Key"] == "test-key"
    body = json.loads(puts[0].content)
    assert set(body) == {"positions"}
    # player_id anahtarları STRING olmalı (api_contract §3)
    assert all(isinstance(k, str) for k in body["positions"])
    assert body["positions"] == {
        str(pid): EXPECTED_ROLES[(pid - 1) % 5] for pid in range(1, 11)
    }
    assert stats.matched == 1 and stats.updated == 1 and stats.positions_sent == 10
    assert stats.errors == [] and stats.unmatched_matches == []


def eog_players(raw):
    """EOG arşivindeki 10 oyuncu (takım sırasıyla)."""
    return [p for team in raw["teams"] for p in team["players"]]


def test_eog_archive_uses_explicit_selected_position(config):
    """Canlı EOG arşivi (teams[].players[]) açık `selectedPosition` taşır →
    10/10 rol gönderilir. Tahmin zinciri tek başına burada yalnızca Smite'çıyı
    (takım başına 1 JUNGLE) çözebilirdi; açık alan kazanır."""
    raw = load_fixture("eog_custom_real.json")  # gameId 1734664864
    write_archive(config, raw)
    players = {p["puuid"]: pid for pid, p in enumerate(eog_players(raw), start=1)}
    matches = [{
        "id": 42, "source_game_id": "1734664864", "status": "valid",
        "participants": [{"player_id": pid} for pid in players.values()],
    }]
    transport, calls = backend(matches, players)

    stats = run_position_backfill(config, transport=transport)

    body = json.loads(put_requests(calls)[0].content)
    assert body["positions"] == {
        str(players[p["puuid"]]): p["selectedPosition"] for p in eog_players(raw)
    }
    assert len(body["positions"]) == 10
    assert stats.matched == 1 and stats.updated == 1 and stats.positions_sent == 10
    assert stats.unresolved == 0 and stats.unknown_players == 0 and stats.errors == []
    # her takımda 5 farklı rol
    for team_slice in (slice(0, 5), slice(5, 10)):
        sent_roles = [body["positions"][str(players[p["puuid"]])]
                      for p in eog_players(raw)[team_slice]]
        assert sorted(sent_roles) == ["BOTTOM", "JUNGLE", "MIDDLE", "TOP", "UTILITY"]


def test_eog_archive_uses_detected_position_when_selected_is_empty(config):
    """2026-08-13 vakası (gameId 1734940206) backfill yolunda: arşivlenmiş EOG'de
    `selectedPosition` 10/10 boş string ama `detectedTeamPosition` 10/10 dolu →
    aynı öncelik burada da geçerli, tespit edilen 10 rol gönderilir (zincir tek
    başına yalnız 2 JUNGLE çözebilirdi)."""
    raw = load_fixture("eog_custom_detected.json")
    assert all(p["selectedPosition"] == "" for p in eog_players(raw))
    write_archive(config, raw)
    players = {p["puuid"]: pid for pid, p in enumerate(eog_players(raw), start=1)}
    matches = [{
        "id": 77, "source_game_id": "1734940206", "status": "valid",
        "participants": [{"player_id": pid} for pid in players.values()],
    }]
    transport, calls = backend(matches, players)

    stats = run_position_backfill(config, transport=transport)

    body = json.loads(put_requests(calls)[0].content)
    assert body["positions"] == {
        str(players[p["puuid"]]): p["detectedTeamPosition"] for p in eog_players(raw)
    }
    assert len(body["positions"]) == 10
    assert stats.matched == 1 and stats.updated == 1 and stats.positions_sent == 10
    assert stats.unresolved == 0 and stats.unknown_players == 0 and stats.errors == []
    for team_slice in (slice(0, 5), slice(5, 10)):
        sent_roles = [body["positions"][str(players[p["puuid"]])]
                      for p in eog_players(raw)[team_slice]]
        assert sorted(sent_roles) == ["BOTTOM", "JUNGLE", "MIDDLE", "TOP", "UTILITY"]


def test_eog_archive_explicit_position_still_beats_detected(config):
    """Regresyon: dolu `selectedPosition` taşıyan eski arşiv EOG'unda (gameId
    1734664864) davranış DEĞİŞMEDİ — çelişen bir tespit değeri eklense bile
    gönderilen roller açık alandan gelir (1. katman > 2. katman)."""
    raw = load_fixture("eog_custom_real.json")
    for p in eog_players(raw):
        p["detectedTeamPosition"] = "TOP" if p["selectedPosition"] != "TOP" else "MIDDLE"
    write_archive(config, raw)
    players = {p["puuid"]: pid for pid, p in enumerate(eog_players(raw), start=1)}
    matches = [{
        "id": 42, "source_game_id": "1734664864", "status": "valid",
        "participants": [{"player_id": pid} for pid in players.values()],
    }]
    transport, calls = backend(matches, players)

    run_position_backfill(config, transport=transport)

    body = json.loads(put_requests(calls)[0].content)
    assert body["positions"] == {
        str(players[p["puuid"]]): p["selectedPosition"] for p in eog_players(raw)
    }


def test_eog_archive_without_explicit_position_falls_back_to_inference(config):
    """Açık alan VE Riot tespiti boş/geçersizse (eski LCU sürümü) zincir devreye
    girer: EOG'de lane/role olmadığından yalnızca Smite taşıyanlar JUNGLE olarak
    gider. (2026-08-13'ten beri tespit alanı 2. katmandır; zincirin koşması için
    onun da boşaltılması gerekir — gerçek fixture'da ikisi de dolu.)"""
    raw = load_fixture("eog_custom_real.json")
    for p in eog_players(raw):
        p["selectedPosition"] = "NONE"
        p["detectedTeamPosition"] = "NONE"
    write_archive(config, raw)
    players = {p["puuid"]: pid for pid, p in enumerate(eog_players(raw), start=1)}
    matches = [{
        "id": 42, "source_game_id": "1734664864", "status": "valid",
        "participants": [{"player_id": pid} for pid in players.values()],
    }]
    transport, calls = backend(matches, players)

    stats = run_position_backfill(config, transport=transport)

    body = json.loads(put_requests(calls)[0].content)
    assert set(body["positions"].values()) == {"JUNGLE"}
    assert len(body["positions"]) == 2  # takım başına 1 Smite taşıyıcı
    assert stats.unresolved == 8


def test_dry_run_sends_nothing(config):
    write_archive(config, raw_match())
    transport, calls = default_backend()

    stats = run_position_backfill(config, transport=transport, dry_run=True)

    assert put_requests(calls) == []
    assert stats.updated == 1 and stats.positions_sent == 10  # ne gönderileceği raporlanır


def test_null_positions_are_not_sent(config):
    """Belirsiz kalan roller gövdeye girmez (kısmi güncelleme)."""
    raw = raw_match()
    for p in raw["participants"][:5]:
        p["spell1Id"] = 11  # takım 100'de 5 Smite → JUNGLE belirsiz, zincir çöker
        p["timeline"] = {"lane": "NONE", "role": "NONE"}
    write_archive(config, raw)
    transport, calls = default_backend()

    stats = run_position_backfill(config, transport=transport)

    body = json.loads(put_requests(calls)[0].content)
    assert set(body["positions"]) == {"6", "7", "8", "9", "10"}  # yalnız takım 200
    assert stats.unresolved == 5


def test_unmatched_match_is_warned_and_skipped(config):
    write_archive(config, raw_match(game_id=999))
    transport, calls = default_backend(game_id=1734450310)

    stats = run_position_backfill(config, transport=transport)

    assert put_requests(calls) == []
    assert stats.unmatched_matches == ["999"]
    assert stats.matched == 0 and stats.errors == []


def test_unknown_player_is_skipped_but_rest_sent(config):
    write_archive(config, raw_match())
    matches = [{
        "id": 42, "source_game_id": "1734450310", "status": "valid",
        "participants": [{"player_id": pid} for pid in range(1, 11)],
    }]
    players = {f"p-{pid}": pid for pid in range(2, 11)}  # p-1 backend'de yok
    transport, calls = backend(matches, players)

    stats = run_position_backfill(config, transport=transport)

    body = json.loads(put_requests(calls)[0].content)
    assert "1" not in body["positions"]
    assert len(body["positions"]) == 9
    assert stats.unknown_players == 1 and stats.errors == []


def test_player_not_in_that_match_is_skipped(config):
    """Backend'de var ama bu maçın katılımcısı değilse gönderilmez (422 yerine uyarı)."""
    write_archive(config, raw_match())
    matches = [{
        "id": 42, "source_game_id": "1734450310", "status": "valid",
        "participants": [{"player_id": pid} for pid in range(1, 10)],  # 10 eksik
    }]
    players = {f"p-{pid}": pid for pid in range(1, 11)}
    transport, calls = backend(matches, players)

    stats = run_position_backfill(config, transport=transport)

    assert "10" not in json.loads(put_requests(calls)[0].content)["positions"]
    assert stats.unknown_players == 1


def test_backend_rejection_is_recorded_and_scan_continues(config):
    write_archive(config, raw_match(game_id=1))
    write_archive(config, raw_match(game_id=2))
    matches = [
        {"id": 41, "source_game_id": "1", "participants": [{"player_id": p} for p in range(1, 11)]},
        {"id": 42, "source_game_id": "2", "participants": [{"player_id": p} for p in range(1, 11)]},
    ]
    players = {f"p-{pid}": pid for pid in range(1, 11)}
    transport, calls = backend(matches, players, put_status=422)

    stats = run_position_backfill(config, transport=transport)

    assert len(put_requests(calls)) == 2  # ilk hata taramayı durdurmaz
    assert len(stats.errors) == 2 and stats.updated == 0
    assert "422" in stats.errors[0]


def test_empty_archive_does_no_requests(config):
    transport, calls = default_backend()
    stats = run_position_backfill(config, transport=transport)
    assert calls == [] and stats.archives == 0


def test_backend_unreachable_is_error_not_crash(config):
    write_archive(config, raw_match())

    def handler(request):
        raise httpx.ConnectError("bağlanamadı")

    stats = run_position_backfill(config, transport=httpx.MockTransport(handler))

    assert stats.errors and stats.updated == 0


def test_corrupt_archive_file_is_skipped(config):
    write_archive(config, raw_match())
    config.raw_archive_dir.joinpath("bozuk.json").write_text("{ değil json", encoding="utf-8")
    transport, calls = default_backend()

    stats = run_position_backfill(config, transport=transport)

    assert stats.archives == 1 and len(put_requests(calls)) == 1


def test_match_list_limit_capped_at_200(config):
    """api_contract §3: limit üst sınırı 200; aşarsak backend 422 döner."""
    write_archive(config, raw_match())
    transport, calls = default_backend()

    run_position_backfill(config, transport=transport, limit=10_000)

    get_matches = next(c for c in calls if c.method == "GET" and c.url.path == "/api/v1/matches")
    assert get_matches.url.params["limit"] == "200"


@pytest.mark.parametrize("dry_run", [True, False])
def test_cli_wiring(config, monkeypatch, dry_run):
    """`python -m collector backfill-positions [--dry-run]` doğru fonksiyonu çağırır."""
    from collector import __main__ as cli

    seen = {}

    def fake_run(cfg, *, dry_run):
        seen["dry_run"] = dry_run
        return type("S", (), {"errors": []})()

    monkeypatch.setattr(cli, "load_config", lambda: config)
    monkeypatch.setattr(cli, "run_position_backfill", fake_run)
    # GÖREV 5: CLI artık .env kontrolü + backend ön-doğrulaması yapıyor; testte ikisi de devre dışı
    monkeypatch.setattr(cli, "_ensure_env", lambda force_setup=False: None)
    monkeypatch.setattr(cli, "report_backend_check", lambda url, key: None)

    argv = ["backfill-positions"] + (["--dry-run"] if dry_run else [])
    assert cli.main(argv) == 0
    assert seen["dry_run"] is dry_run
