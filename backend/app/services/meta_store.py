"""META/counter verisinin DB'deki yasami (GOREV 34; api_contract §8 "Meta verisi").

Okuma onceligi: etkin `meta_snapshots` satiri -> yoksa repodaki TOHUM dosyalar
(`webui/assets/meta/{tiers,counters}.json`) -> ikisi de yoksa None (uc 404 doner).

Refresh akisi (`POST /admin/meta/refresh`): kaynak + Data Dragon cek -> iki
belgeye cevir (meta_source) -> ad dogrula -> etkin veriyle fark -> guvenlik
esigi -> (dry_run degilse ve esik gectiyse) TEK transaction'da yeni anlik goruntu
yaz + etkinlestir + saklama (en fazla 5, etkin asla silinmez).

Rating/replay/ingest ile HICBIR iliskisi yoktur; bu modul yalniz
`meta_snapshots` tablosuna yazar.

Ag erisimi `meta_source.fetch_json` uzerinden gecer; `fetch` parametresiyle
enjekte edilebilir (varsayilan cagri aninda cozulur, testler monkeypatch'ler).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import HTTPException

from . import meta_source
from .meta_source import (
    DDRAGON_CHAMPION,
    DDRAGON_VERSIONS,
    LANES,
    OPGG_URL,
    TIERS,
    build_counters_document,
    build_document,
    champion_names_by_id,
    count_counters,
    count_tiers_entries,
    diff_counters,
    diff_tiers,
    load_valid_names,
)

Fetcher = Callable[..., Any]

# Contract sabitleri (api_contract §8 "Kurallar").
SNAPSHOT_KEEP = 5
RAW_CACHE_TTL_S = 600          # ham kaynak yaniti <=10 dk onbellek
SOURCE_TIMEOUT_S = 30          # OP.GG + Data Dragon champion.json
STATUS_TIMEOUT_S = 5           # yalniz versions.json (hafif uc)
ALREADY_CURRENT_MAX_AGE_DAYS = 7
UPDATE_AVAILABLE_AGE_DAYS = 14
GUARD_MIN_RATIO = 0.5
TRIGGER_PANEL = "panel"

SUMMARY_KEYS = (
    "tiers_added", "tiers_removed", "tiers_moved",
    "counters_added", "counters_removed", "counters_changed",
)

# Surec ici kilit: ayni anda tek refresh (ikinci istek 409). Tek replica.
_refresh_lock = threading.Lock()

# (anahtar) -> (monotonic zaman, ham yanit). Anahtar: ("opgg", region, tier)
# ya da ("dd", version). Yalniz surec belleginde; anlam degismez.
_raw_cache: dict[tuple, tuple[float, Any]] = {}
_raw_cache_lock = threading.Lock()


def reset_state() -> None:
    """Onbellegi temizler (testler; surec ici bakim). Kilide dokunmaz."""
    with _raw_cache_lock:
        _raw_cache.clear()


def is_running() -> bool:
    return _refresh_lock.locked()


# --- Yardimcilar --------------------------------------------------------------


def _resolve_fetch(fetch: Optional[Fetcher]) -> Fetcher:
    # Cagri aninda cozulur: `monkeypatch.setattr(meta_source, "fetch_json", ...)`
    # router yolunda da etkili olsun.
    return fetch if fetch is not None else meta_source.fetch_json


def utc_now(now: datetime | None = None) -> datetime:
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _utc_date_str(now: datetime) -> str:
    return now.strftime("%Y-%m-%d")


def _utc_iso(now: datetime) -> str:
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def age_days(updated: Any, today: date) -> Optional[int]:
    """`updated` (YYYY-MM-DD) ile bugun arasindaki gun; ayristirilamazsa None."""
    if not isinstance(updated, str):
        return None
    try:
        d = datetime.strptime(updated[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return (today - d).days


def major_minor(version: Any) -> Optional[str]:
    """'16.19.1' -> '16.19'; '16.19' -> '16.19'; bos/None -> None."""
    if not version:
        return None
    parts = str(version).split(".")
    if len(parts) < 2:
        return str(version)
    return ".".join(parts[:2])


def _meta_dir(settings) -> Path:
    return Path(settings.webui_dir) / "assets" / "meta"


def _ddragon_dir(settings) -> Path:
    return Path(settings.webui_dir) / "assets" / "ddragon"


def vendored_dd_version(settings) -> Optional[str]:
    """webui/assets/ddragon/manifest.json -> version; yoksa/bozuksa None."""
    path = _ddragon_dir(settings) / "manifest.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    ver = data.get("version") if isinstance(data, dict) else None
    return str(ver) if ver else None


def latest_dd_version(fetch: Optional[Fetcher] = None,
                      timeout: int = STATUS_TIMEOUT_S) -> Optional[str]:
    """Data Dragon versions.json[0]; erisilemezse None (hata yutulur)."""
    try:
        versions = _resolve_fetch(fetch)(DDRAGON_VERSIONS, timeout=timeout)
        if isinstance(versions, list) and versions and versions[0]:
            return str(versions[0])
    except Exception:  # noqa: BLE001 — ag/JSON/zaman asimi: hafif ucta yalniz "bilinmiyor"
        return None
    return None


def _read_json_file(path: Path) -> Optional[dict]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return data if isinstance(data, dict) else None


def read_seed(settings, kind: str) -> Optional[dict]:
    """Tohum dosya: `tiers` -> tiers.json, `counters` -> counters.json."""
    return _read_json_file(_meta_dir(settings) / f"{kind}.json")


# --- Snapshot okuma ------------------------------------------------------------


def active_snapshot(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM meta_snapshots WHERE is_active = 1"
    ).fetchone()


def get_document(conn: sqlite3.Connection, settings, kind: str) -> Optional[dict]:
    """`GET /meta/{kind}` govdesi: belge + {origin, snapshot_id}; veri yoksa None."""
    assert kind in ("tiers", "counters")
    row = active_snapshot(conn)
    if row is not None:
        doc = json.loads(row[f"{kind}_json"])
        return {**doc, "origin": "snapshot", "snapshot_id": row["id"]}
    seed = read_seed(settings, kind)
    if seed is None:
        return None
    return {**seed, "origin": "seed", "snapshot_id": None}


def _active_info(conn: sqlite3.Connection, settings) -> Optional[dict]:
    """status.active / refresh.before'un ortak govdesi (sayimlarla)."""
    row = active_snapshot(conn)
    if row is not None:
        tiers_doc = json.loads(row["tiers_json"])
        counters_doc = json.loads(row["counters_json"])
        anchors, rows = count_counters(counters_doc.get("counters"))
        return {
            "origin": "snapshot",
            "snapshot_id": row["id"],
            "patch": tiers_doc.get("patch"),
            "updated": tiers_doc.get("updated"),
            "source": tiers_doc.get("source"),
            "created_at": row["created_at"],
            "trigger": row["trigger"],
            "tiers_entries": count_tiers_entries(tiers_doc.get("tiers")),
            "counters_anchors": anchors,
            "counters_rows": rows,
            "_tiers": tiers_doc.get("tiers") or {},
            "_counters": counters_doc.get("counters") or {},
        }
    tiers_doc = read_seed(settings, "tiers")
    counters_doc = read_seed(settings, "counters")
    if tiers_doc is None and counters_doc is None:
        return None
    head = tiers_doc if tiers_doc is not None else counters_doc
    anchors, rows = count_counters((counters_doc or {}).get("counters"))
    return {
        "origin": "seed",
        "snapshot_id": None,
        "patch": head.get("patch"),
        "updated": head.get("updated"),
        "source": head.get("source"),
        "created_at": None,
        "trigger": None,
        "tiers_entries": count_tiers_entries((tiers_doc or {}).get("tiers")),
        "counters_anchors": anchors,
        "counters_rows": rows,
        "_tiers": (tiers_doc or {}).get("tiers") or {},
        "_counters": (counters_doc or {}).get("counters") or {},
    }


