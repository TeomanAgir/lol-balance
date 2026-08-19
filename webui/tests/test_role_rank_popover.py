# test_role_rank_popover.py — profildeki ROL SIRALAMASI PENCERESI
# (Teoman, CHANGE_REQUESTS 2026-08-19).
#
# Istenen: profil > ROL RATINGLERI panelinde bir rolun SIMGESINE basinca sayfa
# degismeden kucuk bir pencere acilir ve icerik su duzendedir:
#     lider -> silik ayrac -> oyuncunun +-3 komsulugu (kendisi vurgulu)
#              -> silik ayrac -> sonuncu
#
# Node YOK (CI ubuntu'da yalniz pytest kosuyor), bu yuzden iki katmanli kanit:
#   A) app.js'teki roleRankPlan() KAYNAGI dondurulur (golden snapshot).
#   B) Ayni kural burada Python'da birebir yazilir ve TUM kenar durumlari
#      uzerinde kosturulur. A snapshot'i, B'nin gercekten gonderilen kodu
#      tarif ettigini garanti eder: JS degisirse (A) kirilir ve kural iki
#      yerde birden bilincli olarak guncellenir.
# Kalan maddeler (tiklanabilirlik, kapatma davranisi, i18n, tema, mock) kaynak
# kanitidir — repodaki webui testlerinin mevcut yontemi.

import re
from pathlib import Path

from test_i18n import load_dict

WEBUI = Path(__file__).resolve().parent.parent
APP = WEBUI / "app.js"
CSS = WEBUI / "style.css"
MOCK = WEBUI / "mock_api.js"


def app_text():
    return APP.read_text(encoding="utf-8")


def css_text():
    return CSS.read_text(encoding="utf-8")


def mock_text():
    return MOCK.read_text(encoding="utf-8")


def fn_body(text, header, end="\n  }\n"):
    """app.js'teki bir fonksiyon govdesini kabaca keser (test_badge_ui deseni)."""
    i = text.index(header)
    j = text.index(end, i)
    return text[i:j]


# ── A) Pencere plani: kaynak dondurulmus ────────────────────────
# Yorumlar ve bos satirlar atilir, girinti kirpilir. Bu liste DEGISIRSE
# asagidaki Python referansi da ayni anlamda guncellenmelidir.

FROZEN_PLAN = [
    "function roleRankPlan(n, idx) {",
    "const out = [];",
    "if (n <= RR_MAX) {",
    "for (let i = 0; i < n; i++) out.push(i);",
    "return out;",
    "}",
    "const lo = Math.max(0, idx - RR_R);",
    "const hi = Math.min(n - 1, idx + RR_R);",
    "if (lo > 0) out.push(0);",
    'if (lo > 1) out.push("gap");',
    "for (let i = lo; i <= hi; i++) out.push(i);",
    'if (hi < n - 2) out.push("gap");',
    "if (hi < n - 1) out.push(n - 1);",
    "return out;",
]


def plan_statements():
    body = fn_body(app_text(), "function roleRankPlan(n, idx) {")
    out = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        out.append(line)
    return out


def test_window_plan_source_is_frozen():
    assert plan_statements() == FROZEN_PLAN, (
        "roleRankPlan() degismis — kenar durumu kurali degistiyse bu testteki\n"
        "FROZEN_PLAN ve asagidaki Python referansi BIRLIKTE guncellenmeli."
    )


def test_window_constants_are_the_agreed_ones():
    text = app_text()
    assert "const RR_R = 3;" in text, "komsuluk yaricapi +-3 olmali (Teoman)"
    assert "const RR_MAX = 2 * RR_R + 3;" in text, (
        "pencereye sigan satir sayisi: lider + 2*3+1 komsu + sonuncu = 9"
    )


# ── B) Kuralin Python referansi + kenar durumlari ───────────────

RR_R = 3
RR_MAX = 2 * RR_R + 3  # 9


def plan(n, idx):
    """app.js roleRankPlan() ile birebir ayni kural."""
    out = []
    if n <= RR_MAX:
        return list(range(n))
    lo = max(0, idx - RR_R)
    hi = min(n - 1, idx + RR_R)
    if lo > 0:
        out.append(0)
    if lo > 1:
        out.append("gap")
    out.extend(range(lo, hi + 1))
    if hi < n - 2:
        out.append("gap")
    if hi < n - 1:
        out.append(n - 1)
    return out


