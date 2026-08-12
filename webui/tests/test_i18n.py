# test_i18n.py — docs/i18n_contract.md §4/1-3 doğrulaması (yalnız stdlib, Node yok).
#
# 1) tr ve en sözlüklerinin anahtar kümeleri birebir aynı ve tüm değerler dolu.
# 2) en değerlerinde Türkçe'ye özgü karakter yok.
# 3) webui/index.html ve webui/app.js'te (yorumlar hariç) Türkçe'ye özgü
#    karakter kalmadı. i18n/ dizini ve mock_api.js (veri taklidi) muaftır.
#
# Sözlükler JS dosyalarından çıkarılır: nesne gövdeleri bilinçli olarak katı
# JSON'dur (bkz. i18n/tr.js not satırı), regex ile kesilip json.loads edilir.

import json
import re
from pathlib import Path

WEBUI = Path(__file__).resolve().parent.parent
TURKISH_CHARS = re.compile(r"[çğıöşüÇĞİÖŞÜ]")


# ── Sözlük çıkarma ──────────────────────────────────────────────


def load_dict(lang):
    """window.I18N_DICTS.<lang> = {...}; ifadesindeki JSON gövdesini çıkarır."""
    path = WEBUI / "i18n" / f"{lang}.js"
    text = path.read_text(encoding="utf-8")
    m = re.search(
        r"window\.I18N_DICTS\.%s\s*=\s*(\{.*\})\s*;" % re.escape(lang),
        text,
        re.DOTALL,
    )
    assert m, f"{path.name}: window.I18N_DICTS.{lang} sozluk nesnesi bulunamadi"
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError as e:  # pragma: no cover - hata mesaji icin
        raise AssertionError(f"{path.name}: sozluk govdesi gecerli JSON degil: {e}")
    assert isinstance(data, dict) and data, f"{path.name}: sozluk bos"
    return data


# ── Yorum ayıklama (string-bilinçli mini JS sözücüsü) ───────────
# Naif regex yaklaşımı app.js'te yanılır: template literal'lar ${ } içinde
# backtick barındırabilir ve /[&<>"']/g gibi regex literal'ları tırnak içerir.
# Bu yüzden küçük bir durum makinesi: string/template/regex içerikleri aynen
# korunur, yalnız // satır ve /* blok */ yorumları atılır.

_REGEX_PREV = set("(,=:[!&|?{};+~*%<>^-")


def strip_js_comments(src):
    out = []
    i, n = 0, len(src)
    mode = "code"  # code | sq | dq | tpl
    tpl_stack = []  # ${ } girişinde dış süslü ayraç derinliği saklanır
    brace_depth = 0  # yalnız ${ } içindeyken anlamlı
    last_sig = ""  # code modundaki son boşluk-dışı karakter (regex ayrımı için)

    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""

        if mode == "code":
            if c == "/" and nxt == "/":  # satır yorumu: satır sonuna dek at
                while i < n and src[i] != "\n":
                    i += 1
                continue
            if c == "/" and nxt == "*":  # blok yorumu: */ 'a dek at
                i += 2
                while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                    i += 1
                i += 2
                continue
            if c == "/" and (last_sig in _REGEX_PREV or last_sig == ""):
                # regex literal: içerik aynen korunur ([ ] sınıfı içindeki / bitirmez)
                out.append(c)
                i += 1
                in_class = False
                while i < n:
                    ch = src[i]
                    out.append(ch)
                    if ch == "\\" and i + 1 < n:
                        out.append(src[i + 1])
                        i += 2
                        continue
                    if ch == "[":
                        in_class = True
                    elif ch == "]":
                        in_class = False
                    elif ch == "/" and not in_class:
                        i += 1
                        break
                    elif ch == "\n":  # emniyet: regex satır aşamaz
                        i += 1
                        break
                    i += 1
                last_sig = "/"
                continue
            if c == "'":
                mode = "sq"
            elif c == '"':
                mode = "dq"
            elif c == "`":
                mode = "tpl"
            elif tpl_stack and c == "{":
                brace_depth += 1
            elif tpl_stack and c == "}":
                if brace_depth == 0:  # ${ } ifadesi bitti, template'a dön
                    brace_depth = tpl_stack.pop()
                    mode = "tpl"
                    out.append(c)
                    i += 1
                    continue
                brace_depth -= 1
            out.append(c)
            if not c.isspace():
                last_sig = c
            i += 1
        elif mode in ("sq", "dq"):
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(src[i + 1])
                i += 2
                continue
            if (mode == "sq" and c == "'") or (mode == "dq" and c == '"'):
                mode = "code"
                last_sig = c
            i += 1
        else:  # tpl
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(src[i + 1])
                i += 2
                continue
            if c == "`":
                mode = "code"
                last_sig = "`"
                i += 1
                continue
            if c == "$" and nxt == "{":
                out.append(nxt)
                tpl_stack.append(brace_depth)
                brace_depth = 0
                mode = "code"
                last_sig = "{"
                i += 2
                continue
            i += 1

    return "".join(out)


def strip_html_comments(src):
    return re.sub(r"<!--.*?-->", "", src, flags=re.DOTALL)


def _report(text, path):
    """İhlal eden satırları numarasıyla listeler (hata mesajı okunur olsun)."""
    bad = [
        f"  {path.name}:{no}: {line.strip()}"
        for no, line in enumerate(text.splitlines(), 1)
        if TURKISH_CHARS.search(line)
    ]
    return "\n".join(bad)


# ── §4/1: anahtar kümeleri birebir aynı, değerler dolu ──────────


def test_dictionaries_have_identical_key_sets():
    tr = load_dict("tr")
    en = load_dict("en")
    only_tr = sorted(set(tr) - set(en))
    only_en = sorted(set(en) - set(tr))
    assert not only_tr and not only_en, (
        f"anahtar kumeleri ayristi — yalniz tr'de: {only_tr}, yalniz en'de: {only_en}"
    )


def test_dictionary_values_are_non_empty_strings():
    for lang in ("tr", "en"):
        d = load_dict(lang)
        bad = sorted(
            k for k, v in d.items() if not isinstance(v, str) or not v.strip()
        )
        assert not bad, f"{lang}.js icinde bos/string-disi degerler: {bad}"


# ── §4/2: en değerlerinde Türkçe'ye özgü karakter yok ───────────


def test_english_values_contain_no_turkish_characters():
    en = load_dict("en")
    bad = sorted(k for k, v in en.items() if TURKISH_CHARS.search(v))
    assert not bad, f"en.js degerlerinde Turkce'ye ozgu karakter: {bad}"


# ── §4/3: index.html ve app.js yorum dışı Türkçe karakter içermez ──
# (i18n/ dizini ve mock_api.js muaf: sözlük Türkçe taşır, mock veri taklididir.)


def test_index_html_has_no_turkish_outside_comments():
    path = WEBUI / "index.html"
    text = strip_html_comments(path.read_text(encoding="utf-8"))
    # Gömülü <script> içindeki // ve /* */ yorumları da yorumdur.
    text = strip_js_comments(text)
    bad = _report(text, path)
    assert not bad, f"index.html yorum disinda Turkce karakter iceriyor:\n{bad}"


def test_app_js_has_no_turkish_outside_comments():
    path = WEBUI / "app.js"
    text = strip_js_comments(path.read_text(encoding="utf-8"))
    bad = _report(text, path)
    assert not bad, f"app.js yorum disinda Turkce karakter iceriyor:\n{bad}"
