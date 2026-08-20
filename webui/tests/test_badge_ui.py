# test_badges.py — rozet vitrini sozlesmesi (GOREV 24, 28 rozet).
#
# Node YOK: JS dosyalari stdlib ile ayiklanir. Dogrulananlar:
#   1) app.js BADGE_KEYS sirasi = badges/rozetler.md ID sirasi (gorsel dosya
#      adlari bu ID'ye bagli — sira DONDURULMUS, kayma sessiz bir hata olurdu).
#   2) mock_api.js BADGE_CATALOG ayni sirada ve ayni anahtarlarla (mock pariteligi).
#   3) Her rozet icin ad + aciklama tr VE en'de var; katalog disi (olu) rozet
#      anahtari sozluklerde KALMAMIS.
#   4) Kademeli rozetler tam olarak api_contract §2'deki 7 tanesi (6 standart
#      olcek + perfect_quad nadir olcek); kademe SAYAC esikleriyle.
#   5) Gorsel hatti "ucu acik": dosya adi ID'den TURETILIR (manifest yok),
#      klasor .gitkeep ile commit'lenebilir. Icine gorsel KONABILIR (drop-in) —
#      konursa adi app.js'in gercekte istedigi bicimle (sifirsiz ID + .png/.webp)
#      esmeli, yoksa madalyon sessizce hic yuklenmez.
#   6) app.js/mock_api.js'te literal `t("...")` anahtarlarinin hepsi sozlukte var.
#   7) SOZDIZIMI KANITI (node'suz): yorum ve string govdeleri atilmis "iskelet"
#      uzerinde {}/()/[]  dengeli ve kapatilmamis string/template YOK.

import re
from pathlib import Path

from test_i18n import load_dict

WEBUI = Path(__file__).resolve().parent.parent
REPO = WEBUI.parent
APP = WEBUI / "app.js"
MOCK = WEBUI / "mock_api.js"
CSS = WEBUI / "style.css"
BADGE_DIR = WEBUI / "assets" / "badges"

TIERED = ["mvp", "vision", "damage", "cs_per_min", "gold", "role_duel", "perfect_quad"]
# api_contract §2 "Kademe — ALTI SEVİYE" (GOREV 24): sira ARTAN.
TIERS = ["bronze", "silver", "gold", "platinum", "diamond", "stellar"]


# ── Kaynak ayiklama ─────────────────────────────────────────────


def catalog_from_md():
    """badges/rozetler.md tablolarindaki `key` sutunu, ID sirasinda."""
    text = (REPO / "badges" / "rozetler.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\|\s*(\d{2})\s*\|.*\|\s*`([a-z0-9_]+)`\s*\|\s*$", text, re.M)
    assert rows, "rozetler.md katalog tablosu okunamadi"
    ids = [int(i) for i, _ in rows]
    assert ids == list(range(1, len(ids) + 1)), f"ID'ler 1..N degil: {ids}"
    return [k for _, k in rows]


def keys_from_app():
    text = APP.read_text(encoding="utf-8")
    m = re.search(r"const BADGE_KEYS = \[(.*?)\];", text, re.DOTALL)
    assert m, "app.js icinde BADGE_KEYS bulunamadi"
    return re.findall(r'"([a-z0-9_]+)"', m.group(1))


def catalog_from_mock():
    text = MOCK.read_text(encoding="utf-8")
    m = re.search(r"const BADGE_CATALOG = \[(.*?)\n  \];", text, re.DOTALL)
    assert m, "mock_api.js icinde BADGE_CATALOG bulunamadi"
    rows = re.findall(r'\{\s*key:\s*"([a-z0-9_]+)".*?tiered:\s*(true|false)', m.group(1))
    assert rows, "mock BADGE_CATALOG satirlari okunamadi"
    return [(k, t == "true") for k, t in rows]


# ── 1-2) ID <-> key eslemesi ve mock pariteligi ─────────────────


def test_app_badge_order_matches_frozen_catalog():
    cat = catalog_from_md()
    assert len(cat) == 28, f"katalog 28 rozet olmali, {len(cat)} bulundu"
    assert keys_from_app() == cat, "app.js BADGE_KEYS sirasi katalog ID sirasindan sapti"


def test_mock_catalog_matches_frozen_catalog():
    assert [k for k, _ in catalog_from_mock()] == catalog_from_md()


def test_tiered_badges_are_exactly_the_contract_seven():
    """api_contract §2: 6 standart olcekli + perfect_quad (nadir olcek)."""
    assert [k for k, t in catalog_from_mock() if t] == TIERED


def test_mock_exposes_badge_catalog_endpoint():
    text = MOCK.read_text(encoding="utf-8")
    assert 'path === "/badges"' in text, "mock'ta GET /badges ucu yok"
    assert "include_locked" in text, "mock'ta include_locked yolu yok"


def test_webui_requests_locked_badges():
    text = APP.read_text(encoding="utf-8")
    assert "badges?include_locked=true" in text
    assert 'api("/badges")' in text, "nadirlik icin GET /badges cagrisi yok"


# ── 4) Kazanilmamis rozet filtresi (GOREV 24-fix, Teoman karari) ──────────
# Kural: include_locked=true istegi KALIR (ilerlemeli kilitliler icin gerekli),
# filtre ISTEMCIDE uygulanir. Kilitli rozet YALNIZCA `progress` var VE
# `progress.current > 0` ise gorunur ("Demirbas 22/50"); progress yoksa
# (mac-ani kosullu siniflar) ya da current 0 ise ("Kumarbaz 0/5") kart hic
# basilmaz. Ozet satiri ("X / 27") kazanilmis sayisini ve katalog toplamini
# gostermeye devam eder — filtre bu sayiyi BOZMAZ, yalnizca gorunen kart
# sayisini etkiler.


