"""META/counter verisi uçları (GÖREV 34; api_contract §5 + §8 "Meta verisi").

- `GET /meta/tiers`, `GET /meta/counters`: yalnız `X-API-Key` (main.py global
  dependency); `Cache-Control: no-cache`; veri yoksa 404.
- `/admin/meta/*`: `X-Admin-Key` de ister (admin.py deseni, fix-2/fix-3).

Rating/replay/ingest ile HİÇBİR ilişkisi yoktur; yalnız `meta_snapshots`.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response

from ..config import Settings, get_settings
from ..deps import get_db, require_admin_key
from ..schemas import (
    MetaActivateOut,
    MetaCountersOut,
    MetaHistoryOut,
    MetaRefreshIn,
    MetaRefreshOut,
    MetaStatusOut,
    MetaTiersOut,
)
from ..services import meta_store

router = APIRouter()

_NOT_FOUND = {
    "tiers": "Meta tier verisi yok (etkin anlık görüntü ve tohum dosya bulunamadı).",
    "counters": "Meta counter verisi yok (etkin anlık görüntü ve tohum dosya bulunamadı).",
}


def _document(kind: str, conn: sqlite3.Connection, settings: Settings,
              response: Response) -> dict:
    doc = meta_store.get_document(conn, settings, kind)
    if doc is None:
        raise HTTPException(404, detail=_NOT_FOUND[kind])
    # Veri panelden anında değişebilir: tarayıcı revalidate etmeden kullanmasın
    # (statik mount ile aynı ilke, no-store DEĞİL).
    response.headers["Cache-Control"] = "no-cache"
    return doc


@router.get("/meta/tiers")
def get_meta_tiers(
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MetaTiersOut:
    return MetaTiersOut(**_document("tiers", conn, settings, response))


@router.get("/meta/counters")
def get_meta_counters(
    response: Response,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MetaCountersOut:
    return MetaCountersOut(**_document("counters", conn, settings, response))


@router.get("/admin/meta/status", dependencies=[Depends(require_admin_key)])
def admin_meta_status(
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MetaStatusOut:
    return MetaStatusOut(**meta_store.status(conn, settings))


@router.post("/admin/meta/refresh", dependencies=[Depends(require_admin_key)])
def admin_meta_refresh(
    body: MetaRefreshIn | None = None,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MetaRefreshOut:
    body = body or MetaRefreshIn()
    result = meta_store.refresh(
        conn, settings, dry_run=body.dry_run, force=body.force,
        region=body.region, tier=body.tier,
    )
    return MetaRefreshOut(**result)


@router.get("/admin/meta/history", dependencies=[Depends(require_admin_key)])
def admin_meta_history(
    conn: sqlite3.Connection = Depends(get_db),
) -> MetaHistoryOut:
    return MetaHistoryOut(**meta_store.history(conn))


@router.post("/admin/meta/activate/{snapshot_id}",
             dependencies=[Depends(require_admin_key)])
def admin_meta_activate(
    snapshot_id: int,
    conn: sqlite3.Connection = Depends(get_db),
) -> MetaActivateOut:
    return MetaActivateOut(**meta_store.activate(conn, snapshot_id))
