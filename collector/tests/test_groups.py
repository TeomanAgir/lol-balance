"""GÖREV 36 — collector çoklu grup (docs/ingest_contract.md "Çoklu grup — collector tarafı").

Kapsam (kabul ölçütleri a-g):
a) tek anahtarlı eski kurulum: groups.json yok → tek profil, düz Sender, davranış aynı
b) otomatik yönlendirme kuralı (tek/çoklu eşleşme, seçili > en çok tanınan > profil sırası)
c) outbox hedefi (grup dizini), hedefsiz eski kayıt → ilk profil, silinmiş profil → yerinde
d) heartbeat her profile; biri hata verse diğeri etkilenmez
e) ilk kurulum taraması: listeleme sıfır gönderim; işaretliler kronolojik, seçili gruba
f) profil kalıcılığı; anahtar hiçbir log satırında/repr'de düz görünmez
g) yeni i18n anahtarları iki dilde

Ağ yok: backend `httpx.MockTransport` (istek başlığındaki anahtara göre grup taklidi).
"""

from __future__ import annotations

import copy
import dataclasses
import json
import logging
from datetime import date, datetime, timezone

import httpx
import pytest

from collector import gui, i18n
from collector.backfill import (
    FIRST_SETUP_MIN_DAYS,
    first_setup_days,
    run_backfill,
    scan_first_setup,
    send_first_setup,
)
from collector.groups import (
    FIRST_PROFILE_ID,
    GroupError,
    GroupRouter,
    choose_group,
    load_groups,
    mask_key,
    needs_router,
    orphan_outbox_counts,
    profile_config,
    profile_outbox_dir,
    save_groups,
)
from collector.live import LiveRunner
from collector.normalizer import normalize_eog
from collector.sender import HEARTBEAT_PATH, INGEST_PATH, Sender

from .fakes import FakeLcu
from .test_backfill import custom_summary, make_remake_game, remake_summary

KEY_A = "test-key"  # conftest config'inin (.env) anahtarı = ilk profil
KEY_B = "group-b-secret-key"
KEY_C = "group-c-secret-key"

GAME_1 = 6874231001  # mh_game_custom: Teoman, Kaan, Mert, Ece, Deniz, Baran, Selin, Arda, Yusuf, Zeynep
FIRST_SIX = ["Teoman#TR1", "Kaan#TR1", "Mert#EUW", "Ece#TR1", "Deniz#TR1", "Baran#TR1"]
LAST_EIGHT = ["Mert#EUW", "Ece#TR1", "Deniz#TR1", "Baran#TR1", "Selin#TR1", "Arda#TR1",
              "Yusuf#TR1", "Zeynep#TR1"]


# --------------------------------------------------------------------------- #
# Yardımcılar
# --------------------------------------------------------------------------- #


class FakeBackend:
    """Anahtar → grup. `GET /players` o grubun roster'ını döner; ingest/heartbeat kaydedilir."""

    def __init__(self, rosters, *, ingest_fail=(), heartbeat_fail=()):
        self.rosters = rosters
        self.ingest_fail = set(ingest_fail)
        self.heartbeat_fail = set(heartbeat_fail)
        self.ingests: list[tuple[str, str]] = []
        self.beats: list[str] = []
        self.requests: list[tuple[str, str, str]] = []
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        key = request.headers.get("X-API-Key", "")
        path = request.url.path
        self.requests.append((request.method, path, key))
        if key not in self.rosters:
            return httpx.Response(401, json={"detail": "bad key"})
        if path == "/api/v1/players":
            return httpx.Response(200, json=[{"riot_id": r} for r in self.rosters[key]])
        if path == HEARTBEAT_PATH:
            if key in self.heartbeat_fail:
                raise httpx.ConnectError("heartbeat down")
            self.beats.append(key)
            return httpx.Response(200, json={"ok": True})
        if path == INGEST_PATH:
            if key in self.ingest_fail:
                return httpx.Response(503, json={"detail": "busy"})
            self.ingests.append((key, json.loads(request.content)["source_game_id"]))
            return httpx.Response(201, json={"match_id": 1, "duplicate": False})
        return httpx.Response(404)

    def sends(self) -> list[tuple[str, str]]:
        return [(key, path) for method, path, key in self.requests if method == "POST"]


