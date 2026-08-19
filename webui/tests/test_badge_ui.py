# test_badges.py — rozet vitrini sozlesmesi (GOREV 24, 27 rozet).
#
# Node YOK: JS dosyalari stdlib ile ayiklanir. Dogrulananlar:
#   1) app.js BADGE_KEYS sirasi = badges/rozetler.md ID sirasi (gorsel dosya
#      adlari bu ID'ye bagli — sira DONDURULMUS, kayma sessiz bir hata olurdu).
#   2) mock_api.js BADGE_CATALOG ayni sirada ve ayni anahtarlarla (mock pariteligi).
#   3) Her rozet icin ad + aciklama tr VE en'de var; katalog disi (olu) rozet
#      anahtari sozluklerde KALMAMIS.
#   4) Kademeli rozetler tam olarak api_contract §2'deki 6 tanesi.
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
BADGE_DIR = WEBUI / "assets" / "badges"

TIERED = ["mvp", "vision", "damage", "cs_per_min", "gold", "role_duel"]


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
    assert len(cat) == 27, f"katalog 27 rozet olmali, {len(cat)} bulundu"
    assert keys_from_app() == cat, "app.js BADGE_KEYS sirasi katalog ID sirasindan sapti"


def test_mock_catalog_matches_frozen_catalog():
    assert [k for k, _ in catalog_from_mock()] == catalog_from_md()


def test_tiered_badges_are_exactly_the_six():
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
        "progress", "progress_aria", "tier_bronze", "tier_silver", "tier_gold",
        "tier_aria", "tier_next", "rate", "holders", "holders_none",
    }
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
                  "rate", "next_tier_rate", "progress", "roster_size",
                  "holders", "holders_pct", "one_time"):
        assert field in text, f"mock_api.js '{field}' alanini uretmiyor"
    # Kademe esikleri contract'takiler olmali.
    assert "TIER_SILVER = 0.2" in text and "TIER_GOLD = 0.32" in text
    assert "TIER_MIN_MATCHES = 8" in text
