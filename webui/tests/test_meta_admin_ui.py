# test_meta_admin_ui.py — GÖREV 34 web UI tarafı (yalnız stdlib, Node yok).
#
# 1) app.js meta/counter belgelerini artık statik dosyadan DEĞİL API'den okur
#    (GET /meta/tiers, GET /meta/counters) ve statik yola hiç başvurmaz.
# 2) Kontrol Paneli'nde dördüncü sekme "meta" vardır; dört idari uç admin: true
#    ile çağrılır; refresh gövdesi dry_run/force taşır.
# 3) mock_api.js altı meta rotasını da sunar (contract paritesi) ve tohum
#    dosyaları assets/meta/*.json'dan okur; yanıta origin alanı ekler.
# 4) cm- sınıfları style.css'te tanımlıdır; fark tablosu kendi overflow-x
#    kabındadır (360px taşma kuralı).
# 5) Önbellek düşürme: cpInvalidateCaches meta promise'lerini sıfırlar.

import re
from pathlib import Path

WEBUI = Path(__file__).resolve().parent.parent
APP = (WEBUI / "app.js").read_text(encoding="utf-8")
MOCK = (WEBUI / "mock_api.js").read_text(encoding="utf-8")
CSS = (WEBUI / "style.css").read_text(encoding="utf-8")


def test_meta_documents_come_from_the_api_not_static_files():
    assert 'metaFetchDoc("/meta/tiers", "tiers")' in APP
    assert 'metaFetchDoc("/meta/counters", "counters")' in APP
    # Statik yola fetch kalmadi (yorumlarda tohum dosya adi gecebilir; mock_api.js
    # tohum olarak okumaya devam eder).
    assert 'fetch("assets/meta' not in APP, "app.js hala statik meta dosyasina basvuruyor"
    assert "META_URL" not in APP and "PA_COUNTERS_URL" not in APP


def test_loader_maps_api_errors_to_kinds_and_never_rejects():
    m = re.search(r"function metaFetchDoc\(path, field\) \{(.*?)\n  \}", APP, re.S)
    assert m, "metaFetchDoc bulunamadi"
    body = m.group(1)
    for kind in ('kind: "http"', 'kind: "shape"', 'kind: "network"'):
        assert kind in body
    assert "api(path)" in body
    # 404 = veri yok mesaji
    assert 'e.status === 404 ? t("meta.err_none")' in APP


def test_control_panel_has_meta_tab_and_admin_calls():
    m = re.search(r"const CP_TABS = \[(.*?)\];", APP, re.S)
    assert m and '{ id: "meta", label: "control.tab_meta" }' in m.group(1)
    assert 'api("/admin/meta/status", { admin: true })' in APP
    assert 'api("/admin/meta/history", { admin: true })' in APP
    assert "api(`/admin/meta/activate/${id}`, { method: \"POST\", admin: true })" in APP
    refresh_calls = re.findall(r'api\("/admin/meta/refresh",\s*\{ method: "POST", admin: true, body: (\{[^}]*\}) \}\)', APP)
    assert len(refresh_calls) == 2, refresh_calls
    assert any("dry_run: true" in b for b in refresh_calls)
    assert any("dry_run: false, force: !!force" in b for b in refresh_calls)


def test_update_button_is_locked_until_a_successful_check():
    # data-lock: cpSetBusy kilidi kaldirirken bu dugmeyi acmaz.
    assert 'el.disabled = on || el.hasAttribute("data-lock")' in APP
    assert 'canApply ? "" : " disabled data-lock"' in APP


def test_caches_are_dropped_after_admin_actions():
    m = re.search(r"function cpInvalidateCaches\(\) \{(.*?)\n  \}", APP, re.S)
    assert m
    body = m.group(1)
    assert "metaPromise = null;" in body
    assert "paCountersPromise = null;" in body
    assert "state.meta = null;" in body


def test_mock_serves_all_meta_routes_from_seed_files():
    for route in ('path === "/meta/tiers"', 'path === "/meta/counters"',
                  'path === "/admin/meta/status"', 'path === "/admin/meta/history"',
                  'path === "/admin/meta/refresh"'):
        assert route in MOCK, route
    assert "admin\\/meta\\/activate\\/(\\d+)$/" in MOCK, "activate/{id} rotasi yok"
    assert 'window.fetch("assets/meta/" + name)' in MOCK
    assert 'origin: d.origin, snapshot_id: d.snapshot_id' in MOCK
    for field in ("already_current", "guard_rejected", "loss_ratio", "empty_lanes",
                  "tiers_moved", "counters_changed", "warnings_count", "duration_ms"):
        assert field in MOCK, field
    # 409 / 502 senaryo bayraklari
    assert "MOCK_META_RUNNING" in MOCK and "MOCK_META_SOURCE_DOWN" in MOCK


def test_cm_styles_exist_and_diff_table_scrolls_in_its_own_box():
    for sel in (".cm-bar", ".cm-pill", ".cm-cmp", ".cm-card", ".cm-tablewrap",
                ".cm-table", ".cm-tok", ".cm-warn", ".cm-hist", ".cm-hrow"):
        assert sel in CSS, sel
    m = re.search(r"\.cm-tablewrap \{([^}]*)\}", CSS)
    assert m and "overflow-x: auto" in m.group(1)
    # Konseptin mc- oneki ADIYLA tasinmadi (global ad alani: .mc-kda zaten mac
    # kartinda kullaniliyor — cakisma tam da bu yuzden onlendi).
    for sel in (".mc-bar", ".mc-pill", ".mc-cmp", ".mc-card", ".mc-hist"):
        assert sel not in CSS and sel[1:] not in APP, sel


def test_server_text_rows_wrap_unbreakable_strings():
    """Uyari/gerekce/ad metinleri sunucudan gelir ve kirilmaz dizge (dosya yolu)
    tasiyabilir; 360px'te belge yatay tasmasin diye overflow-wrap: anywhere sart
    (orkestrator bulgusu: .cm-warn 500px'e tasiyordu)."""
    def block(selector):
        m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
        assert m, f"{selector} kurali yok"
        return m.group(1)
    warn = block(".cm-warn")
    assert "overflow-wrap: anywhere" in warn and "min-width: 0" in warn
    for sel in (".cm-table td.cm-names", ".cm-table td.cm-empty", ".cm-sec h3 small",
                ".cm-sub", ".cm-hmain", ".cm-bar-text"):
        assert "overflow-wrap: anywhere" in block(sel), sel