def two_groups(config, *, selected=None, third=False):
    """İlk profil (.env anahtarı) + B (+ isteğe bağlı C), kaydedilip yeniden yüklenmiş."""
    settings = load_groups(config)
    b = settings.add("Grup B", KEY_B)
    c = settings.add("Grup C", KEY_C) if third else None
    if selected == "b":
        settings.select(b.id)
    elif selected == "c" and c is not None:
        settings.select(c.id)
    save_groups(config, settings)
    return load_groups(config), b, c


def renamed_game(game, game_id, created, suffix):
    """Aynı maçın farklı oyunculu kopyası (ikinci grubun maçı)."""
    clone = copy.deepcopy(game)
    clone["gameId"] = game_id
    clone["gameCreationDate"] = created
    for identity in clone["participantIdentities"]:
        player = identity["player"]
        player["gameName"] = player["gameName"] + suffix
        player["puuid"] = player["puuid"] + suffix.lower()
    return clone


def names_with(suffix, names):
    return [name.split("#")[0] + suffix + "#" + name.split("#")[1] for name in names]


# --------------------------------------------------------------------------- #
# a) Tek anahtarlı eski kurulum
# --------------------------------------------------------------------------- #


def test_legacy_env_without_groups_file_is_a_single_first_profile(config):
    settings = load_groups(config)
    assert [p.id for p in settings.profiles] == [FIRST_PROFILE_ID]
    assert settings.first.api_key == KEY_A
    assert settings.selected_id == FIRST_PROFILE_ID
    assert settings.is_multi is False
    assert needs_router(config, settings) is False
    assert not config.groups_path.exists()  # okumak dosya YAZMAZ
    assert profile_config(config, settings.first) is config  # ilk profil = config'in kendisi


def test_cli_keeps_the_plain_sender_for_a_single_profile(config):
    from collector import __main__ as cli

    sender = cli._make_sender(config, load_groups(config))
    try:
        assert type(sender) is Sender
    finally:
        sender.close()
    settings, _, _ = two_groups(config)
    router = cli._make_sender(config, settings)
    try:
        assert isinstance(router, GroupRouter)
    finally:
        router.close()


def test_single_profile_router_live_has_no_roster_filter(config, eog_custom):
    """Tek profilde canlı mod filtresizdir (bugünkü davranış): roster bile çekilmez."""
    backend = FakeBackend({KEY_A: []})
    router = GroupRouter(config, transport=backend.transport)
    runner = LiveRunner(config, FakeLcu(eog=eog_custom), router, sleep=lambda s: None)
    assert runner.on_end_of_game() is True
    assert [k for k, _ in backend.ingests] == [KEY_A]
    assert not [r for r in backend.requests if r[1] == "/api/v1/players"]


def test_single_profile_router_backfill_matches_the_plain_sender(
    config, mh_list_page, mh_game_custom, champion_summary
):
    from .test_backfill import make_lcu

    backend = FakeBackend({KEY_A: FIRST_SIX})
    router = GroupRouter(config, transport=backend.transport)
    stats = run_backfill(config, make_lcu(mh_list_page, mh_game_custom, champion_summary), router)
    assert stats.sent == 2 and stats.skipped_roster == 0
    assert backend.ingests == [(KEY_A, "6874230000"), (KEY_A, "6874231001")]  # kronolojik
    assert stats.sent_by_group == {FIRST_PROFILE_ID: 2}


# --------------------------------------------------------------------------- #
# b) Otomatik yönlendirme
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "counts,selected,expected",
    [
        ([("a", 6), ("b", 2)], "a", "a"),  # yalnız A geçer
        ([("a", 2), ("b", 7)], "a", "b"),  # yalnız B geçer (seçili olsa bile A geçmiyor)
        ([("a", 2), ("b", 5)], "a", None),  # hiçbiri geçmez → atla
        ([("a", 6), ("b", 8)], "a", "a"),  # ikisi de geçer, seçili A geçenlerde → A
        ([("a", 6), ("b", 8)], "b", "b"),
        ([("a", 6), ("b", 8), ("c", 0)], "c", "b"),  # seçili geçmiyor → en çok tanınan
        ([("a", 7), ("b", 7), ("c", 0)], "c", "a"),  # eşitlik → profil sırası
        ([("a", 7), ("b", 7), ("c", 0)], None, "a"),
        ([("a", 6), ("b", 9), ("c", 9)], "a", "a"),
        ([("a", 6), ("b", 9), ("c", 9)], "x", "b"),
    ],
)
def test_choose_group_rule(counts, selected, expected):
    assert choose_group(counts, 6, selected) == expected