def test_locked_badges_without_started_progress_are_filtered_client_side():
    text = APP.read_text(encoding="utf-8")
    # include_locked=true istegi KALDI (ilerlemeli kilitliler backend'den
    # gelmeye devam etmeli); filtre istemcide, ayri bir adimda uygulanir.
    assert "badges?include_locked=true" in text
    assert ".filter(badgeVisible)" in text, (
        "badgeList() artik badgeVisible ile kilitli+ilerlemesiz rozetleri elemeli"
    )
    m = re.search(r"const badgeVisible = \(b\) => \{(.*?)\n  \};", text, re.DOTALL)
    assert m, "badgeVisible fonksiyonu bulunamadi"
    body = m.group(1)
    assert "badgeLocked(b)" in body, "kazanilmis rozet her zaman gorunmeli"
    assert "badgeProgress(b)" in body, "gorunurluk badgeProgress'e dayanmali"
    assert "p.c > 0" in body, "kural tam olarak progress.current > 0 olmali"


def test_badge_summary_count_is_unaffected_by_the_visibility_filter():
    """'X / 27 rozet kazanildi' filtre yuzunden degismemeli — n = kazanilmis
    sayisi, total = katalog toplami (BADGE_KEYS.length), gorunen kart sayisindan
    BAGIMSIZ hesaplanmali."""
    text = APP.read_text(encoding="utf-8")
    assert "const earned = list.filter(x => !badgeLocked(x)).length;" in text
    assert "n: earned, total: BADGE_KEYS.length" in text


def test_mock_has_a_player_covering_all_three_locked_progress_states():
    """Node yok: 8 donen maclik havuz rotasyonu ile rakip/rulet katilimci
    listeleri mock_api.js'ten METIN olarak ayiklanir, rotasyon formulu (mock'taki
    `matchPool.map((_, i, all) => all[(i + m) % all.length]).slice(0, 10)`)
    burada TEKRARLANIR (rastgele stat uretimine dokunulmaz, yalnizca katilim
    sayisi hesaplanir). Amac: en az bir oyuncuda ayni anda
      - veteran_10 -> kilitli + ilerlemesi baslamis (current>0)  => GORUNMELI
      - gambler    -> kilitli + ilerlemesi sifir   (current==0)  => GORUNMEMEZ
      - roulette_complete -> kilitli + progress YOK              => GORUNMEMEZ
    bulundugunu KANITLAMAK."""
    text = MOCK.read_text(encoding="utf-8")

    # Rotasyon havuzu: matches_played > 0 olan herkes, players dizisindeki sirayla.
    player_rows = re.findall(
        r'id:\s*(\d+),\s*display_name:\s*"[^"]*",\s*riot_id:\s*"[^"]*",'
        r'\s*matches_played:\s*(\d+)', text)
    assert player_rows, "players dizisi okunamadi"
    pool = [int(pid) for pid, mp in player_rows if int(mp) > 0]
    assert len(pool) >= 10, "rotasyon havuzu 10'dan kucuk"

    n = len(pool)
    played = {pid: 0 for pid in pool}
    for m in range(8):
        window = {pool[(i + m) % n] for i in range(10)}
        for pid in window:
            played[pid] += 1

    # Rakip (nemesis/duo) sabit kadrosu: RIVAL_BASE ["ROL", mavi, kirmizi] uclemeleri.
    rival_pairs = re.findall(r'\["[A-Z]+",\s*(\d+),\s*(\d+)\]', text)
    assert rival_pairs, "RIVAL_BASE okunamadi"
    rival_ids = {int(x) for pair in rival_pairs for x in pair}

    # Rulet macinin sabit katilimcilari.
    m_ids = re.search(r'const ids = \[([0-9,\s]+)\];', text)
    assert m_ids, "rulet maci katilimci listesi okunamadi"
    roulette_ids = {int(x) for x in re.findall(r'\d+', m_ids.group(1))}

    # Aday: havuzda, rakip VE rulet maclarinin disinda, 1-9 arasi mac oynamis
    # (veteran_10 hic tetiklenmez -> kilitli kalir, current = played > 0).
    candidates = [
        pid for pid in pool
        if pid not in rival_ids and pid not in roulette_ids and 0 < played[pid] < 10
    ]
    assert candidates, (
        "ilerleme-filtresi senaryosu icin uygun oyuncu yok: rakip/rulet "
        "maclarinin disinda kalan, 1-9 mac oynamis en az 1 oyuncu gerekir"
    )

    # `gambler` HER oyuncu icin progress'te var (rouletteWins her zaman izlenir);
    # rulet disi adaylarda bu deger hep 0 kalir -> current==0 -> GORUNMEZ.
    assert "gambler: { current: rouletteWins, target: 5 }" in text

    # `roulette_complete` / `roulette_winner` prog haritasinda HIC yok -> progress
    # null kalir -> GORUNMEZ (mac-ani kosullu sinif, ilerleme tanimsiz).
    prog_block = re.search(r"const prog = \{(.*?)\n    \};", text, re.DOTALL)
    assert prog_block, "prog haritasi bulunamadi"
    assert "roulette_complete" not in prog_block.group(1)
    assert "roulette_winner" not in prog_block.group(1)


# ── 3) i18n: her rozet iki dilde, olu anahtar kalmamis ──────────


def test_every_badge_has_name_and_description_in_both_languages():
    cat = catalog_from_md()
    for lang in ("tr", "en"):
        d = load_dict(lang)
        missing = [
            f"profile.badge_{k}{suffix}"
            for k in cat
            for suffix in ("", "_desc")
            if f"profile.badge_{k}{suffix}" not in d
        ]
        assert not missing, f"{lang}.js eksik rozet anahtarlari: {missing}"


