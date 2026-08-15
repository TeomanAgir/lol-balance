"""Oto-yetişme (docs/ingest_contract.md "Oto-yetişme", CHANGE_REQUESTS 2026-08-13).

Kapsam: `run_catchup` davranışı (pencere, kapalı hâli, hata yutması),
`CATCHUP_DAYS` config'i, CLI `backfill` alias'ı ve canlı yoldaki bağlantı.
"""

from __future__ import annotations

import logging
from datetime import date

import pytest

from collector import catchup as catchup_module
from collector.backfill import BackfillStats
from collector.catchup import catchup_since, run_catchup
from collector.config import load_config

from .fakes import FakeLcu


class FakeSender:
    """Sender sahtesi: yalnız çağrı sırasını kaydeder (ağ yok)."""

    def __init__(self, calls: list[str]):
        self._calls = calls

    def flush_outbox(self) -> None:
        self._calls.append("flush")

    def send_or_outbox(self, payload):  # pragma: no cover - bu testlerde çağrılmaz
        self._calls.append("send")

    def send_heartbeat(self, reason: str = "") -> bool:
        self._calls.append(f"heartbeat:{reason}" if reason else "heartbeat")
        return True

    def close(self) -> None:
        self._calls.append("close")


@pytest.fixture
def calls() -> list[str]:
    return []


# --------------------------------------------------------------------------- #
# 1. Pencere ve çağrı sırası
# --------------------------------------------------------------------------- #


def test_run_catchup_calls_backfill_with_windowed_since_after_flush(
    config, calls, monkeypatch, capsys
):
    seen = {}

    def fake_backfill(cfg, lcu, sender, since=None, roster=None):
        calls.append("backfill")
        seen["config"] = cfg
        seen["since"] = since
        return BackfillStats(scanned=7, customs=2, sent=2)

    monkeypatch.setattr(catchup_module, "run_backfill", fake_backfill)
    config.catchup_days = 14

    stats = run_catchup(config, FakeLcu(), FakeSender(calls), today=date(2026, 8, 13))

    assert stats is not None and stats.sent == 2
    assert seen["since"] == date(2026, 7, 30)  # 13 Ağustos - 14 gün
    assert seen["config"] is config
    # outbox önce boşaltılır (backfill modundaki gibi), bitiminde heartbeat (GÖREV 13)
    assert calls == ["flush", "backfill", "heartbeat:catchup"]

    out = capsys.readouterr().out
    assert "2026-07-30" in out and "14" in out  # yetişme başlangıcı kullanıcıya bildirilir
    assert "7" in out and "2" in out  # kısa özet: taranan / gönderilen


def test_catchup_since_is_a_plain_day_window():
    assert catchup_since(14, date(2026, 8, 13)) == date(2026, 7, 30)
    assert catchup_since(1, date(2026, 1, 1)) == date(2025, 12, 31)


@pytest.mark.parametrize("days", [0, -3])
def test_disabled_catchup_never_touches_backfill_or_sender(
    config, calls, days, monkeypatch, capsys
):
    monkeypatch.setattr(
        catchup_module,
        "run_backfill",
        lambda *a, **k: pytest.fail("CATCHUP_DAYS<=0 iken backfill koşmamalıydı"),
    )
    config.catchup_days = days

    assert run_catchup(config, FakeLcu(), FakeSender(calls)) is None
    assert calls == []  # flush_outbox bile çağrılmaz
    assert capsys.readouterr().out == ""  # kullanıcıya mesaj da yok


def test_catchup_applies_the_summoners_rift_filter(
    config, mh_game_custom, champion_summary, monkeypatch
):
    """Yetişme yolu gerçek `run_backfill`i çağırır: SR olmayan custom burada da
    elenir (Teoman, 2026-08-13). Sahte backfill kullanılmaz — zincir test edilir."""
    from collector import backfill as backfill_module
    from collector.roster import KnownRoster

    from .test_backfill import KNOWN_SIX, capturing_sender, custom_summary

    monkeypatch.setattr(
        backfill_module, "build_known_roster", lambda cfg: KnownRoster(riot_ids=set(KNOWN_SIX))
    )
    aram_id, sr_id = 6874235555, 6874231001
    lcu = FakeLcu(
        summoner={"puuid": "puuid-t1"},
        pages=[
            [
                custom_summary(aram_id, gameMode="ARAM", mapId=12),
                custom_summary(sr_id, gameCreationDate="2026-08-06T20:00:00.000Z"),
            ],
            [],
        ],
        games={sr_id: mh_game_custom},  # ARAM detayı hiç istenmemeli
        champions=champion_summary,
    )
    sender, sent = capturing_sender(config)
    config.catchup_days = 14

    stats = run_catchup(config, lcu, sender, today=date(2026, 8, 13))

    assert stats is not None
    assert stats.skipped_non_sr == 1
    assert stats.errors == []
    assert [p["source_game_id"] for p in sent] == [str(sr_id)]


