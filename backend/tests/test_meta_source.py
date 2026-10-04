"""meta_source: kaynak -> belge donusumu ve fark (GOREV 34; api_contract §8).

deploy/fetch_meta.py'nin eski `_selftest`'indeki HER kontrol burada pytest
testidir (davranis birebir korunarak backend/app/services/meta_source.py'ye
tasindi). Ag YOK: tum testler sentetik OP.GG/Data Dragon kayitlariyla calisir.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from app.services.meta_source import (
    LANES,
    TIERS,
    _rate,
    build_counters,
    build_counters_document,
    build_document,
    build_tiers,
    champion_names_by_id,
    count_counters,
    count_tiers_entries,
    diff_counters,
    diff_tiers,
    format_counters_diff,
    format_diff,
    lane_key,
    load_valid_names,
    tier_letter,
)

REPO = Path(__file__).resolve().parents[2]


# ── Yardimcilar (selftest'teki sentetik payload birebir) ─────────────────


def pos(name, tier, rank, win_rate=0.5, pick_rate=0.05, counters=None):
    return {
        "name": name,
        "stats": {
            "win_rate": win_rate,
            "pick_rate": pick_rate,
            "tier_data": {"tier": tier, "rank": rank},
        },
        "counters": counters or [],
    }


@pytest.fixture
def payload():
    return {
        "meta": {"version": "16.16"},
        "data": [
            {"id": 103, "positions": [
                pos("MID", 1, 3, win_rate=0.521, pick_rate=0.081,
                    counters=[{"champion_id": 62, "play": 100, "win": 40}]),
                pos("SUPPORT", 4, 20),
            ]},
            {"id": 62, "positions": [pos("MID", 1, 1, win_rate=0.55, pick_rate=0.02),
                                     pos("TOP", 0, 1)]},
            {"id": 999, "positions": [pos("TOP", 1, 2)]},          # DD'de yok
            {"id": 777, "positions": [pos("TOP", 1, 2)]},          # champions.json'da yok
            {"id": 555, "is_rip": True, "positions": [pos("TOP", 1, 1)]},  # kaldirilmis
            {"id": 111, "positions": [{"name": "MID", "stats": {}, "counters": []}]},  # tier_data yok
        ],
    }


ID_TO_NAME = {103: "Ahri", 62: "Wukong", 777: "Sicak", 555: "Rip", 111: "Bos"}
VALID = {"Ahri", "Wukong", "Rip", "Bos"}


# ── tier_letter / lane_key ────────────────────────────────────────────────


@pytest.mark.parametrize("raw,expected", [
    (0, "S"), (1, "S"), (2, "A"), (3, "B"),
    (4, None), (5, None), (None, None), ("1", None), (True, None),
])
def test_tier_letter(raw, expected):
    assert tier_letter(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("MID", "middle"), ("adc", "bottom"), ("SUPPORT", "utility"),
    ("BOTTOM", None), ("", None), (None, None),
])
def test_lane_key(raw, expected):
    assert lane_key(raw) == expected


# ── champion_names_by_id / _rate ──────────────────────────────────────────


def test_champion_names_by_id_skips_entries_without_key():
    dd = {
        "Ahri": {"key": "103", "name": "Ahri"},
        "MonkeyKing": {"key": "62", "name": "Wukong"},
        "Bogus": {"name": "NoKey"},
    }
    assert champion_names_by_id(dd) == {103: "Ahri", 62: "Wukong"}


def test_rate_rounds_and_defends():
    assert _rate({"win_rate": 0.512345}, "win_rate") == 0.5123
    assert _rate({}, "win_rate") == 0.0
    assert _rate({"win_rate": "x"}, "win_rate") == 0.0
    assert _rate({"win_rate": True}, "win_rate") == 0.0


# ── build_tiers ───────────────────────────────────────────────────────────


def test_build_tiers_order_shape_and_filters(payload):
    tiers, warns = build_tiers(payload, ID_TO_NAME, VALID)
    # rank sirasi (kucuk = iyi)
    assert [e["name"] for e in tiers["middle"]["S"]] == ["Wukong", "Ahri"]
    assert tiers["middle"]["S"][1] == {"name": "Ahri", "win_rate": 0.521, "pick_rate": 0.081}
    # OP (0) -> S
    assert [e["name"] for e in tiers["top"]["S"]] == ["Wukong"]
    # C tier alinmadi
    assert tiers["utility"]["S"] == [] and tiers["utility"]["A"] == []
    # bos lane tam anahtarli, 5 lane her zaman mevcut
    assert tiers["bottom"] == {"S": [], "A": [], "B": []}
    assert set(tiers) == set(LANES)
    # tier_data'siz kayit atlandi
    assert tiers["middle"]["B"] == []
    # uyarilar: bilinmeyen id + champions.json disi
    assert len(warns) == 2
    assert any("999" in w for w in warns)
    assert any("Sicak" in w for w in warns)


def test_build_tiers_max_per_tier(payload):
    capped, _ = build_tiers(payload, ID_TO_NAME, VALID, max_per_tier=1)
    assert [e["name"] for e in capped["middle"]["S"]] == ["Wukong"]


def test_build_tiers_warnings_are_deduplicated():
    payload = {"data": [
        {"id": 999, "positions": [pos("TOP", 1, 1)]},
        {"id": 999, "positions": [pos("MID", 1, 1)]},
    ]}
    _, warns = build_tiers(payload, {}, set())
    assert len(warns) == 1


# ── build_document / build_counters_document ──────────────────────────────


def test_build_document_schema_and_patch(payload):
    doc, _ = build_document(payload, ID_TO_NAME, VALID, source="test", updated="2026-01-01")
    assert doc["patch"] == "16.16"
    assert set(doc) == {"patch", "updated", "source", "tiers"}
    assert doc["source"] == "test" and doc["updated"] == "2026-01-01"


def test_build_document_patch_fallback_when_meta_missing():
    doc2, _ = build_document({"data": []}, {}, set(), source="t", updated="d",
                             patch_fallback="9.9")
    assert doc2["patch"] == "9.9"


def test_build_counters_document_schema(payload):
    cdoc, _ = build_counters_document(payload, ID_TO_NAME, VALID, source="test",
                                      updated="2026-01-01")
    assert set(cdoc) == {"patch", "updated", "source", "counters"}
    assert cdoc["patch"] == "16.16"


# ── build_counters ────────────────────────────────────────────────────────


def test_build_counters_record_and_warnings(payload):
    counters, cwarns = build_counters(payload, ID_TO_NAME, VALID)
    # win_rate_against = (play - win) / play
    assert counters["middle"]["Ahri"] == [
        {"champion": "Wukong", "games": 100, "win_rate_against": 0.6}
    ]
    # counter listesi bos olan anahtar girmez
    assert "Wukong" not in counters["middle"]
    assert set(counters) == set(LANES)
    # anchor 999/777 tiers'daki gibi burada da anahtar-sampiyon uyarisi uretir
    assert len(cwarns) == 2
    assert any("999" in w for w in cwarns)
    assert any("Sicak" in w for w in cwarns)


def test_build_counters_invalid_opponents_skipped_with_warnings():
    payload_bad_opp = {
        "data": [
            {"id": 103, "positions": [pos("MID", 1, 1, counters=[
                {"champion_id": 9999, "play": 10, "win": 5},   # DD'de yok
                {"champion_id": 777, "play": 10, "win": 5},    # champions.json'da yok
                {"champion_id": 62, "play": 0, "win": 0},      # play=0 -> atlanir
            ])]},
        ],
    }
    counters2, cwarns2 = build_counters(payload_bad_opp, ID_TO_NAME, VALID)
    assert counters2["middle"] == {}
    assert len(cwarns2) == 2


def test_build_counters_rip_anchor_skipped():
    payload_rip = {"data": [{"id": 555, "is_rip": True,
                             "positions": [pos("MID", 1, 1)]}]}
    counters3, _ = build_counters(payload_rip, ID_TO_NAME, VALID)
    assert all(not v for v in counters3.values())


def test_build_counters_does_not_require_sab_tier():
    """S/A/B sarti ARANMAZ: C tier'daki anahtar sampiyon da counter uretir."""
    payload_c = {"data": [{"id": 103, "positions": [
        pos("MID", 4, 30, counters=[{"champion_id": 62, "play": 10, "win": 3}])
    ]}]}
    tiers, _ = build_tiers(payload_c, ID_TO_NAME, VALID)
    counters, _ = build_counters(payload_c, ID_TO_NAME, VALID)
    assert tiers["middle"] == {"S": [], "A": [], "B": []}
    assert counters["middle"]["Ahri"][0]["win_rate_against"] == 0.7