def test_no_dead_badge_keys_left_in_dictionaries():
    cat = set(catalog_from_md())
    # profile.badge_* ad alaninda rozet anahtari OLMAYAN yardimci anahtarlar
    # (sayac, kademe, ilerleme, nadirlik metinleri) katalogdan bagimsizdir.
    helpers = {
        "count", "count_aria", "last", "best", "best_value", "best_go", "locked",
        "progress", "progress_aria", "tier_aria", "tier_next", "holders",
        "holders_none", "quest", "quest_done",
    } | {"tier_" + name for name in TIERS}
    for lang in ("tr", "en"):
        dead = []
        for key in load_dict(lang):
            m = re.match(r"^profile\.badge_(.+?)(_desc)?$", key)
            if not m:
                continue
            name = m.group(1)
            if name in helpers or (m.group(2) is None and name in helpers):
                continue
            if name not in cat:
                dead.append(key)
        assert not dead, f"{lang}.js'te katalog disi (olu) rozet anahtari: {dead}"


# ── 5) Gorsel hatti: ucu acik, manifest yok ─────────────────────


def test_badge_asset_dir_is_committable_and_well_formed():
    """Klasor bos-veya-dolu her iki halde de commit'lenebilir olmali. Icine
    gorsel KONURSA, app.js'in gercekte aradigi adla (sifirsiz ID + .png/.webp,
    bkz. yukarida BADGE_IMG_DIR/BADGE_IMG_EXT/badgeId) birebir eslesmeli —
    aksi halde dosya repoya girer ama madalyon sessizce hic yuklenmez."""
    assert (BADGE_DIR / ".gitkeep").is_file(), "webui/assets/badges/.gitkeep yok"
    n = len(catalog_from_md())
    allowed_ext = {"png", "webp"}  # app.js BADGE_IMG_EXT — baskasi hic denenmez
    for p in BADGE_DIR.iterdir():
        if p.name == ".gitkeep":
            continue
        assert p.is_file(), f"webui/assets/badges/ altinda beklenmeyen klasor: {p.name}"
        stem, dot, ext = p.name.rpartition(".")
        assert dot and ext.lower() in allowed_ext, (
            f"{p.name}: rozet gorseli yalnizca .png veya .webp olabilir "
            f"(app.js baska uzanti denemez, dosya sessizce hic gosterilmez)"
        )
        assert stem.isdigit(), (
            f"{p.name}: dosya adi salt sayisal ID olmali, ornek '5.png' "
            f"('mvp.png' gibi adlar app.js tarafindan hic istenmez)"
        )
        assert str(int(stem)) == stem, (
            f"{p.name}: ID sifir dolgulu olmamali — app.js tam olarak "
            f"'{int(stem)}.{ext}' ister, '{stem}.{ext}' degil; "
            f"'{int(stem)}.{ext}' olarak yeniden adlandir"
        )
        badge_id = int(stem)
        assert 1 <= badge_id <= n, (
            f"{p.name}: ID katalog araligi disinda (1..{n} olmali, "
            f"rozetler.md {n} rozet tanimliyor) — app.js bu ID'yi hic uretmez"
        )


def test_badge_image_path_is_derived_from_id_not_a_manifest():
    text = APP.read_text(encoding="utf-8")
    assert 'BADGE_IMG_DIR = "assets/badges/"' in text
    # Dosya adi ID'den turer: BADGE_KEYS'teki konum + 1.
    assert "const badgeId = (key) => BADGE_KEYS.indexOf(key) + 1;" in text
    # Iki uzantiyi da dener ve yuklenemezse simgeye duser.
    assert 'BADGE_IMG_EXT = ["png", "webp"]' in text
    assert "badgeImgFail" in text and "img.remove()" in text
    # Gorsel adlarini tek tek sayan bir liste/manifest OLMAMALI.
    assert not re.search(r'"assets/badges/\d', text), "gorsel yolu elle yazilmis"


# ── 7) Sozdizimi kaniti (node yok) ──────────────────────────────
# Yorumlari ve string/template/regex GOVDELERINI atan mini sozucu: geriye kalan
# "iskelet"te ayraclar dengeli olmali ve sozucu code modunda bitmeli. Bu, node
# olmadan yakalanabilen sinifta hatalari (kapatilmamis template literal, eksik
# parantez/suslu ayrac) kanitlar.

_REGEX_PREV = set("(,=:[!&|?{};+~*%<>^-")


def code_skeleton(src):
    out = []
    i, n = 0, len(src)
    mode = "code"
    tpl_stack = []
    depth = 0
    last = ""
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if mode == "code":
            if c == "/" and nxt == "/":
                while i < n and src[i] != "\n":
                    i += 1
                continue
            if c == "/" and nxt == "*":
                i += 2
                while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                    i += 1
                i += 2
                continue
            if c == "/" and (last in _REGEX_PREV or last == ""):
                i += 1
                in_class = False
                while i < n:
                    ch = src[i]
                    if ch == "\\":
                        i += 2
                        continue
                    if ch == "[":
                        in_class = True
                    elif ch == "]":
                        in_class = False
                    elif ch == "/" and not in_class:
                        i += 1
                        break
                    elif ch == "\n":
                        i += 1
                        break
                    i += 1
                last = "/"
                continue
            if c in "'\"":
                mode = "sq" if c == "'" else "dq"
                i += 1
                continue
            if c == "`":
                mode = "tpl"
                i += 1
                continue
            if tpl_stack and c == "{":
                depth += 1
            elif tpl_stack and c == "}":
                if depth == 0:  # ${ } ifadesi bitti — ac/kapa cifti birlikte dusuyor
                    depth = tpl_stack.pop()
                    mode = "tpl"
                    i += 1
                    continue
                depth -= 1
            out.append(c)
            if not c.isspace():
                last = c
            i += 1
        elif mode in ("sq", "dq"):
            if c == "\\":
                i += 2
                continue
            if (mode == "sq" and c == "'") or (mode == "dq" and c == '"'):
                mode = "code"
                last = c
            i += 1
        else:  # tpl
            if c == "\\":
                i += 2
                continue
            if c == "`":
                mode = "code"
                last = "`"
                i += 1
                continue
            if c == "$" and nxt == "{":
                tpl_stack.append(depth)
                depth = 0
                mode = "code"
                last = "{"
                i += 2
                continue
            i += 1
    return "".join(out), mode, tpl_stack


