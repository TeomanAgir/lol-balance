"""GÖREV 16 Faz C: arayüzün SAF parçaları + CLI giriş davranışı.

Buradaki testlerin (bir tanesi hariç) hiçbiri ekran/tkinter GEREKTİRMEZ:
`collector.gui` modülü tkinter'ı modül düzeyinde import etmez ve durum makinesi,
log kuyruğu, sihirbaz adaptörü, özet biçimleyicileri saf fonksiyonlardır.
Gerçek pencereyi açan tek test ekran yoksa `skip` edilir.
"""

from __future__ import annotations

import ast
import logging
import queue
from pathlib import Path

import pytest

from collector import gui, i18n
from collector.commands import (
    STATUS_CATCHUP,
    STATUS_CONNECTED,
    STATUS_LIVE,
    STATUS_RECONNECTING,
    STATUS_STOPPED,
    STATUS_WAITING_CLIENT,
)
from collector.gui import (
    JOB_BACKFILL,
    JOB_ITEMS,
    JOB_LIVE,
    JOB_POSITIONS,
    JOB_SETTINGS,
    JOBS,
    NO_ANSWER,
    YES_ANSWER,
    DialogConsole,
    QueueLogHandler,
    UiState,
    WizardCancelled,
    drain_queue,
    excess_lines,
    is_yes_no_prompt,
    status_text,
    tkinter_available,
)


# --------------------------------------------------------------------------- #
# 1. Import sınırı: tkinter modül düzeyinde import EDİLMEZ
# --------------------------------------------------------------------------- #


def test_gui_module_does_not_import_tkinter_at_module_level():
    """Ekransız CI, `collector.gui`'yi toplayabilmeli — tkinter geç import edilir."""
    tree = ast.parse(Path(gui.__file__).read_text(encoding="utf-8"))
    top_level_names: list[str] = []
    for node in tree.body:  # yalnız modül düzeyi (fonksiyon gövdeleri hariç)
        if isinstance(node, ast.Import):
            top_level_names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            top_level_names.append(node.module or "")
    assert not [name for name in top_level_names if name.split(".")[0] == "tkinter"]


def _imported_modules(path: Path) -> set[str]:
    """Dosyadaki TÜM (modül düzeyi + gömülü) import adları."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
    return names


def test_only_gui_module_imports_tkinter():
    """tkinter YALNIZ gui.py'den import edilir (diğer modüller ekransız koşabilmeli)."""
    package_dir = Path(gui.__file__).resolve().parent
    offenders = [
        path.name
        for path in sorted(package_dir.glob("*.py"))
        if path.name != "gui.py"
        and any(name.split(".")[0] == "tkinter" for name in _imported_modules(path))
    ]
    assert offenders == []


# --------------------------------------------------------------------------- #
# 2. Durum makinesi (düğme kilitleri)
# --------------------------------------------------------------------------- #


def test_idle_state_enables_every_button():
    state = UiState()
    assert state.busy is False
    assert state.button_states() == {job: True for job in JOBS}
    assert state.live_button_key() == "gui.btn.live_start"


@pytest.mark.parametrize("job", [JOB_BACKFILL, JOB_ITEMS, JOB_POSITIONS, JOB_SETTINGS])
def test_running_job_locks_every_button(job):
    state = UiState()
    state.start(job)
    assert state.busy is True
    assert state.button_states() == {name: False for name in JOBS}
    assert state.can_start(JOB_LIVE) is False


def test_live_keeps_its_own_button_open_as_stop():
    state = UiState()
    state.start(JOB_LIVE)
    states = state.button_states()
    assert states[JOB_LIVE] is True  # "Durdur" olarak açık
    assert all(not enabled for job, enabled in states.items() if job != JOB_LIVE)
    assert state.live_button_key() == "gui.btn.live_stop"

    assert state.request_stop() is True
    assert state.button_states() == {job: False for job in JOBS}  # durdurulurken hepsi kilitli
    assert state.request_stop() is False  # ikinci istek yok sayılır


def test_request_stop_is_only_for_live():
    state = UiState()
    state.start(JOB_ITEMS)
    assert state.request_stop() is False


def test_finish_returns_to_idle_and_second_start_is_rejected():
    state = UiState()
    state.start(JOB_ITEMS)
    with pytest.raises(RuntimeError):
        state.start(JOB_BACKFILL)
    state.finish()
    assert state.button_states() == {job: True for job in JOBS}
    state.start(JOB_BACKFILL)  # artık serbest