# ── diff_tiers / format_diff ──────────────────────────────────────────────


def _empty_lanes():
    return {lane: {"S": [], "A": [], "B": []} for lane in LANES}


@pytest.fixture
def tiers_old_new():
    old = _empty_lanes()
    old["top"] = {"S": ["A"], "A": ["B", "C"], "B": []}  # eski duz-string bicimi
    new = _empty_lanes()
    new["top"] = {"S": [{"name": "A", "win_rate": 0.5, "pick_rate": 0.1},
                        {"name": "B", "win_rate": 0.5, "pick_rate": 0.1}],
                  "A": [], "B": [{"name": "D", "win_rate": 0.5, "pick_rate": 0.1}]}
    return old, new


def test_diff_tiers_added_removed_moved(tiers_old_new):
    old, new = tiers_old_new
    d = diff_tiers(old, new)
    assert d["top"]["added"] == [("D", "B")]
    assert d["top"]["removed"] == [("C", "A")]
    assert d["top"]["moved"] == [("B", "A", "S")]
    assert d["jungle"] == {"added": [], "removed": [], "moved": []}


def test_diff_tiers_tolerates_missing_old(tiers_old_new):
    _, new = tiers_old_new
    d2 = diff_tiers({}, new)
    assert len(d2["top"]["added"]) == 3


