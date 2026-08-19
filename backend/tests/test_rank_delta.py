"""Sıra değişimi `rank_delta` (api_contract §5, Teoman 2026-08-19).

Yöntem — BAĞIMSIZ ORACLE: "önceki sıralama"nın tanımı zaten leaderboard'un
kendisidir, o yüzden beklenen değer ikinci bir formülle değil, ucun GEÇMİŞTEKİ
çıktısıyla üretilir: önce N-1 maç ingest edilip leaderboard sırası kaydedilir,
sonra N. maç ingest edilir; `rank_delta` bu iki sıranın farkına eşit olmalıdır.
Böylece test, implementasyonun P_avg/mu_before aritmetiğini kopyalamaz.
"""
from __future__ import annotations

from conftest import make_roster_payload

M1_AT = "2026-08-10T20:00:00Z"
M2_AT = "2026-08-11T20:00:00Z"


def _players(client, n=15):
    return [
        client.post("/api/v1/players", json={"display_name": f"P{i:02d}"}).json()["id"]
        for i in range(n)
    ]


def _ingest(client, payload):
    resp = client.post("/api/v1/ingest/match", json=payload)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def _board(client):
    resp = client.get("/api/v1/leaderboard")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _order(board):
    """player_id → 0 tabanlı sıra."""
    return {p["id"]: i for i, p in enumerate(board)}


def _deltas(board):
    return {p["id"]: p["rank_delta"] for p in board}


def _scenario(client):
    """M1 (eski) + M2 (referans) — dört sınıfı birden üreten kurulum.

    ids[0..4]  : M1'i kazandı, M2'yi KAYBETTİ  → düşer
    ids[5..9]  : M1'i kaybetti, M2'de OYNAMADI → score'u sabit, sırası oynayabilir
    ids[10..14]: ilk maçları M2                → `null` (listeye yeni girdi)

    Döner: (ids, M2 öncesi sıralama, M2 sonrası leaderboard)
    """
    ids = _players(client)
    _ingest(client, make_roster_payload("m1", M1_AT, ids[0:5], ids[5:10], winner_team=100))
    before = _order(_board(client))
    _ingest(
        client,
        make_roster_payload(
            "m2", M2_AT, ids[0:3] + ids[10:12], ids[12:15] + ids[3:5], winner_team=200
        ),
    )
    return ids, before, _board(client)


# ── Temel tanım ─────────────────────────────────────────────────────────────

def test_delta_equals_previous_leaderboard_order(client):
    ids, before, board = _scenario(client)
    now = _order(board)
    deltas = _deltas(board)

    entrants = set(ids[10:15])  # ilk maçı M2 olanlar → karşılaştırılamaz
    for pid, delta in deltas.items():
        if pid in entrants:
            assert delta is None, f"{pid}: yeni giren oyuncuda null beklenir"
        else:
            assert delta == before[pid] - now[pid], f"{pid} sıra farkı tutmuyor"

    # Senaryo gerçekten hareket üretiyor mu (aksi hâlde "hep 0" döndüren bir
    # implementasyon da geçerdi)? "Değişmedi" hâli ayrı testte.
    values = [d for d in deltas.values() if d is not None]
    assert any(v > 0 for v in values), "yükselen oyuncu yok"
    assert any(v < 0 for v in values), "düşen oyuncu yok"
    # Sıra permütasyonu: toplam yer değişimi sıfır toplamlıdır.
    assert sum(before[p] - now[p] for p in before) == 0


def test_unchanged_rank_is_zero(client):
    """Aynı sonuç tekrarlanırsa kimse yer değiştirmez → hepsi 0 (null değil)."""
    ids = _players(client, n=10)
    _ingest(client, make_roster_payload("m1", M1_AT, ids[0:5], ids[5:10], winner_team=100))
    before = _order(_board(client))
    _ingest(client, make_roster_payload("m2", M2_AT, ids[0:5], ids[5:10], winner_team=100))
    board = _board(client)
    assert _order(board) == before
    assert set(_deltas(board).values()) == {0}


def test_up_is_positive_and_down_is_negative(client):
    ids, before, board = _scenario(client)
    now = _order(board)
    deltas = _deltas(board)
    # M2'yi kaybedenler (ids[0..2]) düşer, kazananlar (ids[3..4]) yükselir.
    for pid in ids[0:3]:
        assert deltas[pid] == before[pid] - now[pid]
        assert deltas[pid] < 0
    for pid in ids[3:5]:
        assert deltas[pid] == before[pid] - now[pid]
        assert deltas[pid] > 0


def test_non_participant_rank_can_change(client):
    """O maçta oynamayan oyuncunun score'u değişmez ama SIRASI değişebilir."""
    ids, before, board = _scenario(client)
    now = _order(board)
    deltas = _deltas(board)
    outsiders = ids[5:10]  # score'ları sabit (ayrı testte kanıtlı)
    moved = [p for p in outsiders if deltas[p] != 0]
    assert moved, "senaryo bozuldu: oynamayan hiçbir oyuncunun sırası değişmemiş"
    for pid in outsiders:
        assert deltas[pid] == before[pid] - now[pid]