def rows(p):
    return [x for x in p if x != "gap"]


def test_example_from_teoman_12th_of_18():
    """Teoman'in ornegi: 18 kisilik listede 12. sirada (idx 11)."""
    p = plan(18, 11)
    assert p == [0, "gap", 8, 9, 10, 11, 12, 13, 14, "gap", 17]
    assert p.count("gap") == 2


def test_leader_is_not_repeated_when_the_player_is_first():
    """1. sirada: lider satiri ZATEN kendisi -> tepede tekrar yok, ust ayrac yok."""
    p = plan(18, 0)
    assert p[0] == 0 and p[1] != "gap"
    assert rows(p)[:4] == [0, 1, 2, 3]
    assert p.count("gap") == 1  # yalniz alt ayrac
    assert len(rows(p)) == len(set(rows(p)))


def test_top_four_never_show_an_upper_separator_or_a_duplicate():
    """2-4. sirada lider komsuluk penceresinin ICINDEdir."""
    for idx in (1, 2, 3):
        p = plan(20, idx)
        assert p[0] == 0, f"idx={idx}: lider satiri eksik"
        assert p[1] != "gap", f"idx={idx}: gereksiz ust ayrac"
        assert rows(p)[0] == 0 and rows(p)[1] == 1
        assert len(rows(p)) == len(set(rows(p))), f"idx={idx}: tekrar eden satir"


def test_fifth_place_touches_the_leader_so_no_separator():
    """idx=4 -> lo=1: lider satiri var ama ATLANAN satir yok -> ayrac yok."""
    p = plan(20, 4)
    assert p[:9] == [0, 1, 2, 3, 4, 5, 6, 7, "gap"]
    assert p.count("gap") == 1


def test_sixth_place_is_the_first_index_with_an_upper_separator():
    p = plan(20, 5)
    assert p[:3] == [0, "gap", 2]
    assert p.count("gap") == 2


def test_last_four_never_show_a_lower_separator_or_a_duplicate():
    n = 20
    for idx in (n - 1, n - 2, n - 3, n - 4):
        p = plan(n, idx)
        assert p[-1] == n - 1, f"idx={idx}: sonuncu satir eksik"
        assert p[-2] != "gap", f"idx={idx}: gereksiz alt ayrac"
        assert len(rows(p)) == len(set(rows(p))), f"idx={idx}: tekrar eden satir"
        assert p.count("gap") == 1  # yalniz ust ayrac


def test_fifth_from_last_touches_the_last_row_so_no_separator():
    n = 20
    p = plan(n, n - 5)  # hi = n-2, sonuncu BITISIK
    assert p[-2:] == [n - 2, n - 1]
    assert p.count("gap") == 1


def test_small_rosters_are_shown_in_full_without_separators():
    for n in range(1, RR_MAX + 1):
        for idx in range(n):
            p = plan(n, idx)
            assert p == list(range(n)), f"n={n}, idx={idx}: liste tam degil"
            assert "gap" not in p


def test_window_never_repeats_a_row_and_never_exceeds_nine_rows():
    for n in range(1, 40):
        for idx in range(n):
            p = plan(n, idx)
            r = rows(p)
            assert r == sorted(r), f"n={n}, idx={idx}: siralama artan degil"
            assert len(r) == len(set(r)), f"n={n}, idx={idx}: ayni satir iki kez"
            assert len(r) <= RR_MAX, f"n={n}, idx={idx}: {len(r)} satir (max {RR_MAX})"
            assert idx in r, f"n={n}, idx={idx}: oyuncunun kendisi pencerede yok"
            assert 0 in r and n - 1 in r, f"n={n}, idx={idx}: lider/sonuncu eksik"


def test_a_separator_only_stands_where_rows_were_skipped():
    for n in range(1, 40):
        for idx in range(n):
            p = plan(n, idx)
            for i, x in enumerate(p):
                if x != "gap":
                    continue
                assert 0 < i < len(p) - 1, f"n={n}, idx={idx}: ayrac ucta"
                assert p[i + 1] - p[i - 1] > 1, (
                    f"n={n}, idx={idx}: bitisik satirlar arasinda ayrac var"
                )


# ── Siralama kurali TEK yerde (harita ekraniyla paylasim) ───────


