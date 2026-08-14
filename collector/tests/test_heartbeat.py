"""GÖREV 13 — collector ayağı: cihaz kimliği (`client_id`) + heartbeat.

Contract: docs/api_contract.md §6 "Collector sağlığı (GÖREV 13)" ve
docs/ingest_contract.md "client_id" maddesi.

Kapsam:
1. Kimlik çözümü (env > hostname, trim, 64'e kırpma)
2. Config (`CLIENT_ID`, `HEARTBEAT_MINUTES`) ve eski kurulumla geriye uyum
3. Sihirbaz sorusu (varsayılan hostname, boş giriş kabul) + i18n
4. Ingest payload'ında `client_id` (canlı + backfill + outbox), eski outbox dosyaları
5. Heartbeat gövdesi / anları / bekleyen sayacı ve hatanın YUTULMASI

Ağ yok: her şey httpx.MockTransport ve tests/fakes.py sahteleriyle.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from collector import __version__
from collector import config as config_mod
from collector import wizard as wiz
from collector.config import (
    CLIENT_ID_MAX_LEN,
    FALLBACK_CLIENT_ID,
    hostname_client_id,
    load_config,
    normalize_client_id,
    resolve_client_id,
)
from collector.live import LiveRunner
from collector.sender import HEARTBEAT_PATH, INGEST_PATH, SendOutcome, Sender

from .fakes import FakeLcu
from .test_packaging import Console

# --------------------------------------------------------------------------- #
# Yardımcılar
# --------------------------------------------------------------------------- #


def recording_sender(config, *, heartbeat=200, ingest=201):
    """Ingest ve heartbeat gövdelerini AYRI toplayan Sender.

    `heartbeat` / `ingest` bir int (HTTP kodu) ya da çağrılabilir (istek → yanıt).
    Yalnız backend'e ULAŞAN gövdeler kaydedilir: ağ hatası taklit eden handler
    fırlatırsa liste boş kalır.
    """
    sent: list[dict] = []
    beats: list[dict] = []

    def respond(spec, request):
        if callable(spec):
            return spec(request)
        return httpx.Response(spec, json={"ok": True, "match_id": 1, "duplicate": False})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == HEARTBEAT_PATH:
            response = respond(heartbeat, request)
            beats.append(json.loads(request.content))
            return response
        if request.url.path == INGEST_PATH:
            response = respond(ingest, request)
            sent.append(json.loads(request.content))
            return response
        return httpx.Response(404)

    return Sender(config, transport=httpx.MockTransport(handler)), sent, beats


class Clock:
    """Her çağrıda sabit adım ilerleyen saat (LiveRunner'ın `now` bağımlılığı)."""

    def __init__(self, step_minutes: float = 2.0):
        self._t = datetime(2026, 8, 14, 20, 0, 0, tzinfo=timezone.utc)
        self._step = timedelta(minutes=step_minutes)

    def __call__(self) -> datetime:
        now = self._t
        self._t += self._step
        return now


def make_payload(game_id="900", **extra):
    return {"source": "lcu_eog", "source_game_id": game_id, "participants": [], **extra}


# --------------------------------------------------------------------------- #
# 1. Kimlik çözümü
# --------------------------------------------------------------------------- #


def test_env_value_wins_over_hostname(monkeypatch):
    monkeypatch.setattr(config_mod.socket, "gethostname", lambda: "MAKINE-ADI")
    assert resolve_client_id("Ali-PC") == "Ali-PC"


@pytest.mark.parametrize("value", ["", "   ", None])
def test_empty_value_falls_back_to_hostname(monkeypatch, value):
    monkeypatch.setattr(config_mod.socket, "gethostname", lambda: "MAKINE-ADI")
    assert resolve_client_id(value) == "MAKINE-ADI"


def test_value_is_trimmed():
    assert normalize_client_id("  Ali-PC \n") == "Ali-PC"
    assert resolve_client_id("  Ali-PC  ") == "Ali-PC"


def test_value_is_capped_at_64_chars():
    long_name = "x" * 200
    assert len(normalize_client_id(long_name)) == CLIENT_ID_MAX_LEN
    assert len(resolve_client_id(long_name)) == CLIENT_ID_MAX_LEN


def test_cap_never_leaves_trailing_space():
    """64. karakterden sonrası kesilince sonda boşluk kalmamalı (backend trim'ler)."""
    value = "a" * 63 + "   son"
    result = normalize_client_id(value)
    assert result == "a" * 63
    assert result == result.strip()


def test_hostname_is_trimmed_and_capped(monkeypatch):
    monkeypatch.setattr(config_mod.socket, "gethostname", lambda: "  " + "h" * 100 + "  ")
    assert hostname_client_id() == "h" * CLIENT_ID_MAX_LEN


def test_hostname_failure_falls_back_to_constant(monkeypatch):
    def boom():
        raise OSError("hostname okunamadı")

    monkeypatch.setattr(config_mod.socket, "gethostname", boom)
    assert hostname_client_id() == FALLBACK_CLIENT_ID
    assert resolve_client_id(None) == FALLBACK_CLIENT_ID


def test_empty_hostname_falls_back_to_constant(monkeypatch):
    monkeypatch.setattr(config_mod.socket, "gethostname", lambda: "   ")
    assert hostname_client_id() == FALLBACK_CLIENT_ID


# --------------------------------------------------------------------------- #
# 2. Config: CLIENT_ID / HEARTBEAT_MINUTES
# --------------------------------------------------------------------------- #


def _base_env(monkeypatch):
    monkeypatch.setenv("LOL_DIR", r"C:\Riot Games\League of Legends")
    monkeypatch.setenv("BACKEND_URL", "http://backend.test")
    monkeypatch.setenv("API_KEY", "k")
    for key in ("CLIENT_ID", "HEARTBEAT_MINUTES"):
        monkeypatch.delenv(key, raising=False)


def test_client_id_read_from_env(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("CLIENT_ID", "  Ali-PC  ")
    assert load_config().client_id == "Ali-PC"


def test_client_id_missing_falls_back_to_hostname_at_runtime(monkeypatch):
    """Eski kurulum (.env'de CLIENT_ID yok): sihirbaz KOŞMAZ, hostname kullanılır."""
    _base_env(monkeypatch)
    monkeypatch.setattr(config_mod.socket, "gethostname", lambda: "ESKI-KURULUM")
    assert load_config().client_id == "ESKI-KURULUM"


def test_client_id_from_env_file(tmp_path: Path, monkeypatch):
    for key in ("LOL_DIR", "BACKEND_URL", "API_KEY", "CLIENT_ID"):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "LOL_DIR=x\nBACKEND_URL=http://b.test\nAPI_KEY=k\nCLIENT_ID=Kaan-PC\n", encoding="utf-8"
    )
    assert load_config(env).client_id == "Kaan-PC"


def test_client_id_is_not_a_required_key_and_never_retriggers_the_wizard(
    tmp_path: Path, monkeypatch
):
    from collector import __main__ as cli

    assert "CLIENT_ID" not in cli.REQUIRED_ENV_KEYS
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "LOL_DIR=x\nBACKEND_URL=http://b.test\nAPI_KEY=k\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        cli, "run_wizard", lambda: pytest.fail("CLIENT_ID eksik diye sihirbaz koşmamalı")
    )
    cli._ensure_env()