# --------------------------------------------------------------------------- #
# 3. Log kuyruğu
# --------------------------------------------------------------------------- #


def test_queue_handler_formats_and_enqueues():
    sink: "queue.Queue[str]" = queue.Queue()
    handler = QueueLogHandler(sink)
    logger = logging.getLogger("collector.test.gui")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        logger.info("maç gönderildi: %s", "123")
    finally:
        logger.removeHandler(handler)
        logger.setLevel(logging.NOTSET)

    lines = drain_queue(sink)
    assert len(lines) == 1
    assert "maç gönderildi: 123" in lines[0]
    assert "INFO" in lines[0]


def test_full_queue_drops_lines_without_raising():
    """Log yazımı ASLA iş thread'ini bloklamaz/patlatmaz: kuyruk dolarsa satır düşer."""
    sink: "queue.Queue[str]" = queue.Queue(maxsize=2)
    handler = QueueLogHandler(sink)
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "satır", None, None)
    for _ in range(10):
        handler.emit(record)  # istisna fırlatmamalı
    assert sink.qsize() == 2


def test_drain_queue_respects_limit_and_never_blocks():
    sink: "queue.Queue[int]" = queue.Queue()
    for value in range(5):
        sink.put(value)
    assert drain_queue(sink, limit=2) == [0, 1]
    assert drain_queue(sink) == [2, 3, 4]
    assert drain_queue(sink) == []  # boş kuyruk → boş liste, bekleme yok


@pytest.mark.parametrize(
    "total,maximum,expected", [(10, 100, 0), (100, 100, 0), (150, 100, 50), (0, 100, 0)]
)
def test_excess_lines(total, maximum, expected):
    assert excess_lines(total, maximum) == expected


# --------------------------------------------------------------------------- #
# 4. Sihirbaz adaptörü (paylaşılan mantık, iki kopya YOK)
# --------------------------------------------------------------------------- #


class FakeDialogs:
    def __init__(self, answers: list[str | None]):
        self._answers = list(answers)
        self.asked: list[tuple[str, str]] = []
        self.shown: list[str] = []
        self.echoed: list[str] = []

    def ask(self, prompt: str, context: str):
        self.asked.append((prompt, context))
        if not self._answers:
            raise AssertionError(f"beklenmeyen soru: {prompt!r}")
        return self._answers.pop(0)

    def show(self, text: str) -> None:
        self.shown.append(text)

    def echo(self, text: str) -> None:
        self.echoed.append(text)

    def console(self) -> DialogConsole:
        return DialogConsole(ask=self.ask, show=self.show, echo=self.echo)


def test_dialog_console_carries_printed_context_into_the_next_question():
    dialogs = FakeDialogs(["cevap"])
    console = dialogs.console()
    console.write("UYARI: klasör boş")
    assert console.read("Soru: ") == "cevap"
    prompt, context = dialogs.asked[0]
    assert prompt == "Soru: "
    assert context == "UYARI: klasör boş"


def test_dialog_console_cancel_raises():
    console = FakeDialogs([None]).console()
    with pytest.raises(WizardCancelled):
        console.read("Soru: ")


def test_dialog_console_flush_shows_remaining_output_once():
    dialogs = FakeDialogs([])
    console = dialogs.console()
    console.write("Kaydedildi:")
    console.write("  dosya : x")
    console.flush()
    console.flush()  # ikinci çağrı boş → kutu tekrar açılmaz
    assert dialogs.shown == ["Kaydedildi:\n  dosya : x"]


def test_dialog_console_never_echoes_answers():
    """Gizlilik: API anahtarı yanıtı log'a/echo'ya YAZILMAZ."""
    dialogs = FakeDialogs(["gizli-anahtar"])
    console = dialogs.console()
    console.read("API anahtarı: ")
    assert "gizli-anahtar" not in "\n".join(dialogs.echoed)


def test_is_yes_no_prompt_matches_only_the_lol_dir_confirmation():
    i18n.set_language("tr")
    assert is_yes_no_prompt(i18n.msg("wizard.lol_dir_confirm")) is True
    assert is_yes_no_prompt(i18n.msg("wizard.ask_api_key")) is False
    i18n.set_language("en")
    assert is_yes_no_prompt(i18n.msg("wizard.lol_dir_confirm")) is True


