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
        }
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
