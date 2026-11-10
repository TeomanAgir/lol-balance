"""GÖREV 37 — /api/v1 önbellek yalıtım başlıkları (api_contract "İstemci tarafı yalıtım").

`Vary: X-API-Key` her API yanıtında (hatalar dahil); Cache-Control'ü uç koymadıysa
`no-store`; uç koyduysa (meta: no-cache) dokunulmaz; statik mount etkilenmez.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, Response
from conftest import ADMIN_KEY, API_KEY, make_payload


def _vary_tokens(r):
    return [t.strip().lower() for t in r.headers.get("vary", "").split(",")]


def _assert_isolated(r):
    assert "x-api-key" in _vary_tokens(r), dict(r.headers)
    assert r.headers.get("cache-control") == "no-store", dict(r.headers)


def test_successful_get_has_headers(client):
    r = client.get("/api/v1/players")
    assert r.status_code == 200
    _assert_isolated(r)


def test_successful_post_has_headers(client):
    r = client.post("/api/v1/ingest/match", json=make_payload())
    assert r.status_code == 201, r.text
    _assert_isolated(r)


def test_401_has_headers(client):
    r = client.get("/api/v1/players", headers={"X-API-Key": "yanlis"})
    assert r.status_code == 401
    _assert_isolated(r)
    r = client.get("/api/v1/players", headers={"X-API-Key": ""})
    _assert_isolated(r)


def test_admin_403_has_headers(client):
    r = client.get("/api/v1/admin/ping", headers={"X-Admin-Key": "yanlis"})
    assert r.status_code == 403
    _assert_isolated(r)


def test_admin_429_has_headers(client, monkeypatch):
    from app import deps

    monkeypatch.setattr(deps, "ADMIN_FAIL_LIMIT", 1)
    client.get("/api/v1/admin/ping", headers={"X-Admin-Key": "yanlis"})
    r = client.get("/api/v1/admin/ping", headers={"X-Admin-Key": "yanlis"})
    assert r.status_code == 429
    _assert_isolated(r)


def test_admin_503_has_headers(db_path, monkeypatch):
    monkeypatch.setenv("API_KEY", API_KEY)
    monkeypatch.delenv("ADMIN_KEY", raising=False)
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("WEBUI_DIR", str(db_path.parent / "_no_webui_"))
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        r = c.get(
            "/api/v1/admin/ping",
            headers={"X-API-Key": API_KEY, "X-Admin-Key": ADMIN_KEY},
        )
    get_settings.cache_clear()
    assert r.status_code == 503
    _assert_isolated(r)


def test_404_has_headers(client):
    r = client.get("/api/v1/matches/999999")
    assert r.status_code == 404
    _assert_isolated(r)
    r = client.get("/api/v1/yok-boyle-bir-uc")
    assert r.status_code == 404
    _assert_isolated(r)


def test_422_has_headers(client):
    r = client.post("/api/v1/ingest/match", json={"bozuk": True})
    assert r.status_code == 422
    _assert_isolated(r)


def test_endpoint_own_cache_control_and_vary_preserved_and_merged():
    """Uç kendi Cache-Control'ünü koyduysa dokunulmaz; mevcut Vary birleştirilir."""
    from fastapi.testclient import TestClient

    from app.main import ApiCacheHeadersMiddleware

    app = FastAPI()
    app.add_middleware(ApiCacheHeadersMiddleware)

    @app.get("/api/v1/x")
    def x(response: Response):
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Vary"] = "Accept-Encoding"
        return {"ok": 1}

    @app.get("/api/v1/y")
    def y(response: Response):
        response.headers["Vary"] = "x-api-key"
        return {"ok": 1}

    @app.get("/disari")
    def disari():
        return {"ok": 1}

    c = TestClient(app)
    r = c.get("/api/v1/x")
    assert r.headers["cache-control"] == "no-cache"
    assert _vary_tokens(r) == ["accept-encoding", "x-api-key"]
    r = c.get("/api/v1/y")
    assert r.headers["vary"] == "x-api-key"  # zaten var: tekrar eklenmez
    r = c.get("/disari")
    assert "cache-control" not in r.headers and "vary" not in r.headers


def test_meta_endpoints_keep_no_cache_and_get_vary(client):
    r = client.get("/api/v1/meta/tiers")
    if r.status_code == 200:
        assert r.headers["cache-control"] == "no-cache"
    else:  # tohum yok → 404, uç Cache-Control koymaz
        assert r.headers["cache-control"] == "no-store"
    assert "x-api-key" in _vary_tokens(r)


def test_static_mount_unaffected(db_path, tmp_path, monkeypatch):
    webui_dir = tmp_path / "webui"
    webui_dir.mkdir()
    (webui_dir / "index.html").write_text("<title>x</title>", encoding="utf-8")
    monkeypatch.setenv("API_KEY", API_KEY)
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("WEBUI_DIR", str(webui_dir))
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        r = c.get("/")
        r2 = c.get("/index.html")
    get_settings.cache_clear()
    for resp in (r, r2):
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-cache"
        assert "no-store" not in resp.headers["cache-control"]
        assert "x-api-key" not in resp.headers.get("vary", "").lower()