def assert_balanced(path):
    src = path.read_text(encoding="utf-8")
    skeleton, mode, tpl_stack = code_skeleton(src)
    assert mode == "code", f"{path.name}: kapatilmamis string/template (mod={mode})"
    assert not tpl_stack, f"{path.name}: kapatilmamis ${{ }} ifadesi"
    pairs = {")": "(", "]": "[", "}": "{"}
    stack = []
    for ch in skeleton:
        if ch in "([{":
            stack.append(ch)
        elif ch in pairs:
            assert stack and stack[-1] == pairs[ch], f"{path.name}: eslesmeyen '{ch}'"
            stack.pop()
    assert not stack, f"{path.name}: kapatilmamis ayrac(lar): {''.join(stack)}"


def test_js_sources_are_syntactically_balanced():
    for name in ("app.js", "mock_api.js", "advisor.js"):
        assert_balanced(WEBUI / name)
    for lang in ("tr", "en", "core"):
        assert_balanced(WEBUI / "i18n" / f"{lang}.js")


# ── 6) Literal i18n anahtarlari sozlukte var ────────────────────


def test_literal_translation_keys_exist_in_both_dictionaries():
    """t("bir.anahtar") cagrilari — anahtarin PARCASI birlestirilenler
    (t("profile.badge_" + key) gibi) kapsam disidir, onlari katalog testi tutar."""
    tr, en = load_dict("tr"), load_dict("en")
    for name in ("app.js", "advisor.js"):
        src = (WEBUI / name).read_text(encoding="utf-8")
        keys = set(re.findall(r'\bt\(\s*"([a-z0-9_]+\.[a-z0-9_]+)"\s*[),]', src))
        missing = sorted(k for k in keys if k not in tr or k not in en)
        assert not missing, f"{name}: sozlukte olmayan anahtarlar: {missing}"


# ── mock yaniti sekil kontrolu (alan adlari) ────────────────────


def test_mock_badge_row_carries_the_new_contract_fields():
    text = MOCK.read_text(encoding="utf-8")
    for field in ("matches_played", "best_match_id", "best_value", "tier",
                  "rate", "next_tier_count", "progress", "roster_size",
                  "holders", "holders_pct", "one_time", "tier_scale"):
        assert field in text, f"mock_api.js '{field}' alanini uretmiyor"
    # Kademe artik SAYAC esikleridir (oran DEGIL) ve iki olcek vardir.
    assert "next_tier_rate" not in text, "next_tier_rate KALDIRILDI (contract)"
    assert "TIER_MIN_MATCHES" not in text, "matches_played >= 8 sarti KALDIRILDI"
    assert re.search(r"standard:\s*\{\s*silver:\s*3,\s*gold:\s*5,\s*platinum:\s*8,\s*diamond:\s*12\s*\}", text)
    assert re.search(r"rare:\s*\{\s*silver:\s*2,\s*gold:\s*3,\s*platinum:\s*4,\s*diamond:\s*6\s*\}", text)
    assert "TIER_BRONZE = 1" in text and "STELLAR_TARGET = 3" in text
    assert "stellar_quest" in text, "mock 'stellar_quest' alanini uretmiyor"


# ── GOREV 24 UI turu (Teoman 2026-08-19): K2-2 yerlesimi + 6 duzeltme ──
# Bu blok, insanin ACIKCA istedigi kararlarin koda gectigini kanitlar; hepsi
# metin/kaynak kaniti (node yok), davranis degil.


def app_text():
    return APP.read_text(encoding="utf-8")


def css_text():
    return CSS.read_text(encoding="utf-8")


def fn_body(text, header, end="\n  }\n"):
    """app.js'teki bir fonksiyon/atama govdesini kabaca keser."""
    i = text.index(header)
    j = text.index(end, i)
    return text[i:j]


def test_app_knows_the_six_tiers_in_ascending_order():
    m = re.search(r"const BADGE_TIERS = \[(.*?)\];", app_text(), re.DOTALL)
    assert m, "BADGE_TIERS bulunamadi"
    assert re.findall(r'"([a-z]+)"', m.group(1)) == TIERS


def test_every_tier_has_its_own_frame_style():
    css = css_text()
    for name in TIERS:
        assert f".pb-t-{name}" in css, f"style.css '.pb-t-{name}' kademe stili yok"


def test_tier_names_exist_in_both_dictionaries():
    for lang in ("tr", "en"):
        d = load_dict(lang)
        missing = [f"profile.badge_tier_{x}" for x in TIERS
                   if f"profile.badge_tier_{x}" not in d]
        assert not missing, f"{lang}.js eksik kademe adlari: {missing}"


def test_stellar_frame_is_privileged_and_reduced_motion_safe():
    """Duzeltme 5: `stellar` gokkusagi + parlak metal kirinimi. Animasyon
    prefers-reduced-motion'da durur ama KIRINIM HISSI (statik gradient) kalir —
    yani gradient bir animasyonun ICINDE tanimlanmis olmamali."""
    css = css_text()
    block = css[css.index(".pb-t-stellar"):css.index("@keyframes pb-stellar-turn")]
    assert "conic-gradient" in block, "stellar kirinimi gokkusagi (conic) degil"
    assert "@property --pb-turn" in css, "acinin animasyonu icin @property yok"
    assert "animation: pb-stellar-turn" in block
    # Global azaltilmis-hareket blogu animasyonu kapatir; gradient background'ta
    # kaldigi icin statik kirinim durur.
    assert re.search(r"@media \(prefers-reduced-motion: reduce\)[^}]*animation: none", css)


