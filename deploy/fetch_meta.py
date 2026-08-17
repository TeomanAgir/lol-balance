"""META tier + karsilastirma verisini topluluk kaynagindan ceker.

api_contract §8 "Meta tier verisi" + "Secim danismani verisi (GOREV 21)": onayli
veri repo'daki `webui/assets/meta/tiers.json` VE `webui/assets/meta/counters.json`
dosyalaridir. Akis YARI OTOMATIKtir ve bu betik onun ilk adimidir, AYNI TEK OP.GG
isteginden iki dosyayi birden uretir:

    kaynaktan cek (TEK istek) -> bizim iki semaya cevir -> adlari champions.json'a
    karsi dogrula -> mevcut dosyalarla FARKI bas -> (yalniz --write ile) yaz

VARSAYILAN OLARAK HICBIR SEY YAZMAZ. Commit/PR karari insanindir (Teoman).
Otomatik cron YOK; patch basina elle kosulur.

Kullanim (repo kokunden):

    backend\\.venv\\Scripts\\python.exe deploy\\fetch_meta.py            # sadece fark
    backend\\.venv\\Scripts\\python.exe deploy\\fetch_meta.py --write    # dosyaya yaz
    backend\\.venv\\Scripts\\python.exe deploy\\fetch_meta.py --selftest # agsiz test

Kaynak: OP.GG acik sampiyon tier listesi ucu (anonim GET, JSON, tek istek,
rol bazli tier + win_rate + pick_rate + karsilasma (counters) verir). Sampiyon
adi eslemesi icin Data Dragon `champion.json` (numeric key -> gorunen ad) cekilir;
`champions.json`a alan EKLENMEZ (o fetch_ddragon.py'nin isi).

Yalniz stdlib kullanir (fetch_ddragon.py deseniyle ayni ilke).
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# --- Kaynak -----------------------------------------------------------------

OPGG_URL = "https://lol-api-champion.op.gg/api/{region}/champions/ranked?tier={tier}"
DDRAGON_VERSIONS = "https://ddragon.leagueoflegends.com/api/versions.json"
DDRAGON_CHAMPION = "https://ddragon.leagueoflegends.com/cdn/{ver}/data/en_US/champion.json"

# CommunityDragon/OP.GG varsayilan Python UA'sini reddedebilir; kimligimizi veriyoruz.
_UA = {
    "User-Agent": "lol-balance-fetch-meta/1.0 (+https://lol.teomanagir.com)",
    "Accept": "application/json",
}

# OP.GG lane adi -> bizim sema anahtari (api_contract §8).
LANE_MAP = {
    "TOP": "top",
    "JUNGLE": "jungle",
    "MID": "middle",
    "ADC": "bottom",
    "SUPPORT": "utility",
}
LANES = ("top", "jungle", "middle", "bottom", "utility")

# OP.GG tier_data.tier -> bizim harf. 0 = "OP" rozeti (tier 1'in ustu), S'ye
# katlanir (ince siniflar S'ye katlanir kurali). 4/5 = C/D: sayfa yalniz S/A/B
# gosterdigi icin ALINMAZ. Bilinmeyen/None de alinmaz.
TIER_MAP = {0: "S", 1: "S", 2: "A", 3: "B"}
TIERS = ("S", "A", "B")


# --- Ag ---------------------------------------------------------------------


def fetch_json(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# --- Yollar -----------------------------------------------------------------


def webui_root() -> Path:
    """fetch_ddragon.py ile ayni cozum: once CWD/webui, yoksa repo kokundeki."""
    cwd_webui = Path.cwd() / "webui"
    if cwd_webui.is_dir():
        return cwd_webui
    return Path(__file__).resolve().parent.parent / "webui"


# --- Donusum (agsiz, test edilebilir) ----------------------------------------


def tier_letter(raw) -> str | None:
    """Kaynak tier sayisini S/A/B'ye cevirir; kapsam disi ise None."""
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return TIER_MAP.get(raw)


def lane_key(raw: str) -> str | None:
    """OP.GG lane adini bizim sema anahtarina cevirir; taninmiyorsa None."""
    return LANE_MAP.get((raw or "").upper())


def champion_names_by_id(dd_champion_data: dict) -> dict[int, str]:
    """Data Dragon champion.json 'data' blogundan {numeric_key: gorunen_ad}."""
    out: dict[int, str] = {}
    for entry in dd_champion_data.values():
        try:
            key = int(entry["key"])
        except (KeyError, TypeError, ValueError):
            continue
        name = entry.get("name")
        if name:
            out[key] = name
    return out