def _single_game_lcu(mh_game_custom, champion_summary):
    return FakeLcu(
        summoner={"puuid": "puuid-t1"},
        pages=[[custom_summary(GAME_1, gameCreationDate="2026-08-01T19:12:44.000Z")], []],
        games={GAME_1: mh_game_custom},
        champions=champion_summary,
    )


@pytest.mark.parametrize(
    "roster_a,roster_b,selected,expected",
    [
        (FIRST_SIX, FIRST_SIX[:2], None, KEY_A),
        (FIRST_SIX[:2], LAST_EIGHT, None, KEY_B),
        (FIRST_SIX, LAST_EIGHT, None, KEY_A),  # ikisi de geçer, seçili = ilk profil
        (FIRST_SIX, LAST_EIGHT, "b", KEY_B),
        (FIRST_SIX, LAST_EIGHT, "c", KEY_B),  # seçili C geçmiyor → en çok tanınan B (8 > 6)
        (FIRST_SIX[:5], LAST_EIGHT[:5], None, None),  # hiçbiri geçmez
    ],
)
def test_backfill_routes_each_match_to_at_most_one_group(
    config, mh_game_custom, champion_summary, roster_a, roster_b, selected, expected
):
    settings, _, _ = two_groups(config, selected=selected, third=True)
    backend = FakeBackend({KEY_A: roster_a, KEY_B: roster_b, KEY_C: []})
    router = GroupRouter(config, settings, transport=backend.transport)

    stats = run_backfill(config, _single_game_lcu(mh_game_custom, champion_summary), router)

    ingest_keys = [key for key, path in backend.sends() if path == INGEST_PATH]
    if expected is None:
        assert ingest_keys == [] and stats.skipped_roster == 1 and stats.sent == 0
    else:
        assert ingest_keys == [expected]  # tek değerlendirmede EN FAZLA bir grup
        assert stats.sent == 1


def test_backfill_splits_matches_between_groups_chronologically(
    config, mh_game_custom, champion_summary
):
    """Yalnız A'nın roster'ını geçen A'ya, yalnız B'ninkini geçen B'ye; sıra kronolojik."""
    game_b = renamed_game(mh_game_custom, 6874239999, "2026-08-02T10:00:00.000Z", "X")
    old_a = renamed_game(mh_game_custom, 6874230000, "2026-07-01T18:00:00.000Z", "")
    lcu = FakeLcu(
        summoner={"puuid": "puuid-t1"},
        pages=[[
            custom_summary(6874239999, gameCreationDate="2026-08-02T10:00:00.000Z"),
            custom_summary(GAME_1, gameCreationDate="2026-08-01T19:12:44.000Z"),
            custom_summary(6874230000, gameCreationDate="2026-07-01T18:00:00.000Z"),
        ], []],
        games={6874239999: game_b, GAME_1: mh_game_custom, 6874230000: old_a},
        champions=champion_summary,
    )
    settings, b, _ = two_groups(config)
    backend = FakeBackend({KEY_A: FIRST_SIX, KEY_B: names_with("X", LAST_EIGHT)})
    router = GroupRouter(config, settings, transport=backend.transport)

    stats = run_backfill(config, lcu, router)

    assert backend.ingests == [
        (KEY_A, "6874230000"), (KEY_A, str(GAME_1)), (KEY_B, "6874239999")
    ]
    assert stats.sent_by_group == {FIRST_PROFILE_ID: 2, b.id: 1}


def test_seed_roster_counts_only_for_the_first_profile(config, mh_game_custom, champion_summary):
    config.seed_roster_path.write_text(json.dumps(FIRST_SIX), encoding="utf-8")
    settings, _, _ = two_groups(config)
    backend = FakeBackend({KEY_A: [], KEY_B: []})
    router = GroupRouter(config, settings, transport=backend.transport)
    rosters = router.build_rosters()
    assert len(rosters[FIRST_PROFILE_ID].riot_ids) == 6
    assert rosters[settings.profiles[1].id].is_empty()

    run_backfill(config, _single_game_lcu(mh_game_custom, champion_summary), router)
    assert backend.ingests == [(KEY_A, str(GAME_1))]


