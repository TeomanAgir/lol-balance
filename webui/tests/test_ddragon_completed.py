# test_ddragon_completed.py — rulet eşya havuzunun süzgeci (GÖREV 23).
#
# `webui/assets/ddragon/items.json` içindeki `completed` bayrağı (api_contract §8)
# web UI'ın RULET havuzudur: çark yalnız `completed: true` eşyalardan çeker.
# Bayrağı üreten sezgisel `deploy/fetch_ddragon.py`'dedir; burada AĞA ÇIKMADAN,
# Data Dragon kayıtlarının sentetik örnekleriyle doğrulanır.
#
# Bu dosya webui/tests altındadır çünkü doğrulanan şey webui'ın varlık
# sözleşmesidir ve CI zaten `pytest webui/tests` koşar (ek iş adımı gerekmez).
#
# Kabul ölçütleri (api_contract §8):
#   * klasik efsanevi eşyalar (3031 Ebedi Kılıç, 3026 Koruyucu Melek) → True
#   * bileşen / tüketilebilir / trinket / bot eşyaları → False
#   * (GÖREV 23 düzeltmesi) mod/kuyruk VARYANTI kayıtları → False: Data Dragon
#     aynı eşyayı 6 haneli ikinci bir id ile de taşır (ör. 322065) ve bu kayıt
#     `maps` sözlüğünde YALNIZ "11"i açık bırakır. Gerçek maç sonu envanteri
#     kanonik id'yi bildirdiği için varyant atanan oyuncu görevi ASLA
#     tamamlayamazdı (collector fixtures/mh_game_custom_real.json: hepsi 4 haneli).

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "deploy" / "fetch_ddragon.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("fetch_ddragon_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def dd():
    assert SCRIPT.is_file(), f"betik bulunamadi: {SCRIPT}"
    return _load_module()


# Kanonik SR haritalari: 11 (SR) + en az bir baskasi. Varyant kayitlarda
# yalniz "11" aciktir — ayrimin tek kaynagi budur.
CANONICAL_MAPS = {"11": True, "12": True, "21": True, "22": False, "30": False,
                  "33": False, "35": True, "453": True}
VARIANT_MAPS = {"11": True, "12": False, "21": False, "22": False, "30": False,
                "33": False, "35": False, "453": False}


def item(from_list=None, **over):
    """Varsayilan: kanonik, tamamlanmis efsanevi esya (3031 kaliba).

    `from` bir Python anahtar kelimesi oldugundan bilesen listesi `from_list`
    ile verilir; digerleri dogrudan Data Dragon alan adlaridir.
    """
    base = {
        "name": "Infinity Edge",
        "from": from_list if from_list is not None else ["1038", "1037", "1018"],
        "gold": {"base": 725, "purchasable": True, "total": 3500, "sell": 2450},
        "tags": ["Damage", "CriticalStrike"],
        "maps": dict(CANONICAL_MAPS),
    }
    base.update(over)
    return base


# ── Kabul olcutu: klasik efsanevi esyalar ───────────────────────


def test_legendary_items_are_completed(dd):
    assert dd.is_completed(item()) is True                       # 3031 Ebedi Kilic
    # 3026 Koruyucu Melek: gercek kayitta yalniz 11 + 453 acik — "birden fazla
    # harita" kurali bu daralmis kanonik esyayi ELEMEZ.
    assert dd.is_completed(item(
        name="Guardian Angel",
        from_list=["3031", "1031"],
        maps={"11": True, "12": False, "21": False, "453": True},
        tags=["Damage", "Armor"],
    )) is True


# ── Kabul olcutu: bilesen / tuketilebilir / trinket / bot ───────


@pytest.mark.parametrize("bad, why", [
    ({"from": []}, "bilesenlerden uretilmeyen (from yok) = bilesen"),
    ({"into": ["3031"]}, "baska esyaya donusen = bilesen"),
    ({"tags": ["Trinket"]}, "ziynet esyasi"),
    ({"tags": ["Consumable"]}, "tuketilebilir"),
    ({"tags": ["Boots"]}, "bot"),
    ({"gold": {"purchasable": False, "total": 3500}}, "satin alinamaz"),
    ({"inStore": False}, "magazada yok"),
    ({"maps": {"11": False, "12": True, "21": True}}, "SR'da yok"),
    ({"requiredChampion": "Gangplank"}, "sampiyona ozel"),
    ({"requiredAlly": "Ornn"}, "muttefike ozel (Ornn ustalik isi)"),
])
def test_non_completed_classes(dd, bad, why):
    assert dd.is_completed(item(**bad)) is False, why


# ── GÖREV 23 duzeltmesi: mod/kuyruk varyantlari havuza girmez ───


def test_mode_variant_record_is_excluded(dd):
    # 322065 gibi: tum yapisal kosullari saglar ama YALNIZ map 11 acik.
    assert dd.is_completed(item(
        name="Shurelya's Battlesong", from_list=["3113", "4642"],
        maps=dict(VARIANT_MAPS),
    )) is False


def test_canonical_twin_of_a_variant_stays_completed(dd):
    assert dd.is_completed(item(
        name="Shurelya's Battlesong", from_list=["3113", "4642"],
    )) is True


# ── Ikinci emniyet: ayni ad iki kez bayrakliysa kanonik id kalir ─


def test_duplicate_names_keep_the_canonical_shorter_id(dd):
    items = {
        "2065": {"name_en": "Shurelya's Battlesong", "completed": True},
        "322065": {"name_en": "Shurelya's Battlesong", "completed": True},
        "6676": {"name_en": "The Collector", "completed": True},
        "667666": {"name_en": "The Collector", "completed": True},
        "3031": {"name_en": "Infinity Edge", "completed": True},
        "1038": {"name_en": "B. F. Sword", "completed": False},
    }
    dd.drop_duplicate_completed(items)
    flagged = sorted(k for k, v in items.items() if v["completed"])
    assert flagged == ["2065", "3031", "6676"]


def test_dedupe_does_not_resurrect_unflagged_items(dd):
    items = {
        "3031": {"name_en": "Infinity Edge", "completed": False},
        "1038": {"name_en": "B. F. Sword", "completed": False},
    }
    dd.drop_duplicate_completed(items)
    assert not any(v["completed"] for v in items.values())
