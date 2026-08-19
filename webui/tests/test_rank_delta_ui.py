# test_rank_delta_ui.py — SIRALAMA sayfasindaki sira degisimi gostergesi
# (api_contract §5 `rank_delta`; V1 "Ince Chevron", Teoman 2026-08-19).
#
# Node YOK (CI'da yalniz pytest): kanit kaynak duzeyindedir — repodaki diger
# webui testlerinin yontemi. Uc sey kilitlenir:
#   1) Gosterge ADIN YANINDA, ayni hucrede ve tabloya SUTUN EKLEMEDEN durur.
#   2) Uc hal (yukseldi / dustu / degismedi-null) ayri siniflar ve dogru
#      renk degiskenleriyle ayrilir; olculer V1 tasariminin birebir aynisidir.
#   3) Anlam ekran okuyucuya i18n metniyle tasinir (gorsel kisim aria-hidden).


import re
from pathlib import Path

from test_i18n import load_dict

WEBUI = Path(__file__).resolve().parent.parent
APP = (WEBUI / "app.js").read_text(encoding="utf-8")
CSS = (WEBUI / "style.css").read_text(encoding="utf-8")
MOCK = (WEBUI / "mock_api.js").read_text(encoding="utf-8")
HTML = (WEBUI / "index.html").read_text(encoding="utf-8")

I18N_KEYS = [
    "leaderboard.rank_up",
    "leaderboard.rank_down",
    "leaderboard.rank_same",
    "leaderboard.rank_delta_none",
]


def board_row():
    """loadLeaderboard'un satir sablonu (template literal govdesi)."""
    i = APP.index("async function loadLeaderboard()")
    j = APP.index('.join("");', i)
    row = APP[i:j]
    assert "<tr>" in row
    return row


# ── 1) Gosterge adin yaninda, satir yapisi bozulmadi ────────────


def test_indicator_sits_next_to_the_name_in_the_same_cell():
    row = board_row()
    m = re.search(
        r'<td class="player"><span class="pname">'
        r'<button type="button" class="name-link" data-player="\$\{p\.id\}">'
        r"\$\{esc\(p\.display_name\)\}</button>"
        r"\$\{rankDeltaHtml\(p\.rank_delta\)\}</span></td>",
        row,
    )
    assert m, "gosterge adin hemen saginda, ayni .pname kabuginda olmali"


def test_row_still_has_exactly_four_cells_in_the_same_order():
    row = board_row()
    cells = re.findall(r"<td[^>]*>", row)
    assert len(cells) == 4, "sira degisimi TABLOYA SUTUN EKLEMEZ"
    assert 'class="rank"' in cells[0]
    assert 'class="player"' in cells[1]
    assert cells[2].count("num strong") == 1
    assert 'class="num"' in cells[3]
    # Basliklar da 4 kalir (index.html'e th eklenmedi).
    thead = HTML[HTML.index('<table class="board">'): HTML.index('<tbody id="board-body">')]
    assert len(re.findall(r"<th[ >]", thead)) == 4


def test_row_height_tokens_untouched():
    """Satir yuksekligini belirleyen kurallar aynen duruyor (tema korunur)."""
    assert ".board td { padding: 12px 10px; border-bottom: 1px solid var(--line); }" in CSS
    assert ".board .rank { width: 36px;" in CSS
    # Gosterge line-height:1 ile adin satirinin icinde kalir.
    assert re.search(r"\.rd-vis\s*\{[^}]*line-height:\s*1;", CSS, re.S)


def test_long_names_never_hide_the_indicator():
    """Ad kirpilir (ellipsis), gosterge flex:none ile yerinde kalir."""
    assert ".board td.player { max-width: 0; width: 100%; }" in CSS
    pname = re.search(r"\.board \.pname \{[^}]*\}", CSS).group(0)
    assert "display: flex" in pname and "min-width: 0" in pname
    link = re.search(r"\.board \.pname \.name-link \{[^}]*\}", CSS, re.S).group(0)
    assert "text-overflow: ellipsis" in link and "min-width: 0" in link
    assert re.search(r"\.rd \{[^}]*flex:\s*0 0 auto;", CSS, re.S)


# ── 2) Uc hal: siniflar, renkler, V1 olculeri ───────────────────


