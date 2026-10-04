"""META tier + karsilastirma verisi: kaynak -> belge donusumu ve fark (GOREV 34).

api_contract §8 "Meta tier + secim danismani verisi": donusum/fark kodunun TEK
sahibi bu moduldur. `deploy/fetch_meta.py` buradaki fonksiyonlari cagiran ince
bir CLI'dir; `services/meta_store.py` ise ayni fonksiyonlarla DB'ye anlik goruntu
yazar. Kod burada yasar, baska yere KOPYALANMAZ.

Bu modul SAF ve stdlib-only'dir (CLI backend bagimliliklari olmadan import
edebilsin): FastAPI/sqlite yok, ag erisimi TEK fonksiyondan (`fetch_json`)
gecer — testler ve store onu monkeypatch'ler/enjekte eder, gercek aga cikmaz.

Tarihce: 2026-08-15/17'de bu kod deploy/fetch_meta.py'deydi; GOREV 34 ile
davranis BIREBIR korunarak buraya tasindi (fetch_meta'nin _selftest'indeki her
kontrol backend/tests/test_meta_source.py'de pytest testidir).
"""
from __future__ import annotations

import json
import urllib.request
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


# --- Ag (TEK giris noktasi) --------------------------------------------------


def fetch_json(url: str, timeout: int = 30) -> dict:
    """Anonim GET + JSON. Store/CLI'daki tum ag erisimi buradan gecer."""
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


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
    yani `(play - win) / play`. S/A/B tier sarti ARANMAZ (secim danismani her
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


# --- Sayimlar (store + CLI ortak) --------------------------------------------


def count_tiers_entries(tiers: dict) -> int:
    """S/A/B'de yer alan (lane, sampiyon) kayit sayisi."""
    return sum(
        len(((tiers or {}).get(lane) or {}).get(t) or [])
        for lane in LANES for t in TIERS
    )


def count_counters(counters: dict) -> tuple[int, int]:
    """(anahtar sampiyon sayisi, karsi-sampiyon satiri sayisi)."""
    anchors = rows = 0
    for lane in LANES:
        lane_map = (counters or {}).get(lane) or {}
        anchors += len(lane_map)
        rows += sum(len(v or []) for v in lane_map.values())
    return anchors, rows


# --- Dogrulama kumesi --------------------------------------------------------


def load_valid_names(path: Path, id_to_name: dict[int, str]) -> tuple[set[str], str]:
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