def _public(info: Optional[dict], keys: tuple[str, ...]) -> Optional[dict]:
    if info is None:
        return None
    return {k: info.get(k) for k in keys}


ACTIVE_KEYS = (
    "origin", "snapshot_id", "patch", "updated", "source", "created_at", "trigger",
    "tiers_entries", "counters_anchors", "counters_rows",
)
BEFORE_KEYS = (
    "origin", "snapshot_id", "patch", "updated",
    "tiers_entries", "counters_anchors", "counters_rows",
)


# --- Status --------------------------------------------------------------------


def status(conn: sqlite3.Connection, settings, fetch: Optional[Fetcher] = None,
           now: datetime | None = None) -> dict:
    """`GET /admin/meta/status` — hafif: OP.GG'ye GITMEZ, yalniz versions.json."""
    now = utc_now(now)
    active = _active_info(conn, settings)
    vendored = vendored_dd_version(settings)
    latest = latest_dd_version(fetch)
    age = age_days(active["updated"], now.date()) if active else None

    if active is None:
        state = "empty"
    elif latest is None:
        state = "unknown"
    elif major_minor(latest) != major_minor(active["patch"]) or (
        age is not None and age > UPDATE_AVAILABLE_AGE_DAYS
    ):
        state = "update_available"
    else:
        state = "up_to_date"

    return {
        "active": _public(active, ACTIVE_KEYS),
        "ddragon": {"vendored": vendored, "latest": latest},
        "age_days": age,
        "state": state,
        "running": is_running(),
    }


