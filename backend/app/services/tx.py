"""Transaction yardımcısı (api_contract §5 "Durum değişimi + replay ATOMİKTİR").

sqlite3'ün `with conn:` bloğu ÇIKIŞTA commit eder; iç içe kullanıldığında
içteki blok dıştakini erken commit eder — yani "tek transaction" iddiası
sessizce bozulur. Bu yüzden kendi transaction'ını açan servisler
(`replay`, `replay_roles`, `unlink_match`) `join_transaction=True` ile
ÇAĞIRANIN açık transaction'ına katılabilir: commit/rollback kararı tamamen
dıştaki `with conn:` bloğunundur.
"""
from __future__ import annotations

import sqlite3
from contextlib import AbstractContextManager, nullcontext


def maybe_transaction(
    conn: sqlite3.Connection, join_transaction: bool
) -> AbstractContextManager:
    """`join_transaction` ise no-op (çağıranın transaction'ı), değilse `conn`."""
    return nullcontext() if join_transaction else conn
