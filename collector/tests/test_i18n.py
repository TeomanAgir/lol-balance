"""GÖREV 6: i18n sözlük bütünlüğü (contract §4) + dil çözümü (contract §1/§3)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from collector import i18n
from collector.i18n import (
    DEFAULT_LANGUAGE,
    LANGUAGE_PROMPT,
    MESSAGES,
    SUPPORTED_LANGUAGES,
    language_from_env_file,
    msg,
    persist_language,
    resolve_language,
    set_language,
)

TURKISH_CHARS = re.compile(r"[çğıöşüÇĞİÖŞÜ]")


# --------------------------------------------------------------------------- #
# 1. Sözlük bütünlüğü (contract §4/1-2)
# --------------------------------------------------------------------------- #


def test_supported_languages_and_default():
    assert set(MESSAGES) == set(SUPPORTED_LANGUAGES) == {"tr", "en"}
    assert DEFAULT_LANGUAGE == "tr"


def test_key_sets_are_identical():
    assert set(MESSAGES["tr"]) == set(MESSAGES["en"])


def test_no_empty_values():
    for lang, table in MESSAGES.items():
        for key, value in table.items():
            assert isinstance(value, str) and value, f"{lang}:{key} boş"


def test_en_values_have_no_turkish_characters():
    for key, value in MESSAGES["en"].items():
        assert not TURKISH_CHARS.search(value), f"en:{key} Türkçe karakter içeriyor: {value!r}"


def test_language_prompt_is_the_contract_text_in_both_languages():
    """Contract §1: soru dil bilinmeden sorulur — iki sözlükte de aynı İngilizce metin."""
    assert LANGUAGE_PROMPT == "Select language / Dil secin [tr/en]: "
    assert MESSAGES["tr"]["lang.prompt"] == MESSAGES["en"]["lang.prompt"] == LANGUAGE_PROMPT


# --------------------------------------------------------------------------- #
# 2. msg()
# --------------------------------------------------------------------------- #


def test_msg_returns_language_specific_text_with_params():
    set_language("tr")
    assert "Çalışma klasörü" in msg("cli.workdir", path="X")
    set_language("en")
    assert msg("cli.workdir", path="X") == "Working folder: X"


def test_msg_missing_key_returns_key_never_empty():
    assert msg("no.such.key") == "no.such.key"


# --------------------------------------------------------------------------- #
# 3. Dil çözümü (contract §1/§3)
# --------------------------------------------------------------------------- #


class FakeInput:
    """input() sahtesi: verilen yanıtları sırayla döner, sorulan prompt'ları kaydeder."""

    def __init__(self, answers: list[str] | None = None):
        self._answers = list(answers or [])
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._answers:
            raise AssertionError("beklenmeyen input() çağrısı (soru sorulmamalıydı)")
        return self._answers.pop(0)


def _write_env(path: Path, extra: str = "") -> Path:
    path.write_text(
        "LOL_DIR=C:\\Riot Games\\League of Legends\n"
        "BACKEND_URL=https://lol.example.com\n"
        "API_KEY=k\n" + extra,
        encoding="utf-8",
    )
    return path


def test_config_with_language_is_used_silently(tmp_path: Path, monkeypatch):
    """Config'de dil varsa soru SORULMAZ (input çağrısı asserte düşer)."""
    env = _write_env(tmp_path / ".env", "LANGUAGE=en\n")
    monkeypatch.setattr("builtins.input", FakeInput())  # emniyet: global input da yasak

    assert resolve_language(env, input_fn=FakeInput()) == "en"
    assert i18n.get_language() == "en"


def test_missing_language_reasks_once_then_persists_lowercase(tmp_path: Path):
    """Geçersiz giriş ("xx") aynı soruyu tekrarlatır; "EN" kabul edilir ve 'en' yazılır."""
    env = _write_env(tmp_path / ".env")
    fake = FakeInput(["xx", "EN"])

    assert resolve_language(env, input_fn=fake) == "en"
    assert fake.prompts == [LANGUAGE_PROMPT, LANGUAGE_PROMPT]  # bir kez yeniden soruldu
    assert language_from_env_file(env) == "en"