def test_ranking_rule_is_a_single_shared_helper():
    """GOREV 4'un harita pop-up'i ile profil penceresi AYNI fonksiyonu cagirir;
    kural kopyalanmis degildir (yoksa iki ekran ayri siralar gosterebilirdi)."""
    text = app_text()
    assert text.count("function roleRanking(rows, role)") == 1
    # Siralama kirilimi da tek yerde durur.
    assert text.count("b.r.score - a.r.score") == 1
    assert text.count("b.r.matches - a.r.matches") == 1
    # Iki cagiran: harita (state.board) ve profil (state.roster).
    assert "roleRanking(state.board, r)" in text
    assert "roleRanking(state.board, role)" in text
    assert "roleRanking(state.roster, role)" in text


def test_ranking_keeps_the_contract_rule():
    """api_contract §2: o rolde matches >= 1 olanlar; score azalan -> matches
    azalan -> ad alfabetik."""
    body = fn_body(app_text(), "function roleRanking(rows, role)")
    assert "x.r.matches > 0" in body, "matches === 0 default prior siralamaya girmemeli"
    assert 'typeof x.r.score === "number"' in body
    assert "localeCompare" in body


def test_popover_derives_from_the_already_fetched_roster():
    """YENI UC YOK: pencere state.roster'daki role_ratings'ten turer, ek istek
    atmaz (profil roster'i zaten cekiyor)."""
    body = fn_body(app_text(), "function openRoleRank(btn)")
    assert "roleRanking(state.roster, role)" in body
    assert "api(" not in body, "pencere icin yeni istek atilmamali"
    assert "/leaderboard" not in body


# ── Tiklanabilirlik: oynanmamis rol pencere ACMAZ ───────────────


def test_unplayed_role_icon_is_not_a_button():
    """matches === 0 -> siralama yok: dugme HIC kurulmaz (odak sirasina girmez),
    kutu aria-disabled tasir ve imleci tiklama vaat etmez."""
    grid = fn_body(app_text(), "function k2Gauges(rr)")
    assert 'const off = !v.matches;' in grid
    assert '<div class="k2-gg-w" aria-disabled="true"' in grid, (
        "oynanmamis rol icin aria-disabled'li DIV bekleniyor"
    )
    assert '<button type="button" class="k2-gg-w k2-gg-btn" data-role="${r}"' in grid
    # Dugme yalnizca off DEGILKEN basilir.
    assert "off\n        ? `<div" in grid or "off ? `<div" in grid
    css = css_text()
    assert re.search(r'\.k2-gg-w\[aria-disabled="true"\] \{[^}]*cursor: default', css), (
        "oynanmamis rolde imlec tiklama vaat etmemeli"
    )
    # Baglayici SADECE gercek dugmeleri secer.
    bind = fn_body(app_text(), "function bindRoleRankButtons(root)")
    assert 'querySelectorAll(".k2-gg-btn")' in bind


def test_popover_does_not_open_when_no_one_played_the_role():
    body = fn_body(app_text(), "function openRoleRank(btn)")
    assert "if (!list.length || idx === -1) return;" in body


# ── Kapatma / konumlandirma: rozet baloncugu deseni ─────────────


def test_popover_reuses_the_badge_tip_dismiss_pattern():
    text = app_text()
    bind = fn_body(text, "function bindRoleRankButtons(root)")
    # Tekrar tiklama kapatir.
    assert "if (roleRankOpen === btn) closeRoleRank();" in bind
    assert "else openRoleRank(btn);" in bind
    # Klavye odagi acar, FARE odagi acmaz (focus + click toggle tuzagi).
    assert 'addEventListener("focus"' in bind
    assert 'btn.matches(":focus-visible")' in bind
    # Esc: diger kutulari kapatan ORTAK Escape blogu (tarihce/rozet/build).
    esc = re.search(
        r'if \(e\.key !== "Escape"\) return;(.*?)\n  \}\);', text, re.DOTALL
    )
    assert esc, "ortak Escape blogu bulunamadi"
    assert "closeRoleRank();" in esc.group(1), "Esc pencereyi kapatmali"
    # Disina tiklama (dugme ve kutu ici haric).
    assert 'e.target.closest(".rrp, .k2-gg-btn")' in text
    # Tek kutu: rozet baloncugu acilirken bu pencere kapanir ve tersi.
    tip = fn_body(text, "function openBadgeTip(card, b)")
    assert "closeRoleRank(false)" in tip
    opener = fn_body(text, "function openRoleRank(btn)")
    assert "closeBadgeTip();" in opener
    assert "closeHistPopup(false);" in opener
    assert "closeBuildTip();" in opener
    # Gorunum degisimi / yeniden cizim acik kutuyu birakmaz.
    view = fn_body(text, "function showView(name, forceReload = false)")
    assert "closeRoleRank(false);" in view


