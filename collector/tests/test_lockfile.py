import pytest

from collector.lockfile import LockfileNotFound, parse_lockfile, read_lockfile


def test_parse_lockfile():
    info = parse_lockfile("LeagueClient:12345:54321:s3cr3t:https")
    assert info.name == "LeagueClient"
    assert info.pid == 12345
    assert info.port == 54321
    assert info.password == "s3cr3t"
    assert info.protocol == "https"
    assert info.base_url == "https://127.0.0.1:54321"


def test_parse_lockfile_password_with_colon():
    info = parse_lockfile("LeagueClient:1:2:pa:ss:https")
    assert info.password == "pa:ss"
    assert info.protocol == "https"


def test_parse_lockfile_malformed():
    with pytest.raises(ValueError):
        parse_lockfile("bozuk-icerik")


def test_read_lockfile(tmp_path):
    (tmp_path / "lockfile").write_text("LeagueClient:1:9999:pw:https", encoding="utf-8")
    info = read_lockfile(tmp_path)
    assert info.port == 9999


def test_read_lockfile_missing(tmp_path):
    with pytest.raises(LockfileNotFound):
        read_lockfile(tmp_path / "yok")
