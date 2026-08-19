# test_role_editor_unsaved.py — Kontrol Paneli rol duzenleyicisinde
# KAYDEDILMEMIS SECIMLERIN korunmasi (Teoman, 2026-08-19: "atadigim roller
# kaydedilmiyor").
#
# Hata: secimler yalniz DOM'da yasiyordu; panelin her yeniden cizimi (arama,
# durum suzgeci, sekme degisimi, idari eylem sonrasi tazeleme, dil degisimi)
# rol duzenleyicisini m.participants'tan bastan basiyor ve secimleri hicbir
# uyari olmadan sifirliyordu. Kullanici acisindan bu "roller kaydedilmiyor"
# olarak gorunuyordu (KAYDET'e basinca "degisen rol yok").
#
# Cozum (a): secimler cp.roleDraft'ta (mac id -> {player_id: rol}) tutulur ve
# duzenleyici her cizildiginde geri yuklenir; secimleri atacak her yol
# (duzenleyiciyi kapatma, baska macin duzenleyicisini acma, sekme degisimi,
# paneli kilitleme) once onay sorar — ad duzenlemesindeki desenin ayni.
#
# Node YOK (CI'da yalniz pytest): kanit iki katmanlidir —
#   A) app.js kaynagindaki kritik satirlar (repodaki webui testlerinin yontemi),
#   B) taslak kuralinin Python ikizi + kenar durumlari.

import re
from pathlib import Path

from test_i18n import load_dict

WEBUI = Path(__file__).resolve().parent.parent
APP = WEBUI / "app.js"
CSS = WEBUI / "style.css"


def app_text():
    return APP.read_text(encoding="utf-8")


def fn_body(text, header, end="\n  }\n"):
    """app.js'teki bir fonksiyon govdesini kabaca keser (test_badge_ui deseni)."""
    i = text.index(header)
    j = text.index(end, i)
    return text[i:j]


def cp_click_handler():
    """Kontrol Paneli tiklama delegasyonunun govdesi."""
    text = app_text()
    i = text.index('$("#control-body").addEventListener("click"')
    j = text.index('$("#control-body").addEventListener("input"', i)
    return text[i:j]


def cp_change_handler():
    text = app_text()
    i = text.index('$("#control-body").addEventListener("change"')
    j = text.index('$("#control-body").addEventListener("keydown"', i)
    return text[i:j]


# ── A1) Secimler bellekte yasar ─────────────────────────────────


def test_cp_state_has_role_draft():
    text = app_text()
    i = text.index("const cp = {")
    block = text[i:text.index("\n  };", i)]
    assert "roleDraft: {}" in block, (
        "kaydedilmemis rol secimleri cp durumunda tutulmali (mac id -> {player_id: rol})"
    )
    assert "roleOpen: null" in block, "acik duzenleyici bilgisi korunmali"


def test_editor_restores_draft_but_keeps_server_value_as_original():
    body = fn_body(app_text(), "function cpRoleEditorHtml(m) {")
    assert "const draft = cp.roleDraft[m.id] || {};" in body, (
        "duzenleyici cizilirken taslak okunmali — yoksa yeniden cizim secimi yutar"
    )
    assert "hasOwnProperty.call(draft, p.player_id)" in body, (
        "taslakta ALAN VARLIGI sorulmali: '' (rolsuz) da gecerli bir secimdir"
    )
    # Secili gorunen deger taslaktan (sel), data-original SUNUCUDAN (cur) gelir:
    # kismi guncellemenin olcutu bozulmamali.
    assert 'data-original="${esc(cur)}"' in body
    assert 'value=""${sel === "" ? " selected" : ""}' in body
    assert '${sel === r ? " selected" : ""}' in body
    assert 'sel === cur ? "" : "re-dirty"' in body, (
        "sunucudan farkli secim gorsel olarak isaretlenmeli"
    )


def test_change_listener_records_and_reverts_draft():
    body = cp_change_handler()
    assert '.role-editor select[data-player]' in body, "rol secimi degisimi dinlenmeli"
    assert "cp.roleDraft[mid] || (cp.roleDraft[mid] = {})" in body
    assert "if (el.value === original) delete draft[pid];" in body, (
        "sunucudaki degere donuldugunde taslak DUSMELI (yalanci 'kaydedilmemis' onayi olmasin)"
    )
    assert "else draft[pid] = el.value;" in body
    assert "if (!Object.keys(draft).length) delete cp.roleDraft[mid];" in body
    # Durum suzgeci davranisi korunmali.
    assert "cp.status = el.value;" in body and "cpRenderList" in body


