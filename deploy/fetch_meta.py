"""META tier verisini topluluk kaynagindan ceker (webui/assets/meta/tiers.json).

api_contract §8 "Meta tier verisi": onayli veri repo'daki
`webui/assets/meta/tiers.json`'dir. Akis YARI OTOMATIKtir ve bu betik onun ilk
adimidir:

    kaynaktan cek -> bizim semaya cevir -> adlari champions.json'a karsi dogrula
    -> mevcut dosyayla FARKI bas -> (yalniz --write ile) dosyaya yaz

VARSAYILAN OLARAK HICBIR SEY YAZMAZ. Commit/PR karari insanindir (Teoman).
Otomatik cron YOK; patch basina elle kosulur.

Kullanim (repo kokunden):

    backend\\.venv\\Scripts\\python.exe deploy\\fetch_meta.py            # sadece fark
    backend\\.venv\\Scripts\\python.exe deploy\\fetch_meta.py --write    # dosyaya yaz
    backend\\.venv\\Scripts\\python.exe deploy\\fetch_meta.py --selftest # agsiz test

Kaynak: OP.GG acik sampiyon tier listesi ucu (anonim GET, JSON, tek istek,
rol bazli tier verir). Sampiyon adi eslemesi icin Data Dragon `champion.json`
(numeric key -> gorunen ad) cekilir; `champions.json`a alan EKLENMEZ.

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


# --- Donusum (agsiz, test edilebilir) ---------------------------------------


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


def build_tiers(payload: dict, id_to_name: dict[int, str], valid_names: set[str],
                max_per_tier: int | None = None) -> tuple[dict, list[str]]:
    """OP.GG yanitini bizim `tiers` blogumuza cevirir.

    Donen: (tiers, uyarilar). Uyari = eslenemeyen sampiyon (dosyaya GIRMEZ).
    Tier ici siralama kaynagin kendi `rank`i (kucuk = iyi), esitlikte ad
    alfabetik -> cikti deterministiktir.
    """
    warnings: list[str] = []
    seen_unknown: set[str] = set()
    # lane -> tier -> [(rank, name)]
    buckets: dict[str, dict[str, list[tuple[int, str]]]] = {
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
            buckets[lane][letter].append((rank, name))

    tiers: dict[str, dict[str, list[str]]] = {}
    for lane in LANES:
        tiers[lane] = {}
        for t in TIERS:
            ordered = [n for _, n in sorted(buckets[lane][t], key=lambda x: (x[0], x[1]))]
            if max_per_tier is not None:
                ordered = ordered[:max_per_tier]
            tiers[lane][t] = ordered
    return tiers, warnings


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


# --- Fark (agsiz, test edilebilir) ------------------------------------------


def _placement(lane_tiers: dict) -> dict[str, str]:
    """{sampiyon: tier} — ayni sampiyon bir lane'de tek tierdedir."""
    out: dict[str, str] = {}
    for t in TIERS:
        for name in (lane_tiers or {}).get(t) or []:
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
    lines.append("FARK: mevcut tiers.json  ->  yeni (kaynak)")
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