def test_live_eog_is_routed_with_multiple_profiles(config, eog_custom):
    names = [p.riot_id for p in normalize_eog(eog_custom, datetime.now(timezone.utc)).participants]
    settings, _, _ = two_groups(config)

    backend = FakeBackend({KEY_A: names[:2], KEY_B: names})
    router = GroupRouter(config, settings, transport=backend.transport)
    runner = LiveRunner(config, FakeLcu(eog=eog_custom), router, sleep=lambda s: None)
    assert runner.on_end_of_game() is True
    assert [k for k, _ in backend.ingests] == [KEY_B]


def test_live_eog_known_by_no_group_is_skipped_but_archived(config, eog_custom):
    settings, _, _ = two_groups(config)
    backend = FakeBackend({KEY_A: [], KEY_B: []})
    router = GroupRouter(config, settings, transport=backend.transport)
    matches: list[str] = []
    runner = LiveRunner(
        config, FakeLcu(eog=eog_custom), router, sleep=lambda s: None, on_match=matches.append
    )
    assert runner.on_end_of_game() is False
    assert backend.ingests == [] and matches == []
    assert (config.raw_archive_dir / f"{eog_custom['gameId']}.json").is_file()


def test_live_routing_uses_the_last_known_roster_when_fetch_fails(config, eog_custom):
    names = [p.riot_id for p in normalize_eog(eog_custom, datetime.now(timezone.utc)).participants]
    settings, _, _ = two_groups(config)
    backend = FakeBackend({KEY_A: [], KEY_B: names})
    router = GroupRouter(config, settings, transport=backend.transport)
    router.build_rosters()  # önbellek dolar
    del backend.rosters[KEY_B]  # B'nin roster'ı artık çekilemiyor (401)
    assert router.route_live(normalize_eog(eog_custom, datetime.now(timezone.utc)).model_dump()) \
        == settings.profiles[1].id


# --------------------------------------------------------------------------- #
# c) Outbox
# --------------------------------------------------------------------------- #


def _payload(game_id="777"):
    return {"source": "lcu_eog", "source_game_id": game_id, "played_at": "2026-08-01T00:00:00Z",
            "duration_s": 1500, "winner_team": 100, "participants": []}


def test_outbox_record_retries_only_with_its_own_groups_key(config):
    settings, b, _ = two_groups(config)
    backend = FakeBackend({KEY_A: [], KEY_B: []}, ingest_fail={KEY_B})
    router = GroupRouter(config, settings, transport=backend.transport)

    router.send_or_outbox(_payload("777"), b.id)
    b_dir = profile_outbox_dir(config, b.id)
    assert (b_dir / "777.json").is_file()
    assert not list(config.outbox_dir.glob("*.json"))  # ilk profilin outbox'ına DÜŞMEZ

    backend.ingest_fail.clear()
    backend.requests.clear()
    router.flush_outbox()
    assert backend.ingests == [(KEY_B, "777")]
    assert [k for k, p in backend.sends() if p == INGEST_PATH] == [KEY_B]
    assert not (b_dir / "777.json").exists()


def test_legacy_outbox_record_without_target_goes_to_the_first_profile(config):
    config.outbox_dir.mkdir(parents=True)
    (config.outbox_dir / "555.json").write_text(json.dumps(_payload("555")), encoding="utf-8")
    settings, _, _ = two_groups(config)
    backend = FakeBackend({KEY_A: [], KEY_B: []})
    router = GroupRouter(config, settings, transport=backend.transport)

    router.flush_outbox()
    assert backend.ingests == [(KEY_A, "555")]


def test_deleted_profiles_records_are_kept_unsent_and_warned(config, caplog):
    settings, b, _ = two_groups(config)
    b_dir = profile_outbox_dir(config, b.id)
    b_dir.mkdir(parents=True)
    (b_dir / "888.json").write_text(json.dumps(_payload("888")), encoding="utf-8")
    settings.delete(b.id)
    save_groups(config, settings)
    settings = load_groups(config)
    assert orphan_outbox_counts(config, settings) == {b.id: 1}
    assert needs_router(config, settings) is True  # uyarı için router kullanılır

    backend = FakeBackend({KEY_A: [], KEY_B: []})
    router = GroupRouter(config, settings, transport=backend.transport)
    with caplog.at_level(logging.WARNING, logger="collector.groups"):
        router.flush_outbox()
        router.flush_outbox()
    assert backend.ingests == []  # gönderilmez
    assert (b_dir / "888.json").is_file()  # silinmez
    warnings = [r for r in caplog.records if "deleted group" in r.getMessage()]
    assert len(warnings) == 1  # her grup için bir kez uyarılır (döngüde log seli yok)


