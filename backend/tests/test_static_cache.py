"""Statik dosya servis başlıkları (üretim olayı düzeltmesi).

GÖREV 17 deploy'unda tarayıcılar Cache-Control'süz servis edilen eski
style.css'i yeni index.html ile birleştirdi → sayfa stilsiz açıldı.
Düzeltme: TÜM statik yanıtlar `Cache-Control: no-cache` taşır (no-store
değil — ETag/304 revalidasyonu çalışmaya devam eder). API yanıtları etkilenmez.
"""
from __future__ import annotations

import pytest
from conftest import API_KEY


@pytest.fixture
def webui_client(db_path, tmp_path, monkeypatch):
    """conftest.client'ın webui'li hâli: gerçek bir statik dizin mount edilir."""
    webui_dir = tmp_path / "webui"
    (webui_dir / "assets").mkdir(parents=True)
    (webui_dir / "index.html").write_text(
        "<!doctype html><title>lol-balance</title>", encoding="utf-8"
    )
    (webui_dir / "style.css").write_text("body{margin:0}", encoding="utf-8")
    (webui_dir / "app.js").write_text("console.log('ok');", encoding="utf-8")
    (webui_dir / "assets" / "logo.svg").write_text("<svg></svg>", encoding="utf-8")

    monkeypatch.setenv("API_KEY", API_KEY)
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("WEBUI_DIR", str(webui_dir))

    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as c:
        c.headers.update({"X-API-Key": API_KEY})
        yield c
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "path",
    ["/", "/index.html", "/style.css", "/app.js", "/assets/logo.svg"],
)
def test_statik_yanitlar_no_cache_tasir(webui_client, path):
    """Her statik yol 200 döner ve Cache-Control: no-cache taşır."""
    r = webui_client.get(path)
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-cache"


def test_no_store_degil(webui_client):
    """no-store KULLANILMAZ — revalidasyonlu cache'e izin verilir."""
    r = webui_client.get("/style.css")
    assert "no-store" not in r.headers.get("cache-control", "")


def test_etag_304_davranisi_korundu(webui_client):
    """ETag hâlâ üretiliyor; If-None-Match ile 304 dönüyor ve 304 de no-cache taşıyor."""
    r1 = webui_client.get("/style.css")
    etag = r1.headers.get("etag")
    assert etag, "ETag üretimi bozulmamalı"

    r2 = webui_client.get("/style.css", headers={"If-None-Match": etag})
    assert r2.status_code == 304
    assert r2.headers.get("cache-control") == "no-cache"


def test_index_304_davranisi(webui_client):
    """html=True yolu (/) için de revalidasyon çalışır."""
    r1 = webui_client.get("/")
    etag = r1.headers.get("etag")
    assert etag
    r2 = webui_client.get("/", headers={"If-None-Match": etag})
    assert r2.status_code == 304


def test_api_yanitlari_etkilenmez(webui_client):
    """API yanıtlarına Cache-Control eklenmez (yalnız statik mount kapsanır)."""
    r = webui_client.get("/api/v1/players")
    assert r.status_code == 200
    assert "cache-control" not in r.headers