# --- Refresh -------------------------------------------------------------------


def _cached(key: tuple, loader: Callable[[], Any]) -> Any:
    """<=10 dk onbellek: aynı anahtar icin kaynaga ikinci kez gidilmez."""
    now = time.monotonic()
    with _raw_cache_lock:
        hit = _raw_cache.get(key)
        if hit is not None and now - hit[0] <= RAW_CACHE_TTL_S:
            return hit[1]
    value = loader()
    with _raw_cache_lock:
        _raw_cache[key] = (time.monotonic(), value)
    return value


def _source_error(what: str, exc: BaseException) -> HTTPException:
    # 502: dis kaynak dustu; DB'ye hicbir sey yazilmadi.
    return HTTPException(502, detail=f"{what} ({exc.__class__.__name__}: {exc})")


def _fetch_dd_champions(fetch: Fetcher, dd_version: str) -> dict:
    def load():
        data = fetch(DDRAGON_CHAMPION.format(ver=dd_version), timeout=SOURCE_TIMEOUT_S)
        if not isinstance(data, dict) or not isinstance(data.get("data"), dict):
            raise ValueError("beklenen 'data' blogu yok")
        return data["data"]

    try:
        return _cached(("dd", dd_version), load)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — URLError/OSError/ValueError/KeyError
        raise _source_error(
            f"Data Dragon champion.json alınamadı (sürüm {dd_version})", exc
        ) from exc


def _fetch_source(fetch: Fetcher, region: str, tier: str) -> dict:
    url = OPGG_URL.format(region=region, tier=tier)

    def load():
        payload = fetch(url, timeout=SOURCE_TIMEOUT_S)
        if not isinstance(payload, dict):
            raise ValueError("bozuk JSON (nesne bekleniyordu)")
        if not payload.get("data"):
            raise ValueError("kaynak boş `data` döndü")
        return payload

    try:
        return _cached(("opgg", region, tier), load)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _source_error(f"Kaynak alınamadı: {url}", exc) from exc