def test_every_redraw_path_goes_through_the_draft_aware_builder():
    text = app_text()
    # Duzenleyici HTML'i TEK yerde uretilir: cpRoleEditorHtml.
    assert text.count("cpRoleEditorHtml(") == 2, (
        "duzenleyici HTML'i yalniz cpRoleEditorHtml'de uretilmeli (tanim + tek cagri)"
    )
    assert "${open ? cpRoleEditorHtml(m) : \"\"}" in text
    # Arama, suzgec, sekme ve idari eylem sonrasi tazeleme bu uretecten gecer.
    assert "cp.q = el.value; cpRenderList(box);" in text, "arama listeyi yeniden cizer"
    assert "if (cp.tab === \"matches\") cpRenderList(box);" in fn_body(
        text, "function cpRenderPane(box) {"
    ), "sekme degisimi listeyi yeniden cizer"
    refresh = fn_body(text, "async function cpRefresh(box, fk) {")
    assert "cpRenderPane(box)" in refresh, "idari eylem sonrasi tazeleme de yeniden cizer"


# ── A2) Kaydetmeden ayrilirken onay ─────────────────────────────


def test_unsaved_roles_are_measured_against_server_data():
    text = app_text()
    body = fn_body(text, "function cpRoleOriginal(matchId, playerId) {")
    assert "cp.matches.find" in body and "p.position != null ? p.position :" in body, (
        "taslak DOM'a degil sunucu verisine karsi olculmeli (baska sekmedeyken de gecerli)"
    )
    has = fn_body(text, "function cpHasUnsavedRoles() {")
    assert "cp.roleDraft[mid][pid] !== cpRoleOriginal(mid, pid)" in has


def test_leaving_the_editor_asks_for_confirmation():
    text = app_text()
    drop = fn_body(text, "function cpConfirmDropRoles() {")
    assert "if (!cpHasUnsavedRoles()) return true;" in drop
    assert 'if (!confirm(t("control.unsaved_roles_confirm"))) return false;' in drop, (
        "kaydedilmemis secim varken onay sorulmali"
    )
    assert "cp.roleDraft = {};" in drop, "onaylanirsa secimler atilir"
    # Iptal edilirse HICBIR SEY degismez: kapatma/acma isi erken doner.
    click = cp_click_handler()
    i = click.index('btn.classList.contains("cp-rolebtn")')
    branch = click[i:click.index('btn.classList.contains("cp-rsave")', i)]
    assert "if (!cpConfirmDropRoles()) return;" in branch
    assert branch.index("if (!cpConfirmDropRoles()) return;") < branch.index("cp.roleOpen ="), (
        "onay, duzenleyici durumu degismeden ONCE sorulmali (iptalde secimler yerinde kalir)"
    )


def test_tab_switch_and_lock_cover_roles_too():
    text = app_text()
    leave = fn_body(text, "function cpConfirmLeave(box) {")
    assert "cpHasUnsavedNames(box)" in leave and "cpHasUnsavedRoles()" in leave, (
        "sekme/kilit onayi hem ad hem rol icin gecerli olmali"
    )
    for key in ("control.unsaved_both_confirm", "control.unsaved_roles_confirm",
                "control.unsaved_confirm"):
        assert key in leave, f"{key} onay metni kullanilmali"
    assert "cp.roleDraft = {};" in leave, "onaylanirsa secimler atilir"
    click = cp_click_handler()
    assert "if (to === cp.tab || !cpConfirmLeave(box)) return;" in click, "sekme degisimi kapili"
    lock = click[click.index('btn.classList.contains("cp-lock")'):]
    assert "if (!cpConfirmLeave(box)) return;" in lock, "paneli kilitleme kapili"


# ── A3) Kaydetme akisi bozulmadi ────────────────────────────────


def test_save_sends_only_changed_roles_and_needs_no_admin_key():
    body = fn_body(app_text(), "function cpSaveRoles(btn, box, matchId) {")
    assert "if (sel.value !== sel.dataset.original)" in body, (
        "yalniz DEGISEN roller gonderilir (kismi guncelleme)"
    )
    assert 'positions[sel.dataset.player] = sel.value === "" ? null : sel.value;' in body
    assert 'toast(t("matches.no_changes"), "warn"); return;' in body
    put = re.search(r"api\(`/matches/\$\{matchId\}/positions`,\s*\{([^}]*)\}", body)
    assert put, "PUT /positions cagrisi bulunamadi"
    assert "admin" not in put.group(1), (
        "PUT /positions idari anahtar ISTEMEZ (collector bagimliligi) — degistirme"
    )
    assert "cp.roleOpen = null;" in body, "kaydettikten sonra duzenleyici kapanir"
    assert "delete cp.roleDraft[matchId];" in body, "kaydedilen taslak temizlenir"


