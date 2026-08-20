# test_score_offset.py — GOSTERIM OFSETI (docs/rating_contract.md
# "Gosterim ofseti (display offset) — SUNUM KATMANI, veri DEGIL").
#
# Karar (Teoman, 2026-08-20): aktif engine `openskill-pl-blend30-s2-v1` ile
# macsiz oyuncunun HAM skoru 0 degil ~8.3333'tur (25 - 2*(25/3)). Skorun
# ekranda yine 0 TABANINDAN baslamasi istendi:
#
#     gosterilen_score = ham_score - NEUTRAL_SCORE
#
# Bu dosyanin ASIL isi tek bir seyi kilitlemektir: `webui/app.js` icindeki
# SCORE_OFFSET sabiti, rating engine'inin URETTIGI notr skorla ayni olmalidir.
# Sigma katsayisi (S) ileride yine degisirse bu test kirilir ve taban sessizce
# kaymaz. Kalan testler kaynak kanitidir (Node yok, CI'da yalniz pytest kosar):
# ofsetin UYGULANDIGI gosterim yerleri ve UYGULANMADIGI (ordinal / fark-delta)
# yerler tek tek dondurulur.

import math
import re
from pathlib import Path

import pytest

WEBUI = Path(__file__).resolve().parent.parent
APP = WEBUI / "app.js"
MOCK = WEBUI / "mock_api.js"
FAQ = WEBUI / "assets" / "faq"

# rating_contract "Harman Engine — blend30-s2"; FAQ metniyle capraz dogrulanir
# (asagidaki test_active_engine_version_matches_the_faq).
ACTIVE_ENGINE = "openskill-pl-blend30-s2-v1"


def app_text():
    return APP.read_text(encoding="utf-8")


def mock_text():
    return MOCK.read_text(encoding="utf-8")


# ── Sabitin okunmasi ──────────────────────────────────────────────────────
# Sabit ARITMETIK IFADE olarak yazilir (`25 - 2 * (25 / 3)`), duz bir sayi
# olarak DEGIL: engine parametreleri kaynakta gorunur kalsin. Burada ifade
# ayristirilip degerlendirilir; eval yalnizca aritmetik karakterlere izin
# veren bir suzgecten sonra kosar.
OFFSET_RE = re.compile(r"^\s*const SCORE_OFFSET = ([^;]+);", re.M)
_ALLOWED = set("0123456789.+-*/() ")


def offset_expr():
    hits = OFFSET_RE.findall(app_text())
    assert len(hits) == 1, f"SCORE_OFFSET tam olarak BIR kez tanimlanmali: {hits}"
    return hits[0].strip()


def offset_value():
    expr = offset_expr()
    assert set(expr) <= _ALLOWED, f"SCORE_OFFSET saf aritmetik olmali: {expr!r}"
    return eval(expr, {"__builtins__": {}}, {})  # noqa: S307 — suzgecten gecti


def engine_neutral_score():
    """Aktif engine'in macsiz oyuncu skoru (mu=25, sigma=25/3, P_avg=1.0)."""
    from rating.engine import Engine

    engine = Engine(ACTIVE_ENGINE)
    prior = engine.default_rating()
    return engine.effective(prior.mu, prior.sigma, 1.0).score


# ── 1) ASIL KILIT: sabit == engine'in notr skoru ──────────────────────────
def test_offset_equals_the_engines_neutral_score():
    try:
        neutral = engine_neutral_score()
    except ImportError as exc:  # pragma: no cover — rating kurulu degilse
        pytest.skip(f"rating paketi import edilemedi: {exc}")
    assert math.isclose(offset_value(), neutral, rel_tol=0, abs_tol=1e-9), (
        f"app.js SCORE_OFFSET ({offset_value()}) aktif engine'in notr skoruyla "
        f"({neutral}) ayni degil — sigma katsayisi degistiyse ofset de guncellenmeli."
    )


def test_offset_equals_the_engine_constants_written_out():
    """Ikinci kemer: rating import edilemese bile taban kilitli kalir.

    mu_0 = 25, S = 2, sigma_0 = 25/3 (rating_contract blend30-s2).
    """
    assert math.isclose(offset_value(), 25 - 2 * (25 / 3), abs_tol=1e-12)