def _guard(new_tiers: dict, new_counters: dict, new_tiers_entries: int,
           new_anchors: int, before: Optional[dict]) -> dict:
    """Guvenlik esigi (api_contract §8): bos koridor / yaridan fazla kayip."""
    reasons: list[str] = []
    empty_lanes: list[str] = []
    for lane in LANES:
        total = sum(len((new_tiers.get(lane) or {}).get(t) or []) for t in TIERS)
        if total == 0:
            empty_lanes.append(lane)
            reasons.append(f"{lane}: S+A+B toplamı 0 (boş koridor)")
    for lane in LANES:
        if len(new_counters.get(lane) or {}) == 0:
            if lane not in empty_lanes:
                empty_lanes.append(lane)
            reasons.append(f"{lane}: counter anahtarı 0 (boş koridor)")

    loss_ratio = 0.0
    if before is not None:
        prev_tiers = before["tiers_entries"] or 0
        prev_anchors = before["counters_anchors"] or 0
        if prev_tiers > 0:
            loss_ratio = round(1 - min(1.0, new_tiers_entries / prev_tiers), 4)
            if new_tiers_entries < prev_tiers * GUARD_MIN_RATIO:
                reasons.append(
                    f"tiers kaydı {prev_tiers} → {new_tiers_entries} (yarıdan fazla kayıp)"
                )
        if prev_anchors > 0 and new_anchors < prev_anchors * GUARD_MIN_RATIO:
            reasons.append(
                f"counter anahtarı {prev_anchors} → {new_anchors} (yarıdan fazla kayıp)"
            )
    return {
        "ok": not reasons,
        "loss_ratio": loss_ratio,
        "empty_lanes": empty_lanes,
        "reasons": reasons,
    }


def _build_diff(before: Optional[dict], new_tiers: dict, new_counters: dict) -> dict:
    old_tiers = before["_tiers"] if before else {}
    old_counters = before["_counters"] if before else {}
    dt = diff_tiers(old_tiers, new_tiers)
    dc = diff_counters(old_counters, new_counters)
    tiers_out: dict[str, Any] = {}
    counters_out: dict[str, Any] = {}
    summary = {k: 0 for k in SUMMARY_KEYS}
    for lane in LANES:
        d = dt[lane]
        tiers_out[lane] = {
            "added": [list(x) for x in d["added"]],
            "removed": [list(x) for x in d["removed"]],
            "moved": [list(x) for x in d["moved"]],
            "counts": {t: len((new_tiers.get(lane) or {}).get(t) or []) for t in TIERS},
        }
        summary["tiers_added"] += len(d["added"])
        summary["tiers_removed"] += len(d["removed"])
        summary["tiers_moved"] += len(d["moved"])
        c = dc[lane]
        counters_out[lane] = {
            "added": list(c["added"]),
            "removed": list(c["removed"]),
            "changed": list(c["changed"]),
            "anchors": len(new_counters.get(lane) or {}),
        }
        summary["counters_added"] += len(c["added"])
        summary["counters_removed"] += len(c["removed"])
        summary["counters_changed"] += len(c["changed"])
    return {"tiers": tiers_out, "counters": counters_out, "summary": summary}


def _write_snapshot(conn: sqlite3.Connection, *, trigger: str, source: str,
                    patch: str, dd_version: str, tiers_doc: dict, counters_doc: dict,
                    warnings: list[str], summary: dict, created_at: str) -> int:
    """TEK transaction: eskiyi pasifle + yeni etkin satir + saklama (<=5)."""
    with conn:
        conn.execute("UPDATE meta_snapshots SET is_active = 0 WHERE is_active = 1")
        cur = conn.execute(
            "INSERT INTO meta_snapshots (created_at, trigger, source, source_patch,"
            " dd_version, tiers_json, counters_json, warnings_json, summary_json,"
            " is_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
            (
                created_at, trigger, source, patch, dd_version,
                json.dumps(tiers_doc, ensure_ascii=False),
                json.dumps(counters_doc, ensure_ascii=False),
                json.dumps(warnings, ensure_ascii=False),
                json.dumps(summary, ensure_ascii=False),
            ),
        )
        snapshot_id = int(cur.lastrowid)
        # Saklama: etkin olmayan en eskiler silinir; en yeni 5 (etkin dahil) kalir.
        conn.execute(
            "DELETE FROM meta_snapshots WHERE is_active = 0 AND id NOT IN"
            " (SELECT id FROM meta_snapshots ORDER BY id DESC LIMIT ?)",
            (SNAPSHOT_KEEP,),
        )
    return snapshot_id


