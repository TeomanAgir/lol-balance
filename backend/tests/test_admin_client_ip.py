"""GÖREV 30b-B — admin hız sınırı GERÇEK istemci IP'si başına sayar.

Canlıda pod nginx ingress arkasındadır; ProxyHeadersMiddleware olmadan her
istemci ingress IP'si olarak görünür ve "IP başına 10 deneme" herkes için tek
sayaca düşer (10 yanlış deneme paneli herkese kilitler). Header'a güvenme
kararı `create_app`'teki middleware'de, FORWARDED_ALLOW_IPS ile verilir;
`deps._client_ip` header okumaz.
"""
from __future__ import annotations

from contextlib import contextmanager

from conftest import ADMIN_KEY, API_KEY

PING = "/api/v1/admin/ping"


@contextmanager
def _client(db_path, monkeypatch, forwarded_allow_ips: str | None):
    monkeypatch.setenv("API_KEY", API_KEY)
    monkeypatch.setenv("ADMIN_KEY", ADMIN_KEY)
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("WEBUI_DIR", str(db_path.parent / "_no_webui_"))
    if forwarded_allow_ips is None:
        monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    else:
        monkeypatch.setenv("FORWARDED_ALLOW_IPS", forwarded_allow_ips)

    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as c:
            c.headers.update({"X-API-Key": API_KEY})
            yield c
    finally:
        get_settings.cache_clear()


def _wrong(client, ip: str | None):
    headers = {"X-Admin-Key": "yanlis"}
    if ip is not None:
        headers["X-Forwarded-For"] = ip
    return client.get(PING, headers=headers).status_code


def test_each_forwarded_ip_gets_its_own_counter(db_path, monkeypatch):
    """Varsayılan ("*"): her istemci kendi 429'unu alır; üçüncüsü etkilenmez."""
    from app import deps

    with _client(db_path, monkeypatch, None) as c:
        for ip in ("203.0.113.1", "203.0.113.2"):
            for i in range(deps.ADMIN_FAIL_LIMIT):
                assert _wrong(c, ip) == 403, f"{ip} {i}. deneme"
            assert _wrong(c, ip) == 429
        # Diğer iki IP kilitli ama üçüncü IP'nin İLK denemesi 403 (429 değil).
        assert _wrong(c, "203.0.113.3") == 403
        # Ingress zinciri: en soldaki (gerçek istemci) sayılır.
        assert _wrong(c, "203.0.113.1, 10.0.0.5") == 429


def test_header_ignored_when_trusted_list_empty(db_path, monkeypatch):
    """FORWARDED_ALLOW_IPS boş: header yok sayılır, herkes soket adresinde."""
    from app import deps

    with _client(db_path, monkeypatch, "") as c:
        for i in range(deps.ADMIN_FAIL_LIMIT):
            ip = f"203.0.113.{i + 1}"
            assert _wrong(c, ip) == 403, f"{i}. deneme"
        # Farklı X-Forwarded-For'lar aynı sayaca yazıldı → yeni "IP" de 429.
        assert _wrong(c, "198.51.100.77") == 429
        assert _wrong(c, None) == 429


def test_untrusted_peer_cannot_spoof_forwarded_for(db_path, monkeypatch):
    """Bağlanan güvenilen listede değilse header yok sayılır (sahte IP ile
    sayaç seyreltilemez). TestClient'ın soket adresi "testclient"tir."""
    from app import deps

    with _client(db_path, monkeypatch, "10.0.0.1") as c:
        for i in range(deps.ADMIN_FAIL_LIMIT):
            assert _wrong(c, f"203.0.113.{i + 1}") == 403
        assert _wrong(c, "198.51.100.77") == 429


def test_correct_key_resets_only_own_counter(db_path, monkeypatch):
    """Başarılı doğrulama yalnız O istemcinin sayacını sıfırlar."""
    from app import deps

    monkeypatch.setattr(deps, "ADMIN_FAIL_LIMIT", 2)
    with _client(db_path, monkeypatch, None) as c:
        for ip in ("203.0.113.1", "203.0.113.2"):
            assert _wrong(c, ip) == 403
            assert _wrong(c, ip) == 403
        # .1 kilitli; .2 kilitli. .3 doğru anahtarla girer → başkasını açmaz.
        r = c.get(PING, headers={"X-Admin-Key": ADMIN_KEY,
                                 "X-Forwarded-For": "203.0.113.3"})
        assert r.status_code == 204
        assert _wrong(c, "203.0.113.1") == 429
