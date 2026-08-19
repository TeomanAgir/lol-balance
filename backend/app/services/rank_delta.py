"""Sıra değişimi `rank_delta` (api_contract §5) — salt-okur türetilmiş.

Tanım: EN SON valid maçtan hemen ÖNCEKİ sıralamaya göre kaç sıra değişildiği.
Pozitif = yükseldi, negatif = düştü, 0 = değişmedi, None = karşılaştırılamaz.

DB'ye HİÇBİR ŞEY yazılmaz (değişmez 1: rating türetilmiş veridir, `rank_delta`
onun da türevidir). `POST /admin/replay` sonrası bit-bit aynı kalır: referans an
replay'in sıralama anahtarıyla (`replay_order_by`) bulunur ve önceki score'lar
replay'in yeniden ürettiği `mu_before/sigma_before` + `perf_score` satırlarından
okunur.

Ucuzluk notu: referans maç + oyuncu başına tek toplu özet + referans maçın
satırları = 3 ek sorgu, oyuncu/maç sayısından BAĞIMSIZ (leaderboard'un mevcut
sorgularının üstüne sabit maliyet; replay ya da ikinci bir tam hesap YOK).
Önceki anın score'ları için tüm evren yeniden hesaplanmaz — referans
maç EN SON maç olduğundan o maçta OYNAMAYAN oyuncunun score'u değişmemiştir
(sırası değişebilir, o da bu yüzden gösterilir).
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from rating import Engine, Rating

from .ratings import effective_score, is_blend, replay_order_by


def leaderboard_order(
    scored: Iterable[tuple[int, float]]
) -> list[int]:
    """(player_id, score) çiftlerini leaderboard sırasına dizer — TEK nokta.

    Kural: `score` AZALAN; eşitlikte `player_id` ARTAN (mevcut leaderboard'un
    deterministik kırılımı — liste id sırasında kurulup stable sort'la score'a
    göre sıralanıyordu, bu ifade onun birebir aynısıdır).

    Hem güncel hem de "önceki an" sıralaması bu fonksiyonla kurulur; kural
    hiçbir çağırana kopyalanmaz (api_contract §5: iki an da leaderboard'un
    KENDİ kuralıyla sıralanır).
    """
    return [pid for pid, _score in sorted(scored, key=lambda t: (-t[1], t[0]))]


def _ranks(scored: Iterable[tuple[int, float]]) -> dict[int, int]:
    """player_id → 0 tabanlı sıra (küçük = üstte)."""
    return {pid: i for i, pid in enumerate(leaderboard_order(scored))}


def rank_deltas(
    conn: sqlite3.Connection,
    engine_version: str,
    scores: dict[int, float],
) -> dict[int, int | None]:
    """`scores` (güncel player_id → score) için `rank_delta` haritası.

    `null` (None) halleri (api_contract §5):
    - Hiç valid maç yoksa (referans an yok) → hepsi None.
    - Oyuncunun ÖNCEKİ anda hiç rating satırı yoksa: ilk maçıyla listeye yeni
      girmiştir (sahte yükseliş gösterilmez) ya da hiç maçı yoktur.
    """
    engine = Engine(version=engine_version)
    blend = is_blend(engine)
    none_map: dict[int, int | None] = {pid: None for pid in scores}

    # 1) Referans an: aktif engine'in rating_history'sindeki EN YENİ valid maç
    #    (replay sort-key'inin tersi). Rulet/void maçlar rating dışıdır, bu
    #    yüzden JOIN + status='valid' ikisini birden eler.
    ref = conn.execute(
        "SELECT rh.match_id AS match_id FROM rating_history rh "
        "JOIN matches m ON m.id = rh.match_id "
        "WHERE rh.engine_version = ? AND m.status = 'valid' "
        f"{replay_order_by('m', desc=True)} LIMIT 1",
        (engine_version,),
    ).fetchone()
    if ref is None:
        return none_map
    ref_match_id = ref["match_id"]

    # 2) Referans maç HARİÇ tüm valid maçların oyuncu başına özeti:
    #    n_rows → önceki anda rating satırı var mı (None kuralı),
    #    perf toplam/adet → önceki andaki kariyer P_avg'i (perf_averages ile
    #    aynı semantik: NULL perf_score ortalamaya girmez).
    prior: dict[int, tuple[int, int, float | None]] = {}
    for row in conn.execute(
        "SELECT rh.player_id AS pid, COUNT(*) AS n_rows,"
        " COUNT(rh.perf_score) AS n_perf, SUM(rh.perf_score) AS s_perf "
        "FROM rating_history rh JOIN matches m ON m.id = rh.match_id "
        "WHERE rh.engine_version = ? AND m.status = 'valid' "
        "AND rh.match_id <> ? GROUP BY rh.player_id",
        (engine_version, ref_match_id),
    ):
        prior[row["pid"]] = (row["n_rows"], row["n_perf"], row["s_perf"])

    # 3) Önceki anın score'ları: oynamayanlarda güncel score aynen geçerlidir;
    #    oynayanlarda referans maçın `*_before` değerleri + o maçsız P_avg.
    prev: dict[int, float] = dict(scores)
    played = conn.execute(
        "SELECT player_id, mu_before, sigma_before FROM rating_history "
        "WHERE match_id = ? AND engine_version = ?",
        (ref_match_id, engine_version),
    ).fetchall()
    for row in played:
        pid = row["player_id"]
        if pid not in prev:  # oyuncu silinmişse (pratikte olmaz) atla
            continue
        _n_rows, n_perf, s_perf = prior.get(pid, (0, 0, None))
        p_avg = (s_perf / n_perf) if (n_perf and s_perf is not None) else None
        prev[pid] = effective_score(
            engine,
            blend,
            Rating(mu=row["mu_before"], sigma=row["sigma_before"]),
            p_avg,
        )

    now_ranks = _ranks(scores.items())
    prev_ranks = _ranks(prev.items())
    return {
        pid: (prev_ranks[pid] - now_ranks[pid]) if pid in prior else None
        for pid in scores
    }