def test_yes_no_answers_are_understood_by_the_wizard_in_both_languages(tmp_path, monkeypatch):
    """Adaptörün ürettiği "y"/"n" yanıtları sihirbazın kendi doğrulamasından geçer."""
    from collector import wizard as wiz

    detected = tmp_path / "bulunan"
    detected.mkdir()
    (detected / "lockfile").write_text("", encoding="utf-8")
    real = tmp_path / "gercek"
    real.mkdir()
    (real / "lockfile").write_text("", encoding="utf-8")
    monkeypatch.setattr(wiz, "detect_lol_dir", lambda *a, **k: (detected, "x"))

    for language, answer, expected in (("tr", YES_ANSWER, detected), ("en", NO_ANSWER, real)):
        target = tmp_path / f"{language}.env"
        # sırayla: dil, backend URL (Enter), anahtar, klasör onayı [, elle klasör], cihaz adı
        answers = (
            [language, "", "k1", answer]
            + ([str(real)] if answer == NO_ANSWER else [])
            + [""]
        )
        console = FakeDialogs(answers).console()
        i18n.set_language(language)
        wiz.run_wizard(
            target,
            input_fn=console.read,
            print_fn=console.write,
            check=lambda url, key: wiz.BackendCheck(True, "ok"),
        )
        from collector.config import _load_env_file

        assert _load_env_file(target)["LOL_DIR"] == str(expected)


def test_wizard_runs_end_to_end_through_the_dialog_console(tmp_path, monkeypatch):
    """Sihirbaz mantığı TEK kopyadır: arayüz aynı `run_wizard`'ı G/Ç değiştirerek koşar."""
    from collector import wizard as wiz
    from collector.config import _load_env_file

    lol_dir = tmp_path / "lol"
    lol_dir.mkdir()
    (lol_dir / "lockfile").write_text("", encoding="utf-8")
    monkeypatch.setattr(wiz, "detect_lol_dir", lambda *a, **k: (lol_dir, "kayıt defteri"))
    target = tmp_path / ".env"

    # dil, backend URL (Enter), anahtar, LOL klasörü onayı, cihaz adı
    dialogs = FakeDialogs(["tr", "", "gizli-anahtar", YES_ANSWER, "masaustu"])
    console = dialogs.console()
    wiz.run_wizard(
        target,
        input_fn=console.read,
        print_fn=console.write,
        check=lambda url, key: wiz.BackendCheck(True, "ok"),
    )
    console.flush()

    values = _load_env_file(target)
    assert values["API_KEY"] == "gizli-anahtar"
    assert values["LOL_DIR"] == str(lol_dir)
    assert values["CLIENT_ID"] == "masaustu"
    assert values["LANGUAGE"] == "tr"
    assert dialogs.asked[0][0] == i18n.LANGUAGE_PROMPT  # ilk soru yine dil
    assert "gizli-anahtar" not in "\n".join(dialogs.shown + dialogs.echoed)  # özet maskeli


# --------------------------------------------------------------------------- #
# 5. Metinler / özetler
# --------------------------------------------------------------------------- #


def test_status_text_shows_state_and_last_match():
    i18n.set_language("tr")
    assert "bekliyor" in status_text("idle")
    assert "—" in status_text("idle")
    assert "6874231955" in status_text("live", "6874231955")


ALL_STATUS_KEYS = (
    "idle",
    "stopping",
    JOB_BACKFILL,
    JOB_ITEMS,
    JOB_POSITIONS,
    JOB_SETTINGS,
    STATUS_WAITING_CLIENT,
    STATUS_CONNECTED,
    STATUS_CATCHUP,
    STATUS_LIVE,
    STATUS_RECONNECTING,
    STATUS_STOPPED,
)