def test_offset_is_written_as_engine_arithmetic_not_a_magic_number():
    expr = offset_expr()
    assert "25" in expr and "/ 3" in expr, (
        f"SCORE_OFFSET engine sabitlerinden turetilmeli (25 - S*(25/3)), "
        f"cakma bir sayi olmamali: {expr!r}"
    )
    # Notr skor KODA hicbir yerde duz sayi olarak gomulmez (yorumlarda
    # aciklama amacli gecebilir).
    code = [ln for ln in app_text().splitlines() if not ln.lstrip().startswith("//")]
    assert not [ln for ln in code if "8.33" in ln]


def test_active_engine_version_matches_the_faq():
    """Testteki version string'i SSS'teki baglayici referansla ayni olmali."""
    text = (FAQ / "tr" / "skor-hesabi.md").read_text(encoding="utf-8")
    assert ACTIVE_ENGINE in text


# ── 2) Tek yardimci fonksiyon; her gosterim ondan gecer ───────────────────
def test_display_score_helper_is_defined_once():
    body = app_text()
    assert body.count("const displayScore = ") == 1
    # Sayi olmayan deger (null) oldugu gibi gecer -> num1() "—" yolunu korur.
    assert 'const displayScore = (s) => (typeof s === "number" ? s - SCORE_OFFSET : s);' in body


def test_negative_zero_is_never_printed():
    """API score'u 2 ondaliga yuvarlar (notr = 8.33), ofset tam notrdur.

    Fark −0.0033 cikar ve toFixed(1) bunu "-0.0" yazardi — macsiz oyuncunun
    ve oynanmamis her rolun ekraninda eksi isaretli sifir gorunurdu. Tek
    formatlayici (fix1) bu artigi eler; fmtRating ve num1 ondan gecer.
    """
    body = app_text()
    assert 'const fix1 = (x) => { const s = x.toFixed(1); return s === "-0.0" ? "0.0" : s; };' in body
    assert "const fmtRating = (x) => fix1(x);" in body
    assert 'const num1 = (x) => (typeof x === "number" ? fix1(x) : "—");' in body


DISPLAY_SITES = [
    # (aciklama, app.js'te birebir gecmesi gereken parca)
    ("rol serit kutusu (oyuncu karti)", '<span class="rc-score">${fmtRating(displayScore(v.score))}</span>'),
    ("rol serit title", "score: fmtRating(displayScore(v.score))"),
    ("dengeleme karti puani", '<span class="p-meta">${fmtRating(displayScore(p.rating.score))}'),
    ("siralama listesi", '<td class="num strong">${fmtRating(displayScore(p.rating.score))}'),
    ("profil rol yaylari (sayi)", '${off ? "—" : fmtRating(displayScore(v.score))}'),
    ("profil buyuk puan", '<b>${fmtRating(displayScore(rp.rating.score))}</b>'),
    ("rating grafigi nokta aria", "score: fmtRating(displayScore(Number(q.p.score_after)))"),
    ("rating grafigi y ekseni", '<span class="ph-ytick" style="top:${(y / PH.H * 100).toFixed(2)}%">${fmtRating(displayScore(v))}</span>'),
    ("rating grafigi kunye", '<span class="ph-pop-score">${fmtRating(displayScore(Number(p.score_after)))}'),
    ("enler rol karti", '<span class="hl-value">${num1(displayScore(d.score))}</span>'),
    ("enler haftanin oyuncusu", '<span class="hl-value">${num1(displayScore(h.best_player.score))}'),
    ("harita baloncugu", "const score = fmtRating(displayScore(top.r.score));"),
    ("rol siralamasi pop-up'i", '<span class="rr-score">${fmtRating(displayScore(r.score))}</span>'),
]


@pytest.mark.parametrize("label,needle", DISPLAY_SITES, ids=[x[0] for x in DISPLAY_SITES])
def test_every_score_display_goes_through_the_helper(label, needle):
    assert needle in app_text(), f"{label}: gosterim ofseti uygulanmamis"


def test_no_raw_score_display_is_left_behind():
    """fmtRating/num1'e CIPLAK bir `.score` gecirilmemeli (ordinal haric)."""
    body = app_text()
    leftovers = re.findall(r"(?:fmtRating|num1)\(\s*(?:Number\()?[A-Za-z_.\[\]]*\.score(?:_after|_before)?\b", body)
    assert leftovers == [], f"ofsetsiz score gosterimi kalmis: {leftovers}"


# ── 3) UYGULANMAYAN yerler (bilincli) ─────────────────────────────────────
def test_ordinal_is_not_offset():
    """ordinal farkli bir buyukluktur (mu-3sigma) ve dengeleme ona bakar."""
    assert "fmtRating(r.ordinal)" in app_text()


