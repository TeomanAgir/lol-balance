"""Maç sonu envanteri (GÖREV 14 — ingest_contract "items", api_contract §3).

`match_participants.items_json` KÜRATÖRLÜ alandır (position deseni, db_schema
ilke 4): ham `ingest_events` değişmez, `PUT /matches/{id}/items` üstüne yazar.
Rating'e HİÇBİR etkisi yoktur — gösterim/istatistik verisidir.

Doğrulama kuralının (0-7 eleman, hepsi int) TEK tanımı burasıdır; ingest de PUT
da bu yardımcılardan geçer, kural iki yerde kopyalanmaz (health.py deseni).
Eşya META VERİSİ (ad, ikon, tags/trinket) backend'e GİRMEZ — o web UI'dadır.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import HTTPException

MAX_ITEMS = 7


def validate_items(raw: Any, where: str) -> list[int]:
    """0-7 elemanlı int dizisini doğrular; `where` hata metnindeki konumdur.

    `bool` reddedilir: Python'da `isinstance(True, int)` doğrudur ama eşya id'si
    değildir. Ham SIRA korunur (son eleman genelde trinket) — sıralanmaz.
    """
    if not isinstance(raw, list):
        raise HTTPException(
            422, detail=f"{where}: items bir dizi olmalı, geldi: {type(raw).__name__}."
        )
    if len(raw) > MAX_ITEMS:
        raise HTTPException(
            422,
            detail=(
                f"{where}: items en fazla {MAX_ITEMS} eleman içerebilir, "
                f"geldi: {len(raw)}."
            ),
        )
    for i, value in enumerate(raw):
        if isinstance(value, bool) or not isinstance(value, int):
            raise HTTPException(
                422,
                detail=(
                    f"{where}: items[{i}] tam sayı eşya id'si olmalı, "
                    f"geldi: {value!r}."
                ),
            )
    return list(raw)


def dump_items(items: list[int]) -> str:
    """DB'ye yazılan JSON metni (ayraçsız, deterministik)."""
    return json.dumps(items, separators=(",", ":"))


def normalize_optional_items(raw: Any, where: str) -> Optional[str]:
    """Ingest'teki OPSİYONEL `items` alanını `items_json` metnine çevirir.

    Alan yok/None → NULL saklanır ("bilinmiyor"; eski exe'ler göndermez,
    geriye uyumluluk). `[]` ise "bilgi var, envanter boş" demektir ve JSON
    dizisi olarak yazılır — iki durum yanıtta da ayrı görünür.
    """
    if raw is None:
        return None
    return dump_items(validate_items(raw, where))


def load_items(items_json: Optional[str]) -> Optional[list[int]]:
    """Yanıt için `items` alanı: NULL → None (bilinmiyor), aksi hâlde liste."""
    if items_json is None:
        return None
    return json.loads(items_json)