@pytest.mark.parametrize("language", ["tr", "en"])
def test_every_gui_key_used_by_the_window_exists(language):
    """Eksik anahtar sessizce anahtar adını basar — burada kırılsın."""
    i18n.set_language(language)
    keys = (
        ["gui.title", "gui.banner", "gui.first_run", "gui.unavailable", "gui.need_setup",
         "gui.config_error", "gui.status_line", "gui.last_match_none", "gui.live.stopping",
         "gui.backfill.no_lockfile", "gui.dry_run.title", "gui.dry_run.started",
         "gui.dry_run.question", "gui.dry_run.cancelled", "gui.dry_run.applied",
         "gui.update.banner", "gui.update.button", "gui.update.open_failed",
         "gui.wizard.title", "gui.wizard.cancelled", "gui.close.title", "gui.close.question",
         "gui.job.started", "gui.job.done", "gui.job.failed", "gui.btn.live_start",
         "gui.btn.live_stop", "cli.help.console"]
        + [f"gui.status.{key}" for key in ALL_STATUS_KEYS]
        + [f"gui.job.name.{job}" for job in JOBS]
        + [f"gui.btn.{job}" for job in (JOB_BACKFILL, JOB_ITEMS, JOB_POSITIONS, JOB_SETTINGS)]
    )
    missing = [key for key in keys if key not in i18n.MESSAGES[language]]
    assert missing == []


def test_summaries_report_the_numbers_that_matter():
    from collector.backfill import BackfillStats
    from collector.backfill_items import ItemsBackfillStats
    from collector.backfill_positions import PositionBackfillStats

    i18n.set_language("tr")
    text = gui.format_backfill_summary(BackfillStats(scanned=40, customs=7, sent=3))
    assert "40" in text and "7" in text and "3" in text

    text = gui.format_items_summary(
        ItemsBackfillStats(archives=9, matched=8, updated=8, participants_sent=80)
    )
    assert "80" in text

    text = gui.format_positions_summary(
        PositionBackfillStats(archives=9, matched=8, updated=8, positions_sent=79, unresolved=1)
    )
    assert "79" in text and "1" in text


# --------------------------------------------------------------------------- #
# 6. CLI giriş davranışı (GUI dispatch, --console, eski komutlar bozulmadı)
# --------------------------------------------------------------------------- #


def _configured_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOL_DIR", str(tmp_path))
    monkeypatch.setenv("BACKEND_URL", "http://backend.test")
    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.setenv("COLLECTOR_NO_WIZARD", "1")


def test_no_arguments_opens_the_window(monkeypatch):
    from collector import __main__ as cli

    monkeypatch.setattr(gui, "tkinter_available", lambda: True)
    monkeypatch.setattr(gui, "run_gui", lambda: 0)
    monkeypatch.setattr(
        cli, "run_live_command", lambda *a, **k: pytest.fail("konsol canlı mod açılmamalıydı")
    )
    assert cli.main([]) == 0


def test_no_arguments_falls_back_to_console_when_tkinter_is_missing(
    monkeypatch, tmp_path, capsys
):
    from collector import __main__ as cli

    _configured_env(monkeypatch, tmp_path)
    monkeypatch.setattr(gui, "tkinter_available", lambda: False)
    monkeypatch.setattr(gui, "run_gui", lambda: pytest.fail("tkinter yokken açılmamalıydı"))
    monkeypatch.setattr(cli, "report_backend_check", lambda url, key: None)
    started: list[str] = []
    monkeypatch.setattr(cli, "run_live_command", lambda cfg, sender: started.append("live"))

    assert cli.main([]) == 0
    assert started == ["live"]
    assert "tkinter" in capsys.readouterr().out


def test_console_flag_keeps_the_old_console_live_mode(monkeypatch, tmp_path):
    from collector import __main__ as cli

    _configured_env(monkeypatch, tmp_path)
    monkeypatch.setattr(gui, "run_gui", lambda: pytest.fail("--console pencere AÇMAZ"))
    monkeypatch.setattr(cli, "report_backend_check", lambda url, key: None)
    started: list[str] = []
    monkeypatch.setattr(cli, "run_live_command", lambda cfg, sender: started.append("live"))

    assert cli.main(["--console"]) == 0
    assert started == ["live"]


def test_backfill_command_still_runs_from_the_terminal(monkeypatch, tmp_path):
    from collector import __main__ as cli
    from collector.backfill import BackfillStats

    _configured_env(monkeypatch, tmp_path)
    monkeypatch.setattr(gui, "run_gui", lambda: pytest.fail("backfill pencere AÇMAZ"))
    monkeypatch.setattr(cli, "report_backend_check", lambda url, key: None)
    seen: list = []

    def fake_backfill(config, sender, *, since=None):
        seen.append(since)
        return BackfillStats(scanned=1)

    monkeypatch.setattr(cli, "run_backfill_command", fake_backfill)
    assert cli.main(["backfill", "--since", "2026-01-02"]) == 0
    assert [str(value) for value in seen] == ["2026-01-02"]


