from __future__ import annotations

import json
from pathlib import Path

import pytest

from collector import config as config_module
from collector import i18n
from collector.config import Config

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture(autouse=True)
def _isolated_app_dir(tmp_path_factory, monkeypatch):
    """Testler geliştiricinin GERÇEK collector/.env'ini asla okumasın/yazmasın.

    Kaynak modda `app_dir()` paket dizinini (PACKAGE_DIR) döner ve
    `env_candidates()` buna ek olarak cwd'ye bakar — repo checkout'unda gerçek
    bir `.env` varsa, `main()`/`load_config()` çağıran her test ona ulaşır
    (LANGUAGE'sız gerçek .env'de dil çözümü stdin'den soru sormaya kalkar:
    "reading from stdin while output is captured"). İkisi de teste özel boş
    bir geçici dizine yönlendirilir; `.env` görmesi gereken testler kendi
    dosyalarını zaten açıkça yazar (ör. test_packaging'in frozen fixture'ı).
    """
    isolated = tmp_path_factory.mktemp("isolated_app_dir")
    monkeypatch.setattr(config_module, "PACKAGE_DIR", isolated)
    monkeypatch.chdir(isolated)
    yield isolated


@pytest.fixture(autouse=True)
def _reset_language():
    """Dil, süreç-genel durumdur: her test varsayılan (tr) ile başlasın."""
    i18n.reset_language()
    yield
    i18n.reset_language()


def load_fixture(name: str):
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def eog_custom():
    return load_fixture("eog_custom.json")


@pytest.fixture
def mh_game_custom():
    return load_fixture("mh_game_custom.json")


@pytest.fixture
def mh_list_page():
    return load_fixture("mh_list_page.json")


@pytest.fixture
def champion_summary():
    return load_fixture("champion_summary.json")


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        lol_dir=tmp_path / "lol",
        backend_url="http://backend.test",
        api_key="test-key",
        min_known=6,
        poll_interval_s=0.0,
        raw_archive_dir=tmp_path / "raw_archive",
        outbox_dir=tmp_path / "outbox",
        seed_roster_path=tmp_path / "seed_roster.json",
    )
