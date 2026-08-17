"""FastAPI uygulaması: /api/v1 API + webui/ statik servis (api_contract §7)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from starlette.responses import Response
from starlette.types import Scope

from .config import get_settings
from .db import run_migrations
from .deps import require_api_key
from .routers import (
    admin,
    balance,
    health,
    highlights,
    ingest,
    matches,
    nemesis,
    players,
    roulette,
)


class NoCacheStaticFiles(StaticFiles):
    """Statik yanıtlara `Cache-Control: no-cache` ekler.

    Amaç: deploy sonrası tarayıcının eski CSS/JS'i taze index.html ile
    karıştırmasını önlemek. no-store DEĞİL: ETag/If-None-Match revalidasyonu
    (304) çalışmaya devam eder; sadece "revalidate etmeden kullanma" denir.
    Yalnız webui mount'unu etkiler, /api/v1 yanıtlarına dokunmaz.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def _validation_detail(exc: RequestValidationError) -> str:
    """Pydantic hatalarını contract'ın tek-string Türkçe detail formatına çevirir."""
    parts = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(x) for x in err["loc"] if x != "body")
        parts.append(f"{loc}: {err['msg']}" if loc else err["msg"])
    return "Şema ihlali — " + "; ".join(parts)


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        run_migrations(settings.db_path)
        yield

    app = FastAPI(title="lol-balance backend", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422, content={"detail": _validation_detail(exc)}
        )

    api_deps = [Depends(require_api_key)]
    for router in (ingest.router, players.router, matches.router,
                   balance.router, admin.router, highlights.router,
                   nemesis.router, health.router, roulette.router):
        app.include_router(router, prefix="/api/v1", dependencies=api_deps)

    webui = Path(settings.webui_dir)
    if webui.is_dir():
        app.mount("/", NoCacheStaticFiles(directory=webui, html=True), name="webui")

    return app


app = create_app()