def test_persisted_language_respected_on_next_resolution(tmp_path: Path):
    env = _write_env(tmp_path / ".env")
    resolve_language(env, input_fn=FakeInput(["tr"]))
    i18n.reset_language()

    # İkinci çözümde soru yok: FakeInput cevapsız — çağrılırsa test düşer.
    assert resolve_language(env, input_fn=FakeInput()) == "tr"


def test_persist_adds_field_alongside_existing_ones(tmp_path: Path):
    """Dil alanı mevcut config'e EKLENİR; diğer alanlar aynen korunur."""
    env = _write_env(tmp_path / ".env")
    before = dict(
        line.split("=", 1) for line in env.read_text(encoding="utf-8").splitlines() if "=" in line
    )

    persist_language("en", env)

    text = env.read_text(encoding="utf-8")
    after = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    assert after.pop("LANGUAGE") == "en"
    assert after == before  # mevcut alanlar yeniden yapılandırılmadı

    persist_language("tr", env)  # var olan satır yerinde güncellenir, çoğalmaz
    assert env.read_text(encoding="utf-8").count("LANGUAGE=") == 1
    assert language_from_env_file(env) == "tr"


def test_no_env_file_keeps_default_without_prompting(tmp_path: Path):
    assert resolve_language(tmp_path / "yok.env", input_fn=FakeInput()) == DEFAULT_LANGUAGE


def test_allow_prompt_false_never_asks(tmp_path: Path):
    env = _write_env(tmp_path / ".env")
    assert resolve_language(env, input_fn=FakeInput(), allow_prompt=False) == DEFAULT_LANGUAGE


def test_invalid_language_value_in_config_treated_as_missing(tmp_path: Path):
    env = _write_env(tmp_path / ".env", "LANGUAGE=de\n")
    assert language_from_env_file(env) is None
    assert resolve_language(env, input_fn=FakeInput(["tr"])) == "tr"


# --------------------------------------------------------------------------- #
# 4. Sihirbaz entegrasyonu (contract §1: İLK soru dil seçimidir)
# --------------------------------------------------------------------------- #


def _console(answers: list[str]):
    from .test_packaging import Console

    return Console(answers)


def test_wizard_asks_language_first_and_persists_it(tmp_path: Path, monkeypatch):
    from collector import wizard as wiz

    lol_dir = tmp_path / "lol"
    lol_dir.mkdir()
    (lol_dir / "lockfile").write_text("", encoding="utf-8")
    monkeypatch.setattr(wiz, "detect_lol_dir", lambda *a, **k: (lol_dir, "x"))
    target = tmp_path / ".env"

    console = _console(["en", "", "key-1", ""])
    wiz.run_wizard(
        target,
        input_fn=console.read,
        print_fn=console.write,
        check=lambda url, key: wiz.BackendCheck(True, "ok"),
    )

    assert console.prompts[0] == LANGUAGE_PROMPT  # diğer her sorudan önce
    assert language_from_env_file(target) == "en"
    assert "Backend address" in console.prompts[1]  # sihirbazın devamı seçilen dilde
    assert "Saved:" in console.text


def test_wizard_skips_language_question_when_config_has_it(tmp_path: Path, monkeypatch):
    from collector import wizard as wiz

    lol_dir = tmp_path / "lol"
    lol_dir.mkdir()
    (lol_dir / "lockfile").write_text("", encoding="utf-8")
    monkeypatch.setattr(wiz, "detect_lol_dir", lambda *a, **k: (lol_dir, "x"))
    target = _write_env(tmp_path / ".env", "LANGUAGE=en\n")

    console = _console(["", "key-1", ""])  # dil cevabı YOK — soru da yok
    wiz.run_wizard(
        target,
        input_fn=console.read,
        print_fn=console.write,
        check=lambda url, key: wiz.BackendCheck(True, "ok"),
    )

    assert LANGUAGE_PROMPT not in console.prompts
    assert language_from_env_file(target) == "en"  # --setup sonrası da korunur