# --------------------------------------------------------------------------- #
# d) Heartbeat
# --------------------------------------------------------------------------- #


def test_heartbeat_goes_to_every_profile_and_one_failure_does_not_block(config):
    settings, _, _ = two_groups(config)
    backend = FakeBackend({KEY_A: [], KEY_B: []}, heartbeat_fail={KEY_A})
    router = GroupRouter(config, settings, transport=backend.transport)

    assert router.send_heartbeat("test") is True
    assert backend.beats == [KEY_B]
    hb_keys = [k for k, p in backend.sends() if p == HEARTBEAT_PATH]
    assert hb_keys == [KEY_A, KEY_B]  # ikisine de denendi

    backend.heartbeat_fail = set()
    backend.beats.clear()
    router.send_heartbeat("test")
    assert backend.beats == [KEY_A, KEY_B]


def test_backfill_positions_and_items_use_the_selected_group(config, monkeypatch, tmp_path):
    from collector import __main__ as cli

    monkeypatch.setenv("LOL_DIR", str(tmp_path))
    monkeypatch.setenv("BACKEND_URL", "http://backend.test")
    monkeypatch.setenv("API_KEY", KEY_A)
    monkeypatch.setenv("COLLECTOR_NO_WIZARD", "1")
    monkeypatch.setattr(cli, "report_backend_check", lambda url, key: None)
    from collector.config import load_config

    real = load_config()
    two_groups(real, selected="b")
    seen: list[str] = []
    stub = type("S", (), {"errors": []})()
    monkeypatch.setattr(cli, "run_position_backfill",
                        lambda cfg, *, dry_run: seen.append(cfg.api_key) or stub)
    monkeypatch.setattr(cli, "run_items_backfill",
                        lambda cfg, *, dry_run: seen.append(cfg.api_key) or stub)

    assert cli.main(["backfill-positions", "--dry-run"]) == 0
    assert cli.main(["backfill-items", "--dry-run"]) == 0
    assert seen == [KEY_B, KEY_B]


# --------------------------------------------------------------------------- #
# e) İlk kurulum taraması
# --------------------------------------------------------------------------- #


def _setup_lcu(mh_game_custom, champion_summary):
    newer = renamed_game(mh_game_custom, 6874239999, "2026-08-02T10:00:00.000Z", "X")
    older = renamed_game(mh_game_custom, 6874230000, "2026-07-01T18:00:00.000Z", "Y")
    remake_id = 6874233333
    aram_id = 6874235555
    pages = [[
        custom_summary(aram_id, gameMode="ARAM", mapId=12),
        remake_summary(remake_id),
        custom_summary(6874239999, gameCreationDate="2026-08-02T10:00:00.000Z"),
        {"gameId": 6874232000, "gameType": "MATCHED_GAME", "queueId": 420,
         "gameCreationDate": "2026-08-01T21:00:00.000Z", "gameMode": "CLASSIC"},
        custom_summary(GAME_1, gameCreationDate="2026-08-01T19:12:44.000Z"),
        custom_summary(6874230000, gameCreationDate="2026-07-01T18:00:00.000Z"),
    ], []]
    return FakeLcu(
        summoner={"puuid": "puuid-t1"},
        pages=pages,
        games={
            6874239999: newer, GAME_1: mh_game_custom, 6874230000: older,
            remake_id: make_remake_game(mh_game_custom, remake_id),
            aram_id: mh_game_custom,
        },
        champions=champion_summary,
    )


def test_first_setup_listing_sends_nothing_and_skips_remakes_and_non_sr(
    config, mh_game_custom, champion_summary, monkeypatch
):
    from collector import commands

    def no_network(*a, **k):
        raise AssertionError("listeleme adımı ağa çıkmamalı")

    monkeypatch.setattr(httpx.Client, "send", no_network)
    monkeypatch.setattr(commands, "read_lockfile", lambda lol_dir: {"port": 1})
    lcu = _setup_lcu(mh_game_custom, champion_summary)
    monkeypatch.setattr(commands, "HttpLcuClient", lambda info: lcu)

    result = commands.run_first_setup_scan_command(config, since=date(2026, 1, 1))

    ids = [c.game_id for c in result.candidates]
    assert ids == ["6874239999", str(GAME_1), "6874230000"]  # en yeni önce; remake/ARAM/ranked yok
    assert result.stats.skipped_remake == 1 and result.stats.skipped_non_sr == 1
    assert not config.raw_archive_dir.exists()  # arşive de yazmaz
    assert not config.outbox_dir.exists()
    first = result.candidates[1]
    assert first.duration_s == 2011
    assert [name for team, name in first.players if team == 100][0] == "Teoman#TR1"
    assert len(first.players) == 10