def test_stellar_has_no_ring_outside_the_medal():
    """[REVIZE — Teoman fix2] Madalyonun DISINDA donen ekstra halka KALDIRILDI:
    komsu bilesenlerin kutusuna giriyordu. Stellar'in sekli diger kademelerle
    BIREBIR AYNI olmali; kirinim madalyonun kendi yuzeyinde (plaka geometrisine
    clip-path ile kirpilmis) kalir."""
    css = css_text()
    block = css[css.index(".pb-t-stellar  {"):css.index("@keyframes pb-stellar-turn")]
    # Madalyon KUTUSUNUN DISINA cikan bir katman olmamali: negatif inset yok.
    assert not re.search(r"inset:\s*-", block), (
        "stellar katmani madalyon kutusunun disina tasiyor (negatif inset)"
    )
    # Kirinim .pb-medal uzerinde ve plakanin sekizgenine kirpilmis.
    assert ".pb-t-stellar .pb-medal::before" in block
    assert "clip-path: polygon(" in block
    # Isima kutusu (.pb-glow) stellar'a OZEL bir kural tasimamali: sekil ortak.
    assert ".pb-t-stellar .pb-glow" not in css, (
        "stellar'in isima/halka kutusu diger kademelerden farkli"
    )


def test_score_number_is_centered_and_unit_hangs_outside_the_flow():
    """Duzeltme 4: "18.5" kaidenin tam ortasinda; birim ana eksende yer
    kaplamadigi icin (sifir genislikli esnek oge) merkezi kaydirmaz."""
    text, css = app_text(), css_text()
    assert 'class="k2-sc-u"' in text, "birim ayri bir sinif tasimali"
    row = re.search(r"\.k2-cap-sc \{([^}]*)\}", css)
    assert row and "justify-content: center" in row.group(1)
    assert "align-items: baseline" in row.group(1), "taban hizasi korunmali"
    unit = re.search(r"\.k2-cap-sc \.k2-sc-u \{([^}]*)\}", css)
    assert unit, ".k2-sc-u kurali bulunamadi"
    u = unit.group(1)
    assert "width: 0" in u and "flex: 0 0 0" in u and "overflow: visible" in u, (
        "birim sifir genislikli + tasmasi gorunur olmali (merkezi kaydirmasin)"
    )


def test_showcase_picks_the_highest_tier_three_not_the_rarest():
    """api_contract §2 'Profil vitrini': secim olcutu EN YUKSEK KADEME; esitlikte
    holders_pct kucuk -> count buyuk -> katalog sirasi. Kilitli rozet giremez."""
    body = fn_body(app_text(), "function badgeShowcase()")
    assert "!badgeLocked(b)" in body, "kilitli rozet vitrine girmemeli"
    order = [
        "badgeTierRank(b) - badgeTierRank(a)",
        "badgeHoldersPct(a.key) - badgeHoldersPct(b.key)",
        "Number(b.count) - Number(a.count)",
        "BADGE_KEYS.indexOf(a.key) - BADGE_KEYS.indexOf(b.key)",
    ]
    pos = [body.index(x) for x in order]  # hepsi var ve BU SIRADA
    assert pos == sorted(pos), f"vitrin siralama zinciri bozuk: {order}"
    assert "slice(0, SHOWCASE_N)" in body
    assert "const SHOWCASE_N = 3;" in app_text()


def test_showcase_has_no_rank_label_and_no_rarity_percent():
    """Duzeltmeler 3-4: 'EN NADIR 1/2/3' sira etiketi YOK; 'grupta %X kiside'
    vitrinde YAZMAZ (nadirlik yalniz bilgi baloncugunda)."""
    text = app_text()
    big = fn_body(text, "function badgeBigCard(b)")
    assert "badgeHoldersText" not in big, "nadirlik vitrin kartinda basiliyor"
    assert "pb-rank" not in text and "showcase_rank" not in text
    card = fn_body(text, "function badgeCard(b)")
    assert "badgeHoldersText" not in card, "nadirlik kuyruk kartinda basiliyor"
    # Nadirlik TEK yerde: baloncuk.
    tip = fn_body(text, "function openBadgeTip(card, b)")
    assert "badgeHoldersText(b.key)" in tip


def test_badge_tip_works_on_hover_touch_and_keyboard_for_both_places():
    """Duzeltme 6: baloncuk hem USTTEKI 3 buyuk rozette hem alttaki kuyrukta,
    hover + dokunma (click) + klavye odagiyla acilir; tek bir baglayici basar."""
    text = app_text()
    bind = fn_body(text, "function badgeBindCards(root, list)")
    assert '.querySelectorAll(".pb-card, .pb-big")' in bind, (
        "ayni baglayici hem kuyruk kartlarini hem vitrin madalyonlarini kapsamali"
    )
    for ev in ("mouseenter", "mouseleave", "click", "focus", "blur"):
        assert f'addEventListener("{ev}"' in bind, f"baloncuk '{ev}' olayina bagli degil"
    # Vitrin ve kuyruk aynı fonksiyonla baglanir.
    render = fn_body(text, "function renderBadges()")
    assert "badgeBindCards(plinth, top)" in render
    assert "badgeBindCards(sec, rest)" in render


def test_showcase_badges_are_not_repeated_in_the_tail():
    render = fn_body(app_text(), "function renderBadges()")
    assert "topKeys.indexOf(x.key) === -1" in render


def test_profile_header_has_no_engine_or_formula_line():
    """Duzeltme 1: puanin altindaki `openskill-pl-blend30-s2-v1 · mu_eff − 2σ`
    satiri KALDIRILDI (profilde hic basilmaz)."""
    text = app_text()
    m = re.search(r"const head =\n\s*`(.*?)`;", text, re.DOTALL)
    assert m, "profil kaidesinin head sablonu bulunamadi"
    head = m.group(1)
    for marker in ("openskill", "mu_eff", "engine", "sigma"):
        assert marker not in head, f"kaide basliginda '{marker}' izi var"


