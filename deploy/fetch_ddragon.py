"""Data Dragon varlıklarını webui/assets/ddragon/ altına indirir (GÖREV 14).

Build-time vendoring (Teoman kararı, CHANGE_REQUESTS 2026-08-14): bu betik deploy
imajı kurulurken (Dockerfile) koşar; canlı sitede tarayıcı dışarı istek atmaz.
Yerel geliştirmede elle de koşulabilir:

    backend\\.venv\\Scripts\\python.exe deploy\\fetch_ddragon.py

Patch güncellemesi = DDRAGON_VERSION'ı değiştir + redeploy. Çıktı yerleşimi
api_contract §8'de sabittir: manifest.json, items.json, champions.json,
item/<id>.png, champion/<Name>.png.

Yalnız stdlib kullanır (imaj kurulumunda ek bağımlılık istemiyoruz).
"""
from __future__ import annotations

import html
import json
import re
import sys
import urllib.request
from pathlib import Path

# Sabitlenmiş patch. Güncellerken https://ddragon.leagueoflegends.com/api/versions.json
DDRAGON_VERSION = "16.16.1"

CDN = f"https://ddragon.leagueoflegends.com/cdn/{DDRAGON_VERSION}"

# Pozisyon ikonları Data Dragon'da YOK; resmî client ikonları CommunityDragon'dan
# gelir (aynı sabitleme ilkesi: sürüm = DDRAGON_VERSION'ın major.minor'u).
CDRAGON = (
    "https://raw.communitydragon.org/"
    + ".".join(DDRAGON_VERSION.split(".")[:2])
    + "/plugins/rcp-fe-lol-static-assets/global/default/svg"
)
POSITIONS = ("top", "jungle", "middle", "bottom", "utility")
# Çıktı kökü: önce CWD/webui (Docker imajında WORKDIR /app, webui ./webui'dedir),
# yoksa betiğe göre repo kökü (yerelde herhangi bir dizinden koşulabilsin).
_cwd_webui = Path.cwd() / "webui"
_repo_webui = Path(__file__).resolve().parent.parent / "webui"
OUT = (_cwd_webui if _cwd_webui.is_dir() else _repo_webui) / "assets" / "ddragon"

TAG_RE = re.compile(r"<[^>]+>")


# CommunityDragon varsayılan Python UA'sını 403'ler; kimliğimizi açıkça veriyoruz.
_UA = {"User-Agent": f"lol-balance-fetch/{DDRAGON_VERSION}"}


def _open(url: str):
    return urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=60)