def _rate(stats: dict, field: str) -> float:
    """0-1 orani 4 ondaliga yuvarlar; sayi degilse 0.0 (savunmaci varsayilan)."""
    val = stats.get(field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return 0.0
    return round(float(val), 4)


def build_tiers(payload: dict, id_to_name: dict[int, str], valid_names: set[str],
                max_per_tier: int | None = None) -> tuple[dict, list[str]]:
    """OP.GG yanitini bizim `tiers` blogumuza cevirir.

    Her kayit `{name, win_rate, pick_rate}` (api_contract §8, GOREV 21 sema
    genislemesi). Donen: (tiers, uyarilar). Uyari = eslenemeyen sampiyon
    (dosyaya GIRMEZ). Tier ici siralama kaynagin kendi `rank`i (kucuk = iyi),
    esitlikte ad alfabetik -> cikti deterministiktir.
    """
    warnings: list[str] = []
    seen_unknown: set[str] = set()
    # lane -> tier -> [(rank, name, win_rate, pick_rate)]
    buckets: dict[str, dict[str, list[tuple[int, str, float, float]]]] = {
        lane: {t: [] for t in TIERS} for lane in LANES
    }

    for champ in payload.get("data") or []:
        if champ.get("is_rip"):
            continue  # oyundan kaldirilmis sampiyon
        cid = champ.get("id")
        name = id_to_name.get(cid)
        if name is None:
            note = f"bilinmeyen sampiyon id={cid} (Data Dragon'da yok)"
            if note not in seen_unknown:
                seen_unknown.add(note)
                warnings.append(note)
            continue
        if name not in valid_names:
            note = f"'{name}' champions.json'da yok (id={cid})"
            if note not in seen_unknown:
                seen_unknown.add(note)
                warnings.append(note)
            continue

        for pos in champ.get("positions") or []:
            lane = lane_key(pos.get("name", ""))
            if lane is None:
                continue
            stats = pos.get("stats") or {}
            tier_data = stats.get("tier_data") or {}
            letter = tier_letter(tier_data.get("tier"))
            if letter is None:
                continue  # C/D veya veri yok -> alinmaz
            rank = tier_data.get("rank")
            rank = rank if isinstance(rank, int) else 9999
            win_rate = _rate(stats, "win_rate")
            pick_rate = _rate(stats, "pick_rate")
            buckets[lane][letter].append((rank, name, win_rate, pick_rate))

    tiers: dict[str, dict[str, list[dict]]] = {}
    for lane in LANES:
        tiers[lane] = {}
        for t in TIERS:
            ordered = sorted(buckets[lane][t], key=lambda x: (x[0], x[1]))
            if max_per_tier is not None:
                ordered = ordered[:max_per_tier]
            tiers[lane][t] = [
                {"name": n, "win_rate": wr, "pick_rate": pr} for _, n, wr, pr in ordered
            ]
    return tiers, warnings


def build_counters(payload: dict, id_to_name: dict[int, str],
                    valid_names: set[str]) -> tuple[dict, list[str]]:
    """OP.GG `positions[].counters`'i bizim `counters` blogumuza cevirir (GOREV 21).

    Sema: `{lane: {"<anahtar sampiyon adi>": [{champion, games, win_rate_against}]}}`.
    Kaynak kaydi anahtar sampiyonun (X) karsi sampiyona (Y) karsi KENDI mac/galibiyet
    sayisidir (`play`/`win` = X'in Y'ye karsi oynadigi/kazandigi mac); bizim
    `win_rate_against` alani Y'nin X'e karsi winrate'idir (yuksek = Y iyi counter),
    yani `(play - win) / play`. S/A/B tier sartý ARANMAZ (secim danismani her
    sampiyon icin calismali); yalniz is_rip ve ad dogrulamasi elenir.
    """
    warnings: list[str] = []
    seen_unknown: set[str] = set()

    def resolve(cid, ctx: str) -> str | None:
        name = id_to_name.get(cid)
        if name is None:
            note = f"bilinmeyen sampiyon id={cid} ({ctx}, Data Dragon'da yok)"
            if note not in seen_unknown:
                seen_unknown.add(note)
                warnings.append(note)
            return None
        if name not in valid_names:
            note = f"'{name}' champions.json'da yok ({ctx}, id={cid})"
            if note not in seen_unknown:
                seen_unknown.add(note)
                warnings.append(note)
            return None
        return name

    counters: dict[str, dict[str, list[dict]]] = {lane: {} for lane in LANES}

    for champ in payload.get("data") or []:
        if champ.get("is_rip"):
            continue
        cid = champ.get("id")
        anchor_name = resolve(cid, "anahtar sampiyon")
        if anchor_name is None:
            continue

        for pos in champ.get("positions") or []:
            lane = lane_key(pos.get("name", ""))
            if lane is None:
                continue
            entries: list[dict] = []
            for c in pos.get("counters") or []:
                opp_name = resolve(c.get("champion_id"), f"{anchor_name}/{lane} karsi sampiyon")
                if opp_name is None:
                    continue
                play = c.get("play")
                win = c.get("win")
                if not isinstance(play, int) or play <= 0 or not isinstance(win, int):
                    continue
                win_rate_against = round((play - win) / play, 4)
                entries.append({
                    "champion": opp_name,
                    "games": play,
                    "win_rate_against": win_rate_against,
                })
            if entries:
                counters[lane][anchor_name] = entries

    return counters, warnings


def build_document(payload: dict, id_to_name: dict[int, str], valid_names: set[str],
                   source: str, updated: str, patch_fallback: str = "",
                   max_per_tier: int | None = None) -> tuple[dict, list[str]]:
    """Tam tiers.json belgesini uretir (api_contract §8 semasi)."""
    tiers, warnings = build_tiers(payload, id_to_name, valid_names, max_per_tier)
    meta = payload.get("meta") or {}
    patch = str(meta.get("version") or patch_fallback or "")
    return (
        {"patch": patch, "updated": updated, "source": source, "tiers": tiers},
        warnings,
    )


def build_counters_document(payload: dict, id_to_name: dict[int, str], valid_names: set[str],
                            source: str, updated: str,
                            patch_fallback: str = "") -> tuple[dict, list[str]]:
    """Tam counters.json belgesini uretir (api_contract §8, GOREV 21 semasi)."""
    counters, warnings = build_counters(payload, id_to_name, valid_names)
    meta = payload.get("meta") or {}
    patch = str(meta.get("version") or patch_fallback or "")
    return (
        {"patch": patch, "updated": updated, "source": source, "counters": counters},
        warnings,
    )


# --- Fark (agsiz, test edilebilir) -------------------------------------------


def _entry_name(item) -> str | None:
    """Bir tier girdisinin adini dondurur; eski duz-string bicimi de kabul edilir
    (web UI geriye uyumu icin dosyada bulunabilir, fark burada da tolere eder)."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return item.get("name")
    return None


def _placement(lane_tiers: dict) -> dict[str, str]:
    """{sampiyon: tier} — ayni sampiyon bir lane'de tek tierdedir."""
    out: dict[str, str] = {}
    for t in TIERS:
        for item in (lane_tiers or {}).get(t) or []:
            name = _entry_name(item)
            if name:
                out.setdefault(name, t)
    return out


def diff_tiers(old: dict, new: dict) -> dict:
    """Lane basina eklenen / cikan / tier degistiren sampiyonlar."""
    result: dict[str, dict[str, list]] = {}
    for lane in LANES:
        o = _placement((old or {}).get(lane) or {})
        n = _placement((new or {}).get(lane) or {})
        added = sorted((name, n[name]) for name in n if name not in o)
        removed = sorted((name, o[name]) for name in o if name not in n)
        moved = sorted(
            (name, o[name], n[name]) for name in n if name in o and o[name] != n[name]
        )
        result[lane] = {"added": added, "removed": removed, "moved": moved}
    return result


def format_diff(diff: dict, old_doc: dict, new_doc: dict) -> str:
    """Insan-okur fark tablosu (ASCII; Windows konsolu icin)."""
    lines: list[str] = []
    lines.append("=" * 64)
    lines.append("FARK: tiers.json  (mevcut -> yeni)")
    lines.append("=" * 64)
    for field in ("patch", "updated", "source"):
        o = (old_doc or {}).get(field, "-")
        n = (new_doc or {}).get(field, "-")
        mark = "  " if o == n else "* "
        lines.append(f"{mark}{field:8s}: {o}  ->  {n}")
    lines.append("")

    tot_a = tot_r = tot_m = 0
    for lane in LANES:
        d = diff[lane]
        tot_a += len(d["added"])
        tot_r += len(d["removed"])
        tot_m += len(d["moved"])
        counts = {t: len((new_doc["tiers"][lane]).get(t) or []) for t in TIERS}
        head = f"[{lane}]  S={counts['S']} A={counts['A']} B={counts['B']}"
        if not (d["added"] or d["removed"] or d["moved"]):
            lines.append(f"{head}   (degisiklik yok)")
            continue
        lines.append(head)
        for name, t in d["added"]:
            lines.append(f"   + {t}  {name}")
        for name, t in d["removed"]:
            lines.append(f"   - {t}  {name}")
        for name, o, n in d["moved"]:
            lines.append(f"   ~ {o}->{n}  {name}")
    lines.append("")
    lines.append(f"Ozet: {tot_a} eklendi, {tot_r} cikti, {tot_m} tier degistirdi.")
    return "\n".join(lines)


def _counter_names(entries) -> set[str]:
    return {e.get("champion") for e in (entries or []) if isinstance(e, dict) and e.get("champion")}


def diff_counters(old: dict, new: dict) -> dict:
    """Lane basina eklenen / cikan anahtar sampiyon + karsi-liste degisen sampiyonlar."""
    result: dict[str, dict[str, list]] = {}
    for lane in LANES:
        o = (old or {}).get(lane) or {}
        n = (new or {}).get(lane) or {}
        added = sorted(name for name in n if name not in o)
        removed = sorted(name for name in o if name not in n)
        changed = sorted(
            name for name in n
            if name in o and _counter_names(n[name]) != _counter_names(o[name])
        )
        result[lane] = {"added": added, "removed": removed, "changed": changed}
    return result


def format_counters_diff(diff: dict, old_doc: dict, new_doc: dict) -> str:
    """Insan-okur fark tablosu (ASCII; Windows konsolu icin)."""
    lines: list[str] = []
    lines.append("=" * 64)
    lines.append("FARK: counters.json  (mevcut -> yeni)")
    lines.append("=" * 64)
    for field in ("patch", "updated", "source"):
        o = (old_doc or {}).get(field, "-")
        n = (new_doc or {}).get(field, "-")
        mark = "  " if o == n else "* "
        lines.append(f"{mark}{field:8s}: {o}  ->  {n}")
    lines.append("")

    tot_a = tot_r = tot_c = 0
    for lane in LANES:
        d = diff[lane]
        tot_a += len(d["added"])
        tot_r += len(d["removed"])
        tot_c += len(d["changed"])
        n_anchors = len((new_doc.get("counters") or {}).get(lane) or {})
        head = f"[{lane}]  anahtar sampiyon={n_anchors}"
        if not (d["added"] or d["removed"] or d["changed"]):
            lines.append(f"{head}   (degisiklik yok)")
            continue
        lines.append(head)
        for name in d["added"]:
            lines.append(f"   + {name}")
        for name in d["removed"]:
            lines.append(f"   - {name}")
        for name in d["changed"]:
            lines.append(f"   ~ {name}")
    lines.append("")
    lines.append(f"Ozet: {tot_a} eklendi, {tot_r} cikti, {tot_c} karsi-listesi degisti.")
    return "\n".join(lines)


# --- Selftest (ag YOK) -------------------------------------------------------


def _selftest() -> int:
    fails: list[str] = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    # tier_letter
    check(tier_letter(0) == "S", "tier 0 (OP) -> S")
    check(tier_letter(1) == "S", "tier 1 -> S")
    check(tier_letter(2) == "A", "tier 2 -> A")
    check(tier_letter(3) == "B", "tier 3 -> B")
    check(tier_letter(4) is None, "tier 4 (C) alinmaz")
    check(tier_letter(5) is None, "tier 5 (D) alinmaz")
    check(tier_letter(None) is None, "tier None alinmaz")
    check(tier_letter("1") is None, "tier string alinmaz")
    check(tier_letter(True) is None, "bool tier alinmaz")

    # lane_key
    check(lane_key("MID") == "middle", "MID -> middle")
    check(lane_key("adc") == "bottom", "ADC -> bottom (case-insensitive)")
    check(lane_key("SUPPORT") == "utility", "SUPPORT -> utility")
    check(lane_key("BOTTOM") is None, "bilinmeyen lane -> None")

    # champion_names_by_id
    dd = {
        "Ahri": {"key": "103", "name": "Ahri"},
        "MonkeyKing": {"key": "62", "name": "Wukong"},
        "Bogus": {"name": "NoKey"},
    }
    ids = champion_names_by_id(dd)
    check(ids == {103: "Ahri", 62: "Wukong"}, f"id->ad eslemesi: {ids}")

    # _rate
    check(_rate({"win_rate": 0.512345}, "win_rate") == 0.5123, f"_rate yuvarlama: {_rate({'win_rate': 0.512345}, 'win_rate')}")
    check(_rate({}, "win_rate") == 0.0, "_rate eksik alan -> 0.0")
    check(_rate({"win_rate": "x"}, "win_rate") == 0.0, "_rate string -> 0.0")
    check(_rate({"win_rate": True}, "win_rate") == 0.0, "_rate bool -> 0.0")

    # build_tiers
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

    payload = {
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
    id_to_name = {103: "Ahri", 62: "Wukong", 777: "Sicak", 555: "Rip", 111: "Bos"}
    valid = {"Ahri", "Wukong", "Rip", "Bos"}
    tiers, warns = build_tiers(payload, id_to_name, valid)
    check([e["name"] for e in tiers["middle"]["S"]] == ["Wukong", "Ahri"],
          f"rank sirasi: {tiers['middle']['S']}")
    check(tiers["middle"]["S"][1] == {"name": "Ahri", "win_rate": 0.521, "pick_rate": 0.081},
          f"kayit sekli: {tiers['middle']['S'][1]}")
    check([e["name"] for e in tiers["top"]["S"]] == ["Wukong"], f"OP tier -> S: {tiers['top']['S']}")
    check(tiers["utility"]["S"] == [] and tiers["utility"]["A"] == [], "C tier alinmadi")
    check(tiers["bottom"] == {"S": [], "A": [], "B": []}, "bos lane tam anahtarli")
    check(set(tiers) == set(LANES), "5 lane her zaman mevcut")
    check(len(warns) == 2, f"2 uyari beklendi: {warns}")
    check(any("999" in w for w in warns), f"bilinmeyen id uyarisi: {warns}")
    check(any("Sicak" in w for w in warns), f"champions.json disi uyari: {warns}")
    check(tiers["middle"]["B"] == [], "tier_data'siz kayit atlandi")

    # max_per_tier
    capped, _ = build_tiers(payload, id_to_name, valid, max_per_tier=1)
    check([e["name"] for e in capped["middle"]["S"]] == ["Wukong"],
          f"max_per_tier: {capped['middle']['S']}")

    # build_document
    doc, _ = build_document(payload, id_to_name, valid, source="test", updated="2026-01-01")
    check(doc["patch"] == "16.16", "patch meta.version'dan")
    check(set(doc) == {"patch", "updated", "source", "tiers"}, f"sema anahtarlari: {set(doc)}")
    doc2, _ = build_document({"data": []}, {}, set(), source="t", updated="d",
                             patch_fallback="9.9")
    check(doc2["patch"] == "9.9", "meta yoksa patch fallback")

    # build_counters (GOREV 21)
    counters, cwarns = build_counters(payload, id_to_name, valid)
    check(counters["middle"]["Ahri"] == [
        {"champion": "Wukong", "games": 100, "win_rate_against": 0.6}
    ], f"counter kaydi: {counters['middle'].get('Ahri')}")
    check("Wukong" not in counters["middle"], "counter listesi bos olan anahtar girmez")
    check(set(counters) == set(LANES), "5 lane her zaman mevcut (counters)")
    # anchor 999/777 tiers'daki gibi burada da anahtar-sampiyon uyarisi uretir
    check(len(cwarns) == 2, f"2 anahtar-sampiyon uyarisi beklendi: {cwarns}")
    check(any("999" in w for w in cwarns), f"bilinmeyen anahtar id uyarisi: {cwarns}")
    check(any("Sicak" in w for w in cwarns), f"champions.json disi anahtar uyarisi: {cwarns}")

    # counter tarafinda bilinmeyen/gecersiz rakip -> kayit atlanir + uyari
    payload_bad_opp = {
        "data": [
            {"id": 103, "positions": [pos("MID", 1, 1, counters=[
                {"champion_id": 9999, "play": 10, "win": 5},   # DD'de yok
                {"champion_id": 777, "play": 10, "win": 5},    # champions.json'da yok
                {"champion_id": 62, "play": 0, "win": 0},      # play=0 -> atlanir
            ])]},
        ],
    }
    counters2, cwarns2 = build_counters(payload_bad_opp, id_to_name, valid)
    check(counters2["middle"] == {}, f"gecersiz rakiplerle bos anahtar: {counters2['middle']}")
    check(len(cwarns2) == 2, f"2 rakip uyarisi beklendi: {cwarns2}")

    # is_rip anahtar sampiyon -> tamamen atlanir
    payload_rip_anchor = {"data": [{"id": 555, "is_rip": True,
                                     "positions": [pos("MID", 1, 1)]}]}
    counters3, _ = build_counters(payload_rip_anchor, id_to_name, valid)
    check(all(not v for v in counters3.values()), "is_rip anahtar sampiyon uretmez")

    # build_counters_document
    cdoc, _ = build_counters_document(payload, id_to_name, valid, source="test", updated="2026-01-01")
    check(set(cdoc) == {"patch", "updated", "source", "counters"}, f"sema anahtarlari: {set(cdoc)}")
    check(cdoc["patch"] == "16.16", "counters patch meta.version'dan")

    # diff_tiers (yeni dict bicimiyle + eski duz-string bicimiyle)
    old = {"top": {"S": ["A"], "A": ["B", "C"], "B": []},
           "jungle": {"S": [], "A": [], "B": []},
           "middle": {"S": [], "A": [], "B": []},
           "bottom": {"S": [], "A": [], "B": []},
           "utility": {"S": [], "A": [], "B": []}}
    new = {"top": {"S": [{"name": "A", "win_rate": 0.5, "pick_rate": 0.1},
                          {"name": "B", "win_rate": 0.5, "pick_rate": 0.1}],
                   "A": [], "B": [{"name": "D", "win_rate": 0.5, "pick_rate": 0.1}]},
           "jungle": {"S": [], "A": [], "B": []},
           "middle": {"S": [], "A": [], "B": []},
           "bottom": {"S": [], "A": [], "B": []},
           "utility": {"S": [], "A": [], "B": []}}
    d = diff_tiers(old, new)
    check(d["top"]["added"] == [("D", "B")], f"eklenen: {d['top']['added']}")
    check(d["top"]["removed"] == [("C", "A")], f"cikan: {d['top']['removed']}")
    check(d["top"]["moved"] == [("B", "A", "S")], f"tasinan: {d['top']['moved']}")
    check(d["jungle"] == {"added": [], "removed": [], "moved": []}, "bos lane farki")

    # eksik/bozuk mevcut dosyaya karsi fark patlamamali
    d2 = diff_tiers({}, new)
    check(len(d2["top"]["added"]) == 3, f"bos mevcut dosya: {d2['top']['added']}")

    # format_diff calisir ve ozet basar
    txt = format_diff(d, {"patch": "16.15"}, {"patch": "16.16", "tiers": new})
    check("1 eklendi, 1 cikti, 1 tier degistirdi" in txt, "ozet satiri")
    check("* patch" in txt, "degisen alan isaretli")
    check(txt.isascii(), "cikti ASCII (Windows konsolu)")

    # diff_counters + format_counters_diff
    old_c = {"top": {"Ahri": [{"champion": "Wukong", "games": 10, "win_rate_against": 0.4}]},
             "jungle": {}, "middle": {}, "bottom": {}, "utility": {}}
    new_c = {"top": {"Ahri": [{"champion": "Wukong", "games": 10, "win_rate_against": 0.4},
                               {"champion": "Rip", "games": 5, "win_rate_against": 0.6}],
                      "Bos": [{"champion": "Rip", "games": 5, "win_rate_against": 0.5}]},
             "jungle": {}, "middle": {}, "bottom": {}, "utility": {}}
    dc = diff_counters(old_c, new_c)
    check(dc["top"]["added"] == ["Bos"], f"eklenen anahtar: {dc['top']['added']}")
    check(dc["top"]["removed"] == [], f"cikan anahtar: {dc['top']['removed']}")
    check(dc["top"]["changed"] == ["Ahri"], f"degisen karsi-liste: {dc['top']['changed']}")
    ctxt = format_counters_diff(dc, {"patch": "16.15"}, {"patch": "16.16", "counters": new_c})
    check("1 eklendi, 0 cikti, 1 karsi-listesi degisti" in ctxt, f"counters ozet satiri: {ctxt}")
    check(ctxt.isascii(), "counters cikti ASCII (Windows konsolu)")

    if fails:
        print("SELFTEST BASARISIZ:")
        for f in fails:
            print("  - " + f)
        return 1
    print("SELFTEST OK (agsiz).")
    return 0


# --- CLI ----------------------------------------------------------------------


def _load_valid_names(path: Path, id_to_name: dict[int, str]) -> tuple[set[str], str]:
    """Dogrulama kumesi: webui/assets/ddragon/champions.json anahtarlari.

    Dosya yoksa (ddragon varliklari gitignore'lu, build-time indirilir) ayni
    kaynaktan -- Data Dragon -- gelen adlara duseriz ve uyariyla belirtiriz.
    """
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data), f"champions.json ({len(data)} ad)"
    return set(id_to_name.values()), (
        f"Data Dragon champion.json ({len(id_to_name)} ad) -- UYARI: {path} yok, "
        "once deploy/fetch_ddragon.py kosun"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="fetch_meta.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "META tier + karsilastirma verisini topluluk kaynagindan ceker ve\n"
            "webui/assets/meta/{tiers,counters}.json ile FARKINI basar (AYNI tek\n"
            "OP.GG isteginden ikisi de). VARSAYILAN OLARAK YAZMAZ -- yazmak icin\n"
            "--write. Kaynak: OP.GG acik sampiyon tier listesi (anonim GET, JSON).\n"
            "Sema: api_contract.md §8 'Meta tier verisi' + 'Secim danismani verisi'."
        ),
        epilog=(
            "Ornekler:\n"
            "  fetch_meta.py                      # farki goster (yazmaz)\n"
            "  fetch_meta.py --tier emerald_plus  # baska rank dilimi\n"
            "  fetch_meta.py --max-per-tier 8     # tier basina en iyi 8 sampiyon\n"
            "  fetch_meta.py --write              # onaydan sonra iki dosyaya da yaz\n"
            "  fetch_meta.py --selftest           # agsiz ic testler\n\n"
            "Tier eslemesi: kaynak OP(0)/1 -> S, 2 -> A, 3 -> B; 4-5 (C/D) ALINMAZ.\n"
            "Yazdiktan sonra commit/PR insanin isidir (otomatik cron YOK)."
        ),
    )
    p.add_argument("--write", action="store_true",
                   help="farki gosterdikten SONRA tiers.json + counters.json'a yaz "
                        "(varsayilan: yazmaz)")
    p.add_argument("--tier", default="platinum_plus",
                   help="kaynak rank dilimi (platinum_plus, emerald_plus, ... ; "
                        "varsayilan: platinum_plus)")
    p.add_argument("--region", default="global",
                   help="kaynak bolge (global, kr, euw, ... ; varsayilan: global)")
    p.add_argument("--max-per-tier", type=int, default=None, metavar="N",
                   help="tier basina en fazla N sampiyon (kaynak rank sirasina gore); "
                        "varsayilan: sinirsiz")
    p.add_argument("--input", metavar="FILE",
                   help="ag yerine kaydedilmis kaynak JSON dosyasindan oku (hata ayiklama)")
    p.add_argument("--out", metavar="FILE",
                   help="tiers hedef dosyasi (varsayilan: webui/assets/meta/tiers.json)")
    p.add_argument("--counters-out", metavar="FILE",
                   help="counters hedef dosyasi (varsayilan: webui/assets/meta/counters.json)")
    p.add_argument("--dd-version", metavar="VER",
                   help="Data Dragon surumu (varsayilan: ddragon manifest.json, yoksa en yeni)")
    p.add_argument("--selftest", action="store_true",
                   help="ag gerektirmeyen ic testleri kosar ve cikar")
    args = p.parse_args(argv)

    if args.selftest:
        return _selftest()

    webui = webui_root()
    out_path = Path(args.out) if args.out else webui / "assets" / "meta" / "tiers.json"
    counters_out_path = (Path(args.counters_out) if args.counters_out
                         else webui / "assets" / "meta" / "counters.json")
    champions_path = webui / "assets" / "ddragon" / "champions.json"
    manifest_path = webui / "assets" / "ddragon" / "manifest.json"

    # 1) Data Dragon: numeric id -> gorunen ad (champions.json'a alan EKLEMEDEN).
    dd_version = args.dd_version
    if not dd_version and manifest_path.is_file():
        try:
            dd_version = json.loads(manifest_path.read_text(encoding="utf-8")).get("version")
        except (ValueError, OSError):
            dd_version = None
    try:
        if not dd_version:
            dd_version = fetch_json(DDRAGON_VERSIONS)[0]
        dd_data = fetch_json(DDRAGON_CHAMPION.format(ver=dd_version))["data"]
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError) as e:
        print(f"HATA: Data Dragon champion.json alinamadi ({e})", file=sys.stderr)
        return 2
    id_to_name = champion_names_by_id(dd_data)
    print(f"Data Dragon {dd_version}: {len(id_to_name)} sampiyon id eslemesi")

    valid_names, valid_src = _load_valid_names(champions_path, id_to_name)
    print(f"Dogrulama kumesi: {valid_src}")

    # 2) Kaynak (TEK istek; tiers VE counters bundan uretilir)
    if args.input:
        source_url = f"file:{args.input}"
        try:
            payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"HATA: {args.input} okunamadi ({e})", file=sys.stderr)
            return 2
    else:
        source_url = OPGG_URL.format(region=args.region, tier=args.tier)
        try:
            payload = fetch_json(source_url)
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f"HATA: kaynak alinamadi {source_url} ({e})", file=sys.stderr)
            return 2
    n_src = len(payload.get("data") or [])
    print(f"Kaynak: {source_url}  ({n_src} sampiyon kaydi)")
    if not n_src:
        print("HATA: kaynak bos veri dondu, islem durduruldu.", file=sys.stderr)
        return 2

    # 3) Semaya cevir + ad dogrulama (iki dosya, ayni payload)
    source_label = f"op.gg ({args.region}, {args.tier})"
    # `updated` insan-okur "ne zaman cekildi" alanidir; kosanin yerel tarihi
    # (UTC, TR saatiyle gece kosuldugunda bir gun geride gorunuyordu).
    updated = datetime.now().strftime("%Y-%m-%d")
    patch_fallback = ".".join(str(dd_version).split(".")[:2])

    new_doc, warnings = build_document(
        payload, id_to_name, valid_names, source=source_label, updated=updated,
        patch_fallback=patch_fallback, max_per_tier=args.max_per_tier,
    )
    matched = len({n for lane in LANES for t in TIERS for e in new_doc["tiers"][lane][t]
                   for n in (e["name"],)})
    print(f"Eslesen sampiyon (tiers): {matched} (S/A/B'de yer alan); uyari: {len(warnings)}")
    for w in warnings:
        print(f"  UYARI (tiers.json'a girmedi): {w}")

    counters_doc, counters_warnings = build_counters_document(
        payload, id_to_name, valid_names, source=source_label, updated=updated,
        patch_fallback=patch_fallback,
    )
    n_anchors = sum(len(counters_doc["counters"][lane]) for lane in LANES)
    n_records = sum(len(v) for lane in LANES for v in counters_doc["counters"][lane].values())
    print(f"Counter kaydi: {n_anchors} anahtar sampiyon / {n_records} karsi-sampiyon satiri; "
          f"uyari: {len(counters_warnings)}")
    for w in counters_warnings:
        print(f"  UYARI (counters.json'a girmedi): {w}")

    # 4) Fark
    old_doc: dict = {}
    if out_path.is_file():
        try:
            old_doc = json.loads(out_path.read_text(encoding="utf-8"))
        except ValueError as e:
            print(f"UYARI: mevcut {out_path} okunamadi ({e}); bos kabul edildi")
    else:
        print(f"NOT: {out_path} yok; tum kayitlar 'eklenen' gorunecek")
    print()
    print(format_diff(diff_tiers(old_doc.get("tiers") or {}, new_doc["tiers"]),
                      old_doc, new_doc))
    print()

    old_counters_doc: dict = {}
    if counters_out_path.is_file():
        try:
            old_counters_doc = json.loads(counters_out_path.read_text(encoding="utf-8"))
        except ValueError as e:
            print(f"UYARI: mevcut {counters_out_path} okunamadi ({e}); bos kabul edildi")
    else:
        print(f"NOT: {counters_out_path} yok; tum kayitlar 'eklenen' gorunecek")
    print()
    print(format_counters_diff(
        diff_counters(old_counters_doc.get("counters") or {}, counters_doc["counters"]),
        old_counters_doc, counters_doc,
    ))
    print()

    # 5) Yazma (yalniz acik onayla)
    if not args.write:
        print(f"YAZILMADI (varsayilan). Onayliyorsan: --write  ->  {out_path} + {counters_out_path}")
        return 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(new_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"YAZILDI: {out_path}")
    counters_out_path.parent.mkdir(parents=True, exist_ok=True)
    counters_out_path.write_text(
        json.dumps(counters_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"YAZILDI: {counters_out_path}")
    print("Sonraki adim (insan): degisikligi gozden gecir, commit/PR ac.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