# --- Selftest (ag YOK) ------------------------------------------------------


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

    # build_tiers
    def pos(name, tier, rank, ):
        return {"name": name, "stats": {"tier_data": {"tier": tier, "rank": rank}}}

    payload = {
        "meta": {"version": "16.16"},
        "data": [
            {"id": 103, "positions": [pos("MID", 1, 3), pos("SUPPORT", 4, 20)]},
            {"id": 62, "positions": [pos("MID", 1, 1), pos("TOP", 0, 1)]},
            {"id": 999, "positions": [pos("TOP", 1, 2)]},          # DD'de yok
            {"id": 777, "positions": [pos("TOP", 1, 2)]},          # champions.json'da yok
            {"id": 555, "is_rip": True, "positions": [pos("TOP", 1, 1)]},  # kaldirilmis
            {"id": 111, "positions": [{"name": "MID", "stats": {}}]},      # tier_data yok
        ],
    }
    id_to_name = {103: "Ahri", 62: "Wukong", 777: "Sicak", 555: "Rip", 111: "Bos"}
    valid = {"Ahri", "Wukong", "Rip", "Bos"}
    tiers, warns = build_tiers(payload, id_to_name, valid)
    check(tiers["middle"]["S"] == ["Wukong", "Ahri"], f"rank sirasi: {tiers['middle']['S']}")
    check(tiers["top"]["S"] == ["Wukong"], f"OP tier -> S: {tiers['top']['S']}")
    check(tiers["utility"]["S"] == [] and tiers["utility"]["A"] == [], "C tier alinmadi")
    check(tiers["bottom"] == {"S": [], "A": [], "B": []}, "bos lane tam anahtarli")
    check(set(tiers) == set(LANES), "5 lane her zaman mevcut")
    check(len(warns) == 2, f"2 uyari beklendi: {warns}")
    check(any("999" in w for w in warns), f"bilinmeyen id uyarisi: {warns}")
    check(any("Sicak" in w for w in warns), f"champions.json disi uyari: {warns}")
    check(tiers["middle"]["B"] == [], "tier_data'siz kayit atlandi")

    # max_per_tier
    capped, _ = build_tiers(payload, id_to_name, valid, max_per_tier=1)
    check(capped["middle"]["S"] == ["Wukong"], f"max_per_tier: {capped['middle']['S']}")

    # build_document
    doc, _ = build_document(payload, id_to_name, valid, source="test", updated="2026-01-01")
    check(doc["patch"] == "16.16", "patch meta.version'dan")
    check(set(doc) == {"patch", "updated", "source", "tiers"}, f"sema anahtarlari: {set(doc)}")
    doc2, _ = build_document({"data": []}, {}, set(), source="t", updated="d",
                             patch_fallback="9.9")
    check(doc2["patch"] == "9.9", "meta yoksa patch fallback")

    # diff_tiers
    old = {"top": {"S": ["A"], "A": ["B", "C"], "B": []},
           "jungle": {"S": [], "A": [], "B": []},
           "middle": {"S": [], "A": [], "B": []},
           "bottom": {"S": [], "A": [], "B": []},
           "utility": {"S": [], "A": [], "B": []}}
    new = {"top": {"S": ["A", "B"], "A": [], "B": ["D"]},
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

    if fails:
        print("SELFTEST BASARISIZ:")
        for f in fails:
            print("  - " + f)
        return 1
    print("SELFTEST OK (agsiz).")
    return 0


# --- CLI --------------------------------------------------------------------


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
            "META tier verisini topluluk kaynagindan ceker ve webui/assets/meta/\n"
            "tiers.json ile FARKINI basar. VARSAYILAN OLARAK YAZMAZ -- yazmak icin\n"
            "--write. Kaynak: OP.GG acik sampiyon tier listesi (anonim GET, JSON).\n"
            "Sema: api_contract.md §8 'Meta tier verisi'."
        ),
        epilog=(
            "Ornekler:\n"
            "  fetch_meta.py                      # farki goster (yazmaz)\n"
            "  fetch_meta.py --tier emerald_plus  # baska rank dilimi\n"
            "  fetch_meta.py --max-per-tier 8     # tier basina en iyi 8 sampiyon\n"
            "  fetch_meta.py --write              # onaydan sonra dosyaya yaz\n"
            "  fetch_meta.py --selftest           # agsiz ic testler\n\n"
            "Tier eslemesi: kaynak OP(0)/1 -> S, 2 -> A, 3 -> B; 4-5 (C/D) ALINMAZ.\n"
            "Yazdiktan sonra commit/PR insanin isidir (otomatik cron YOK)."
        ),
    )
    p.add_argument("--write", action="store_true",
                   help="farki gosterdikten SONRA tiers.json'a yaz (varsayilan: yazmaz)")
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
                   help="hedef dosya (varsayilan: webui/assets/meta/tiers.json)")
    p.add_argument("--dd-version", metavar="VER",
                   help="Data Dragon surumu (varsayilan: ddragon manifest.json, yoksa en yeni)")
    p.add_argument("--selftest", action="store_true",
                   help="ag gerektirmeyen ic testleri kosar ve cikar")
    args = p.parse_args(argv)

    if args.selftest:
        return _selftest()

    webui = webui_root()
    out_path = Path(args.out) if args.out else webui / "assets" / "meta" / "tiers.json"
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

    # 2) Kaynak
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

    # 3) Semaya cevir + ad dogrulama
    source_label = f"op.gg ({args.region}, {args.tier})"
    # `updated` insan-okur "ne zaman cekildi" alanidir; kosanin yerel tarihi
    # (UTC, TR saatiyle gece kosuldugunda bir gun geride gorunuyordu).
    updated = datetime.now().strftime("%Y-%m-%d")
    patch_fallback = ".".join(str(dd_version).split(".")[:2])
    new_doc, warnings = build_document(
        payload, id_to_name, valid_names, source=source_label, updated=updated,
        patch_fallback=patch_fallback, max_per_tier=args.max_per_tier,
    )
    matched = len({n for lane in LANES for t in TIERS for n in new_doc["tiers"][lane][t]})
    print(f"Eslesen sampiyon: {matched} (S/A/B'de yer alan); uyari: {len(warnings)}")
    for w in warnings:
        print(f"  UYARI (dosyaya girmedi): {w}")

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

    # 5) Yazma (yalniz acik onayla)
    if not args.write:
        print(f"YAZILMADI (varsayilan). Onayliyorsan: --write  ->  {out_path}")
        return 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(new_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"YAZILDI: {out_path}")
    print("Sonraki adim (insan): degisikligi gozden gecir, commit/PR ac.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