def test_role_ratings_use_the_shared_official_position_icon():
    """Duzeltme 2: rol simgeleri konseptin cizimleri DEGIL, projenin standart
    ikon kutuphanesi — ortak posIconHtml + mevcut pos-ico varligi/sinifi.
    YENI VARLIK EKLENMEDI: yollar Gecmis/mac detayindakiyle ayni dosyalar."""
    text, css = app_text(), css_text()
    grid = fn_body(text, "function k2Gauges(rr)")
    assert 'posIconHtml(r, roleAbbr(r), "k2-ri")' in grid, (
        "rol yayinda ortak posIconHtml kullanilmiyor"
    )
    assert "<path" not in grid and "<svg" in grid, (
        "rol simgesi elle cizilmis olmamali (yay SVG'si serbest, simge degil)"
    )
    # Simge kutusu boyutunu ORTAK --pos-ico degiskeninden alir.
    assert re.search(r"\.k2-gg-ic \.k2-ri \{[^}]*--pos-ico:", css, re.DOTALL)
    # Varlik yollari degismedi.
    for f in ("top", "jungle", "middle", "bottom", "utility"):
        assert f'url("assets/ddragon/position/{f}.svg")' in css


def test_stellar_quest_row_is_optional_and_diamond_only():
    """Stellar artik ORANLA kazanilmiyor (Teoman 2026-08-19): elmasta oran hedefi
    yerine GOREV gosterilir, stellar'da 'tamamlandi', alt kademelerde hic
    basilmaz. Alan gelmiyorsa (eski backend) satir SESSIZCE atlanir."""
    text = app_text()
    quest = fn_body(text, "const badgeQuest = (b) =>", "\n  };")
    assert "if (!q) return null;" in quest, "eksik alan sessizce atlanmali"
    body = fn_body(text, "function badgeQuestText(b)")
    assert 'tier === "stellar"' in body and "badge_quest_done" in body
    assert 'tier !== "diamond"' in body, "gorev satiri yalniz elmasta gosterilmeli"
    for lang in ("tr", "en"):
        d = load_dict(lang)
        assert "profile.badge_quest" in d and "profile.badge_quest_done" in d


def test_mock_covers_both_stellar_and_diamond_paths():
    """Mock'ta en az bir oyuncuda `met: true` + stellar, birinde diamond +
    best: 2 (goreve 1 kalmis) bulunmali ki iki UI yolu da denenebilsin.
    Kademe artik SAYAC esikli: standart elmas 12, nadir elmas 6."""
    text = MOCK.read_text(encoding="utf-8")
    assert 'if (tier === "diamond" && met) tier = "stellar";' in text
    counts = re.search(r"const COUNTS = \{(.*?)\};", text, re.DOTALL)
    runs = re.search(r"const RUNS = \{(.*?)\};", text, re.DOTALL)
    assert counts and runs, "senaryo sabitleri (COUNTS / RUNS) bulunamadi"
    cd = {k: int(v) for k, v in re.findall(r"(\w+): (\d+)", counts.group(1))}
    ru = {k: int(v) for k, v in re.findall(r"(\w+): (\d+)", runs.group(1))}
    dia = {k: (6 if k == "perfect_quad" else 12) for k in cd}
    stellar = [k for k, v in cd.items() if v >= dia[k] and ru.get(k, 0) >= 3]
    diamond = [k for k, v in cd.items() if v >= dia[k] and ru.get(k, 0) == 2]
    assert stellar, "hicbir rozette stellar yolu (elmas sayaci + gorev tamam) yok"
    assert diamond, "hicbir rozette 'goreve 1 kalmis' elmas yolu yok"
    # Alti kademenin hepsi tek profilde gorunsun (standart olcek esikleri).
    std = {k: v for k, v in cd.items() if k != "perfect_quad"}
    assert min(std.values()) < 3, "bronz yolu yok"
    assert any(3 <= v < 5 for v in std.values()), "gumus yolu yok"
    assert any(5 <= v < 8 for v in std.values()), "altin yolu yok"
    assert any(8 <= v < 12 for v in std.values()), "platin yolu yok"


def test_profile_section_order_follows_k2_2():
    """Zorunlu sira: kaide -> grafik + rol ratingleri -> sinerji -> rozet
    kuyrugu -> favori esya / diger."""
    text = app_text()
    assert 'return head + `<div class="k2-body">${ratingSec}${synSec}${badgeSec}${otherSec}</div>`;' in text
    duo = re.search(r'const duo = `<div class="k2-duo.*?`;', text, re.DOTALL)
    assert duo, "grafik + rol ratingleri ikilisi bulunamadi"
    # Ikili: grafik karti (#prof-history) SOLDA, rol yaylari (roleCard) SAGDA.
    inner = duo.group(0)
    assert inner.index('id="prof-history"') < inner.index("${roleCard}")


def test_history_chart_interaction_is_preserved():
    """Yerlesim tasindi ama grafigin ETKILESIMI aynen kalmali: nokta -> mac
    kunyesi -> mac detayina gitme + zaman araligi dugmeleri."""
    text = app_text()
    for marker in ("ph-hit", "openHistPopup", "openMatchFromHistory",
                   "ph-pill", "state.historyRange"):
        assert marker in text, f"grafik etkilesimi kayboldu: {marker}"


def test_tier_target_is_a_badge_COUNT_not_a_ratio():
    """[REVIZE — Teoman 2026-08-19] Kademe kumulatif SAYACLADIR ve ASLA DUSMEZ:
    UI hedefi "Platin'e 3 rozet kaldi" olarak gosterir (`next_tier_count - count`),
    oran hedefi GOSTERMEZ (`next_tier_rate` alani contract'tan kaldirildi)."""
    text = app_text()
    assert "next_tier_rate" not in text.replace("`next_tier_rate` KALDIRILDI", ""), (
        "app.js hala next_tier_rate okuyor"
    )
    body = fn_body(text, "function badgeTierTargetText(b)")
    assert "numOrNull(b.next_tier_count)" in body
    assert "next - have" in body, "kalan rozet sayisi next_tier_count - count olmali"
    assert "profile.badge_tier_next" in body
    # Esikler UI'da YAZILI OLMAMALI (backend'den gelir).
    assert not re.search(r"(12|8|5|3)\s*[;,)]", body), "kademe esigi UI'a gomulmus"
    for lang in ("tr", "en"):
        d = load_dict(lang)
        assert "profile.badge_rate" not in d, (
            "oran metni artik gosterilmiyor: olu anahtar sozlukte kalmamali"
        )


