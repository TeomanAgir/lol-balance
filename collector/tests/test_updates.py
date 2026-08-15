"""GÖREV 16 Faz B: sürüm karşılaştırma (saf) + güncelleme kontrolünün hata yutması."""

from __future__ import annotations

import json

import pytest

from collector import updates
from collector.updates import (
    RELEASES_PAGE_URL,
    UpdateInfo,
    check_for_update,
    is_newer,
    normalize_version,
    parse_version,
)


# --------------------------------------------------------------------------- #
# 1. Saf sürüm karşılaştırma
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text,expected",
    [
        ("0.3.0", (0, 3, 0)),
        ("v0.3.0", (0, 3, 0)),
        ("  v1.2.3  ", (1, 2, 3)),
        ("v10.0.1", (10, 0, 1)),
        ("0.3", (0, 3)),
        ("v0.3.0-beta.1", (0, 3, 0)),  # ek son ek yok sayılır
        ("v0.3.0+win", (0, 3, 0)),
    ],
)
def test_parse_version_reads_numeric_prefix(text, expected):
    assert parse_version(text) == expected


@pytest.mark.parametrize("text", ["", None, "latest", "vNext", "sürüm-yok"])
def test_parse_version_rejects_non_versions(text):
    assert parse_version(text) is None


@pytest.mark.parametrize(
    "candidate,current",
    [("0.3.0", "0.2.0"), ("v0.2.1", "0.2.0"), ("1.0.0", "0.99.99"), ("0.2.0.1", "0.2.0")],
)
def test_is_newer_true(candidate, current):
    assert is_newer(candidate, current) is True


@pytest.mark.parametrize(
    "candidate,current",
    [
        ("0.2.0", "0.2.0"),
        ("v0.2.0", "0.2.0"),  # etiketteki "v" fark yaratmaz
        ("0.2", "0.2.0"),  # eksik hane sıfır sayılır → eşit
        ("0.1.9", "0.2.0"),
        ("bozuk", "0.2.0"),  # ayrıştırılamayan aday asla "yeni" değildir
        ("0.3.0", "bozuk"),
        (None, "0.2.0"),
    ],
)
def test_is_newer_false(candidate, current):
    assert is_newer(candidate, current) is False


def test_normalize_version_strips_v_prefix():
    assert normalize_version("v0.3.0") == "0.3.0"
    assert normalize_version("0.3.0-beta") == "0.3.0"


# --------------------------------------------------------------------------- #
# 2. check_for_update (sahte urlopen)
# --------------------------------------------------------------------------- #


class FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc) -> bool:
        return False


def opener_for(payload, calls: list | None = None):
    """`payload`: dict → JSON, str/bytes → ham gövde, Exception → fırlatılır."""

    def opener(url: str, timeout: float):
        if calls is not None:
            calls.append((url, timeout))
        if isinstance(payload, Exception):
            raise payload
        body = payload if isinstance(payload, (str, bytes)) else json.dumps(payload)
        return FakeResponse(body.encode("utf-8") if isinstance(body, str) else body)

    return opener


def test_reports_newer_release():
    info = check_for_update("0.2.0", opener=opener_for({"tag_name": "v0.3.0"}))
    assert info == UpdateInfo(version="0.3.0", url=RELEASES_PAGE_URL)


def test_same_or_older_release_is_not_reported():
    assert check_for_update("0.2.0", opener=opener_for({"tag_name": "v0.2.0"})) is None
    assert check_for_update("0.3.0", opener=opener_for({"tag_name": "v0.2.9"})) is None


def test_download_url_is_fixed_not_taken_from_payload():
    """Güvenlik: API yanıtındaki adres tarayıcıda AÇILMAZ, sabit adres kullanılır."""
    info = check_for_update(
        "0.2.0",
        opener=opener_for({"tag_name": "v9.9.9", "html_url": "https://evil.example/x"}),
    )
    assert info is not None
    assert info.url == RELEASES_PAGE_URL


@pytest.mark.parametrize(
    "payload",
    [
        OSError("ağ yok"),
        TimeoutError("zaman aşımı"),
        RuntimeError("beklenmeyen"),
        "bu JSON değil",
        b"\xff\xfe bozuk",
        {"message": "Not Found"},  # tag_name yok
        {"tag_name": None},
        [1, 2, 3],  # sözlük bile değil
    ],
)
def test_every_failure_is_swallowed(payload):
    assert check_for_update("0.2.0", opener=opener_for(payload)) is None


def test_single_request_with_short_timeout():
    calls: list = []
    check_for_update("0.2.0", opener=opener_for({"tag_name": "v0.1.0"}, calls), timeout=1.5)
    assert calls == [(updates.LATEST_RELEASE_API, 1.5)]
    assert updates.DEFAULT_TIMEOUT_S <= 10  # açılış hiçbir koşulda beklemez


def test_api_and_page_urls_point_to_the_project_repo():
    assert updates.LATEST_RELEASE_API.startswith("https://api.github.com/repos/TeomanAgir/lol-balance/")
    assert RELEASES_PAGE_URL == "https://github.com/TeomanAgir/lol-balance/releases/latest"
