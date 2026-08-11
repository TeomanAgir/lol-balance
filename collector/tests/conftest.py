from __future__ import annotations

import json
from pathlib import Path

import pytest

from collector.config import Config

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


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