def test_every_catalog_badge_has_an_icon():
    """Ikon yoksa madalyon BOS bir svg olarak cizilirdi (sessiz gorsel hata)."""
    text = app_text()
    m = re.search(r"const BADGE_ICONS = \{(.*?)\n  \};", text, re.DOTALL)
    assert m, "BADGE_ICONS bulunamadi"
    have = set(re.findall(r"^    ([a-z0-9_]+):", m.group(1), re.M))
    missing = [k for k in catalog_from_md() if k not in have]
    assert not missing, f"ikonu olmayan rozetler: {missing}"


# ── K2-2 konseptinin BIREBIR tasinmasi (Teoman: "aynen uygula") ──


def test_layout_uses_the_concept_skeleton():
    """Iskelet konseptten: .k2-hero > .k2-hero-in > .k2-cap + .k2-stage
    (.k2-nbs-l | .pb-plinth | .k2-nbs-r), sonra .k2-body."""
    text = app_text()
    for marker in ('class="k2-hero"', 'class="k2-hero-in"', 'class="k2-cap"',
                   'class="k2-stage"', 'class="k2-nbs k2-nbs-l"',
                   'class="pb-plinth" id="prof-showcase"', 'class="k2-nbs k2-nbs-r"',
                   'class="k2-floor"', 'class="k2-body"'):
        assert marker in text, f"konsept iskeletinden eksik: {marker}"
    # Sahne sirasi: sol rakamlar -> vitrin -> sag rakamlar.
    i_l = text.index('class="k2-nbs k2-nbs-l"')
    i_p = text.index('class="pb-plinth" id="prof-showcase"')
    i_r = text.index('class="k2-nbs k2-nbs-r"')
    assert i_l < i_p < i_r


def test_concept_measurements_are_copied_verbatim():
    """Konseptin olculeri (kaide, sahne, govde, yaylar, maden) BIREBIR."""
    css = css_text()
    checks = [
        # kaide
        (r"\.k2-hero \{[^}]*radial-gradient\(125% 95% at 50% 0%, #16283a 0%, var\(--bg\) 70%\)", "hero gradient"),
        (r"\.k2-hero-in \{[^}]*max-width: 1240px[^}]*padding: 26px 20px 0", "hero-in"),
        (r"\.k2-cap-nm \{[^}]*clamp\(30px, 6vw, 52px\)", "ad puntosu"),
        (r"\.k2-cap-sc b \{[^}]*clamp\(34px, 7vw, 50px\)", "puan puntosu"),
        (r"\.k2-stage \{[^}]*minmax\(132px, 186px\) minmax\(0, 1fr\) minmax\(132px, 186px\)", "sahne izgarasi"),
        (r"\.k2-nb-v \{[^}]*font-size: 27px", "rakam puntosu"),
        # govde
        (r"\.k2-body \{[^}]*max-width: 1240px[^}]*padding: 24px 20px 70px", "govde"),
        (r"\.k2-duo \{[^}]*minmax\(0, 1fr\) minmax\(220px, 320px\)", "ikili izgara"),
        # rol yaylari
        (r"\.k2-gauges \{[^}]*minmax\(84px, 1fr\)", "yay izgarasi"),
        (r"\.k2-gg-w \{[^}]*clamp\(62px, 18vw, 78px\)", "yay capi"),
        (r"\.k2-gg-v \{[^}]*font-size: 17px", "yay degeri"),
        # vitrin + maden
        (r"\.pb-plinth \{[^}]*gap: clamp\(6px, 3vw, 40px\)", "vitrin bosluklari"),
        (r"\.pb-plinth \.pb-medal \{[^}]*clamp\(58px, 16vw, 116px\)", "madalyon capi"),
        (r"nth-child\(1\) \.pb-medal \{[^}]*clamp\(70px, 20vw, 142px\)", "ortadaki madalyon buyuk"),
        (r"\.pb-coin \{[^}]*min-width: clamp\(28px, 7\.4vw, 52px\)", "maden capi"),
        (r"\.pb-coin b \{[^}]*clamp\(17px, 4\.6vw, 32px\)", "maden rakami"),
    ]
    for pat, name in checks:
        assert re.search(pat, css, re.DOTALL), f"konsept olcusu tasinmamis: {name}"
    # Ortadaki madalyon YUKARI kalkik.
    assert re.search(r"\.pb-big-cell:nth-child\(1\) \{[^}]*order: 2[^}]*translateY\(-12px\)", css, re.DOTALL)


def test_medal_is_an_octagon_plate_not_a_rounded_card():
    """Madalyon formu konseptin .medal bileseni: sekizgen plaka + faset
    cizgileri + ic halka + ortada simge (512 viewBox)."""
    text, css = app_text(), css_text()
    assert 'const MEDAL_PLATE = "M256 22 418 96 492 258 418 420 256 494 94 420 20 258 94 96Z"' in text
    assert "MEDAL_FACET" in text and "MEDAL_RING" in text
    assert 'viewBox="0 0 512 512"' in text, "madalyon 512'lik viewBox kullanmali"
    for cls in ("pb-plate", "pb-facet", "pb-ring", "pb-gl"):
        assert "." + cls in css, f"style.css '{cls}' katmani yok"
    # Kuyruk kartinin kart kromu KALKTI (konseptte .tail ogeleri kart degil).
    card = re.search(r"\n\.pb-card \{(.*?)\n\}", css, re.DOTALL)
    assert card, ".pb-card kurali bulunamadi"
    assert "border: 0" in card.group(1) and "background: none" in card.group(1)