def fetch_json(url: str) -> dict:
    with _open(url) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_binary(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with _open(url) as r:
        dest.write_bytes(r.read())


def plain_text(desc: str) -> str:
    """Data Dragon açıklaması HTML/özel etiket taşır; tooltip için düz metin."""
    text = TAG_RE.sub(" ", desc or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


# GÖREV 23: "tamamlanmış eşya" bayrağı (api_contract §8) — rulet eşya havuzunu
# web UI bu bayrakla süzer, kesin sezgisel BURADADIR:
#   * SR'da satın alınabilir: gold.purchasable + inStore != false + maps["11"]
#   * başka eşyaya DÖNÜŞMEZ (`into` yok) + bileşenlerden ÜRETİLİR (`from` var)
#   * trinket / tüketilebilir / bot eşyaları hariç (tags)
#   * şampiyona/müttefike özel eşyalar (Ornn vb.) hariç
#   * MOD/KUYRUK VARYANTI olmayan KANONİK kayıt (aşağıya bkz.)
# Kabul ölçütü (contract): 3031 Ebedi Kılıç ve 3026 Koruyucu Melek True;
# bileşen (from'suz ya da into'lu), tüketilebilir, trinket ve botlar False.
COMPLETED_EXCLUDED_TAGS = {"Trinket", "Consumable", "Boots"}


def is_completed(item: dict) -> bool:
    """Eşya, rulet havuzuna girecek "tamamlanmış" bir SR eşyası mı?

    MOD VARYANTI ELEMESİ (16.16.1'de 20 kayıt): Data Dragon, aynı eşyanın
    mod/kuyruk'a özel ikinci bir kaydını 6 haneli id ile taşır (ör. 322065
    "Shurelya's Battlesong", 667666 "The Collector"). Bu kayıtlar `maps`
    sözlüğünde YALNIZCA "11"i açık bırakır; kanonik SR eşyaları ise her zaman
    en az bir başka haritada da (12/21/35/453) açıktır. Ayrım önemlidir:
    gerçek maç sonu envanteri KANONİK id'yi bildirir (bkz. collector
    fixtures/mh_game_custom_real.json — hepsi 4 haneli), yani varyant id
    atanan oyuncu görevini ASLA tamamlayamazdı.
    """
    gold = item.get("gold") or {}
    maps = item.get("maps") or {}
    tags = set(item.get("tags") or [])
    return bool(
        gold.get("purchasable")
        and item.get("inStore", True)
        and maps.get("11")
        and sum(1 for enabled in maps.values() if enabled) > 1
        and not item.get("into")
        and item.get("from")
        and not (tags & COMPLETED_EXCLUDED_TAGS)
        and not item.get("requiredChampion")
        and not item.get("requiredAlly")
    )


def drop_duplicate_completed(items: dict[str, dict]) -> None:
    """Aynı ADA sahip birden çok "completed" kaydı kalırsa yalnız KANONİK
    (sayısal olarak en küçük id'li) olan bayraklı kalır; yerinde düzeltir.

    `is_completed`'ın harita kuralı 16.16.1'de tüm varyantları zaten eliyor;
    bu geçiş, Riot varyantlara başka bir harita eklerse havuzun sessizce
    ulaşılamaz id'lerle dolmasını engelleyen İKİNCİ emniyettir.
    """
    canonical: dict[str, str] = {}
    for item_id, meta in items.items():
        if not meta.get("completed"):
            continue
        name = meta["name_en"]
        best = canonical.get(name)
        if best is None:
            canonical[name] = item_id
            continue
        loser = max(best, item_id, key=lambda x: (len(x), x))
        winner = best if loser == item_id else item_id
        items[loser]["completed"] = False
        canonical[name] = winner


def build_items() -> dict[str, dict]:
    tr = fetch_json(f"{CDN}/data/tr_TR/item.json")["data"]
    en = fetch_json(f"{CDN}/data/en_US/item.json")["data"]
    items: dict[str, dict] = {}
    for item_id, en_item in en.items():
        tr_item = tr.get(item_id, en_item)
        items[item_id] = {
            "name_tr": tr_item.get("name", en_item.get("name", item_id)),
            "name_en": en_item.get("name", item_id),
            "desc_tr": plain_text(tr_item.get("plaintext") or tr_item.get("description", "")),
            "desc_en": plain_text(en_item.get("plaintext") or en_item.get("description", "")),
            "tags": en_item.get("tags", []),
            "completed": is_completed(en_item),
        }
    drop_duplicate_completed(items)
    return items


def build_champions() -> dict[str, dict]:
    en = fetch_json(f"{CDN}/data/en_US/champion.json")["data"]
    # Anahtar, participants.champion string'iyle eşleşen görünen ad olmalı
    # (EOG "championName" görünen adı taşır, ör. "Lee Sin"; DD anahtarı "LeeSin").
    champs: dict[str, dict] = {}
    for dd_key, c in en.items():
        display_name = c.get("name", dd_key)
        info = c.get("info") or {}
        champs[display_name] = {
            "icon": f"champion/{c['image']['full']}",
            "dd_key": dd_key,
            "tags": c.get("tags") or [],
            "info": {
                "attack": info.get("attack"),
                "defense": info.get("defense"),
                "magic": info.get("magic"),
                "difficulty": info.get("difficulty"),
            },
        }
    return champs


def champions_output(champions: dict[str, dict]) -> dict[str, dict]:
    """champions.json'a yazilacak alt kume (dd_key disari sizmaz)."""
    return {
        name: {"icon": v["icon"], "tags": v["tags"], "info": v["info"]}
        for name, v in champions.items()
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(
        description="Data Dragon varliklarini webui/assets/ddragon/ altina indirir."
    )
    p.add_argument(
        "--champions-only", action="store_true",
        help=(
            "yalniz champions.json'i tazeler (tags/info alanlari icin); manifest.json, "
            "items.json ve gorseller DOKUNULMAZ, yeni sampiyon ikonu indirilmez "
            "(gorsel dizinleri gitignore'lu, build-time vendoring'de tam kurulumla gelir)"
        ),
    )
    args = p.parse_args(argv)

    print(f"Data Dragon {DDRAGON_VERSION} -> {OUT}")
    OUT.mkdir(parents=True, exist_ok=True)

    if args.champions_only:
        champions = build_champions()
        (OUT / "champions.json").write_text(
            json.dumps(champions_output(champions), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        print(f"OK (--champions-only): {len(champions)} sampiyon, champions.json tazelendi "
              "(manifest/items/gorseller degismedi).")
        return 0

    items = build_items()
    champions = build_champions()

    (OUT / "manifest.json").write_text(
        json.dumps({"version": DDRAGON_VERSION}, ensure_ascii=False), encoding="utf-8"
    )
    (OUT / "items.json").write_text(
        json.dumps(items, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    (OUT / "champions.json").write_text(
        json.dumps(
            champions_output(champions),
            ensure_ascii=False, separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    for i, item_id in enumerate(sorted(items), 1):
        dest = OUT / "item" / f"{item_id}.png"
        if not dest.exists():
            fetch_binary(f"{CDN}/img/item/{item_id}.png", dest)
        if i % 50 == 0:
            print(f"  item {i}/{len(items)}")

    for i, (name, v) in enumerate(sorted(champions.items()), 1):
        dest = OUT / v["icon"]
        if not dest.exists():
            fetch_binary(f"{CDN}/img/champion/{Path(v['icon']).name}", dest)
        if i % 50 == 0:
            print(f"  champion {i}/{len(champions)}")

    for pos in POSITIONS:
        dest = OUT / "position" / f"{pos}.svg"
        if not dest.exists():
            fetch_binary(f"{CDRAGON}/position-{pos}.svg", dest)

    print(f"OK: {len(items)} esya, {len(champions)} sampiyon, {len(POSITIONS)} pozisyon ikonu.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