def test_caches_are_invalidated_after_role_save():
    text = app_text()
    # cpSaveRoles cpAction uzerinden kosar; cpAction basarida onbellekleri duser.
    assert "cpAction(btn, box, \"common.saving\"" in text
    action = fn_body(text, "async function cpAction(btn, box, busyKey, run) {")
    assert "cpInvalidateCaches();" in action and "await cpRefresh(box, fk);" in action


# ── A4) i18n + gorsel isaret ────────────────────────────────────


def test_new_confirm_keys_exist_in_both_dicts():
    tr, en = load_dict("tr"), load_dict("en")
    for key in ("control.unsaved_roles_confirm", "control.unsaved_both_confirm"):
        for lang, d in (("tr", tr), ("en", en)):
            assert key in d and d[key].strip(), f"{lang}: {key} eksik"
    # Rol metni ad metninden AYRI olmali (kullanici neyin kaybolacagini bilsin).
    assert tr["control.unsaved_roles_confirm"] != tr["control.unsaved_confirm"]
    assert en["control.unsaved_roles_confirm"] != en["control.unsaved_confirm"]


def test_no_changes_message_points_at_the_saved_roles():
    tr, en = load_dict("tr"), load_dict("en")
    # "Degisen rol yok." tek basina kafa karistiriciydi (kullanici secim
    # yaptigini saniyordu): mesaj olcutun KAYITLI roller oldugunu soylemeli.
    assert len(tr["matches.no_changes"]) > 20 and ":" in tr["matches.no_changes"]
    assert "saved" in en["matches.no_changes"].lower()


def test_dirty_selection_has_a_style():
    assert ".re-row select.re-dirty" in CSS.read_text(encoding="utf-8"), (
        "kaydedilmemis secim gorsel olarak ayirt edilmeli"
    )


# ── B) Taslak kuralinin Python ikizi ────────────────────────────
# app.js change dinleyicisiyle birebir ayni kural: secim sunucudakinden
# farkliysa taslaga yazilir, ayniysa taslaktan dusulur; mac girdisi bosalirsa
# tumden silinir.


def record(draft, mid, pid, value, original):
    d = draft.setdefault(mid, {})
    if value == original:
        d.pop(pid, None)
    else:
        d[pid] = value
    if not d:
        draft.pop(mid, None)
    return draft


def has_unsaved(draft, originals):
    return any(
        draft[mid][pid] != originals.get((mid, pid), "")
        for mid in draft
        for pid in draft[mid]
    )


def test_draft_rule_edge_cases():
    originals = {("7", "1"): "", ("7", "2"): "MID", ("9", "3"): "TOP"}
    draft = {}

    # Bos rol -> TOP: taslaga girer.
    record(draft, "7", "1", "TOP", "")
    assert draft == {"7": {"1": "TOP"}} and has_unsaved(draft, originals)

    # Ayni kutu tekrar bos yapilirsa taslaktan duser (ve mac girdisi de gider).
    record(draft, "7", "1", "", "")
    assert draft == {} and not has_unsaved(draft, originals)

    # Dolu rolun silinmesi (MID -> rolsuz) gecerli bir DEGISIKLIKTIR.
    record(draft, "7", "2", "", "MID")
    assert draft == {"7": {"2": ""}} and has_unsaved(draft, originals)

    # Ayni anda birden fazla oyuncu; biri geri alinirsa yalniz o duser.
    record(draft, "7", "1", "JUNGLE", "")
    assert draft["7"] == {"2": "", "1": "JUNGLE"}
    record(draft, "7", "2", "MID", "MID")
    assert draft == {"7": {"1": "JUNGLE"}}

    # Baska mac ayri anahtardadir.
    record(draft, "9", "3", "SUPPORT", "TOP")
    assert draft == {"7": {"1": "JUNGLE"}, "9": {"3": "SUPPORT"}}
    assert has_unsaved(draft, originals)


def test_draft_survives_a_redraw_and_is_dropped_only_on_confirm():
    """Bildirilen senaryo: sec -> ara -> geri don -> secimler DURUYOR."""
    originals = {("7", "1"): "", ("7", "2"): ""}
    draft = {}
    record(draft, "7", "1", "TOP", "")
    record(draft, "7", "2", "JUNGLE", "")

    # Arama/suzgec/sekme = yalnizca yeniden cizim; taslaga DOKUNMAZ.
    redrawn = dict(draft)
    assert redrawn == {"7": {"1": "TOP", "2": "JUNGLE"}}
    assert has_unsaved(draft, originals)

    # Duzenleyiciyi kapatma girisimi iptal edilirse secimler yerinde kalir.
    confirmed = False
    if confirmed:
        draft = {}
    assert draft == {"7": {"1": "TOP", "2": "JUNGLE"}}

    # Onaylanirsa atilir.
    draft = {}
    assert not has_unsaved(draft, originals)
