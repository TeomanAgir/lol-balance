"""Rulet eğlence modu (GÖREV 23 — api_contract §4.5, db_schema migration 0006).

Rastgele seçim İSTEMCİ tarafındadır (web UI, vendored ddragon verisinden);
backend eşya/şampiyon meta verisi BİLMEZ — atamayı yalnız ŞEKLEN doğrular,
saklar ve maçla eşler. Rulet maçı (`status='roulette'`) HİÇBİR rating evrenine
girmez; `status='valid'` süzgeci kullanan tüm mevcut sorguların otomatik
dışında kalır.

Doğrulama kurallarının (tam 10 kayıt, 5/5 takım, rol/champion benzersizliği,
tam 2 farklı pozitif int item_ids) TEK tanımı burasıdır; detail'ler Türkçe
tek-string olsun diye pydantic'e bırakılmaz (items/health deseni).

`bought` tanımının (küme bazlı envanter karşılaştırması) TEK doğruluk noktası
da burasıdır: maç yanıtındaki `roulette` alanı ve rulet rozetleri (badges.py)
aynı fonksiyonu kullanır, kural kopyalanmaz.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException
from rating import ROLES

from .health import utc_now_z

ASSIGNMENT_COUNT = 10
TEAM_SIZE = 5
ITEM_COUNT = 2

# Otomatik eşleşme penceresi (api_contract §4.5): açık oturum ancak son 24
# saat içinde açıldıysa maça bağlanır.
LINK_WINDOW = timedelta(hours=24)


# ── Doğrulama (POST /roulette) ───────────────────────────────────────────────

def _validate_item_ids(raw: Any, where: str) -> list[int]:
    """Tam 2 FARKLI pozitif int (api_contract §4.5); "tamamlanmış eşya"
    kontrolü YAPILMAZ — havuz süzgeci istemcidedir, ham id saklanır.

    `bool` reddedilir (items.py gerekçesi: `isinstance(True, int)` doğrudur
    ama eşya id'si değildir).
    """
    if not isinstance(raw, list):
        raise HTTPException(
            422,
            detail=f"{where}: item_ids bir dizi olmalı, geldi: {type(raw).__name__}.",
        )
    if len(raw) != ITEM_COUNT:
        raise HTTPException(
            422,
            detail=(
                f"{where}: item_ids tam {ITEM_COUNT} eleman içermeli, "
                f"geldi: {len(raw)}."
            ),
        )
    for i, value in enumerate(raw):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise HTTPException(
                422,
                detail=(
                    f"{where}: item_ids[{i}] pozitif tam sayı eşya id'si olmalı, "
                    f"geldi: {value!r}."
                ),
            )
    if len(set(raw)) != ITEM_COUNT:
        raise HTTPException(
            422,
            detail=f"{where}: item_ids'teki {ITEM_COUNT} eşya birbirinden farklı olmalı.",
        )
    return list(raw)


def validate_assignments(conn: sqlite3.Connection, assignments: list) -> list[dict]:
    """POST /roulette gövdesini contract kurallarıyla doğrular (aksi 422).

    Tip/enum kontrolü (team 100|200, position rol adı) pydantic'te yapılmıştır;
    burada sayısal/küme kuralları doğrulanır. Dönen liste DB'ye yazılacak
    normalize kayıtlardır (giriş sırası korunur).
    """
    if len(assignments) != ASSIGNMENT_COUNT:
        raise HTTPException(
            422,
            detail=(
                f"assignments tam {ASSIGNMENT_COUNT} kayıt içermeli, "
                f"geldi: {len(assignments)}."
            ),
        )

    player_ids = [a.player_id for a in assignments]
    if len(set(player_ids)) != ASSIGNMENT_COUNT:
        raise HTTPException(
            422, detail="Her oyuncu tam 1 kez atanmalı (player_id'ler tekrarlı)."
        )
    known = {
        row["id"]
        for row in conn.execute(
            "SELECT id FROM players WHERE id IN ({})".format(
                ",".join("?" * len(player_ids))
            ),
            player_ids,
        )
    }
    for i, a in enumerate(assignments):
        if a.player_id not in known:
            raise HTTPException(
                422,
                detail=f"assignments[{i}]: player_id {a.player_id} bulunamadı.",
            )

    n100 = sum(1 for a in assignments if a.team == 100)
    if n100 != TEAM_SIZE:
        raise HTTPException(
            422,
            detail=f"Her takımda tam {TEAM_SIZE} oyuncu olmalı (team=100 için {n100} geldi).",
        )
    for team in (100, 200):
        got = sorted(a.position for a in assignments if a.team == team)
        if got != sorted(ROLES):
            raise HTTPException(
                422,
                detail=(
                    f"team={team} takımında 5 rolün her biri tam 1 kez atanmalı."
                ),
            )

    champions = []
    for i, a in enumerate(assignments):
        if not isinstance(a.champion, str) or not a.champion.strip():
            raise HTTPException(
                422, detail=f"assignments[{i}]: champion boş olmayan bir metin olmalı."
            )
        champions.append(a.champion)
    if len(set(champions)) != ASSIGNMENT_COUNT:
        raise HTTPException(
            422, detail="champion'lar 10 kayıtta birbirinden farklı olmalı."
        )

    return [
        {
            "player_id": a.player_id,
            "team": a.team,
            "position": a.position,
            "champion": a.champion,
            "item_ids": _validate_item_ids(a.item_ids, f"assignments[{i}]"),
        }
        for i, a in enumerate(assignments)
    ]


# ── Oturum yaşam döngüsü ─────────────────────────────────────────────────────

def _dump_item_ids(item_ids: list[int]) -> str:
    return json.dumps(item_ids, separators=(",", ":"))


def create_session(
    conn: sqlite3.Connection, assignments: list[dict], now: datetime | None = None
) -> tuple[int, str]:
    """Yeni oturum açar; o anda `open` olan TÜM oturumları `cancelled` yapar
    (tek açık oturum değişmezi — arkadaş grubu tek lobi). (id, created_at) döner.

    `created_at` SUNUCUDA, `played_at` ile aynı UTC "…Z" biçiminde atanır —
    24 saatlik pencere karşılaştırması metin biçiminden bağımsız, parse ederek
    yapılır ama biçim tutarlılığı yanıt/gösterim için korunur.
    """
    created_at = utc_now_z(now)
    with conn:
        conn.execute(
            "UPDATE roulette_sessions SET status = 'cancelled' WHERE status = 'open'"
        )
        cur = conn.execute(
            "INSERT INTO roulette_sessions (created_at, status) VALUES (?, 'open')",
            (created_at,),
        )
        session_id = cur.lastrowid
        for a in assignments:
            conn.execute(
                "INSERT INTO roulette_assignments"
                " (session_id, player_id, team, position, champion, item_ids_json)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    a["player_id"],
                    a["team"],
                    a["position"],
                    a["champion"],
                    _dump_item_ids(a["item_ids"]),
                ),
            )
    return session_id, created_at


def _session_assignments(conn: sqlite3.Connection, session_id: int) -> list[dict]:
    """Oturumun atamaları, POST gövdesindeki giriş sırasıyla (id artan)."""
    rows = conn.execute(
        "SELECT player_id, team, position, champion, item_ids_json "
        "FROM roulette_assignments WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    return [
        {
            "player_id": row["player_id"],
            "team": row["team"],
            "position": row["position"],
            "champion": row["champion"],
            "item_ids": json.loads(row["item_ids_json"]),
        }
        for row in rows
    ]


def _open_session_row(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    # Değişmez gereği en fazla 1 açık oturum vardır; ORDER BY savunma amaçlıdır
    # (bozuk veri hâlinde en yenisi kazanır, sonuç deterministik kalır).
    return conn.execute(
        "SELECT id, created_at FROM roulette_sessions "
        "WHERE status = 'open' ORDER BY id DESC LIMIT 1"
    ).fetchone()


def current_session(conn: sqlite3.Connection) -> Optional[dict]:
    """GET /roulette/current gövdesi: açık oturum ya da None.

    24 saat penceresi burada UYGULANMAZ — pencere yalnız otomatik eşleşmenin
    koşuludur (api_contract §4.5); bayat açık oturum yeni POST'a dek görünür.
    """
    row = _open_session_row(conn)
    if row is None:
        return None
    return {
        "session_id": row["id"],
        "created_at": row["created_at"],
        "assignments": _session_assignments(conn, row["id"]),
    }


# ── Otomatik eşleşme (ingest) ────────────────────────────────────────────────

def _parse_utc(text: str) -> Optional[datetime]:
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def find_linkable_session(
    conn: sqlite3.Connection,
    match_player_ids: set[int],
    now: datetime | None = None,
) -> Optional[int]:
    """Maça bağlanabilir oturumun id'si; koşullar sağlanmıyorsa None.

    Koşullar (api_contract §4.5): açık oturum var VE `created_at` son 24 saat
    içinde VE maçın 10 player_id kümesi oturumunkiyle birebir aynı. Çağıran
    duplicate/auto-void elemesini ZATEN yapmıştır. `now` yalnız deterministik
    test için enjekte edilir (utc_now_z deseni).
    """
    row = _open_session_row(conn)
    if row is None:
        return None
    created = _parse_utc(row["created_at"])
    now = now if now is not None else datetime.now(timezone.utc)
    if created is None or now - created > LINK_WINDOW:
        return None
    session_players = {
        r["player_id"]
        for r in conn.execute(
            "SELECT player_id FROM roulette_assignments WHERE session_id = ?",
            (row["id"],),
        )
    }
    if session_players != match_player_ids:
        return None
    return row["id"]


def link_session(
    conn: sqlite3.Connection, session_id: int, match_id: int
) -> None:
    """Oturumu maça bağlar; maçı roulette işaretlemek ÇAĞIRANIN işidir
    (ingest transaction'ı içinde koşar, commit çağıranındır)."""
    conn.execute(
        "UPDATE roulette_sessions SET status = 'linked', match_id = ? WHERE id = ?",
        (match_id, session_id),
    )


def unlink_match(conn: sqlite3.Connection, match_id: int) -> None:
    """Unlink'in DB adımı: maç valid'e döner, oturum cancelled olur.

    `match_id` yalnız linked durumda dolu kalır (db_schema 0006 notu), bu
    yüzden NULL'lanır. Replay ÇAĞIRANIN işidir (mevcut mekanizma).
    """
    with conn:
        conn.execute(
            "UPDATE matches SET status = 'valid' WHERE id = ?", (match_id,)
        )
        conn.execute(
            "UPDATE roulette_sessions SET status = 'cancelled', match_id = NULL "
            "WHERE match_id = ?",
            (match_id,),
        )


# ── Maç yanıtındaki `roulette` alanı + rozet paylaşımlı `bought` ─────────────

def assignment_bought(
    item_ids: list[int], items_json: Optional[str]
) -> Optional[bool]:
    """`bought` (api_contract §3): atanan 2 eşyanın İKİSİ DE final envanterde mi?

    Karşılaştırma KÜME bazlıdır (sıra/yinelenme önemsiz). `items` NULL ise
    doğrulanamaz → None. `[]` = "bilgi var, envanter boş" → False.
    Rozet tanımlarıyla (badges.py) birebir aynı mantık — tek doğruluk noktası.
    """
    if items_json is None:
        return None
    return set(item_ids) <= set(json.loads(items_json))


def match_roulette(
    conn: sqlite3.Connection, match_id: int, winner_team: int
) -> Optional[dict]:
    """Maç yanıtındaki `roulette` alanı (api_contract §3); bağlı oturum yoksa None.

    `won` = `bought == True` VE oyuncunun MAÇTAKİ takımı `winner_team`
    (bought null/false iken False). Takım, atamadan değil match_participants'tan
    okunur — rastgele atanan takım ile fiilen oynanan takım farklı olabilir.
    """
    session = conn.execute(
        "SELECT id FROM roulette_sessions WHERE match_id = ? AND status = 'linked'",
        (match_id,),
    ).fetchone()
    if session is None:
        return None
    rows = conn.execute(
        "SELECT ra.player_id, ra.champion, ra.position, ra.item_ids_json,"
        " mp.items_json, mp.team "
        "FROM roulette_assignments ra "
        "LEFT JOIN match_participants mp ON mp.match_id = ?"
        " AND mp.player_id = ra.player_id "
        "WHERE ra.session_id = ? ORDER BY ra.id",
        (match_id, session["id"]),
    ).fetchall()
    assignments = []
    for row in rows:
        item_ids = json.loads(row["item_ids_json"])
        bought = assignment_bought(item_ids, row["items_json"])
        assignments.append(
            {
                "player_id": row["player_id"],
                "champion": row["champion"],
                "position": row["position"],
                "item_ids": item_ids,
                "bought": bought,
                "won": bought is True and row["team"] == winner_team,
            }
        )
    return {"session_id": session["id"], "assignments": assignments}