def test_popover_is_pulled_back_inside_when_it_would_overflow():
    """Rozet baloncugundaki olcum deseni: kutu referans kutunun disina tasarsa
    marginLeft ile iceri cekilir (390px'de yatay tasma yok)."""
    body = fn_body(app_text(), "function openRoleRank(btn)")
    assert "getBoundingClientRect()" in body
    assert 'box.style.marginLeft = Math.round(shift) + "px";' in body
    assert 'cell.closest(".k2-card")' in body


def test_focus_returns_to_the_icon_on_close():
    body = fn_body(app_text(), "function closeRoleRank(restoreFocus = true)")
    assert "btn.setAttribute(\"aria-expanded\", \"false\")" in body
    assert "btn.focus()" in body


def test_popover_is_bound_after_every_profile_render():
    body = fn_body(app_text(), "async function loadProfile()", "\n  }\n\n")
    assert "bindRoleRankButtons(box);" in body


# ── Satirdaki ada tiklayinca o oyuncunun profili ────────────────


def test_row_name_opens_that_players_profile():
    body = fn_body(app_text(), "function openRoleRank(btn)")
    assert 'querySelectorAll(".rrp-name[data-player]")' in body
    assert "closeRoleRank(false);" in body
    assert "openProfile(id);" in body


def test_own_row_is_highlighted_and_is_not_a_link():
    """Kendi satiri vurgulu (pirinc) ve baglanti DEGIL — zaten o profildeyiz."""
    body = fn_body(app_text(), "function roleRankHtml(role, list, idx)")
    assert "const me = x === idx;" in body
    assert 'class="rrp-name rrp-name-me"' in body
    assert 'aria-current="true"' in body
    assert 'class="rrp-row${me ? " rrp-me" : ""}"' in body
    # Ekran okuyucu: renk tek basina tasiyici degil.
    assert 't("profile.role_rank_you")' in body


def test_separator_rows_are_decorative_only():
    body = fn_body(app_text(), "function roleRankHtml(role, list, idx)")
    assert '<li class="rrp-gap" aria-hidden="true"></li>' in body


# ── i18n ────────────────────────────────────────────────────────

NEW_KEYS = [
    "profile.role_rank_open",
    "profile.role_rank_none",
    "profile.role_rank_you",
]


def test_new_texts_exist_in_both_dictionaries():
    tr, en = load_dict("tr"), load_dict("en")
    for key in NEW_KEYS:
        assert key in tr, f"tr.js eksik: {key}"
        assert key in en, f"en.js eksik: {key}"
    assert "{role}" in tr["profile.role_rank_open"]
    assert "{role}" in en["profile.role_rank_open"]


def test_popover_title_reuses_the_map_popup_key():
    """Baslik harita pop-up'iyla AYNI anahtardan gelir; iki yerde ayri metin
    tutulup birinin unutulmasi engellenir."""
    body = fn_body(app_text(), "function roleRankHtml(role, list, idx)")
    assert 't("map.role_ranking_title", { role: roleName(role) })' in body
    for lang in ("tr", "en"):
        assert "map.role_ranking_title" in load_dict(lang)


def test_popover_text_comes_only_from_the_dictionary():
    """Kutudaki her METIN sozlukten gelir (i18n_contract §5): baslik + "sen"
    eki t() cagrisidir, sira numarasindan sonraki nokta ise CSS'te durur
    (isaretlemede sabit metin yok)."""
    body = fn_body(app_text(), "function roleRankHtml(role, list, idx)")
    assert body.count("t(") >= 2
    assert re.search(r"\.rrp-rank::after \{ content: \"\.\"; \}", css_text()), (
        "sira numarasinin noktasi CSS'te olmali"
    )


# ── Tema / mobil ────────────────────────────────────────────────