def refresh(conn: sqlite3.Connection, settings, *, dry_run: bool = False,
            force: bool = False, region: str = "global", tier: str = "platinum_plus",
            fetch: Optional[Fetcher] = None, now: datetime | None = None) -> dict:
    """`POST /admin/meta/refresh` (api_contract §8). Kilit: ikinci istek 409."""
    if not _refresh_lock.acquire(blocking=False):
        raise HTTPException(409, detail="Meta güncellemesi zaten koşuyor.")
    try:
        return _refresh_locked(
            conn, settings, dry_run=dry_run, force=force, region=region, tier=tier,
            fetch=_resolve_fetch(fetch), now=utc_now(now),
        )
    finally:
        _refresh_lock.release()


def _refresh_locked(conn, settings, *, dry_run, force, region, tier, fetch, now) -> dict:
    t0 = time.monotonic()
    before = _active_info(conn, settings)
    warnings: list[str] = []

    # 1) Data Dragon: vendored surum; yoksa en yeni (versions.json).
    vendored = vendored_dd_version(settings)
    latest: Optional[str] = None
    latest_fetched = False
    dd_version = vendored
    if not dd_version:
        try:
            versions = fetch(DDRAGON_VERSIONS, timeout=SOURCE_TIMEOUT_S)
            dd_version = str(versions[0])
        except Exception as exc:  # noqa: BLE001
            raise _source_error("Data Dragon sürüm listesi alınamadı", exc) from exc
        latest, latest_fetched = dd_version, True
    dd_data = _fetch_dd_champions(fetch, dd_version)
    id_to_name = champion_names_by_id(dd_data)

    champions_path = _ddragon_dir(settings) / "champions.json"
    valid_names, _valid_src = load_valid_names(champions_path, id_to_name)
    if not champions_path.is_file():
        # Panelde gösterilen uyarı: sunucu DOSYA YOLU UI'a sızmaz (load_valid_names'in
        # yol içeren metni yalnız CLI çıktısı içindir).
        warnings.append(
            "champions.json yok (Data Dragon varlıkları indirilmemiş); adlar Data "
            f"Dragon champion.json'a ({len(id_to_name)} ad) karşı doğrulandı"
        )

    # 2) Kaynak (TEK istek; <=10 dk onbellek).
    payload = _fetch_source(fetch, region, tier)

    # 3) Belgeler.
    source_label = f"op.gg ({region}, {tier})"
    updated = _utc_date_str(now)
    patch_fallback = major_minor(dd_version) or ""
    tiers_doc, tiers_warnings = build_document(
        payload, id_to_name, valid_names, source=source_label, updated=updated,
        patch_fallback=patch_fallback,
    )
    counters_doc, counters_warnings = build_counters_document(
        payload, id_to_name, valid_names, source=source_label, updated=updated,
        patch_fallback=patch_fallback,
    )
    warnings.extend(f"tiers: {w}" for w in tiers_warnings)
    warnings.extend(f"counters: {w}" for w in counters_warnings)

    new_tiers = tiers_doc["tiers"]
    new_counters = counters_doc["counters"]
    tiers_entries = count_tiers_entries(new_tiers)
    anchors, rows = count_counters(new_counters)
    after = {
        "patch": tiers_doc["patch"],
        "updated": updated,
        "source": source_label,
        "dd_version": dd_version,
        "tiers_entries": tiers_entries,
        "counters_anchors": anchors,
        "counters_rows": rows,
    }

    # 4) Fark + guvenlik esigi.
    diff = _build_diff(before, new_tiers, new_counters)
    guard = _guard(new_tiers, new_counters, tiers_entries, anchors, before)

    if not latest_fetched:
        latest = latest_dd_version(fetch)

    # 5) Karar.
    reason: Optional[str] = None
    if not guard["ok"] and not force:
        reason = "guard_rejected"
    elif (
        not dry_run and not force and before is not None
        and after["patch"] == before["patch"]
    ):
        age = age_days(before["updated"], now.date())
        if age is not None and age <= ALREADY_CURRENT_MAX_AGE_DAYS:
            reason = "already_current"

    written = False
    snapshot_id: Optional[int] = None
    if not dry_run and reason is None:
        summary = {**diff["summary"], "tiers_entries": tiers_entries,
                   "counters_anchors": anchors, "counters_rows": rows}
        snapshot_id = _write_snapshot(
            conn, trigger=TRIGGER_PANEL, source=source_label, patch=after["patch"],
            dd_version=dd_version, tiers_doc=tiers_doc, counters_doc=counters_doc,
            warnings=warnings, summary=summary, created_at=_utc_iso(now),
        )
        written = True

    return {
        "written": written,
        "dry_run": dry_run,
        "snapshot_id": snapshot_id,
        "reason": reason,
        "before": _public(before, BEFORE_KEYS),
        "after": after,
        "ddragon": {"vendored": vendored, "latest": latest},
        "diff": diff,
        "guard": guard,
        "warnings": warnings,
        "duration_ms": int((time.monotonic() - t0) * 1000),
    }