def test_outsider_score_unchanged_but_delta_reported(client):
    ids = _players(client)
    _ingest(client, make_roster_payload("m1", M1_AT, ids[0:5], ids[5:10], winner_team=100))
    score_before = {p["id"]: p["rating"]["score"] for p in _board(client)}
    _ingest(
        client,
        make_roster_payload(
            "m2", M2_AT, ids[0:3] + ids[10:12], ids[12:15] + ids[3:5], winner_team=200
        ),
    )
    board = _board(client)
    score_now = {p["id"]: p["rating"]["score"] for p in board}
    deltas = _deltas(board)
    for pid in ids[5:10]:
        assert score_now[pid] == score_before[pid]
        assert deltas[pid] is not None  # rating satırı var → karşılaştırılabilir


# ── null halleri ────────────────────────────────────────────────────────────

def test_all_null_when_no_valid_match(client):
    _players(client, n=4)
    board = _board(client)
    assert len(board) == 4
    assert all(p["rank_delta"] is None for p in board)


def test_new_entrant_is_null(client):
    ids, _before, board = _scenario(client)
    deltas = _deltas(board)
    for pid in ids[10:15]:
        assert deltas[pid] is None


def test_first_ever_match_all_participants_null(client):
    ids = _players(client, n=10)
    _ingest(client, make_roster_payload("m1", M1_AT, ids[0:5], ids[5:10]))
    assert all(d is None for d in _deltas(_board(client)).values())


def test_matchless_player_is_null(client):
    """Hiç maçı olmayan oyuncunun önceki anda da rating satırı yoktur."""
    ids = _players(client, n=11)
    _ingest(client, make_roster_payload("m1", M1_AT, ids[0:5], ids[5:10]))
    _ingest(
        client,
        make_roster_payload("m2", M2_AT, ids[0:5], ids[5:10], winner_team=200),
    )
    deltas = _deltas(_board(client))
    assert deltas[ids[10]] is None
    assert all(deltas[p] is not None for p in ids[0:10])


# ── Referans anın seçimi ────────────────────────────────────────────────────

def test_roulette_match_does_not_move_reference(client):
    """Rulet maçı rating dışıdır → referans an (ve deltalar) değişmez."""
    ids, _before, board = _scenario(client)
    expected = _deltas(board)

    # 10 kişilik rulet oturumu + eşleşen ingest: played_at M2'den SONRA.
    assignments = [
        {
            "player_id": pid,
            "team": 100 if i < 5 else 200,
            "position": ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"][i % 5],
            "champion": f"Champ{i}",
            "item_ids": [1000 + 2 * i, 1001 + 2 * i],
        }
        for i, pid in enumerate(ids[0:10])
    ]
    resp = client.post("/api/v1/roulette", json={"assignments": assignments})
    assert resp.status_code == 201, resp.text
    _ingest(
        client,
        make_roster_payload(
            "rlt", "2026-08-17T20:00:00Z", ids[0:5], ids[5:10], winner_team=100
        ),
    )
    assert _deltas(_board(client)) == expected


def test_void_of_last_match_moves_reference(client):
    """Son maç void edilirse referans an bir önceki maça kayar."""
    ids = _players(client)
    _ingest(client, make_roster_payload("m1", M1_AT, ids[0:5], ids[5:10], winner_team=100))
    after_m1 = _deltas(_board(client))
    body = _ingest(
        client,
        make_roster_payload(
            "m2", M2_AT, ids[0:3] + ids[10:12], ids[12:15] + ids[3:5], winner_team=200
        ),
    )
    assert _deltas(_board(client)) != after_m1

    resp = client.post(f"/api/v1/matches/{body['match_id']}/void")
    assert resp.status_code == 200, resp.text
    assert _deltas(_board(client)) == after_m1


# ── Determinizm ─────────────────────────────────────────────────────────────

def test_replay_keeps_rank_delta_identical(client):
    _ids, _before, board = _scenario(client)
    resp = client.post("/api/v1/admin/replay")
    assert resp.status_code == 200, resp.text
    assert _board(client) == board


def test_repeated_calls_are_stable(client):
    _ids, _before, board = _scenario(client)
    assert _board(client) == board


# ── Şekil ───────────────────────────────────────────────────────────────────

def test_rank_delta_is_int_or_null_and_only_on_leaderboard(client):
    _scenario(client)
    for p in _board(client):
        assert "rank_delta" in p
        assert p["rank_delta"] is None or isinstance(p["rank_delta"], int)
        assert isinstance(p["rating"]["score"], float)
    # GET /players şekli DEĞİŞMEZ (api_contract §2'de rank_delta yoktur).
    for p in client.get("/api/v1/players").json():
        assert "rank_delta" not in p


def test_leaderboard_still_sorted_by_score(client):
    """Sıralama kuralı değişmedi: score azalan, eşitlikte küçük id üstte."""
    ids = _players(client, n=4)
    board = _board(client)  # hiç maç yok → hepsi eşit score
    assert [p["id"] for p in board] == ids
    _scenario(client)
    scores = [p["rating"]["score"] for p in _board(client)]
    assert scores == sorted(scores, reverse=True)