def test_first_setup_sends_only_ticked_chronologically_to_the_selected_group(
    config, mh_game_custom, champion_summary
):
    settings, b, _ = two_groups(config, selected="b")
    result = scan_first_setup(config, _setup_lcu(mh_game_custom, champion_summary))
    newest, middle, oldest = result.candidates
    ticked = gui.pick_candidates(result.candidates, [True, False, True])
    assert ticked == [newest, oldest]

    # roster'lar boş: filtre bu akışta UYGULANMAZ
    backend = FakeBackend({KEY_A: [], KEY_B: []})
    router = GroupRouter(config, settings, transport=backend.transport)
    stats = send_first_setup(config, router, ticked, settings.selected_id)

    assert backend.ingests == [(KEY_B, oldest.game_id), (KEY_B, newest.game_id)]
    assert stats.sent == 2 and stats.sent_by_group == {b.id: 2}
    assert (config.raw_archive_dir / f"{newest.game_id}.json").is_file()
    assert not (config.raw_archive_dir / f"{middle.game_id}.json").exists()


def test_first_setup_respects_window_and_limit(config, mh_game_custom, champion_summary):
    lcu = _setup_lcu(mh_game_custom, champion_summary)
    result = scan_first_setup(config, lcu, since=date(2026, 7, 15))
    assert [c.game_id for c in result.candidates] == ["6874239999", str(GAME_1)]
    lcu = _setup_lcu(mh_game_custom, champion_summary)
    assert len(scan_first_setup(config, lcu, limit=1).candidates) == 1


def test_first_setup_default_window_is_never_narrower_than_catchup(config):
    config.catchup_days = 14
    assert first_setup_days(config) == FIRST_SETUP_MIN_DAYS == 30
    config.catchup_days = 60
    assert first_setup_days(config) == 60
    config.catchup_days = 0
    assert first_setup_days(config) == 30


def test_first_setup_send_rejects_unknown_group(config):
    router = GroupRouter(config, transport=FakeBackend({KEY_A: []}).transport)
    with pytest.raises(ValueError):
        send_first_setup(config, router, [], "nope")


def test_setup_row_shows_date_duration_and_players(config, mh_game_custom, champion_summary):
    i18n.set_language("tr")
    candidate = scan_first_setup(config, _setup_lcu(mh_game_custom, champion_summary)).candidates[1]
    row = gui.format_setup_row(candidate, local=False)
    assert row.startswith("2026-08-01 19:46")  # played_at = maç sonu (19:12 + 33:31)
    assert "33:31" in row  # 2011 sn
    assert "Teoman#TR1" in row and "Zeynep#TR1" in row and "vs" in row


# --------------------------------------------------------------------------- #
# f) Kalıcılık + gizlilik
# --------------------------------------------------------------------------- #


def test_profiles_and_selection_survive_a_reopen(config):
    settings = load_groups(config)
    b = settings.add("  Cuma   Ekibi ", KEY_B)
    c = settings.add("Ofis", KEY_C)
    settings.rename(FIRST_PROFILE_ID, "Ana Grup")
    settings.rename(c.id, "Ofis 2")
    settings.select(b.id)
    save_groups(config, settings)

    reopened = load_groups(config)
    assert [(p.id, p.label, p.api_key) for p in reopened.profiles] == [
        (FIRST_PROFILE_ID, "Ana Grup", KEY_A), (b.id, "Cuma Ekibi", KEY_B), (c.id, "Ofis 2", KEY_C)
    ]
    assert reopened.selected_id == b.id

    reopened.delete(b.id)  # seçili silinirse seçim ilk profile döner
    save_groups(config, reopened)
    again = load_groups(config)
    assert again.ids() == [FIRST_PROFILE_ID, c.id] and again.selected_id == FIRST_PROFILE_ID
    # ilk profilin anahtarı dosyaya YAZILMAZ (.env'de kalır)
    assert KEY_A not in config.groups_path.read_text(encoding="utf-8")


