"""GÖREV 5: frozen (exe) yolları, ilk açılış sihirbazı, LOL_DIR arama, backend doğrulaması."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

from collector import config as config_mod
from collector import wizard as wiz
from collector.config import Config, app_dir, env_candidates, find_env_file, is_frozen, load_config


# --------------------------------------------------------------------------- #
# 1. Frozen yollar
# --------------------------------------------------------------------------- #


@pytest.fixture
def frozen(monkeypatch, tmp_path: Path) -> Path:
    """sys.frozen + exe yolu taklit edilir; app_dir() exe'nin yanını göstermeli."""
    exe_dir = tmp_path / "portable"
    exe_dir.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "LoLBalanceCollector.exe"))
    return exe_dir.resolve()


def test_source_mode_paths_unchanged(monkeypatch):
    """Kaynaktan çalışmada davranış birebir eski hali: her şey paket dizininde."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert is_frozen() is False
    assert app_dir() == config_mod.PACKAGE_DIR

    cfg = Config(lol_dir=Path("x"), backend_url="http://b", api_key="k")
    assert cfg.raw_archive_dir == config_mod.PACKAGE_DIR / "raw_archive"
    assert cfg.outbox_dir == config_mod.PACKAGE_DIR / "outbox"
    assert cfg.seed_roster_path == config_mod.PACKAGE_DIR / "seed_roster.json"
    assert env_candidates()[0] == config_mod.PACKAGE_DIR / ".env"


def test_frozen_paths_next_to_exe(frozen: Path):
    assert is_frozen() is True
    assert app_dir() == frozen

    cfg = Config(lol_dir=Path("x"), backend_url="http://b", api_key="k")
    assert cfg.raw_archive_dir == frozen / "raw_archive"
    assert cfg.outbox_dir == frozen / "outbox"
    assert cfg.seed_roster_path == frozen / "seed_roster.json"


def test_frozen_paths_are_not_in_meipass(frozen: Path, monkeypatch, tmp_path: Path):
    """Kritik regresyon: onefile geçici dizini (_MEIPASS) kalıcı yol olarak KULLANILMAZ."""
    meipass = tmp_path / "_MEI12345"
    meipass.mkdir()
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)

    cfg = Config(lol_dir=Path("x"), backend_url="http://b", api_key="k")
    for path in (cfg.raw_archive_dir, cfg.outbox_dir, app_dir() / ".env"):
        assert meipass not in path.parents
        assert path.is_relative_to(frozen)


def test_frozen_env_lookup_and_load(frozen: Path, monkeypatch):
    monkeypatch.chdir(frozen.parent)
    for key in ("LOL_DIR", "BACKEND_URL", "API_KEY"):
        monkeypatch.delenv(key, raising=False)

    assert find_env_file() is None

    (frozen / ".env").write_text(
        "LOL_DIR=C:\\Riot Games\\League of Legends\n"
        "BACKEND_URL=https://lol.example.com/\n"
        "API_KEY=abc123\n",
        encoding="utf-8",
    )
    assert find_env_file() == frozen / ".env"

    cfg = load_config()
    assert cfg.backend_url == "https://lol.example.com"  # sondaki / kırpılır
    assert cfg.api_key == "abc123"
    assert cfg.raw_archive_dir == frozen / "raw_archive"


def test_env_candidates_no_duplicate_when_cwd_is_app_dir(frozen: Path, monkeypatch):
    monkeypatch.chdir(frozen)
    assert env_candidates() == [frozen / ".env"]


# --------------------------------------------------------------------------- #
# 2. LOL_DIR arama
# --------------------------------------------------------------------------- #


def _make_lol_dir(root: Path, marker: str = "LeagueClient.exe") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / marker).write_text("", encoding="utf-8")
    return root


@pytest.mark.parametrize("marker", ["lockfile", "LeagueClient.exe", "LeagueClientUx.exe"])
def test_looks_like_lol_dir_accepts_markers(tmp_path: Path, marker):
    assert wiz.looks_like_lol_dir(_make_lol_dir(tmp_path / "lol", marker)) is True


def test_looks_like_lol_dir_rejects_plain_and_missing_dir(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert wiz.looks_like_lol_dir(empty) is False
    assert wiz.looks_like_lol_dir(tmp_path / "yok") is False


def test_detect_lol_dir_priority_registry_first(tmp_path: Path):
    """Kayıt defteri bilinen yollardan ÖNCE gelir."""
    from_registry = _make_lol_dir(tmp_path / "reg")
    from_known = _make_lol_dir(tmp_path / "known")

    sources = [
        ("kayıt defteri", lambda: from_registry),
        ("bilinen yollar", lambda: from_known),
    ]
    assert wiz.detect_lol_dir(sources) == (from_registry, "kayıt defteri")


def test_detect_lol_dir_falls_through_and_survives_errors(tmp_path: Path):
    from_known = _make_lol_dir(tmp_path / "known")

    def boom():
        raise OSError("kayıt defteri okunamadı")

    sources = [
        ("kayıt defteri", boom),
        ("Riot metadata", lambda: None),
        ("bilinen yollar", lambda: from_known),
    ]
    assert wiz.detect_lol_dir(sources) == (from_known, "bilinen yollar")


def test_detect_lol_dir_returns_none_when_nothing_found():
    assert wiz.detect_lol_dir([("x", lambda: None)]) == (None, None)


def test_default_source_order_is_registry_then_known_paths():
    names = [name for name, _ in wiz.LOL_DIR_SOURCES]
    assert names.index("kayıt defteri") < names.index("bilinen yollar")


def test_registry_lookup_is_safe_without_winreg(monkeypatch):
    """winreg yoksa (Windows dışı) çökmez, None döner."""
    monkeypatch.setitem(sys.modules, "winreg", None)
    assert wiz.find_lol_dir_from_registry() is None


def test_riot_metadata_source_reads_install_path(tmp_path: Path, monkeypatch):
    lol_dir = _make_lol_dir(tmp_path / "Riot Games" / "League of Legends")
    yaml_path = tmp_path / "product_settings.yaml"
    yaml_path.write_text(
        f'product_install_full_path: "{lol_dir}"\nother_key: 1\n', encoding="utf-8"
    )
    monkeypatch.setattr(wiz, "RIOT_METADATA_PATHS", (str(yaml_path),))
    assert wiz.find_lol_dir_from_riot_metadata() == lol_dir


# --------------------------------------------------------------------------- #
# 3. Backend doğrulaması
# --------------------------------------------------------------------------- #


def _transport(handler):
    return httpx.MockTransport(handler)


def test_check_backend_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/players"
        assert request.headers["X-API-Key"] == "k"
        return httpx.Response(200, json=[{"id": 1}, {"id": 2}])

    result = wiz.check_backend("https://lol.example.com/", "k", transport=_transport(handler))
    assert result.ok is True
    assert "2" in result.message


@pytest.mark.parametrize(
    "status,expected",
    [(401, "API anahtarı"), (403, "API anahtarı"), (404, "Adres bulunamadı"), (500, "beklenmedik")],
)
def test_check_backend_reports_http_errors_in_turkish(status, expected):
    result = wiz.check_backend(
        "https://lol.example.com", "k",
        transport=_transport(lambda r: httpx.Response(status, text="nope")),
    )
    assert result.ok is False
    assert expected in result.message


def test_check_backend_reports_unreachable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("bağlanılamadı", request=request)

    result = wiz.check_backend("http://127.0.0.1:9/", "k", transport=_transport(handler))
    assert result.ok is False
    assert "ULAŞILAMADI" in result.message


def test_check_backend_rejects_non_json_200():
    result = wiz.check_backend(
        "https://lol.example.com", "k",
        transport=_transport(lambda r: httpx.Response(200, text="<html>hello</html>")),
    )
    assert result.ok is False
    assert "JSON" in result.message


# --------------------------------------------------------------------------- #
# 4. Sihirbaz (mock girdi)
# --------------------------------------------------------------------------- #


class Console:
    """input()/print() sahtesi."""

    def __init__(self, answers: list[str]):
        self._answers = list(answers)
        self.lines: list[str] = []
        self.prompts: list[str] = []

    def read(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._answers:
            raise EOFError
        return self._answers.pop(0)

    def write(self, text: str = "") -> None:
        self.lines.append(str(text))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _ok_check(url: str, key: str) -> wiz.BackendCheck:
    return wiz.BackendCheck(True, f"Backend doğrulandı ({url}): 3 kayıtlı oyuncu.")


def _read_env(path: Path) -> dict[str, str]:
    return config_mod._load_env_file(path)


def test_wizard_writes_env_next_to_exe_with_detected_lol_dir(frozen: Path, monkeypatch, tmp_path):
    lol_dir = _make_lol_dir(tmp_path / "Riot Games" / "League of Legends")
    monkeypatch.setattr(wiz, "detect_lol_dir", lambda *a, **k: (lol_dir, "kayıt defteri"))

    console = Console(["", "gizli-anahtar", ""])  # Enter=varsayılan URL, anahtar, Enter=onay
    path = wiz.run_wizard(input_fn=console.read, print_fn=console.write, check=_ok_check)

    assert path == frozen / ".env"
    values = _read_env(path)
    assert values["BACKEND_URL"] == wiz.DEFAULT_BACKEND_URL
    assert values["API_KEY"] == "gizli-anahtar"
    assert values["LOL_DIR"] == str(lol_dir)
    assert find_env_file() == frozen / ".env"
    assert "gizli-anahtar" not in console.text  # özet maskeli


def test_wizard_custom_url_and_manual_lol_dir(tmp_path: Path, monkeypatch):
    lol_dir = _make_lol_dir(tmp_path / "elle")
    monkeypatch.setattr(wiz, "detect_lol_dir", lambda *a, **k: (None, None))
    target = tmp_path / ".env"

    console = Console(["http://127.0.0.1:8000/", "k1", str(lol_dir)])
    wiz.run_wizard(target, input_fn=console.read, print_fn=console.write, check=_ok_check)

    values = _read_env(target)
    assert values["BACKEND_URL"] == "http://127.0.0.1:8000"
    assert values["LOL_DIR"] == str(lol_dir)
    assert "otomatik bulunamadı" in console.text


def test_wizard_rejects_detected_dir_and_asks(tmp_path: Path, monkeypatch):
    detected = _make_lol_dir(tmp_path / "yanlis")
    real = _make_lol_dir(tmp_path / "dogru")
    monkeypatch.setattr(wiz, "detect_lol_dir", lambda *a, **k: (detected, "bilinen yollar"))
    target = tmp_path / ".env"

    console = Console(["", "k1", "h", str(real)])
    wiz.run_wizard(target, input_fn=console.read, print_fn=console.write, check=_ok_check)

    assert _read_env(target)["LOL_DIR"] == str(real)


def test_wizard_adds_scheme_to_bare_host(tmp_path: Path, monkeypatch):
    lol_dir = _make_lol_dir(tmp_path / "lol")
    monkeypatch.setattr(wiz, "detect_lol_dir", lambda *a, **k: (lol_dir, "x"))
    target = tmp_path / ".env"

    console = Console(["lol.teomanagir.com", "k1", ""])
    wiz.run_wizard(target, input_fn=console.read, print_fn=console.write, check=_ok_check)

    assert _read_env(target)["BACKEND_URL"] == "https://lol.teomanagir.com"


def test_wizard_api_key_cannot_be_empty(tmp_path: Path, monkeypatch):
    lol_dir = _make_lol_dir(tmp_path / "lol")
    monkeypatch.setattr(wiz, "detect_lol_dir", lambda *a, **k: (lol_dir, "x"))
    target = tmp_path / ".env"

    console = Console(["", "", "  ", "sonunda-girdi", ""])
    wiz.run_wizard(target, input_fn=console.read, print_fn=console.write, check=_ok_check)

    assert _read_env(target)["API_KEY"] == "sonunda-girdi"
    assert "boş olamaz" in console.text


def test_wizard_gives_up_when_api_key_never_entered(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(wiz, "detect_lol_dir", lambda *a, **k: (tmp_path, "x"))
    console = Console(["", "", "", "", "", ""])
    with pytest.raises(SystemExit):
        wiz.run_wizard(tmp_path / ".env", input_fn=console.read,
                       print_fn=console.write, check=_ok_check)


def test_wizard_warns_on_dir_without_marker(tmp_path: Path, monkeypatch):
    plain = tmp_path / "bos"
    plain.mkdir()
    monkeypatch.setattr(wiz, "detect_lol_dir", lambda *a, **k: (None, None))
    target = tmp_path / ".env"

    console = Console(["", "k1", str(plain)])
    wiz.run_wizard(target, input_fn=console.read, print_fn=console.write, check=_ok_check)

    assert _read_env(target)["LOL_DIR"] == str(plain)
    assert "UYARI" in console.text


def test_wizard_reports_backend_failure_immediately(tmp_path: Path, monkeypatch):
    lol_dir = _make_lol_dir(tmp_path / "lol")
    monkeypatch.setattr(wiz, "detect_lol_dir", lambda *a, **k: (lol_dir, "x"))

    def failing(url: str, key: str) -> wiz.BackendCheck:
        return wiz.BackendCheck(False, "API anahtarı REDDEDİLDİ (HTTP 401).")

    console = Console(["", "yanlis-anahtar", ""])
    wiz.run_wizard(tmp_path / ".env", input_fn=console.read,
                   print_fn=console.write, check=failing)

    assert "HATA" in console.text
    assert "REDDEDİLDİ" in console.text
    assert "--setup" in console.text  # kullanıcıya düzeltme yolu gösterilir


def test_render_env_is_loadable_roundtrip(tmp_path: Path):
    values = {"BACKEND_URL": "https://x.test", "API_KEY": "k", "LOL_DIR": r"C:\Riot Games\LoL"}
    path = wiz.write_env(tmp_path / ".env", values)
    assert _read_env(path) == {**values}


def test_stdin_interactive_flag_can_be_disabled(monkeypatch):
    monkeypatch.setenv("COLLECTOR_NO_WIZARD", "1")
    assert wiz.stdin_is_interactive() is False


# --------------------------------------------------------------------------- #
# 5. CLI entegrasyonu
# --------------------------------------------------------------------------- #


def test_cli_runs_wizard_when_env_missing(frozen: Path, monkeypatch):
    from collector import __main__ as cli

    monkeypatch.chdir(frozen)
    for key in ("LOL_DIR", "BACKEND_URL", "API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("COLLECTOR_NO_WIZARD", raising=False)

    called = {}

    def fake_wizard():
        called["yes"] = True
        (frozen / ".env").write_text(
            f"LOL_DIR={frozen}\nBACKEND_URL=http://b.test\nAPI_KEY=k\n", encoding="utf-8"
        )

    monkeypatch.setattr(cli, "run_wizard", fake_wizard)
    cli._ensure_env()
    assert called == {"yes": True}


def test_cli_skips_wizard_when_env_exists(frozen: Path, monkeypatch):
    from collector import __main__ as cli

    monkeypatch.chdir(frozen)
    (frozen / ".env").write_text("LOL_DIR=x\nBACKEND_URL=y\nAPI_KEY=z\n", encoding="utf-8")
    monkeypatch.setattr(cli, "run_wizard", lambda: pytest.fail("sihirbaz çalışmamalıydı"))
    cli._ensure_env()


def test_cli_skips_wizard_when_env_vars_present(frozen: Path, monkeypatch):
    from collector import __main__ as cli

    monkeypatch.chdir(frozen)
    for key, value in (("LOL_DIR", "x"), ("BACKEND_URL", "y"), ("API_KEY", "z")):
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(cli, "run_wizard", lambda: pytest.fail("sihirbaz çalışmamalıydı"))
    cli._ensure_env()


def test_cli_setup_flag_forces_wizard_even_with_env(frozen: Path, monkeypatch):
    from collector import __main__ as cli

    monkeypatch.chdir(frozen)
    (frozen / ".env").write_text("LOL_DIR=x\nBACKEND_URL=y\nAPI_KEY=z\n", encoding="utf-8")
    called = {}
    monkeypatch.setattr(cli, "run_wizard", lambda: called.setdefault("yes", True))
    cli._ensure_env(force_setup=True)
    assert called == {"yes": True}


def test_cli_errors_clearly_when_no_env_and_no_tty(frozen: Path, monkeypatch):
    from collector import __main__ as cli

    monkeypatch.chdir(frozen)
    for key in ("LOL_DIR", "BACKEND_URL", "API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("COLLECTOR_NO_WIZARD", "1")

    with pytest.raises(SystemExit) as exc:
        cli._ensure_env()
    assert ".env" in str(exc.value)


def test_cli_setup_command_writes_env_and_exits(frozen: Path, monkeypatch, capsys):
    """`--setup`: sihirbaz + doğrulama koşar, toplamaya geçmez."""
    from collector import __main__ as cli

    monkeypatch.chdir(frozen)
    for key in ("LOL_DIR", "BACKEND_URL", "API_KEY"):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setattr(cli, "run_wizard", lambda: (frozen / ".env").write_text(
        f"LOL_DIR={frozen}\nBACKEND_URL=http://b.test\nAPI_KEY=k\n", encoding="utf-8"))
    monkeypatch.setattr(cli, "report_backend_check",
                        lambda url, key: wiz.BackendCheck(True, "ok"))

    assert cli.main(["--setup"]) == 0
    assert (frozen / ".env").is_file()
    assert "Kurulum bitti" in capsys.readouterr().out


def test_pause_only_when_frozen(monkeypatch, capsys):
    from collector import __main__ as cli

    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("kaynakta beklememeli"))
    cli._pause_if_frozen()

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    seen = {}
    monkeypatch.setattr("builtins.input", lambda prompt="": seen.setdefault("prompt", prompt))
    cli._pause_if_frozen()
    assert "Enter" in seen["prompt"]


def test_configure_console_is_noop_in_source_mode(monkeypatch):
    """Kaynaktan çalışmada konsol kodlamasına dokunulmaz (eski davranış korunur)."""
    from collector import __main__ as cli

    monkeypatch.delattr(sys, "frozen", raising=False)
    touched = []
    monkeypatch.setattr(sys.stdout, "reconfigure",
                        lambda **kw: touched.append(kw), raising=False)
    cli._configure_console()
    assert touched == []


def test_run_wrapper_pauses_and_maps_exit_codes(monkeypatch):
    from collector import __main__ as cli

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(cli, "_configure_console", lambda: None)  # testte codepage'e dokunma
    paused = []
    monkeypatch.setattr("builtins.input", lambda prompt="": paused.append(prompt) or "")

    monkeypatch.setattr(cli, "main", lambda argv=None: 0)
    assert cli.run([]) == 0

    def boom(argv=None):
        raise RuntimeError("beklenmeyen")

    monkeypatch.setattr(cli, "main", boom)
    assert cli.run([]) == 1

    def bail(argv=None):
        raise SystemExit("Eksik config: API_KEY")

    monkeypatch.setattr(cli, "main", bail)
    assert cli.run([]) == 1
    assert len(paused) == 3  # her çıkışta pencere bekletildi