# --------------------------------------------------------------------------- #
# 2. Sağlamlık: yetişme canlı modu ASLA engellemez
# --------------------------------------------------------------------------- #


def test_backfill_exception_is_swallowed_and_logged(config, calls, monkeypatch, caplog):
    def boom(*args, **kwargs):
        raise RuntimeError("backend erişilemiyor")

    monkeypatch.setattr(catchup_module, "run_backfill", boom)
    config.catchup_days = 14

    with caplog.at_level(logging.WARNING, logger="collector.catchup"):
        assert run_catchup(config, FakeLcu(), FakeSender(calls)) is None

    assert "backend erişilemiyor" in caplog.text
    # Hatalı bitişte de heartbeat atılır (bekleyen outbox sayısı güncel kalsın).
    assert calls == ["flush", "heartbeat:catchup"]


def test_flush_outbox_exception_is_swallowed_too(config, monkeypatch):
    class ExplodingSender(FakeSender):
        def flush_outbox(self) -> None:
            raise OSError("outbox okunamadı")

    monkeypatch.setattr(
        catchup_module,
        "run_backfill",
        lambda *a, **k: pytest.fail("flush patlayınca backfill'e geçilmemeli"),
    )
    config.catchup_days = 14

    assert run_catchup(config, FakeLcu(), ExplodingSender([])) is None


def test_keyboard_interrupt_is_not_swallowed(config, monkeypatch):
    """Ctrl+C yetişme sırasında da programı durdurabilmeli (BaseException geçer)."""

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(catchup_module, "run_backfill", interrupt)
    config.catchup_days = 14

    with pytest.raises(KeyboardInterrupt):
        run_catchup(config, FakeLcu(), FakeSender([]))


def test_empty_roster_is_not_an_obstacle(config, calls, monkeypatch, capsys):
    """Roster boşsa run_backfill boş istatistikle döner — bu bir hata değildir."""
    monkeypatch.setattr(
        catchup_module, "run_backfill", lambda *a, **k: BackfillStats()
    )
    config.catchup_days = 14

    stats = run_catchup(config, FakeLcu(), FakeSender(calls))

    assert stats is not None and stats.scanned == 0 and stats.sent == 0
    assert "0" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# 3. Config: CATCHUP_DAYS
# --------------------------------------------------------------------------- #


def _base_env(monkeypatch):
    monkeypatch.setenv("LOL_DIR", r"C:\Riot Games\League of Legends")
    monkeypatch.setenv("BACKEND_URL", "http://backend.test/")
    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.delenv("CATCHUP_DAYS", raising=False)


def test_catchup_days_defaults_to_14(monkeypatch):
    _base_env(monkeypatch)
    assert load_config().catchup_days == 14


@pytest.mark.parametrize("value,expected", [("0", 0), ("30", 30), ("1", 1)])
def test_catchup_days_read_from_env(monkeypatch, value, expected):
    _base_env(monkeypatch)
    monkeypatch.setenv("CATCHUP_DAYS", value)
    assert load_config().catchup_days == expected


def test_catchup_days_from_env_file(tmp_path, monkeypatch):
    for key in ("LOL_DIR", "BACKEND_URL", "API_KEY", "CATCHUP_DAYS"):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "LOL_DIR=x\nBACKEND_URL=http://b.test\nAPI_KEY=k\nCATCHUP_DAYS=3\n", encoding="utf-8"
    )
    assert load_config(env).catchup_days == 3


def test_invalid_catchup_days_raises_like_other_numeric_fields(monkeypatch):
    """Mevcut config kalıbı: MIN_KNOWN/POLL_INTERVAL_S gibi int()/float() hatası yükselir."""
    _base_env(monkeypatch)
    monkeypatch.setenv("CATCHUP_DAYS", "iki-hafta")
    with pytest.raises(ValueError):
        load_config()


# --------------------------------------------------------------------------- #
# 4. i18n: yeni anahtarlar iki sözlükte de var
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("key", ["catchup.start", "catchup.done", "catchup.failed"])
def test_catchup_messages_exist_in_both_languages(key):
    from collector.i18n import MESSAGES

    for lang in ("tr", "en"):
        assert MESSAGES[lang].get(key), f"{lang}:{key} eksik"


def test_catchup_messages_format_with_their_placeholders():
    from collector import i18n

    for lang in ("tr", "en"):
        i18n.set_language(lang)
        assert "7" in i18n.msg("catchup.start", days=7, since="2026-08-01")
        assert "2026-08-01" in i18n.msg("catchup.start", days=7, since="2026-08-01")
        assert "3" in i18n.msg("catchup.done", scanned=9, sent=3)
        assert "patladı" in i18n.msg("catchup.failed", error="patladı")