def test_first_profile_label_follows_language_until_renamed(config):
    i18n.set_language("en")
    assert load_groups(config).first.label == "Group 1"
    i18n.set_language("tr")
    assert load_groups(config).first.label == "Grup 1"
    assert load_groups(config).next_default_label() == "Grup 2"


@pytest.mark.parametrize(
    "action,key",
    [
        (lambda s: s.add("", "k"), "groups.error.label_empty"),
        (lambda s: s.add("x" * 41, "k"), "groups.error.label_too_long"),
        (lambda s: s.add("grup 1", "k"), "groups.error.label_taken"),
        (lambda s: s.add("Yeni", "   "), "groups.error.key_empty"),
        (lambda s: s.add("Yeni", KEY_A), "groups.error.key_taken"),
        (lambda s: s.delete(FIRST_PROFILE_ID), "groups.error.first_not_deletable"),
        (lambda s: s.select("yok"), "groups.error.unknown"),
    ],
)
def test_invalid_group_edits_are_rejected(config, action, key):
    settings = load_groups(config)
    with pytest.raises(GroupError) as info:
        action(settings)
    assert info.value.key == key
    assert info.value.message() != key  # i18n'de var
    assert settings.ids() == [FIRST_PROFILE_ID]


def test_corrupt_groups_file_is_set_aside_not_fatal(config):
    config.groups_path.write_text("{bozuk", encoding="utf-8")
    settings = load_groups(config)
    assert settings.ids() == [FIRST_PROFILE_ID]
    assert config.groups_path.with_name("groups.json.bad").is_file()


def test_api_keys_never_appear_in_logs_or_repr(config, eog_custom, mh_game_custom,
                                               champion_summary, caplog):
    caplog.set_level(logging.DEBUG)
    settings, b, _ = two_groups(config, selected="b")
    settings.rename(b.id, "Yeniden")
    save_groups(config, settings)
    names = [p.riot_id for p in normalize_eog(eog_custom, datetime.now(timezone.utc)).participants]
    backend = FakeBackend({KEY_A: [], KEY_B: names}, ingest_fail={KEY_B})
    router = GroupRouter(config, load_groups(config), transport=backend.transport)
    LiveRunner(config, FakeLcu(eog=eog_custom), router, sleep=lambda s: None).on_end_of_game()
    router.flush_outbox()
    router.send_heartbeat("x")
    run_backfill(config, _single_game_lcu(mh_game_custom, champion_summary), router)
    router.close()

    text = caplog.text + repr(load_groups(config)) + repr(router.settings.profiles)
    assert KEY_B not in text and KEY_A not in text
    assert mask_key(KEY_B) == "gro" + "*" * (len(KEY_B) - 3)