def test_css_speaks_the_existing_theme_language():
    css = css_text()
    for cls in (".rrp", ".rrp-hd", ".rrp-list", ".rrp-row", ".rrp-rank",
                ".rrp-name", ".rrp-me", ".rrp-gap", ".rrp-sr", ".k2-gg-btn"):
        assert cls in css, f"style.css '{cls}' yok"
    box = re.search(r"\n\.rrp \{(.*?)\n\}", css, re.DOTALL)
    assert box, ".rrp kurali bulunamadi"
    b = box.group(1)
    assert "var(--surface-3)" in b and "var(--brass-dim)" in b, "tema disi yuzey/kenar"
    assert "position: absolute" in b, "pencere tiklanan yerden cikmali"
    assert "min(264px, 78vw)" in b, "mobilde (<=420px) tasmayi onleyen ust sinir yok"
    # Kendi satiri pirinc vurgulu.
    me = re.search(r"\n\.rrp-me \{(.*?)\n\}", css, re.DOTALL)
    assert me and "var(--brass)" in me.group(1)
    # Sayilar tabular.
    rank = re.search(r"\n\.rrp-rank \{(.*?)\n\}", css, re.DOTALL)
    assert rank and "tabular-nums" in rank.group(1)
    # Ayrac SILIK (sac teli): 1px + kisik opaklik + solgun pirinc.
    gap = re.search(r"\n\.rrp-gap \{(.*?)\n\}", css, re.DOTALL)
    assert gap, ".rrp-gap kurali yok"
    g = gap.group(1)
    assert "height: 1px" in g and "var(--brass-dim)" in g
    assert re.search(r"opacity: 0\.[1-6]", g), "ayrac silik olmali"
    # Hucre konumlandirma capasi.
    cell = re.search(r"\n\.k2-gg \{(.*?)\n\}", css, re.DOTALL)
    assert cell and "position: relative" in cell.group(1)


def test_icon_button_keeps_the_gauge_geometry_untouched():
    """Konsept olculeri (K2-2) korunur: dugme yalnizca krom sifirlar."""
    css = css_text()
    assert re.search(r"\.k2-gg-w \{[^}]*clamp\(62px, 18vw, 78px\)", css, re.DOTALL)
    btn = re.search(r"\n\.k2-gg-btn \{(.*?)\n\}", css, re.DOTALL)
    assert btn, ".k2-gg-btn kurali yok"
    body = btn.group(1)
    for reset in ("padding: 0", "border: 0", "background: none", "cursor: pointer"):
        assert reset in body, f".k2-gg-btn '{reset}' tasimali"
    assert "width" not in body and "height" not in body, (
        "dugme olcu vermez — geometri .k2-gg-w'de kalir"
    )
    assert ".k2-gg-btn:focus-visible" in css, "klavye odagi gorunur olmali"


# ── mock_api: pencere denenebilir olmali ────────────────────────


def test_mock_has_a_role_crowded_enough_for_the_full_window():
    """Tam pencere (lider + ayrac + 7 komsu + ayrac + sonuncu) ancak 10+
    oyuncunun oynadigi bir rolde gorulur."""
    text = mock_text()
    m = re.search(r'const CROWD_ROLE = "([A-Z]+)";', text)
    assert m, "mock_api.js kalabalik rol bayragi (CROWD_ROLE) tanimlamiyor"
    empty = re.search(r'const EMPTY_ROLE = "([A-Z]+)";', text)
    assert empty, "EMPTY_ROLE bayragi kaybolmus"
    assert m.group(1) != empty.group(1), "kalabalik rol ile bos rol ayni olamaz"
    # Bos rol yine durur: oynanmamis (tiklanamaz) simge senaryosu.
    assert empty.group(1) in ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")
    # Maci olan oyuncu sayisi >= 10 (mock roster'inda 13 kisi).
    played = [int(x) for x in re.findall(r"matches_played: (\d+),", text)]
    assert played, "mock roster'i okunamadi"
    assert sum(1 for x in played if x > 0) >= RR_MAX + 1, (
        "kalabalik rolde pencereyi doldurmaya yetecek oyuncu yok"
    )
    # Kalabalik rol maci OLAN herkese verilir, maci olmayan (Ece) disarida kalir.
    assert "if (!p.matches_played || p.role_ratings[CROWD_ROLE].matches) return;" in text