def test_format_diff_summary_marks_and_ascii(tiers_old_new):
    old, new = tiers_old_new
    d = diff_tiers(old, new)
    txt = format_diff(d, {"patch": "16.15"}, {"patch": "16.16", "tiers": new})
    assert "1 eklendi, 1 cikti, 1 tier degistirdi" in txt
    assert "* patch" in txt
    assert txt.isascii()


# ── diff_counters / format_counters_diff ──────────────────────────────────


@pytest.fixture
def counters_old_new():
    old_c = {"top": {"Ahri": [{"champion": "Wukong", "games": 10, "win_rate_against": 0.4}]},
             "jungle": {}, "middle": {}, "bottom": {}, "utility": {}}
    new_c = {"top": {"Ahri": [{"champion": "Wukong", "games": 10, "win_rate_against": 0.4},
                              {"champion": "Rip", "games": 5, "win_rate_against": 0.6}],
                     "Bos": [{"champion": "Rip", "games": 5, "win_rate_against": 0.5}]},
             "jungle": {}, "middle": {}, "bottom": {}, "utility": {}}
    return old_c, new_c


def test_diff_counters(counters_old_new):
    old_c, new_c = counters_old_new
    dc = diff_counters(old_c, new_c)
    assert dc["top"]["added"] == ["Bos"]
    assert dc["top"]["removed"] == []
    assert dc["top"]["changed"] == ["Ahri"]


def test_format_counters_diff_summary_and_ascii(counters_old_new):
    old_c, new_c = counters_old_new
    dc = diff_counters(old_c, new_c)
    ctxt = format_counters_diff(dc, {"patch": "16.15"}, {"patch": "16.16", "counters": new_c})
    assert "1 eklendi, 0 cikti, 1 karsi-listesi degisti" in ctxt
    assert ctxt.isascii()


# ── Sayimlar + dogrulama kumesi (store/CLI ortak) ─────────────────────────


def test_counts(payload, counters_old_new):
    tiers, _ = build_tiers(payload, ID_TO_NAME, VALID)
    assert count_tiers_entries(tiers) == 3  # middle S: Wukong, Ahri; top S: Wukong
    _, new_c = counters_old_new
    assert count_counters(new_c) == (2, 3)
    assert count_tiers_entries({}) == 0 and count_counters(None) == (0, 0)


def test_load_valid_names_prefers_champions_json(tmp_path):
    path = tmp_path / "champions.json"
    path.write_text('{"Ahri": {"icon": "x"}, "Wukong": {"icon": "y"}}', encoding="utf-8")
    names, src = load_valid_names(path, {1: "Zed"})
    assert names == {"Ahri", "Wukong"}
    assert src.startswith("champions.json (2 ad)")


def test_load_valid_names_falls_back_to_ddragon_names(tmp_path):
    names, src = load_valid_names(tmp_path / "yok.json", {1: "Zed", 2: "Ahri"})
    assert names == {"Zed", "Ahri"}
    assert "UYARI" in src


# ── Tek kaynak ilkesi: CLI donusum kodunu KOPYALAMAZ ──────────────────────


def _load_cli():
    script = REPO / "deploy" / "fetch_meta.py"
    spec = importlib.util.spec_from_file_location("fetch_meta_under_test", script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_cli_reuses_meta_source_functions():
    """deploy/fetch_meta.py donusum/fark fonksiyonlarini meta_source'tan alir."""
    cli = _load_cli()
    from app.services import meta_source

    for name in ("build_document", "build_counters_document", "diff_tiers",
                 "diff_counters", "format_diff", "format_counters_diff",
                 "champion_names_by_id", "load_valid_names", "fetch_json"):
        assert getattr(cli, name) is getattr(meta_source, name), name
    assert not hasattr(cli, "TIER_MAP") or cli.TIER_MAP is meta_source.TIER_MAP


def test_cli_selftest_green():
    cli = _load_cli()
    assert cli.main(["--selftest"]) == 0


def test_meta_source_is_stdlib_only():
    """CLI backend bagimliligi olmadan calisir: modul fastapi/sqlite3 import etmez."""
    src = (REPO / "backend" / "app" / "services" / "meta_source.py").read_text(encoding="utf-8")
    code = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    assert not any(ln.startswith(("import fastapi", "from fastapi", "import sqlite3",
                                  "from .", "from app")) for ln in code)