def test_profile_view_is_full_width():
    """Konseptte hero full-bleed, icerik 1240px. Kisit YALNIZ profilde kalkar."""
    text, css = app_text(), css_text()
    assert '$("#main").classList.toggle("pa-full", name === "profile");' in text
    assert re.search(r"main\.pa-full \{[^}]*max-width: none", css)
    # Global main kurali bozulmamis olmali.
    assert re.search(r"^main \{[^}]*max-width: 720px", css, re.M)


def test_tier_label_is_calm_text_not_a_pill():
    """Duzeltme 4: kademe adi madalyonun ALTINDA sakin metin; pill (cerceve +
    dolgu + radius) kaldirildi, renk kademeden gelir."""
    css = css_text()
    tier = re.search(r"\n\.pb-tier \{(.*?)\n\}", css, re.DOTALL)
    assert tier, ".pb-tier kurali bulunamadi"
    body = tier.group(1)
    assert "border" not in body and "border-radius" not in body and "padding" not in body
    assert "--pb-tint" in body, "kademe rengi degiskenden gelmeli"


def test_open_view_is_centered_on_the_viewport():
    """[Teoman fix2] Panel AKISTA oldugu icin ortalanan icerik viewport
    merkezinin sagina kayiyordu. Telafi: kabugun sag ucuna panel genisliginde
    bir BOSLUK OGESI (.sb-app::after) eklemek — main'e tek taraflı margin
    DEGIL (flex'te tek auto-margin tum bosluk alanini yutar, gerekce
    style.css'te). Kural TUM gorunumler icin gecerlidir (gorunume ozel
    degildir) ve YALNIZ panelin akista oldugu genislikte (>=880px) uygulanir
    — mobilde panel cekmeceye donup akistan cikar, orada telafi YOKTUR."""
    css = css_text()
    m = re.search(r"@media \(min-width: 880px\) \{\s*\.sb-app::after \{ content: \"\"; flex: 0 0 var\(--sb-w\); \}\s*\}", css)
    assert m, "viewport merkezleme telafisi yok (.sb-app::after boşluk ögesi, flex: 0 0 var(--sb-w))"
    # Telafi gorunume ozel bir kural DEGIL (main'in kendisinde tanimli degil).
    assert "#view-profile { margin-right" not in css
    assert "main { margin-right" not in css
    # Kural yalniz >=880px media sorgusunda var; disinda (mobil) tekrar etmiyor.
    assert css.count(".sb-app::after") == 1, (
        ".sb-app::after tam olarak bir kez, yalniz min-width:880px icinde tanimli olmali"
    )


def test_fonts_are_declared_with_real_local_fallbacks():
    """[Teoman fix2] Konseptin aileleri gercekten yuklenir; her degiskenin
    SONUNDA gercek yerel yigin durur (font gelmezse site fontsuz kalmaz).
    [Teoman 2026-08-19 duzeltmesi] Bu fontlar YALNIZ profil sayfasinda
    kalir — global :root'a uygulanmaz ("bu sayfaya koydugumuz fontu her
    sayfaya uyarlamissin, hayir, sadece bu sayfada kalsin"). Google Fonts
    <link>'i index.html'de kalir (profil icin gerekli), ama :root eski
    yigina doner ve konseptin aileleri yalniz #view-profile kapsaminda
    tanimlidir."""
    html = (WEBUI / "index.html").read_text(encoding="utf-8")
    assert "fonts.googleapis.com/css2" in html, "Google Fonts link'i yok"
    for fam in ("Barlow+Condensed", "IBM+Plex+Sans", "IBM+Plex+Mono"):
        assert fam in html, f"{fam} yuklenmiyor"
    assert "display=swap" in html, "display=swap yok (ilk boyama bloklanir)"
    assert "preconnect" in html
    css = css_text()

    # :root: ESKİ yigina donmus olmali — konseptin aileleri burada GECMEMELİ.
    # (Yorumlar cikarilir: aciklama metninde gecen font adi degil, GERCEK
    # deger denetlenir.)
    root = re.search(r"^:root \{(.*?)^\}", css, re.DOTALL | re.M)
    assert root
    r = re.sub(r"/\*.*?\*/", "", root.group(1), flags=re.DOTALL)
    for banned in ("Barlow Condensed", "IBM Plex Sans", "IBM Plex Mono"):
        assert banned not in r, (
            f":root icinde '{banned}' var — konsept fontu global uygulanmis, "
            "yalniz #view-profile'da olmali (Teoman 2026-08-19)"
        )
    for var, first in (
        ("--display", '"Bahnschrift"'),
        ("--body", "system-ui"),
    ):
        line = re.search(re.escape(var) + r":([^;]*);", r)
        assert line, f"{var} :root'ta tanimli degil"
        assert first in line.group(1), f"{var} eski aileye donmemis"
    mono_line = re.search(r"--mono:([^;]*);", r)
    assert mono_line, "--mono :root'tan tamamen kaldirilmis olabilir (baska yerde kullaniliyorsa kalmali)"
    assert "IBM Plex Mono" not in mono_line.group(1)

    # #view-profile: konseptin aileleri YALNIZ burada, gercek yerel yedekle.
    prof = re.search(r"#view-profile \{(.*?)^\}", css, re.DOTALL | re.M)
    assert prof, "#view-profile bloğu bulunamadi"
    p = prof.group(1)
    for var, first, fallback in (
        ("--display", '"Barlow Condensed"', '"Bahnschrift"'),
        ("--body", '"IBM Plex Sans"', "system-ui"),
        ("--mono", '"IBM Plex Mono"', "ui-monospace"),
    ):
        line = re.search(re.escape(var) + r":([^;]*);", p)
        assert line, f"{var} #view-profile icinde tanimli degil"
        val = line.group(1)
        assert first in val, f"{var} konseptin ailesini istemiyor"
        assert fallback in val, f"{var} gercek yerel yedek tasimiyor"
