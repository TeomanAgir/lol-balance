"""META tier + karsilastirma verisini topluluk kaynagindan ceker (INCE CLI).

api_contract §8 "Meta tier + secim danismani verisi — GOREV 34": donusum/fark
kodunun TEK sahibi `backend/app/services/meta_source.py`'dir; bu betik o modulu
cagiran ince sarmalayicidir ve YALNIZ repodaki TOHUM dosyalari yazar
(`webui/assets/meta/tiers.json` + `counters.json` — ilk kurulum ve yedek).
Canlidaki veri artik DB'de yasar (`meta_snapshots`) ve Kontrol Paneli'nden
`POST /admin/meta/refresh` ile guncellenir; bu betik ona DOKUNMAZ.

Akis (degismedi), AYNI TEK OP.GG isteginden iki dosya:

    kaynaktan cek (TEK istek) -> bizim iki semaya cevir -> adlari champions.json'a
    karsi dogrula -> mevcut dosyalarla FARKI bas -> (yalniz --write ile) yaz

VARSAYILAN OLARAK HICBIR SEY YAZMAZ. Commit/PR karari insanindir (Teoman).

Kullanim (repo kokunden):

    backend/.venv/bin/python deploy/fetch_meta.py            # sadece fark
    backend/.venv/bin/python deploy/fetch_meta.py --write    # tohum dosyalara yaz
    backend/.venv/bin/python deploy/fetch_meta.py --selftest # agsiz hizli kontrol

Not: meta_source stdlib-only'dir; betik `backend/` dizinini sys.path'e ekler,
backend bagimliliklari (FastAPI vb.) gerekmez.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services.meta_source import (  # noqa: E402 — sys.path yukarida
    DDRAGON_CHAMPION,
    DDRAGON_VERSIONS,
    LANES,
    OPGG_URL,
    TIERS,
    build_counters_document,
    build_document,
    champion_names_by_id,
    count_counters,
    diff_counters,
    diff_tiers,
    fetch_json,
    format_counters_diff,
    format_diff,
    load_valid_names,
)


def webui_root() -> Path:
    """fetch_ddragon.py ile ayni cozum: once CWD/webui, yoksa repo kokundeki."""
    cwd_webui = Path.cwd() / "webui"
    if cwd_webui.is_dir():
        return cwd_webui
    return REPO_ROOT / "webui"


# --- Selftest (ag YOK) -------------------------------------------------------


def _selftest() -> int:
    """Hizli agsiz duman testi. TAM kapsam backend/tests/test_meta_source.py'dedir:

        backend/.venv/bin/python -m pytest backend/tests/test_meta_source.py
    """
    from app.services.meta_source import lane_key, tier_letter

    fails: list[str] = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    check(tier_letter(0) == "S" and tier_letter(3) == "B" and tier_letter(4) is None,
          "tier eslemesi (0->S, 3->B, 4 alinmaz)")
    check(lane_key("adc") == "bottom" and lane_key("BOTTOM") is None, "lane eslemesi")
    payload = {"meta": {"version": "16.16"}, "data": [
        {"id": 103, "positions": [{"name": "MID", "stats": {
            "win_rate": 0.521, "pick_rate": 0.081, "tier_data": {"tier": 1, "rank": 1}},
            "counters": [{"champion_id": 62, "play": 100, "win": 40}]}]},
    ]}
    ids = {103: "Ahri", 62: "Wukong"}
    doc, warns = build_document(payload, ids, set(ids.values()), source="t", updated="d")
    check(doc["patch"] == "16.16" and doc["tiers"]["middle"]["S"][0]["name"] == "Ahri"
          and not warns, "build_document")
    cdoc, _ = build_counters_document(payload, ids, set(ids.values()), source="t", updated="d")
    check(cdoc["counters"]["middle"]["Ahri"][0]["win_rate_against"] == 0.6, "build_counters_document")
    d = diff_tiers({}, doc["tiers"])
    check(d["middle"]["added"] == [("Ahri", "S")], "diff_tiers")
    check(format_diff(d, {}, doc).isascii(), "format_diff ASCII")

    if fails:
        print("SELFTEST BASARISIZ:")
        for f in fails:
            print("  - " + f)
        return 1
    print("SELFTEST OK (agsiz). Tam kapsam: pytest backend/tests/test_meta_source.py")
    return 0


# --- CLI ----------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="fetch_meta.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "META tier + karsilastirma verisini topluluk kaynagindan ceker ve\n"
            "webui/assets/meta/{tiers,counters}.json (TOHUM dosyalar) ile FARKINI\n"
            "basar (AYNI tek OP.GG isteginden ikisi de). VARSAYILAN OLARAK YAZMAZ --\n"
            "yazmak icin --write. Canli veri DB'dedir ve Kontrol Paneli'nden\n"
            "guncellenir (GOREV 34); bu betik yalniz repo dosyalarini yazar.\n"
            "Sema: api_contract.md §8 'Meta tier + secim danismani verisi'."
        ),
        epilog=(
            "Ornekler:\n"
            "  fetch_meta.py                      # farki goster (yazmaz)\n"
            "  fetch_meta.py --tier emerald_plus  # baska rank dilimi\n"
            "  fetch_meta.py --max-per-tier 8     # tier basina en iyi 8 sampiyon\n"
            "  fetch_meta.py --write              # onaydan sonra iki dosyaya da yaz\n"
            "  fetch_meta.py --selftest           # agsiz hizli kontrol\n\n"
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
                   help="ag gerektirmeyen hizli kontrol (tam kapsam: pytest "
                        "backend/tests/test_meta_source.py)")
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

    valid_names, valid_src = load_valid_names(champions_path, id_to_name)
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
    matched = len({e["name"] for lane in LANES for t in TIERS
                   for e in new_doc["tiers"][lane][t]})
    print(f"Eslesen sampiyon (tiers): {matched} (S/A/B'de yer alan); uyari: {len(warnings)}")
    for w in warnings:
        print(f"  UYARI (tiers.json'a girmedi): {w}")

    counters_doc, counters_warnings = build_counters_document(
        payload, id_to_name, valid_names, source=source_label, updated=updated,
        patch_fallback=patch_fallback,
    )
    n_anchors, n_records = count_counters(counters_doc["counters"])
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

    # 5) Yazma (yalniz acik onayla; YALNIZ tohum dosyalar — DB'ye dokunmaz)
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
    print("Sonraki adim (insan): degisikligi gozden gecir, commit/PR ac. "
          "Canli veri icin Kontrol Paneli > Meta > Guncelle.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