def test_cli_groups_banner_shows_labels_not_keys(config, monkeypatch, tmp_path, capsys):
    from collector import __main__ as cli

    monkeypatch.setenv("LOL_DIR", str(tmp_path))
    monkeypatch.setenv("BACKEND_URL", "http://backend.test")
    monkeypatch.setenv("API_KEY", KEY_A)
    monkeypatch.setenv("COLLECTOR_NO_WIZARD", "1")
    monkeypatch.setattr(cli, "report_backend_check", lambda url, key: None)
    from collector.config import load_config

    two_groups(load_config(), selected="b")
    stub = type("S", (), {"errors": []})()
    monkeypatch.setattr(cli, "run_position_backfill", lambda cfg, *, dry_run: stub)
    i18n.set_language("tr")
    assert cli.main(["backfill-positions", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Gruplar: Grup 1, Grup B (seçili)" in out
    assert KEY_B not in out


# --------------------------------------------------------------------------- #
# g) i18n + arayüz saf parçaları
# --------------------------------------------------------------------------- #


GROUP_KEYS = [
    "cli.groups", "cli.groups_selected", "groups.default_label",
    "groups.error.label_empty", "groups.error.label_too_long", "groups.error.label_taken",
    "groups.error.key_empty", "groups.error.key_taken", "groups.error.unknown",
    "groups.error.first_not_deletable", "gui.groups.label", "gui.groups.btn.add",
    "gui.groups.btn.rename", "gui.groups.btn.delete", "gui.groups.title",
    "gui.groups.ask_label", "gui.groups.ask_key", "gui.groups.ask_rename", "gui.groups.added",
    "gui.groups.renamed", "gui.groups.deleted", "gui.groups.delete_question",
    "gui.groups.delete_pending", "gui.groups.selected", "gui.groups.target",
    "gui.groups.save_failed", "gui.groups.orphan_outbox", "gui.btn.first_setup",
    "gui.job.name.first_setup", "gui.status.first_setup", "gui.first_setup.intro",
    "gui.first_setup.listed", "gui.first_setup.empty", "gui.first_setup.title",
    "gui.first_setup.target", "gui.first_setup.row", "gui.first_setup.select_all",
    "gui.first_setup.select_none", "gui.first_setup.send", "gui.first_setup.cancel",
    "gui.first_setup.confirm_title", "gui.first_setup.confirm",
    "gui.first_setup.none_selected", "gui.first_setup.done",
]


@pytest.mark.parametrize("language", ["tr", "en"])
def test_every_group_key_exists(language):
    missing = [key for key in GROUP_KEYS if key not in i18n.MESSAGES[language]]
    assert missing == []


def test_group_controls_are_locked_while_a_job_runs():
    state = gui.UiState()
    assert state.groups_enabled() is True
    state.start(gui.JOB_LIVE)
    assert state.groups_enabled() is False
    state.finish()
    state.start(gui.JOB_FIRST_SETUP)
    assert state.groups_enabled() is False
    assert gui.JOB_FIRST_SETUP in gui.JOBS


def test_gui_make_sender_snapshots_the_settings(config):
    settings, _, _ = two_groups(config)
    router = gui.make_sender(config, settings)
    try:
        assert isinstance(router, GroupRouter)
        assert router.settings is not settings  # canlı iş, pencerede değişen listeyi görmez
    finally:
        router.close()
    other = dataclasses.replace(config, groups_path=config.groups_path.with_name("none.json"))
    plain = gui.make_sender(other, load_groups(other))
    try:
        assert type(plain) is Sender
    finally:
        plain.close()


def test_duration_and_played_at_formatting():
    assert gui.format_duration(2011) == "33:31"
    assert gui.format_duration(65) == "1:05"
    assert gui.format_played_at("2026-08-01T19:12:44Z", local=False) == "2026-08-01 19:12"
    assert gui.format_played_at("bozuk", local=False) == "bozuk"


# --------------------------------------------------------------------------- #
# Gerçek pencere: grup bandı + ilk kurulum listesi (ekran yoksa atlanır)
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not gui.tkinter_available(), reason="tkinter kurulu değil")
def test_window_group_bar_and_first_setup_picker(
    config, monkeypatch, mh_game_custom, champion_summary
):
    from .test_gui import _withdrawn_root

    root = _withdrawn_root()
    if root is None:
        pytest.skip("ekran yok (headless)")
    app = gui.CollectorApp(root=root, update_checker=lambda *a, **k: None)
    try:
        assert app.group_buttons["add"]["state"] == "disabled"  # ayarlar yüklenmeden kapalı
        settings, b, _ = two_groups(config)
        app.config = config
        app.groups = load_groups(config)
        app.refresh_groups()
        assert app.group_menu["menu"].index("end") == 1  # iki grup
        assert app.group_buttons["delete"]["state"] == "disabled"  # ilk profil seçili

        app.on_select_group(b.id)
        assert load_groups(config).selected_id == b.id  # kalıcı
        assert app.group_var.get() == "Grup B"
        assert app.group_buttons["delete"]["state"] == "normal"

        app.state.start(gui.JOB_LIVE)
        app.refresh_buttons()
        assert app.group_buttons["add"]["state"] == "disabled"
        assert str(app.group_menu["state"]) == "disabled"
        app.state.finish()
        app.refresh_buttons()

        monkeypatch.setattr(app, "_ask_yes_no", lambda *a: True)
        app.on_delete_group()
        assert load_groups(config).ids() == [FIRST_PROFILE_ID]

        answers = iter(["Yeni", KEY_C])
        monkeypatch.setattr(app, "_ask_text", lambda *a, **k: next(answers))
        monkeypatch.setattr(app, "_check_backend_async", lambda cfg: None)
        app.on_add_group()
        assert [p.label for p in load_groups(config).profiles] == ["Grup 1", "Yeni"]
        assert KEY_C not in app.log_text.get("1.0", "end")

        result = scan_first_setup(config, _setup_lcu(mh_game_custom, champion_summary))
        app._show_first_setup_picker(config, result)
        dialogs = [w for w in root.winfo_children() if w.winfo_class() == "Toplevel"]
        assert len(dialogs) == 1
        dialogs[0].destroy()
    finally:
        app.shutdown()