def test_backfill_reports_missing_lockfile_as_exit_code_1(monkeypatch, tmp_path):
    from collector import __main__ as cli
    from collector.lockfile import LockfileNotFound

    _configured_env(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "report_backend_check", lambda url, key: None)

    def boom(config, sender, *, since=None):
        raise LockfileNotFound("lockfile yok")

    monkeypatch.setattr(cli, "run_backfill_command", boom)
    assert cli.main(["--backfill"]) == 1


# --------------------------------------------------------------------------- #
# 7. Frozen + windowed (konsolsuz exe) güvenliği
# --------------------------------------------------------------------------- #


def test_pause_is_skipped_without_a_console(monkeypatch):
    """--windowed exe: stdin yok → input() ÇAĞRILMAZ ("lost sys.stdin" patlaması yok)."""
    import sys

    from collector import __main__ as cli

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "stdin", None)
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("konsolsuzda beklememeli"))
    cli._pause_if_frozen()


def test_configure_console_tolerates_missing_streams(monkeypatch):
    import sys

    from collector import __main__ as cli

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    cli._configure_console()  # istisna fırlatmamalı


def test_crash_is_written_next_to_the_exe_when_there_is_no_console(
    monkeypatch, _isolated_app_dir
):
    """Konsolsuz exe çökerse yığın izi kaybolmaz, teşhis dosyasına düşer."""
    import sys

    from collector import __main__ as cli

    monkeypatch.setattr(sys, "stderr", None)
    try:
        raise RuntimeError("beklenmeyen çökme")
    except RuntimeError:
        cli._report_crash()

    crash = _isolated_app_dir / cli.CRASH_LOG_NAME
    assert crash.is_file()
    assert "beklenmeyen çökme" in crash.read_text(encoding="utf-8")


def test_crash_prefers_the_console_when_there_is_one(monkeypatch, _isolated_app_dir, capsys):
    from collector import __main__ as cli

    try:
        raise RuntimeError("konsola yazılsın")
    except RuntimeError:
        cli._report_crash()

    assert "konsola yazılsın" in capsys.readouterr().err
    assert not (_isolated_app_dir / cli.CRASH_LOG_NAME).exists()


def test_logging_uses_a_null_handler_without_stderr(monkeypatch):
    import sys

    from collector import __main__ as cli

    root = logging.getLogger()
    original = list(root.handlers)
    root.handlers.clear()
    monkeypatch.setattr(sys, "stderr", None)
    try:
        cli._configure_logging()
        assert root.handlers and all(
            isinstance(handler, logging.NullHandler) for handler in root.handlers
        )
    finally:
        root.handlers[:] = original


# --------------------------------------------------------------------------- #
# 8. Gerçek pencere (ekran yoksa atlanır)
# --------------------------------------------------------------------------- #


def _withdrawn_root():
    try:
        import tkinter
    except Exception:
        return None
    try:
        root = tkinter.Tk()
    except Exception:  # ekran/DISPLAY yok
        return None
    root.withdraw()
    return root


@pytest.mark.skipif(not tkinter_available(), reason="tkinter kurulu değil")
def test_window_smoke(monkeypatch):
    root = _withdrawn_root()
    if root is None:
        pytest.skip("ekran yok (headless)")

    app = gui.CollectorApp(root=root, update_checker=lambda *a, **k: None)
    try:
        assert app.buttons[JOB_LIVE]["state"] == "normal"

        # gömülü log alanı: kuyruğa yazılan satır pump ile widget'a düşer
        logging.getLogger("collector.test.window").info("selam pencere")
        app.pump()
        assert "selam pencere" in app.log_text.get("1.0", "end")

        # iş koşarken düğmeler kilitlenir, bitince açılır
        app.state.start(JOB_ITEMS)
        app.refresh_buttons()
        assert app.buttons[JOB_BACKFILL]["state"] == "disabled"
        app.state.finish()
        app.refresh_buttons()
        assert app.buttons[JOB_BACKFILL]["state"] == "normal"

        # güncelleme bandı yalnız yeni sürüm varsa görünür
        app.show_update(gui.UpdateInfo(version="9.9.9"))
        assert "9.9.9" in app.update_label["text"]
    finally:
        app.shutdown()
    assert app.log_handler not in logging.getLogger().handlers