# --------------------------------------------------------------------------- #
# 5. CLI: `backfill` alias'ı ve canlı yola bağlanma
# --------------------------------------------------------------------------- #


def _cli_env(monkeypatch, lol_dir):
    monkeypatch.setenv("LOL_DIR", str(lol_dir))
    monkeypatch.setenv("BACKEND_URL", "http://backend.test")
    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.setenv("COLLECTOR_NO_WIZARD", "1")
    monkeypatch.delenv("CATCHUP_DAYS", raising=False)


def _stub_cli(monkeypatch, cli, calls):
    """CLI + paylaşılan komut katmanı (GÖREV 16'dan beri canlı/backfill akışı
    `collector.commands`'tedir; CLI ve arayüz aynı fonksiyonları çağırır)."""
    from collector import commands

    monkeypatch.setattr(cli, "report_backend_check", lambda url, key: None)
    monkeypatch.setattr(commands, "read_lockfile", lambda lol_dir: {"port": 1, "password": "x"})
    monkeypatch.setattr(commands, "HttpLcuClient", lambda info: FakeLcu())
    monkeypatch.setattr(cli, "Sender", lambda config: FakeSender(calls))


@pytest.mark.parametrize(
    "argv",
    [["--backfill", "--since", "2026-08-01"], ["backfill", "--since", "2026-08-01"]],
)
def test_positional_backfill_is_an_alias_of_the_flag(tmp_path, monkeypatch, capsys, argv):
    from collector import __main__ as cli

    from collector import commands

    _cli_env(monkeypatch, tmp_path)
    calls: list[str] = []
    _stub_cli(monkeypatch, cli, calls)
    seen = {}

    def fake_backfill(config, lcu, sender, since=None, roster=None):
        seen["since"] = since
        return BackfillStats(scanned=1, sent=1)

    monkeypatch.setattr(commands, "run_backfill", fake_backfill)
    monkeypatch.setattr(
        commands, "run_catchup", lambda *a, **k: pytest.fail("tam backfill'de yetişme koşmaz")
    )

    assert cli.main(argv) == 0
    assert seen["since"] == date(2026, 8, 1)
    # Bağlantı heartbeat'i → outbox boşaltma → backfill → bitiş heartbeat'i (GÖREV 13)
    assert calls == ["heartbeat:lcu-connected", "flush", "heartbeat:backfill-done", "close"]
    assert "backfill" in capsys.readouterr().out  # banner: geçmiş maç backfill modu


def test_positional_backfill_does_not_affect_backfill_positions(tmp_path, monkeypatch):
    from collector import __main__ as cli
    from collector import commands

    _cli_env(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "report_backend_check", lambda url, key: None)
    monkeypatch.setattr(
        cli, "run_backfill_command",
        lambda *a, **k: pytest.fail("rol backfill'de match backfill yok"),
    )
    monkeypatch.setattr(
        commands, "run_backfill", lambda *a, **k: pytest.fail("rol backfill'de match backfill yok")
    )
    seen = {}

    def fake_positions(config, *, dry_run):
        seen["dry_run"] = dry_run
        return type("S", (), {"errors": []})()

    monkeypatch.setattr(cli, "run_position_backfill", fake_positions)

    assert cli.main(["backfill-positions", "--dry-run"]) == 0
    assert seen == {"dry_run": True}


def test_unknown_positional_command_still_rejected(monkeypatch):
    from collector import __main__ as cli

    with pytest.raises(SystemExit):
        cli._build_parser().parse_args(["backfil"])  # typo: choices dışında


def test_live_mode_runs_catchup_before_the_poll_loop(tmp_path, monkeypatch, capsys):
    """`--console`: GÖREV 16 öncesinin argümansız canlı modu birebir korunur."""
    from collector import __main__ as cli
    from collector import commands

    _cli_env(monkeypatch, tmp_path)
    calls: list[str] = []
    _stub_cli(monkeypatch, cli, calls)

    order: list[str] = []

    class FakeRunner:
        def __init__(self, config, lcu, sender, **kwargs):
            pass

        def poll_forever(self):
            order.append("poll")
            raise KeyboardInterrupt  # tek tur sonra canlı döngüden çık

    monkeypatch.setattr(commands, "LiveRunner", FakeRunner)
    monkeypatch.setattr(
        commands, "run_catchup", lambda config, lcu, sender: order.append("catchup")
    )

    assert cli.main(["--console"]) == 0
    assert order == ["catchup", "poll"]  # yetişme canlı döngüden ÖNCE
    assert "canlı mod" in capsys.readouterr().out  # cli.live_hint akışı korundu