def test_three_states_have_distinct_classes():
    body = APP[APP.index("function rankDeltaHtml("): APP.index("async function loadLeaderboard()")]
    assert 'rdSpan("rd-up"' in body
    assert 'rdSpan("rd-down"' in body
    assert body.count('rdSpan("rd-flat"') == 2  # 0 ve null ayni notr hal
    # Isaret: pozitif yukari, negatif asagi; rakam mutlak deger olarak yazilir.
    assert "if (n > 0) return rdSpan(\"rd-up\", RD_CHEVRON.up + n" in body
    assert "if (n < 0) return rdSpan(\"rd-down\", RD_CHEVRON.down + -n" in body


def test_state_colors_use_theme_tokens():
    assert ".rd-up { color: var(--ok); }" in CSS
    assert ".rd-down { color: var(--red); }" in CSS
    assert ".rd-flat { color: var(--muted); opacity: 0.45; }" in CSS
    assert ".rd-flat .rd-vis { font-weight: 400; }" in CSS


def test_v1_measurements_are_verbatim():
    vis = re.search(r"\.rd-vis \{(.*?)\}", CSS, re.S).group(1)
    for rule in (
        "gap: 2px;",
        "font-size: 12px;",
        "font-weight: 700;",
        "line-height: 1;",
        "letter-spacing: 0.01em;",
        "font-variant-numeric: tabular-nums;",
    ):
        assert rule in vis, f"V1 olcusu kaybolmus: {rule}"


def test_chevron_svg_is_the_v1_shape():
    up = 'viewBox="0 0 10 10" width="9" height="9" aria-hidden="true"'
    assert APP.count(up) == 2  # up + down
    assert 'd="M1.6 6.6 L5 3.2 L8.4 6.6"' in APP   # yukari chevron
    assert 'd="M1.6 3.4 L5 6.8 L8.4 3.4"' in APP   # asagi chevron
    assert APP.count('stroke="currentColor" stroke-width="1.9"') == 2
    assert ".rd svg { display: block; }" in CSS


def test_flat_state_holds_its_place():
    """Degisim yoksa tire YER TUTAR (satir/ad genisligi kaymaz)."""
    body = APP[APP.index("function rankDeltaHtml("): APP.index("async function loadLeaderboard()")]
    assert body.count('"&mdash;"') == 2


# ── 3) Erisilebilirlik + i18n ───────────────────────────────────


def test_visual_part_is_aria_hidden_next_to_screen_reader_text():
    span = APP[APP.index("const rdSpan ="): APP.index("// rank_delta: pozitif")]
    assert '<span class="rd-vis" aria-hidden="true">' in span
    assert '<span class="sr-only">${esc(label)}</span>' in span
    assert re.search(r"\.sr-only \{[^}]*position: absolute;", CSS, re.S)
    assert "clip-path: inset(50%);" in CSS


def test_screen_reader_texts_come_from_i18n():
    for key in I18N_KEYS:
        assert f't("{key}"' in APP, f"{key} app.js'te kullanilmiyor"


def test_i18n_keys_exist_in_both_dictionaries():
    tr, en = load_dict("tr"), load_dict("en")
    for key in I18N_KEYS:
        assert key in tr and key in en, key
        assert tr[key].strip() and en[key].strip()
    # Sayi yer tutucusu yon metinlerinde zorunlu, notr metinlerde olmamali.
    for key in ("leaderboard.rank_up", "leaderboard.rank_down"):
        assert "{n}" in tr[key] and "{n}" in en[key]
    for key in ("leaderboard.rank_same", "leaderboard.rank_delta_none"):
        assert "{n}" not in tr[key] and "{n}" not in en[key]
    assert tr["leaderboard.rank_same"] != tr["leaderboard.rank_delta_none"]


# ── 4) mock_api: dort halin dordu de gorulebilir ────────────────


def test_mock_serves_rank_delta_only_on_leaderboard():
    assert "rank_delta: RANK_DELTA[p.id]" in MOCK
    # /players dali dokunulmadan kalir (contract §2'de rank_delta yok).
    assert 'path === "/players"' in MOCK
    players_branch = MOCK[MOCK.index('path === "/players"'):][:400]
    assert "rank_delta" not in players_branch


def test_mock_covers_up_down_flat_and_null():
    raw = re.search(r"const RANK_DELTA = \{(.*?)\};", MOCK, re.S).group(1)
    pairs = re.findall(r"(\d+)\s*:\s*(-?\d+|null)", raw)
    assert len(pairs) >= 4
    values = [None if v == "null" else int(v) for _pid, v in pairs]
    assert any(v is not None and v > 0 for v in values), "yukselen yok"
    assert any(v is not None and v < 0 for v in values), "dusen yok"
    assert any(v == 0 for v in values), "degismeyen yok"
    assert any(v is None for v in values), "null (yeni oyuncu) yok"