def test_heartbeat_minutes_defaults_to_five(monkeypatch):
    _base_env(monkeypatch)
    assert load_config().heartbeat_minutes == 5


@pytest.mark.parametrize("value,expected", [("0", 0), ("1", 1), ("15", 15), ("0.5", 0.5)])
def test_heartbeat_minutes_read_from_env(monkeypatch, value, expected):
    _base_env(monkeypatch)
    monkeypatch.setenv("HEARTBEAT_MINUTES", value)
    assert load_config().heartbeat_minutes == expected


def test_invalid_heartbeat_minutes_raises_like_other_numeric_fields(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("HEARTBEAT_MINUTES", "bes-dakika")
    with pytest.raises(ValueError):
        load_config()


# --------------------------------------------------------------------------- #
# 3. Sihirbaz sorusu
# --------------------------------------------------------------------------- #


def _wizard_env(tmp_path: Path, monkeypatch) -> Path:
    lol_dir = tmp_path / "lol"
    lol_dir.mkdir()
    (lol_dir / "lockfile").write_text("", encoding="utf-8")
    monkeypatch.setattr(wiz, "detect_lol_dir", lambda *a, **k: (lol_dir, "x"))
    return tmp_path / ".env"


def _ok_check(url: str, key: str) -> wiz.BackendCheck:
    return wiz.BackendCheck(True, "ok")


def test_wizard_asks_client_id_and_writes_it(tmp_path: Path, monkeypatch):
    target = _wizard_env(tmp_path, monkeypatch)
    monkeypatch.setattr(config_mod.socket, "gethostname", lambda: "MAKINE-ADI")

    # dil, backend (Enter), anahtar, LOL_DIR onayı (Enter), cihaz adı
    console = Console(["tr", "", "k1", "", "Ali-PC"])
    wiz.run_wizard(target, input_fn=console.read, print_fn=console.write, check=_ok_check)

    assert config_mod._load_env_file(target)["CLIENT_ID"] == "Ali-PC"
    assert "MAKINE-ADI" in console.prompts[-1]  # varsayılan öneri hostname
    assert "Ali-PC" in console.text  # özet satırında görünür


def test_wizard_empty_answer_uses_hostname(tmp_path: Path, monkeypatch):
    target = _wizard_env(tmp_path, monkeypatch)
    monkeypatch.setattr(config_mod.socket, "gethostname", lambda: "MAKINE-ADI")

    console = Console(["tr", "", "k1", "", "   "])  # boşluk = boş giriş
    wiz.run_wizard(target, input_fn=console.read, print_fn=console.write, check=_ok_check)

    assert config_mod._load_env_file(target)["CLIENT_ID"] == "MAKINE-ADI"


def test_wizard_client_id_is_trimmed_and_capped(tmp_path: Path, monkeypatch):
    target = _wizard_env(tmp_path, monkeypatch)

    console = Console(["tr", "", "k1", "", "  " + "z" * 100 + "  "])
    wiz.run_wizard(target, input_fn=console.read, print_fn=console.write, check=_ok_check)

    assert config_mod._load_env_file(target)["CLIENT_ID"] == "z" * CLIENT_ID_MAX_LEN


def test_wizard_client_id_question_comes_after_the_others(tmp_path: Path, monkeypatch):
    """Yeni soru mevcut akışın SONUNA eklenir; önceki sorular yerinde kalır."""
    target = _wizard_env(tmp_path, monkeypatch)

    console = Console(["tr", "", "k1", "", "Ali-PC"])
    wiz.run_wizard(target, input_fn=console.read, print_fn=console.write, check=_ok_check)

    assert len(console.prompts) == 5
    assert "Backend" in console.prompts[1]
    assert "API" in console.prompts[2]
    assert "Cihaz" in console.prompts[4]


def test_wizard_written_env_loads_back_with_the_client_id(tmp_path: Path, monkeypatch):
    """Yazılan dosya load_config ile aynen okunabilmeli (roundtrip)."""
    target = _wizard_env(tmp_path, monkeypatch)
    for key in ("LOL_DIR", "BACKEND_URL", "API_KEY", "CLIENT_ID"):
        monkeypatch.delenv(key, raising=False)

    console = Console(["tr", "", "k1", "", "Ece-PC"])
    wiz.run_wizard(target, input_fn=console.read, print_fn=console.write, check=_ok_check)

    assert load_config(target).client_id == "Ece-PC"


@pytest.mark.parametrize(
    "key", ["wizard.ask_client_id", "wizard.saved_client_id", "env.comment_client_id"]
)
def test_new_i18n_keys_exist_in_both_languages(key):
    from collector.i18n import MESSAGES

    for lang in ("tr", "en"):
        assert MESSAGES[lang].get(key), f"{lang}:{key} eksik"


def test_new_i18n_messages_format_with_their_placeholders():
    from collector import i18n

    for lang in ("tr", "en"):
        i18n.set_language(lang)
        assert "MAKINE" in i18n.msg("wizard.ask_client_id", default="MAKINE")
        assert "Ali-PC" in i18n.msg("wizard.saved_client_id", client_id="Ali-PC")


# --------------------------------------------------------------------------- #
# 4. Ingest payload'ında client_id
# --------------------------------------------------------------------------- #


def test_live_payload_carries_client_id(config, eog_custom, champion_summary):
    sender, sent, _ = recording_sender(config)
    runner = LiveRunner(
        config, FakeLcu(eog=eog_custom, champions=champion_summary), sender,
        sleep=lambda s: None,
        now=lambda: datetime(2026, 8, 14, 20, 0, tzinfo=timezone.utc),
    )

    assert runner.on_end_of_game() is True
    assert sent[0]["client_id"] == "test-client"


def test_backfill_payload_carries_client_id(
    config, mh_list_page, mh_game_custom, champion_summary, monkeypatch
):
    from collector import backfill as backfill_module
    from collector.backfill import run_backfill
    from collector.roster import KnownRoster

    from .test_backfill import KNOWN_SIX, make_lcu

    monkeypatch.setattr(
        backfill_module, "build_known_roster", lambda cfg: KnownRoster(riot_ids=set(KNOWN_SIX))
    )
    sender, sent, _ = recording_sender(config)

    run_backfill(config, make_lcu(mh_list_page, mh_game_custom, champion_summary), sender)

    assert sent and all(payload["client_id"] == "test-client" for payload in sent)


def test_send_or_outbox_does_not_mutate_the_callers_payload(config):
    sender, sent, _ = recording_sender(config)
    payload = make_payload()

    sender.send_or_outbox(payload)

    assert "client_id" not in payload  # çağıranın dict'i el değmemiş
    assert sent[0]["client_id"] == "test-client"


def test_outbox_file_is_written_with_the_client_id(config):
    sender, _, _ = recording_sender(config, ingest=500)

    assert sender.send_or_outbox(make_payload("222")) is SendOutcome.RETRY
    written = json.loads((config.outbox_dir / "222.json").read_text(encoding="utf-8"))
    assert written["client_id"] == "test-client"


def test_old_outbox_file_without_client_id_is_sent_untouched(config):
    """GÖREV 13 öncesinden kalan dosyalar olduğu gibi gider (alan EKLENMEZ)."""
    config.outbox_dir.mkdir(parents=True)
    old = make_payload("eski-111")
    (config.outbox_dir / "eski-111.json").write_text(json.dumps(old), encoding="utf-8")

    sender, sent, _ = recording_sender(config)
    sender.flush_outbox()

    assert sent == [old]
    assert "client_id" not in sent[0]
    assert not (config.outbox_dir / "eski-111.json").exists()


def test_no_client_id_means_no_field(config):
    """Kimlik boşsa alan hiç gönderilmez (backend'de opsiyonel)."""
    config.client_id = ""
    sender, sent, _ = recording_sender(config)

    sender.send_or_outbox(make_payload())

    assert "client_id" not in sent[0]


def test_position_backfill_body_has_no_client_id(config):
    """`PUT /matches/{id}/positions` bir ingest payload'ı DEĞİLDİR: kimlik taşımaz."""
    from collector.backfill_positions import run_position_backfill

    from .test_backfill_positions import backend, raw_match, write_archive

    raw = raw_match()
    write_archive(config, raw)
    matches = [{
        "id": 7,
        "source_game_id": str(raw["gameId"]),
        "participants": [{"player_id": pid} for pid in range(1, 11)],
    }]
    transport, calls = backend(matches, {f"p-{pid}": pid for pid in range(1, 11)})

    run_position_backfill(config, transport=transport)

    puts = [call for call in calls if call.method == "PUT"]
    assert puts, "rol güncellemesi atılmalıydı"
    assert set(json.loads(puts[0].content)) == {"positions"}


# --------------------------------------------------------------------------- #
# 5. Heartbeat: gövde, sayaç, hata yutma
# --------------------------------------------------------------------------- #


def test_heartbeat_body_and_headers(config):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    sender = Sender(config, transport=httpx.MockTransport(handler))

    assert sender.send_heartbeat("test") is True
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/api/v1/health/heartbeat"
    assert request.headers["X-API-Key"] == "test-key"
    assert json.loads(request.content) == {
        "client_id": "test-client",
        "version": __version__,
        "outbox_pending": 0,
    }


def test_heartbeat_counts_pending_outbox_files_only(config):
    (config.outbox_dir / "rejected").mkdir(parents=True)
    (config.outbox_dir / "a.json").write_text("{}", encoding="utf-8")
    (config.outbox_dir / "b.json").write_text("{}", encoding="utf-8")
    (config.outbox_dir / "not-json.txt").write_text("x", encoding="utf-8")
    (config.outbox_dir / "rejected" / "c.json").write_text("{}", encoding="utf-8")

    sender, _, beats = recording_sender(config)
    sender.send_heartbeat()

    assert beats[0]["outbox_pending"] == 2  # rejected/ ve .json olmayan sayılmaz


def test_heartbeat_pending_count_is_zero_without_an_outbox_dir(config):
    sender, _, beats = recording_sender(config)
    sender.send_heartbeat()
    assert beats[0]["outbox_pending"] == 0


def test_heartbeat_reflects_a_failed_send(config):
    sender, _, beats = recording_sender(config, ingest=500)

    sender.send_or_outbox(make_payload("777"))
    sender.send_heartbeat()

    assert beats[0]["outbox_pending"] == 1


def test_heartbeat_without_client_id_is_skipped(config):
    config.client_id = ""
    sender, _, beats = recording_sender(config)

    assert sender.send_heartbeat() is False
    assert beats == []


@pytest.mark.parametrize("status", [401, 422, 500])
def test_heartbeat_error_is_swallowed_and_never_written_to_outbox(config, status):
    sender, _, _ = recording_sender(config, heartbeat=status)

    assert sender.send_heartbeat("test") is False
    assert not config.outbox_dir.exists()  # outbox YALNIZ maç payload'ları içindir


def test_heartbeat_network_error_is_swallowed(config, caplog):
    def explode(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("bağlanamadı", request=request)

    sender, _, _ = recording_sender(config, heartbeat=explode)

    assert sender.send_heartbeat("test") is False
    assert not config.outbox_dir.exists()


def test_heartbeat_swallows_unexpected_errors_too(config, monkeypatch):
    sender, _, _ = recording_sender(config)
    monkeypatch.setattr(
        sender, "outbox_pending_count", lambda: (_ for _ in ()).throw(RuntimeError("beklenmedik"))
    )
    # Sayaç patlasa bile çağrı hata fırlatmaz.
    assert sender.send_heartbeat("test") is False


# --------------------------------------------------------------------------- #
# 6. Heartbeat anları: canlı mod
# --------------------------------------------------------------------------- #


def _live_runner(config, lcu, sender, clock):
    return LiveRunner(config, lcu, sender, sleep=lambda s: None, now=clock)


def test_live_mode_beats_every_heartbeat_minutes(config):
    config.heartbeat_minutes = 5
    lcu = FakeLcu(phases=["None"] * 6)
    sender, _, beats = recording_sender(config)

    with pytest.raises(KeyboardInterrupt):  # FakeLcu fazlar bitince döngüyü kırar
        _live_runner(config, lcu, sender, Clock(step_minutes=2)).poll_forever()

    # t0 = döngü başı (referans); 6. ve 12. dakikada iki atış
    assert len(beats) == 2
    assert all(beat["client_id"] == "test-client" for beat in beats)


def test_live_mode_does_not_beat_before_the_interval(config):
    config.heartbeat_minutes = 5
    lcu = FakeLcu(phases=["None"] * 3)
    sender, _, beats = recording_sender(config)

    with pytest.raises(KeyboardInterrupt):
        _live_runner(config, lcu, sender, Clock(step_minutes=1)).poll_forever()

    assert beats == []


def test_heartbeat_minutes_zero_disables_live_beats(config):
    config.heartbeat_minutes = 0
    lcu = FakeLcu(phases=["None"] * 10)
    sender, _, beats = recording_sender(config)

    with pytest.raises(KeyboardInterrupt):
        _live_runner(config, lcu, sender, Clock(step_minutes=60)).poll_forever()

    assert beats == []


def test_heartbeat_failure_does_not_stop_live_mode(config, eog_custom, champion_summary):
    """Heartbeat ölü olsa bile maç yakalama/gönderme aynen sürer."""
    config.heartbeat_minutes = 1

    def explode(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("heartbeat ölü", request=request)

    sender, sent, beats = recording_sender(config, heartbeat=explode)
    lcu = FakeLcu(
        phases=["Lobby", "EndOfGame", "None", "None"], eog=eog_custom, champions=champion_summary
    )

    with pytest.raises(KeyboardInterrupt):
        _live_runner(config, lcu, sender, Clock(step_minutes=2)).poll_forever()

    assert [payload["source_game_id"] for payload in sent] == ["6874231955"]
    assert beats == []  # hiçbiri backend'e ulaşmadı ama döngü sürdü


def test_live_beat_counter_advances_even_when_sending_fails(config):
    """Başarısız atış sayacı ilerletir: her turda yeniden denenip döngü yavaşlamaz."""
    config.heartbeat_minutes = 5
    attempts: list[int] = []

    def explode(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        raise httpx.ConnectError("ölü", request=request)

    sender, _, _ = recording_sender(config, heartbeat=explode)
    lcu = FakeLcu(phases=["None"] * 6)

    with pytest.raises(KeyboardInterrupt):
        _live_runner(config, lcu, sender, Clock(step_minutes=2)).poll_forever()

    assert len(attempts) == 2  # 6 turda 2 deneme (her turda değil)
