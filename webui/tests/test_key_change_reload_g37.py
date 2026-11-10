# test_key_change_reload_g37.py — GOREV 37: API anahtari DEGISINCE tam yeniden yukleme.
#
# Backend ayni URL'de anahtara gore farkli grubun verisini dondurur ve oyuncu/mac id'leri
# gruplar arasinda cakisir; bellekteki durum (state, modul onbellekleri, yoldaki yanitlar)
# yeni gruba tasinamaz. Node yok: kanit app.js kaynagi uzerinde yapisal dogrulama.

import re
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app.js"


def app_text():
    return APP.read_text(encoding="utf-8")


def submit_handler(text):
    i = text.index('$("#key-form").addEventListener("submit"')
    j = text.index("\n  });\n", i)
    return text[i:j]


def test_key_change_detected_after_trim_against_old_key():
    h = submit_handler(app_text())
    assert '$("#key-input").value.trim()' in h
    # eski anahtar, state.apiKey ezilmeden ONCE karsilastirilmali
    cmp_pos = h.index("!== state.apiKey")
    assign_pos = h.index("state.apiKey = newKey")
    assert cmp_pos < assign_pos


def test_changed_key_is_persisted_then_page_reloaded():
    h = submit_handler(app_text())
    store = h.index('localStorage.setItem("apiKey"')
    reload_call = h.index("reloadForKeyChange()")
    assert store < reload_call
    # degisen anahtarda yeniden yukleme dalindan sonra return: showView cagrilmaz
    branch = h[h.index("if (changed)"):h.index("showView(currentView, true)")]
    assert "return;" in branch


def test_same_key_keeps_old_behaviour():
    h = submit_handler(app_text())
    assert 'showView(currentView, true)' in h
    # showView, if (changed) {...} blogunun DISINDA
    assert h.index("showView(currentView, true)") > h.index("if (changed)")


def test_reload_helper_reloads_and_clears_foreign_hash():
    t = app_text()
    i = t.index("function reloadForKeyChange()")
    body = t[i:t.index("\n  }\n", i)]
    assert "location.reload()" in body
    assert "FAQ_HASH_RE.test(location.hash)" in body
    assert "history.replaceState" in body


def test_401_flow_still_opens_modal():
    t = app_text()
    assert re.search(r"res\.status === 401\) \{\s*openKeyModal\(\);", t)