# --- History / activate --------------------------------------------------------


def history(conn: sqlite3.Connection) -> dict:
    """`GET /admin/meta/history`: id azalan, en fazla 5."""
    active = active_snapshot(conn)
    items = []
    for row in conn.execute(
        "SELECT * FROM meta_snapshots ORDER BY id DESC LIMIT ?", (SNAPSHOT_KEEP,)
    ):
        tiers_doc = json.loads(row["tiers_json"])
        counters_doc = json.loads(row["counters_json"])
        summary_all = json.loads(row["summary_json"] or "{}")
        anchors, rows = count_counters(counters_doc.get("counters"))
        items.append({
            "id": row["id"],
            "created_at": row["created_at"],
            "trigger": row["trigger"],
            "patch": row["source_patch"],
            "updated": tiers_doc.get("updated"),
            "source": row["source"],
            "dd_version": row["dd_version"],
            "is_active": bool(row["is_active"]),
            "tiers_entries": count_tiers_entries(tiers_doc.get("tiers")),
            "counters_anchors": anchors,
            "counters_rows": rows,
            "summary": {k: int(summary_all.get(k, 0) or 0) for k in SUMMARY_KEYS},
            "warnings_count": len(json.loads(row["warnings_json"] or "[]")),
        })
    return {"active_id": active["id"] if active else None, "items": items}


def activate(conn: sqlite3.Connection, snapshot_id: int) -> dict:
    """`POST /admin/meta/activate/{id}`: tek transaction; zaten etkinse no-op."""
    row = conn.execute(
        "SELECT id, source_patch, is_active FROM meta_snapshots WHERE id = ?",
        (snapshot_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, detail=f"Anlık görüntü bulunamadı: {snapshot_id}.")
    if not row["is_active"]:
        with conn:
            conn.execute("UPDATE meta_snapshots SET is_active = 0 WHERE is_active = 1")
            conn.execute(
                "UPDATE meta_snapshots SET is_active = 1 WHERE id = ?", (snapshot_id,)
            )
    return {"active_id": snapshot_id, "patch": row["source_patch"]}
