"""FastAPI uygulaması: /api/v1 API + webui/ statik servis (api_contract §7)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .db import run_migrations
from .deps import require_api_key
from .routers import admin, balance, ingest, matches, players


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
                   balance.router, admin.router):
        app.include_router(router, prefix="/api/v1", dependencies=api_deps)

    webui = Path(settings.webui_dir)
    if webui.is_dir():
        app.mount("/", StaticFiles(directory=webui, html=True), name="webui")

    return app


app = create_app()
