"""META/counter verisi uçları + meta_store (GÖREV 34; api_contract §5/§8, db_schema 0007).

Kapsam:
  1. Okuma önceliği: snapshot > tohum dosya > 404; `Cache-Control: no-cache`;
     yalnız X-API-Key (admin anahtarı gerekmez).
  2. status: DD versions monkeypatch; erişilemezse `unknown`; empty/up_to_date/
     update_available; running.
  3. refresh: dry_run yazmaz; already_current; guard red (boş koridor, %50 kayıp)
     + force; 502 yolunda sıfır yazma; kilit 409; tek etkin satır; saklama 5;
     ≤10 dk ham yanıt önbelleği; trigger/updated/created_at.
  4. activate idempotent / 404; history sırası.
  5. Admin anahtarı 403/503 (test_admin_key.py deseni).
  6. Rating tablolarına hiç dokunmaz (ingest sonrası tarihçe bit-bit aynı).
Ağ YOK: `meta_source.fetch_json` monkeypatch'lenir.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from conftest import ADMIN_KEY, API_KEY, make_role_payload

from app.services import meta_source, meta_store
from app.services.meta_source import DDRAGON_CHAMPION, DDRAGON_VERSIONS, LANES

VENDORED = "16.16.1"
DD_DATA = {
    "Ahri": {"key": "103", "name": "Ahri"},
    "MonkeyKing": {"key": "62", "name": "Wukong"},
    "Garen": {"key": "86", "name": "Garen"},
    "Nasus": {"key": "75", "name": "Nasus"},
    "Zed": {"key": "238", "name": "Zed"},
    "Thresh": {"key": "412", "name": "Thresh"},
    "Jinx": {"key": "222", "name": "Jinx"},
    "LeeSin": {"key": "64", "name": "Lee Sin"},
}
CHAMPIONS_JSON = {entry["name"]: {"icon": f"champion/{k}.png"} for k, entry in DD_DATA.items()}


def _pos(name, tier=1, rank=1, counters=None):
    return {
        "name": name,
        "stats": {"win_rate": 0.51, "pick_rate": 0.05,
                  "tier_data": {"tier": tier, "rank": rank}},
        "counters": counters or [],
    }


def make_source_payload(patch: str = "16.19", lanes=LANES) -> dict:
    """Her koridorda ≥1 S/A/B kaydı ve ≥1 counter anahtarı olan tam kaynak."""
    lane_src = {"top": "TOP", "jungle": "JUNGLE", "middle": "MID",
                "bottom": "ADC", "utility": "SUPPORT"}
    anchors = {"top": (86, 75), "jungle": (64, 238), "middle": (103, 62),
               "bottom": (222, 412), "utility": (412, 222)}
    data = []
    for lane in lanes:
        a, b = anchors[lane]
        data.append({"id": a, "positions": [
            _pos(lane_src[lane], 1, 1, counters=[{"champion_id": b, "play": 100, "win": 45}])
        ]})
        data.append({"id": b, "positions": [
            _pos(lane_src[lane], 2, 1, counters=[{"champion_id": a, "play": 100, "win": 55}])
        ]})
    return {"meta": {"version": patch}, "data": data}


SEED_TIERS = {
    "patch": "16.16", "updated": "2026-08-17", "source": "op.gg (global, platinum_plus)",
    "tiers": {lane: {"S": [{"name": "Garen", "win_rate": 0.5, "pick_rate": 0.1}],
                     "A": [], "B": []} for lane in LANES},
}
SEED_COUNTERS = {
    "patch": "16.16", "updated": "2026-08-17", "source": "op.gg (global, platinum_plus)",
    "counters": {lane: {"Garen": [{"champion": "Nasus", "games": 10, "win_rate_against": 0.6}]}
                 for lane in LANES},
}


class FakeNet:
    """`meta_source.fetch_json` yerine geçer: URL → yanıt; çağrıları sayar."""

    def __init__(self, source=None, versions=None, dd=None):
        self.source = source if source is not None else make_source_payload()
        self.versions = versions if versions is not None else ["16.19.1", "16.18.1"]
        self.dd = dd if dd is not None else DD_DATA
        self.calls: list[str] = []
        self.fail_source: Exception | None = None
        self.fail_dd: Exception | None = None
        self.fail_versions: Exception | None = None

    def __call__(self, url: str, timeout: int = 30):
        self.calls.append(url)
        if url == DDRAGON_VERSIONS:
            if self.fail_versions:
                raise self.fail_versions
            return self.versions
        if url.startswith("https://ddragon.leagueoflegends.com/cdn/"):
            if self.fail_dd:
                raise self.fail_dd
            return {"data": self.dd}
        if url.startswith("https://lol-api-champion.op.gg/"):
            if self.fail_source:
                raise self.fail_source
            return self.source
        raise AssertionError(f"beklenmeyen URL: {url}")

    def count(self, prefix: str) -> int:
        return sum(1 for u in self.calls if u.startswith(prefix))


@pytest.fixture(autouse=True)
def _meta_state_reset():
    meta_store.reset_state()
    yield
    meta_store.reset_state()


@pytest.fixture
def webui_dir(tmp_path):
    """Tohum meta dosyaları + vendored Data Dragon manifest/champions."""
    root = tmp_path / "webui"
    (root / "assets" / "meta").mkdir(parents=True)
    (root / "assets" / "ddragon").mkdir(parents=True)
    (root / "assets" / "meta" / "tiers.json").write_text(
        json.dumps(SEED_TIERS), encoding="utf-8")
    (root / "assets" / "meta" / "counters.json").write_text(
        json.dumps(SEED_COUNTERS), encoding="utf-8")
    (root / "assets" / "ddragon" / "manifest.json").write_text(
        json.dumps({"version": VENDORED}), encoding="utf-8")
    (root / "assets" / "ddragon" / "champions.json").write_text(
        json.dumps(CHAMPIONS_JSON), encoding="utf-8")
    return root


@contextmanager
def _client(db_path, monkeypatch, webui_dir, admin_key=ADMIN_KEY, attach_admin=True):
    monkeypatch.setenv("API_KEY", API_KEY)
    if admin_key is None:
        monkeypatch.delenv("ADMIN_KEY", raising=False)
    else:
        monkeypatch.setenv("ADMIN_KEY", admin_key)
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("WEBUI_DIR", str(webui_dir))

    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    try:
        with TestClient(app) as c:
            headers = {"X-API-Key": API_KEY}
            if attach_admin and admin_key:
                headers["X-Admin-Key"] = admin_key
            c.headers.update(headers)
            yield c
    finally:
        get_settings.cache_clear()


@pytest.fixture
def net(monkeypatch):
    fake = FakeNet()
    monkeypatch.setattr(meta_source, "fetch_json", fake)
    return fake


@pytest.fixture
def mc(db_path, monkeypatch, webui_dir, net):
    """Tohumlu webui + sahte ağ + admin anahtarlı istemci."""
    with _client(db_path, monkeypatch, webui_dir) as c:
        yield c


def _rows(db, sql="SELECT id, is_active, source_patch, trigger FROM meta_snapshots ORDER BY id"):
    conn = db()
    try:
        return [tuple(r) for r in conn.execute(sql)]
    finally:
        conn.close()


def _refresh(c, **body):
    r = c.post("/api/v1/admin/meta/refresh", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ── 1) Okuma önceliği ────────────────────────────────────────────────────


def test_get_tiers_and_counters_from_seed_when_no_snapshot(mc):
    r = mc.get("/api/v1/meta/tiers")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"
    body = r.json()
    assert body["origin"] == "seed" and body["snapshot_id"] is None
    assert body["patch"] == "16.16" and body["tiers"] == SEED_TIERS["tiers"]

    r = mc.get("/api/v1/meta/counters")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"
    body = r.json()
    assert body["origin"] == "seed" and body["counters"] == SEED_COUNTERS["counters"]


def test_get_meta_404_when_neither_snapshot_nor_seed(db_path, monkeypatch, tmp_path):
    with _client(db_path, monkeypatch, tmp_path / "_no_webui_") as c:
        for kind in ("tiers", "counters"):
            r = c.get(f"/api/v1/meta/{kind}")
            assert r.status_code == 404, kind
            assert r.json()["detail"]


def test_get_meta_prefers_snapshot_over_seed(mc, db):
    res = _refresh(mc)
    assert res["written"] is True
    sid = res["snapshot_id"]
    for kind in ("tiers", "counters"):
        body = mc.get(f"/api/v1/meta/{kind}").json()
        assert body["origin"] == "snapshot" and body["snapshot_id"] == sid
        assert body["patch"] == "16.19"
        assert set(body[kind]) == set(LANES)
    # Belge DB'deki JSON ile birebir (origin/snapshot_id eklenir, başka alan değişmez).
    conn = db()
    tiers_json = json.loads(conn.execute(
        "SELECT tiers_json FROM meta_snapshots WHERE id = ?", (sid,)).fetchone()[0])
    conn.close()
    body = mc.get("/api/v1/meta/tiers").json()
    body.pop("origin"); body.pop("snapshot_id")
    assert body == tiers_json


def test_get_meta_requires_only_api_key(db_path, monkeypatch, webui_dir, net):
    """GET /meta/* admin anahtarı İSTEMEZ; X-API-Key yoksa 401."""
    with _client(db_path, monkeypatch, webui_dir, admin_key=None) as c:
        assert c.get("/api/v1/meta/tiers").status_code == 200
        assert c.get("/api/v1/meta/counters").status_code == 200
        c.headers.pop("X-API-Key")
        assert c.get("/api/v1/meta/tiers").status_code == 401


def test_seed_only_one_file_present(db_path, monkeypatch, tmp_path, net):
    root = tmp_path / "webui"
    (root / "assets" / "meta").mkdir(parents=True)
    (root / "assets" / "meta" / "tiers.json").write_text(json.dumps(SEED_TIERS), encoding="utf-8")
    with _client(db_path, monkeypatch, root) as c:
        assert c.get("/api/v1/meta/tiers").status_code == 200
        assert c.get("/api/v1/meta/counters").status_code == 404
        st = c.get("/api/v1/admin/meta/status").json()
        assert st["active"]["origin"] == "seed"
        assert st["active"]["counters_anchors"] == 0


# ── 2) status ────────────────────────────────────────────────────────────


def test_status_seed_update_available_by_patch(mc, net):
    r = mc.get("/api/v1/admin/meta/status")
    assert r.status_code == 200
    st = r.json()
    assert st["active"] == {
        "origin": "seed", "snapshot_id": None, "patch": "16.16", "updated": "2026-08-17",
        "source": "op.gg (global, platinum_plus)", "created_at": None, "trigger": None,
        "tiers_entries": 5, "counters_anchors": 5, "counters_rows": 5,
    }
    assert st["ddragon"] == {"vendored": VENDORED, "latest": "16.19.1"}
    assert st["state"] == "update_available"
    assert isinstance(st["age_days"], int) and st["age_days"] > 14
    assert st["running"] is False
    # Hafif uç: OP.GG'ye GİTMEZ, yalnız versions.json.
    assert net.count("https://lol-api-champion.op.gg/") == 0
    assert net.calls == [DDRAGON_VERSIONS]


def test_status_unknown_when_ddragon_unreachable(mc, net):
    net.fail_versions = OSError("timeout")
    st = mc.get("/api/v1/admin/meta/status").json()
    assert st["ddragon"]["latest"] is None
    assert st["state"] == "unknown"
    assert st["active"]["origin"] == "seed"


def test_status_empty_when_no_data(db_path, monkeypatch, tmp_path, net):
    with _client(db_path, monkeypatch, tmp_path / "_no_webui_") as c:
        st = c.get("/api/v1/admin/meta/status").json()
        assert st["active"] is None and st["age_days"] is None
        assert st["state"] == "empty"
        assert st["ddragon"] == {"vendored": None, "latest": "16.19.1"}


def test_status_up_to_date_and_age_threshold(mc, net, monkeypatch):
    _refresh(mc)  # patch 16.19 == latest major.minor, updated = bugün
    st = mc.get("/api/v1/admin/meta/status").json()
    assert st["active"]["origin"] == "snapshot"
    assert st["active"]["trigger"] == "panel"
    assert st["age_days"] == 0
    assert st["state"] == "up_to_date"

    # age_days > 14 → update_available (aynı patch olsa da)
    real_status = meta_store.status
    far = datetime(2027, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(meta_store, "status",
                        lambda conn, settings, fetch=None, now=None: real_status(
                            conn, settings, fetch=fetch, now=far))
    st = mc.get("/api/v1/admin/meta/status").json()
    assert st["age_days"] > 14 and st["state"] == "update_available"


def test_status_running_reflects_lock(mc):
    assert meta_store._refresh_lock.acquire(blocking=False)
    try:
        assert mc.get("/api/v1/admin/meta/status").json()["running"] is True
    finally:
        meta_store._refresh_lock.release()
    assert mc.get("/api/v1/admin/meta/status").json()["running"] is False


# ── 3) refresh ───────────────────────────────────────────────────────────


def test_refresh_writes_snapshot_and_response_shape(mc, db, net):
    res = _refresh(mc)
    assert set(res) == {"written", "dry_run", "snapshot_id", "reason", "before", "after",
                        "ddragon", "diff", "guard", "warnings", "duration_ms"}
    assert res["written"] is True and res["dry_run"] is False and res["reason"] is None
    assert res["before"] == {
        "origin": "seed", "snapshot_id": None, "patch": "16.16", "updated": "2026-08-17",
        "tiers_entries": 5, "counters_anchors": 5, "counters_rows": 5,
    }
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert res["after"] == {
        "patch": "16.19", "updated": today, "source": "op.gg (global, platinum_plus)",
        "dd_version": VENDORED, "tiers_entries": 10, "counters_anchors": 10,
        "counters_rows": 10,
    }
    assert res["ddragon"] == {"vendored": VENDORED, "latest": "16.19.1"}
    assert set(res["diff"]) == {"tiers", "counters", "summary"}
    assert set(res["diff"]["tiers"]) == set(LANES)
    top = res["diff"]["tiers"]["top"]
    assert top["counts"] == {"S": 1, "A": 1, "B": 0}
    assert top["added"] == [["Nasus", "A"]] and top["removed"] == [] and top["moved"] == []
    # middle: Garen (seed) çıktı, Ahri S + Wukong A girdi
    mid = res["diff"]["tiers"]["middle"]
    assert mid["removed"] == [["Garen", "S"]]
    assert mid["added"] == [["Ahri", "S"], ["Wukong", "A"]]
    assert res["diff"]["counters"]["top"] == {
        "added": ["Nasus"], "removed": [], "changed": [], "anchors": 2}
    assert res["diff"]["summary"] == {
        "tiers_added": 9, "tiers_removed": 4, "tiers_moved": 0,
        "counters_added": 9, "counters_removed": 4, "counters_changed": 0,
    }
    assert res["guard"] == {"ok": True, "loss_ratio": 0.0, "empty_lanes": [], "reasons": []}
    assert res["warnings"] == []
    assert isinstance(res["duration_ms"], int)

    rows = _rows(db)
    assert rows == [(res["snapshot_id"], 1, "16.19", "panel")]
    conn = db()
    row = conn.execute("SELECT * FROM meta_snapshots").fetchone()
    conn.close()
    assert row["dd_version"] == VENDORED
    assert row["source"] == "op.gg (global, platinum_plus)"
    assert row["created_at"].endswith("Z") and "T" in row["created_at"]
    assert json.loads(row["summary_json"])["tiers_added"] == 9
    assert json.loads(row["warnings_json"]) == []
    # ddragon latest tek bir kez istendi; OP.GG tek istek
    assert net.count("https://lol-api-champion.op.gg/") == 1


def test_refresh_dry_run_computes_but_never_writes(mc, db, net):
    res = _refresh(mc, dry_run=True)
    assert res["dry_run"] is True and res["written"] is False
    assert res["snapshot_id"] is None and res["reason"] is None
    assert res["after"]["patch"] == "16.19"
    assert res["diff"]["summary"]["tiers_added"] == 9
    assert _rows(db) == []
    assert mc.get("/api/v1/meta/tiers").json()["origin"] == "seed"


def test_refresh_dry_run_then_write_uses_raw_cache(mc, net):
    _refresh(mc, dry_run=True)
    assert net.count("https://lol-api-champion.op.gg/") == 1
    res = _refresh(mc)
    assert res["written"] is True
    # "Kontrol et" → "Güncelle": kaynağa ve DD champion.json'a İKİNCİ kez gidilmez.
    assert net.count("https://lol-api-champion.op.gg/") == 1
    assert net.count(DDRAGON_CHAMPION.format(ver=VENDORED)) == 1


def test_refresh_raw_cache_expires_after_ttl(mc, net, monkeypatch):
    _refresh(mc, dry_run=True)
    monkeypatch.setattr(meta_store, "RAW_CACHE_TTL_S", -1)  # her şey süresi dolmuş sayılır
    _refresh(mc, dry_run=True)
    assert net.count("https://lol-api-champion.op.gg/") == 2


def test_refresh_raw_cache_is_per_region_tier(mc, net):
    _refresh(mc, dry_run=True)
    _refresh(mc, dry_run=True, region="kr", tier="emerald_plus")
    assert net.count("https://lol-api-champion.op.gg/api/global/") == 1
    assert net.count("https://lol-api-champion.op.gg/api/kr/") == 1
    assert any("tier=emerald_plus" in u for u in net.calls)


def test_refresh_already_current_short_circuit(mc, db, net):
    first = _refresh(mc)
    assert first["written"] is True
    # Aynı patch (16.19) + updated bugün (age 0 ≤ 7) → hiçbir şey yazılmaz.
    second = _refresh(mc)
    assert second["written"] is False and second["reason"] == "already_current"
    assert second["snapshot_id"] is None
    assert second["before"]["snapshot_id"] == first["snapshot_id"]
    assert len(_rows(db)) == 1
    # dry_run her zaman tam hesaplar, reason already_current DÖNMEZ
    dry = _refresh(mc, dry_run=True)
    assert dry["reason"] is None and dry["written"] is False
    # force eşiği aşar → yeni satır
    forced = _refresh(mc, force=True)
    assert forced["written"] is True and forced["reason"] is None
    assert len(_rows(db)) == 2


def test_refresh_already_current_not_applied_to_old_seed(mc, net):
    """Tohum aynı patch'te olsa bile 7 günden eskiyse yazılır."""
    net.source = make_source_payload(patch="16.16")
    res = _refresh(mc)
    assert res["written"] is True and res["reason"] is None


def test_refresh_new_patch_after_old_snapshot_writes(mc, db, net, monkeypatch):
    _refresh(mc)
    net.source = make_source_payload(patch="16.20")
    meta_store.reset_state()
    res = _refresh(mc)
    assert res["written"] is True and res["after"]["patch"] == "16.20"
    rows = _rows(db)
    assert [r[1] for r in rows] == [0, 1]


def test_refresh_guard_rejects_empty_tier_lane(mc, db, net):
    net.source = make_source_payload(lanes=("top", "jungle", "middle", "bottom"))
    res = _refresh(mc)
    assert res["written"] is False and res["reason"] == "guard_rejected"
    assert res["guard"]["ok"] is False
    assert res["guard"]["empty_lanes"] == ["utility"]
    assert any("utility" in r for r in res["guard"]["reasons"])
    assert _rows(db) == []


def test_refresh_guard_rejects_empty_counter_lane(mc, db, net):
    src = make_source_payload()
    # utility koridorunda counter listelerini boşalt (tier kayıtları kalır)
    for champ in src["data"]:
        for p in champ["positions"]:
            if p["name"] == "SUPPORT":
                p["counters"] = []
    net.source = src
    res = _refresh(mc)
    assert res["reason"] == "guard_rejected"
    assert res["guard"]["empty_lanes"] == ["utility"]
    assert res["diff"]["tiers"]["utility"]["counts"]["S"] == 1
    assert _rows(db) == []


def make_wide_source(patch: str, per_lane: int) -> dict:
    """Her koridorda `per_lane` S kaydı ve `per_lane` counter anahtarı (boş koridor yok)."""
    lane_src = {"top": "TOP", "jungle": "JUNGLE", "middle": "MID",
                "bottom": "ADC", "utility": "SUPPORT"}
    pool = [86, 75, 64, 238, 103, 62, 222, 412]
    assert per_lane <= len(pool)
    data = []
    for lane in LANES:
        for i in range(per_lane):
            cid = pool[i]
            opp = pool[(i + 1) % len(pool)]
            data.append({"id": cid, "positions": [
                _pos(lane_src[lane], 1, i + 1,
                     counters=[{"champion_id": opp, "play": 50, "win": 20}])
            ]})
    return {"meta": {"version": patch}, "data": data}


def test_refresh_guard_half_loss_boundary_passes(mc, db, net):
    """Yeni = etkin*0.5 tam sınır: `<` olmadığı için GEÇER (loss_ratio 0.5)."""
    net.source = make_wide_source("16.20", 4)   # 20 tiers kaydı, 20 anahtar
    assert _refresh(mc)["written"] is True
    net.source = make_wide_source("16.21", 2)   # 10 / 10
    meta_store.reset_state()
    res = _refresh(mc)
    assert res["guard"] == {"ok": True, "loss_ratio": 0.5, "empty_lanes": [], "reasons": []}
    assert res["written"] is True
    assert len(_rows(db)) == 2


def test_refresh_guard_rejects_more_than_half_loss_and_force_overrides(mc, db, net):
    net.source = make_wide_source("16.20", 4)   # 20 / 20
    assert _refresh(mc)["written"] is True
    net.source = make_wide_source("16.21", 1)   # 5 / 5 → %75 kayıp, koridorlar dolu
    meta_store.reset_state()
    res = _refresh(mc)
    assert res["written"] is False and res["reason"] == "guard_rejected"
    assert res["after"]["tiers_entries"] == 5 and res["after"]["counters_anchors"] == 5
    assert res["guard"]["ok"] is False
    assert res["guard"]["loss_ratio"] == 0.75
    assert res["guard"]["empty_lanes"] == []
    assert len(res["guard"]["reasons"]) == 2  # tiers + counter anahtarı
    assert all("yarıdan fazla" in r for r in res["guard"]["reasons"])
    assert len(_rows(db)) == 1  # reddedilen yazılmadı

    # force + dry_run → yine yazmaz
    dry = _refresh(mc, force=True, dry_run=True)
    assert dry["written"] is False and dry["reason"] is None
    assert len(_rows(db)) == 1

    forced = _refresh(mc, force=True)
    assert forced["written"] is True and forced["reason"] is None
    assert forced["guard"]["ok"] is False  # bilgi korunur, eşik aşıldı
    assert len(_rows(db)) == 2
    assert mc.get("/api/v1/meta/tiers").json()["patch"] == "16.21"


def test_refresh_guard_counter_only_loss_rejected(mc, db, net):
    """Yalnız counter anahtarı yarıdan fazla düşse de reddedilir."""
    net.source = make_wide_source("16.20", 4)
    assert _refresh(mc)["written"] is True
    src = make_wide_source("16.21", 4)
    # Her koridorda ilk anahtar hariç counter listelerini boşalt → 5 anahtar / 20 tiers
    for lane_i, lane in enumerate(LANES):
        for j in range(1, 4):
            src["data"][lane_i * 4 + j]["positions"][0]["counters"] = []
    net.source = src
    meta_store.reset_state()
    res = _refresh(mc)
    assert res["reason"] == "guard_rejected"
    assert res["after"]["tiers_entries"] == 20 and res["after"]["counters_anchors"] == 5
    assert res["guard"]["loss_ratio"] == 0.0
    assert res["guard"]["empty_lanes"] == []
    assert len(res["guard"]["reasons"]) == 1
    assert len(_rows(db)) == 1


def test_refresh_502_on_source_failure_writes_nothing(mc, db, net):
    net.fail_source = OSError("bağlantı reddedildi")
    r = mc.post("/api/v1/admin/meta/refresh", json={})
    assert r.status_code == 502
    assert "Kaynak" in r.json()["detail"]
    assert _rows(db) == []


def test_refresh_502_on_empty_data_and_bad_json(mc, db, net):
    net.source = {"meta": {"version": "16.19"}, "data": []}
    r = mc.post("/api/v1/admin/meta/refresh", json={})
    assert r.status_code == 502 and "boş" in r.json()["detail"]
    meta_store.reset_state()
    net.source = ["bozuk"]
    r = mc.post("/api/v1/admin/meta/refresh", json={})
    assert r.status_code == 502 and "JSON" in r.json()["detail"]
    assert _rows(db) == []


def test_refresh_502_on_ddragon_failure(mc, db, net):
    net.fail_dd = ValueError("bozuk")
    r = mc.post("/api/v1/admin/meta/refresh", json={})
    assert r.status_code == 502
    assert "Data Dragon" in r.json()["detail"]
    assert _rows(db) == []
    assert net.count("https://lol-api-champion.op.gg/") == 0


def test_refresh_falls_back_to_latest_ddragon_without_manifest(db_path, monkeypatch, tmp_path, net):
    root = tmp_path / "webui"
    (root / "assets" / "meta").mkdir(parents=True)
    with _client(db_path, monkeypatch, root) as c:
        res = _refresh(c)
        assert res["after"]["dd_version"] == "16.19.1"
        assert res["ddragon"] == {"vendored": None, "latest": "16.19.1"}
        # champions.json yok → DD adlarına düşüldü, uyarı var; sunucu YOLU sızmaz
        assert res["warnings"] == [
            "champions.json yok (Data Dragon varlıkları indirilmemiş); adlar Data "
            f"Dragon champion.json'a ({len(DD_DATA)} ad) karşı doğrulandı"
        ]
        assert not any("/" in w or str(root) in w for w in res["warnings"])
        hist = c.get("/api/v1/admin/meta/history").json()
        assert hist["items"][0]["warnings_count"] == 1
        assert res["before"] is None
        assert res["written"] is True

    net.fail_versions = OSError("yok")
    meta_store.reset_state()
    with _client(db_path, monkeypatch, root) as c:
        r = c.post("/api/v1/admin/meta/refresh", json={})
        assert r.status_code == 502 and "sürüm" in r.json()["detail"]


def test_refresh_unknown_champion_warning_excluded(mc, net):
    src = make_source_payload()
    src["data"].append({"id": 9999, "positions": [_pos("TOP", 1, 1)]})
    net.source = src
    res = _refresh(mc)
    assert res["written"] is True
    assert any("9999" in w for w in res["warnings"])
    assert all("9999" not in e[0] for e in res["diff"]["tiers"]["top"]["added"])
    hist = mc.get("/api/v1/admin/meta/history").json()
    assert hist["items"][0]["warnings_count"] == len(res["warnings"]) >= 1


def test_refresh_lock_409_while_running(mc, db):
    assert meta_store._refresh_lock.acquire(blocking=False)
    try:
        r = mc.post("/api/v1/admin/meta/refresh", json={})
        assert r.status_code == 409
        assert r.json()["detail"] == "Meta güncellemesi zaten koşuyor."
    finally:
        meta_store._refresh_lock.release()
    assert _rows(db) == []
    assert _refresh(mc)["written"] is True  # kilit serbest kaldı


def test_refresh_lock_released_after_502(mc, net):
    net.fail_source = OSError("x")
    assert mc.post("/api/v1/admin/meta/refresh", json={}).status_code == 502
    assert meta_store.is_running() is False
    net.fail_source = None
    meta_store.reset_state()
    assert _refresh(mc)["written"] is True


def test_refresh_rejects_bad_region_tier(mc):
    r = mc.post("/api/v1/admin/meta/refresh", json={"region": "../x"})
    assert r.status_code == 422


def test_refresh_empty_body_defaults(mc):
    r = mc.post("/api/v1/admin/meta/refresh")
    assert r.status_code == 200
    assert r.json()["after"]["source"] == "op.gg (global, platinum_plus)"


def test_single_active_row_enforced_by_db(mc, db):
    _refresh(mc)
    conn = db()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO meta_snapshots (trigger, source, source_patch, dd_version,"
                " tiers_json, counters_json, is_active)"
                " VALUES ('cli', 's', '1.1', '1.1.1', '{}', '{}', 1)"
            )
    finally:
        conn.close()


def test_retention_keeps_five_and_never_deletes_active(mc, db, net):
    ids = []
    for i in range(7):
        net.source = make_source_payload(patch=f"17.{i}")
        meta_store.reset_state()
        ids.append(_refresh(mc)["snapshot_id"])
    rows = _rows(db)
    assert [r[0] for r in rows] == ids[2:]
    assert [r[1] for r in rows] == [0, 0, 0, 0, 1]

    # Eski bir satırı etkinleştir, sonra 2 yeni yaz: etkin olan ASLA silinmez
    old_id = ids[2]
    assert mc.post(f"/api/v1/admin/meta/activate/{old_id}").status_code == 200
    for i in range(2):
        net.source = make_source_payload(patch=f"18.{i}")
        meta_store.reset_state()
        _refresh(mc)
    rows = _rows(db)
    assert len(rows) == 5
    assert sum(r[1] for r in rows) == 1
    assert rows[-1][1] == 1  # en yeni etkin


# ── 4) history / activate ────────────────────────────────────────────────


def test_history_order_and_shape(mc, net):
    assert mc.get("/api/v1/admin/meta/history").json() == {"active_id": None, "items": []}
    ids = []
    for i in range(3):
        net.source = make_source_payload(patch=f"17.{i}")
        meta_store.reset_state()
        ids.append(_refresh(mc)["snapshot_id"])
    hist = mc.get("/api/v1/admin/meta/history").json()
    assert hist["active_id"] == ids[-1]
    assert [it["id"] for it in hist["items"]] == list(reversed(ids))
    newest = hist["items"][0]
    assert set(newest) == {"id", "created_at", "trigger", "patch", "updated", "source",
                           "dd_version", "is_active", "tiers_entries", "counters_anchors",
                           "counters_rows", "summary", "warnings_count"}
    assert newest["is_active"] is True and newest["patch"] == "17.2"
    assert newest["trigger"] == "panel" and newest["dd_version"] == VENDORED
    assert newest["tiers_entries"] == 10 and newest["counters_anchors"] == 10
    assert set(newest["summary"]) == {"tiers_added", "tiers_removed", "tiers_moved",
                                      "counters_added", "counters_removed", "counters_changed"}
    assert all(it["is_active"] is False for it in hist["items"][1:])


def test_history_max_five(mc, net):
    for i in range(6):
        net.source = make_source_payload(patch=f"17.{i}")
        meta_store.reset_state()
        _refresh(mc)
    assert len(mc.get("/api/v1/admin/meta/history").json()["items"]) == 5


def test_activate_switches_and_is_idempotent(mc, db, net):
    a = _refresh(mc)["snapshot_id"]
    net.source = make_source_payload(patch="16.20")
    meta_store.reset_state()
    b = _refresh(mc)["snapshot_id"]
    assert mc.get("/api/v1/meta/tiers").json()["snapshot_id"] == b

    r = mc.post(f"/api/v1/admin/meta/activate/{a}")
    assert r.status_code == 200
    assert r.json() == {"active_id": a, "patch": "16.19"}
    assert mc.get("/api/v1/meta/tiers").json()["snapshot_id"] == a
    assert mc.get("/api/v1/meta/counters").json()["patch"] == "16.19"
    assert [r_[1] for r_ in _rows(db)] == [1, 0]
    assert mc.get("/api/v1/admin/meta/history").json()["active_id"] == a

    # idempotent
    r = mc.post(f"/api/v1/admin/meta/activate/{a}")
    assert r.status_code == 200 and r.json() == {"active_id": a, "patch": "16.19"}
    assert [r_[1] for r_ in _rows(db)] == [1, 0]


def test_activate_404(mc):
    r = mc.post("/api/v1/admin/meta/activate/9999")
    assert r.status_code == 404
    assert "9999" in r.json()["detail"]


# ── 5) Admin anahtarı ────────────────────────────────────────────────────

ADMIN_META_ENDPOINTS = [
    ("GET", "/api/v1/admin/meta/status"),
    ("POST", "/api/v1/admin/meta/refresh"),
    ("GET", "/api/v1/admin/meta/history"),
    ("POST", "/api/v1/admin/meta/activate/1"),
]


def test_admin_meta_503_when_key_not_configured(db_path, monkeypatch, webui_dir, net):
    with _client(db_path, monkeypatch, webui_dir, admin_key=None) as c:
        for method, path in ADMIN_META_ENDPOINTS:
            r = c.request(method, path)
            assert r.status_code == 503, f"{method} {path}: {r.status_code}"
            assert "ADMIN_KEY" in r.json()["detail"]


def test_admin_meta_403_without_or_wrong_header(db_path, monkeypatch, webui_dir, net, db):
    with _client(db_path, monkeypatch, webui_dir, attach_admin=False) as c:
        for method, path in ADMIN_META_ENDPOINTS:
            r = c.request(method, path)
            assert r.status_code == 403, f"{method} {path}: {r.status_code}"
            r = c.request(method, path, headers={"X-Admin-Key": "yanlis"})
            assert r.status_code == 403, f"{method} {path}: {r.status_code}"
    assert _rows(db) == []
    assert net.count("https://lol-api-champion.op.gg/") == 0


def test_admin_meta_401_without_api_key(mc):
    mc.headers.pop("X-API-Key")
    r = mc.get("/api/v1/admin/meta/status")
    assert r.status_code == 401


# ── 6) Rating tablolarına DOKUNMAZ ───────────────────────────────────────


def _rating_tables(db) -> dict:
    conn = db()
    try:
        return {
            t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY 1")]
            for t in ("ingest_events", "matches", "match_participants",
                      "rating_history", "role_rating_history", "players")
        }
    finally:
        conn.close()


def test_meta_flow_never_touches_rating_tables(mc, db, net):
    for gid, day in (("m-1", "11"), ("m-2", "12")):
        r = mc.post("/api/v1/ingest/match",
                    json=make_role_payload(source_game_id=gid,
                                           played_at=f"2026-08-{day}T20:00:00Z"))
        assert r.status_code == 201
    before = _rating_tables(db)
    assert before["rating_history"]

    a = _refresh(mc)["snapshot_id"]
    net.source = make_source_payload(patch="16.20")
    meta_store.reset_state()
    _refresh(mc, dry_run=True)
    _refresh(mc)
    mc.post(f"/api/v1/admin/meta/activate/{a}")
    mc.get("/api/v1/admin/meta/status")
    mc.get("/api/v1/admin/meta/history")
    mc.get("/api/v1/meta/tiers")
    mc.get("/api/v1/meta/counters")

    assert _rating_tables(db) == before
    # Replay da meta'ya dokunmaz
    assert mc.post("/api/v1/admin/replay").status_code == 200
    assert len(_rows(db)) == 2
    assert _rating_tables(db) == before


def test_refresh_warnings_never_contain_server_paths(mc, net, tmp_path):
    """Panelde gösterilen hiçbir uyarı sunucu dosya yolu taşımaz (bilinmeyen id dahil)."""
    src = make_source_payload()
    src["data"].append({"id": 9999, "positions": [_pos("TOP", 1, 1)]})
    net.source = src
    res = _refresh(mc)
    assert res["warnings"]
    assert not any(w.startswith("/") or "/Users" in w or str(tmp_path) in w
                   for w in res["warnings"])