def test_match_card_delta_is_not_offset():
    """Mac sonrasi skor degisimi bir FARKtir: ofset farkta sadelesir."""
    body = app_text()
    assert "? rc.score_after - rc.score_before" in body
    assert "displayScore(rc.score_after)" not in body
    assert "displayScore(rc.score_before)" not in body


def test_rising_star_delta_is_not_offset():
    """rising_star.delta pencere ici ORDINAL farkidir (api_contract)."""
    body = app_text()
    assert "${fmtDelta2(rs.delta)}" in body
    assert "displayScore(rs.delta)" not in body


def test_synergy_score_is_not_offset():
    """Sinerji skoru rating degil, winrate/perf LIFT'idir (GOREV 22)."""
    body = app_text()
    assert "fmtDelta2(x.score)" in body
    assert "displayScore(x.score)" not in body


def test_role_gauge_fill_ratio_stays_on_raw_scores():
    """Yay dolgusu oyuncunun KENDI rolleri arasindaki orandir.

    Ofsetli degerle oranlansaydi notrun altindaki her rol 0'a kirpilir ve yay
    boslardi — bu bir gosterim degil, gorselin anlamini degistirmek olurdu.
    """
    body = app_text()
    assert "Math.min(1, v.score / top)" in body
    assert "displayScore(v.score) / top" not in body


def test_perf_avg_and_mu_sigma_are_not_offset():
    body = app_text()
    assert "r.perf_avg.toFixed(2)" in body
    assert "displayScore(r.perf_avg)" not in body


# ── 4) Mock HAM veri uretmeye devam eder ──────────────────────────────────
def test_mock_api_stays_raw():
    """mock_api gercek API'yi taklit eder: notr score 8.33 KALIR, ofset yok."""
    body = mock_text()
    assert "SCORE_OFFSET" not in body
    assert "displayScore" not in body
    assert "score: 8.33" in body  # macsiz oyuncu / oynanmamis rol: ham notr


# ── 5) SSS metinleri 0 tabanini anlatir ───────────────────────────────────
# 8.33 metinlerde SIGMA ve HAM ara deger olarak gecmeye devam eder; yasakli
# olan "skor ~8.33'ten baslar" anlatimidir (GOREV 27'den kalan cumleler).
BANNED = {
    "tr": ["~8.33'te", "~8.33'ten başlar", "leaderboard'da nötr görünmesinin"],
    "en": ["at ~8.33", "starts at roughly 8.33", "Everyone starts at ~8.33"],
}


@pytest.mark.parametrize("lang", ["tr", "en"])
def test_faq_no_longer_claims_a_833_baseline(lang):
    for md in sorted((FAQ / lang).glob("*.md")):
        text = md.read_text(encoding="utf-8")
        for phrase in BANNED[lang]:
            assert phrase not in text, f"{lang}/{md.name}: eski taban anlatimi -> {phrase}"


@pytest.mark.parametrize("lang", ["tr", "en"])
def test_faq_new_player_article_says_zero(lang):
    text = (FAQ / lang / "yeni-oyuncu-sifir.md").read_text(encoding="utf-8")
    head = text.splitlines()[0]
    assert "8.33" not in head and "0" in head, f"baslik 0 tabanini soylemeli: {head}"
    assert "0.0" in text, "macsiz oyuncunun ekranda 0.0 gorundugu yazmali"


def test_faq_index_new_player_entry_uses_zero_baseline():
    import json

    data = json.loads((FAQ / "index.json").read_text(encoding="utf-8"))
    item = next(x for x in data["items"] if x["slug"] == "yeni-oyuncu-sifir")
    for lang in ("tr", "en"):
        assert "8.33" not in item["title"][lang]
        assert "8.33" not in item["summary"][lang]
        assert "0" in item["title"][lang] or "0" in item["summary"][lang]


@pytest.mark.parametrize("lang", ["tr", "en"])
def test_faq_mentions_that_negative_scores_are_normal(lang):
    """Grubun bir kismi 0'in altinda olacak — SSS bunu soylemeli."""
    for name in ("skor-hesabi.md", "yeni-oyuncu-sifir.md"):
        text = (FAQ / lang / name).read_text(encoding="utf-8")
        assert "-3.8" in text or "−3.8" in text, f"{lang}/{name}: eksi skor notu yok"


def test_faq_files_are_paired_in_both_languages():
    tr = {p.name for p in (FAQ / "tr").glob("*.md")}
    en = {p.name for p in (FAQ / "en").glob("*.md")}
    assert tr == en, f"tr/en SSS dosyalari eslesmiyor: {tr ^ en}"
