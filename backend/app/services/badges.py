"""Oyuncu rozetleri (api_contract §2 "Rozetler"; katalog GÖREV 24'te 27'ye çıktı).

SALT-OKUR gösterim katmanıdır: hiçbir tablo yazılmaz, hiçbir şema/migration
eklenmez, rating hesabına etkisi yoktur. Her rozet mevcut `matches` /
`match_participants` / `rating_history` (+ rulet üçlüsü için `roulette_*`)
satırlarından türetilir.

## Toplu çekirdek (GÖREV 24)
`GET /badges` tüm oyuncuların rozetlerini ister; oyuncu başına ayrı sorgu naif
olurdu. Bu yüzden TEK doğruluk noktası `compute_badges`: valid maçları ve TÜM
katılımcılarını iki sorguda okur, kronolojik TEK geçişte bütün oyuncuların
sayaçlarını birlikte doldurur (maç bazlı ortak hesaplar — rekor tabloları, MVP,
bench/tragic, comeback, koridor düelloları — maç başına BİR kez yapılır ve o
maçın 10 oyuncusu için paylaşılır). `GET /players/{id}/badges` de aynı
çekirdeği çağırır; rozet mantığı İKİ KEZ YAZILMAZ.

## Determinizm (api_contract §2)
Kronoloji gerektiren her rozet maçları `ratings.replay_order_by` ile sıralar —
replay'in sort-key'i burada KOPYALANMAZ, paylaşılır. Hiçbir tanım `now()`,
rastgelelik ya da İLERİYE BAKMA kullanmaz: rol rekoru ve kişisel rekorlar
MAÇ-ÖNCESİ snapshot'la karşılaştırılır, snapshot maç işlendikten sonra
güncellenir. "Gece" tanımı duvar saati değil `played_at - 6 saat`in tarihidir
(SQLite `date(played_at,'-6 hours')`, UTC). Bu yüzden `POST /admin/replay`
sonrası yanıt bit-bit aynı kalır.

perf_score bağımlı rozetler AKTİF engine'in `rating_history` satırlarını HAM
(yuvarlanmamış) okur — backend perf HESAPLAMAZ; yuvarlama yalnız yanıt
katmanındadır.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from rating import ROLES

from .ratings import replay_order_by
from .roulette import assignment_bought


@dataclass(frozen=True)
class BadgeDef:
    """Katalog kaydı (api_contract §2 `GET /badges`).

    `id` görsel dosya adıdır (`webui/assets/badges/<id>.png`) ve sıra
    DONDURULMUŞTUR — yeni rozet yalnız SONA eklenir (badges/rozetler.md).
    """

    id: int
    key: str
    cls: str  # record|role|personal|narrative|streak|relational|identity|milestone|roulette
    source: str  # valid | roulette
    tiered: bool
    one_time: bool


# api_contract §2: yanıt sırası SABİT katalog sırasıdır (badges/rozetler.md ID'leri).
CATALOG: tuple[BadgeDef, ...] = (
    BadgeDef(1, "mvp", "record", "valid", True, False),
    BadgeDef(2, "vision", "record", "valid", True, False),
    BadgeDef(3, "damage", "record", "valid", True, False),
    BadgeDef(4, "cs_per_min", "record", "valid", True, False),
    BadgeDef(5, "gold", "record", "valid", True, False),
    BadgeDef(6, "role_duel", "role", "valid", True, False),
    BadgeDef(7, "role_record", "role", "valid", False, False),
    BadgeDef(8, "pr_perf", "personal", "valid", False, False),
    BadgeDef(9, "pr_damage", "personal", "valid", False, False),
    BadgeDef(10, "kill_20", "narrative", "valid", False, False),
    BadgeDef(11, "kda_10", "narrative", "valid", False, False),
    BadgeDef(12, "deathless", "narrative", "valid", False, False),
    BadgeDef(13, "comeback", "narrative", "valid", False, False),
    BadgeDef(14, "tragic_hero", "narrative", "valid", False, False),
    BadgeDef(15, "marathon_5", "narrative", "valid", False, False),
    BadgeDef(16, "win_streak_3", "streak", "valid", False, False),
    BadgeDef(17, "lose_streak_3", "streak", "valid", False, False),
    BadgeDef(18, "bench_2", "streak", "valid", False, False),
    BadgeDef(19, "nemesis_6", "relational", "valid", False, True),
    BadgeDef(20, "duo_6", "relational", "valid", False, True),
    BadgeDef(21, "versatile", "identity", "valid", False, True),
    BadgeDef(22, "veteran_10", "milestone", "valid", False, True),
    BadgeDef(23, "veteran_20", "milestone", "valid", False, True),
    BadgeDef(24, "veteran_50", "milestone", "valid", False, True),
    BadgeDef(25, "roulette_complete", "roulette", "roulette", False, False),
    BadgeDef(26, "roulette_winner", "roulette", "roulette", False, False),
    BadgeDef(27, "gambler", "roulette", "roulette", False, True),
)

BADGE_KEYS: tuple[str, ...] = tuple(d.key for d in CATALOG)
BADGE_DEFS: dict[str, BadgeDef] = {d.key: d for d in CATALOG}

# api_contract §2 "Kademe": yalnız bu 6 rozet kademelidir.
TIERED_KEYS = frozenset(d.key for d in CATALOG if d.tiered)

# `best_match_id`/`best_value` yalnız ölçülebilir değeri olan sınıflarda.
BEST_VALUE_CLASSES = frozenset(("record", "role", "personal"))
BEST_VALUE_KEYS = frozenset(
    d.key for d in CATALOG if d.cls in BEST_VALUE_CLASSES
)

# Rekor rozetleri: rozet anahtarı → match_participants stat kolonu.
# Kural aynı: maçtaki 10 oyuncu içinde en yüksek, NULL aday değil,
# EŞİTLİKTE eşit olan herkes alır.
RECORD_STATS = {
    "vision": "vision_score",
    "damage": "damage_to_champs",
    "gold": "gold",
}

# Blok rozetleri: tamamlanan her N'lik ardışık blok 1 rozet (bloklar ayrık).
WIN_STREAK_BLOCK = 3  # GÖREV 24: 5 → 3 (en uzun seri 4'tü, rozet ÖLÜYDÜ)
LOSE_STREAK_BLOCK = 3  # GÖREV 24 YENİ: win_streak'in aynası
BENCH_BLOCK = 2  # GÖREV 24: 3 → 2

# Eşik rozetleri: valid maç sayısı; her biri tek seferlik ve bağımsız.
VETERAN_THRESHOLDS = {"veteran_10": 10, "veteran_20": 20, "veteran_50": 50}

# gambler (GÖREV 23): roulette_winner sayısı eşiği — tek seferlik.
GAMBLER_THRESHOLD = 5

# GÖREV 24 eşikleri (kalibrasyon: CHANGE_REQUESTS 2026-08-19).
ROLE_DUEL_RATIO = 1.5  # kendi rolündeki rakibin >= 1.5 katı perf
ROLE_RECORD_MIN_PRIOR = 10  # o rolde en az 10 önceki karşılaştırılabilir slot
PERSONAL_RECORD_MIN_PRIOR = 5  # kişisel rekor: en az 5 önceki hesaplanabilir maç
KILL_THRESHOLD = 20
KDA_THRESHOLD = 10.0
MARATHON_MIN_MATCHES = 5
RELATIONAL_THRESHOLD = 6  # nemesis_6 / duo_6

# Kademe eşikleri (api_contract §2 "Kademe"): oran + en az 8 maç.
TIER_SILVER_RATE = 0.20
TIER_GOLD_RATE = 0.32
TIER_MIN_MATCHES = 8

# `progress` tanımlı sınıflar (kilometre, kimlik, ilişkisel, blok, gambler);
# maç-anı koşullu sınıflarda (rekor, anlatısal, kişisel, rol) progress YOKTUR.
PROGRESS_TARGETS = {
    "win_streak_3": WIN_STREAK_BLOCK,
    "lose_streak_3": LOSE_STREAK_BLOCK,
    "bench_2": BENCH_BLOCK,
    "nemesis_6": RELATIONAL_THRESHOLD,
    "duo_6": RELATIONAL_THRESHOLD,
    "versatile": len(ROLES),
    "veteran_10": 10,
    "veteran_20": 20,
    "veteran_50": 50,
    "gambler": GAMBLER_THRESHOLD,
}

TEAM_SIZE = 5

_SECONDS_PER_MINUTE = 60.0


# ---------------------------------------------------------------------------
# Oyuncu durumu
# ---------------------------------------------------------------------------
class _PlayerState:
    """Bir oyuncunun rozet sayaçları + kronolojik yürüyüş durumu.

    `award` kronolojik sırada çağrıldığı için `last_match` doğal olarak rozeti
    SON kazandıran maçtır (blok rozetinde bloğun son maçı, eşik rozetinde eşiği
    tamamlayan maç). `best_*` yalnız ölçülebilir sınıflarda dolar ve KESİN
    aşmayla güncellenir → eşitlikte replay sırasında İLK gelen maç kalır.
    """

    __slots__ = (
        "counts", "last_match", "best_match", "best_value",
        "matches_played", "win_streak", "lose_streak", "bench_streak",
        "roles", "nights", "wins_vs", "wins_with",
        "pr_max", "pr_count", "roulette_winners",
    )

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.last_match: dict[str, int] = {}
        self.best_match: dict[str, int] = {}
        self.best_value: dict[str, float] = {}
        self.matches_played = 0
        self.win_streak = 0
        self.lose_streak = 0
        self.bench_streak = 0
        self.roles: set[str] = set()
        # gece (date(played_at,'-6 hours')) → o gecenin maç id'leri, kronolojik
        self.nights: dict[str, list[int]] = {}
        self.wins_vs: dict[int, int] = {}  # rakip player_id → galibiyet
        self.wins_with: dict[int, int] = {}  # takım arkadaşı → birlikte galibiyet
        self.pr_max: dict[str, float] = {}  # kişisel rekor metriği → en iyi değer
        self.pr_count: dict[str, int] = {}  # metriği hesaplanabilir maç sayısı
        self.roulette_winners = 0

    def award(self, key: str, match_id: int, value: float | None = None) -> None:
        self.counts[key] = self.counts.get(key, 0) + 1
        self.last_match[key] = match_id
        if value is None or key not in BEST_VALUE_KEYS:
            return
        best = self.best_value.get(key)
        if best is None or value > best:
            self.best_value[key] = value
            self.best_match[key] = match_id

    def has(self, key: str) -> bool:
        return key in self.counts

    def count(self, key: str) -> int:
        return self.counts.get(key, 0)


class _States(dict):
    """player_id → _PlayerState (ilk erişimde oluşturur)."""

    def state(self, player_id: int) -> _PlayerState:
        st = self.get(player_id)
        if st is None:
            st = _PlayerState()
            self[player_id] = st
        return st


# ---------------------------------------------------------------------------
# Veri yükleme (TOPLU: oyuncu süzgeci YOK)
# ---------------------------------------------------------------------------
def _valid_matches(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """TÜM valid maçlar, replay sort-key'iyle kronolojik.

    `night`: api_contract §2 marathon_5 tanımı — `played_at` (UTC) eksi 6 saatin
    TARİHİ (sabaha kadar süren oturum tek gece sayılır). Hesap SQLite'ta yapılır
    (tek yerde, deterministik); ayrıştırılamayan `played_at` NULL gece verir ve
    o maç marathon dışında kalır.
    """
    return conn.execute(
        "SELECT m.id AS match_id, m.duration_s, m.winner_team,"
        " date(m.played_at, '-6 hours') AS night "
        f"FROM matches m WHERE m.status = 'valid' {replay_order_by('m')}"
    ).fetchall()


def _valid_participants(
    conn: sqlite3.Connection, engine_version: str
) -> dict[int, list[sqlite3.Row]]:
    """match_id → o maçın TÜM katılımcıları (stat + aktif engine perf_score).

    `rating_history` LEFT JOIN'dir: satırı olmayan katılımcının perf'i NULL
    sayılır (aday değildir), maç yine de değerlendirilir.
    """
    rows = conn.execute(
        "SELECT mp.match_id, mp.player_id, mp.team, mp.position,"
        " mp.kills, mp.deaths, mp.assists, mp.gold, mp.cs,"
        " mp.damage_to_champs, mp.vision_score, rh.perf_score "
        "FROM match_participants mp "
        "JOIN matches m ON m.id = mp.match_id "
        "LEFT JOIN rating_history rh ON rh.match_id = mp.match_id"
        " AND rh.player_id = mp.player_id AND rh.engine_version = ? "
        "WHERE m.status = 'valid' "
        "ORDER BY mp.match_id, mp.id",
        (engine_version,),
    ).fetchall()
    by_match: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        by_match.setdefault(row["match_id"], []).append(row)
    return by_match


def _roulette_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """TÜM rulet maçlarının katılımcı+atama satırları, kronolojik.

    Kaynak yalnız `status='roulette'` + `linked` oturum maçlarıdır (katalogdaki
    TEK istisna — rulet maçları valid süzgeçli diğer tüm rozetlerin zaten
    dışındadır). Linked oturumda oyuncu kümesi maçınkiyle birebir aynı
    olduğundan atama her zaman vardır.
    """
    return conn.execute(
        "SELECT m.id AS match_id, m.winner_team, mp.player_id, mp.team,"
        " mp.items_json, ra.item_ids_json "
        "FROM matches m "
        "JOIN match_participants mp ON mp.match_id = m.id "
        "JOIN roulette_sessions rs ON rs.match_id = m.id"
        " AND rs.status = 'linked' "
        "JOIN roulette_assignments ra ON ra.session_id = rs.id"
        " AND ra.player_id = mp.player_id "
        f"WHERE m.status = 'roulette' {replay_order_by('m')}"
    ).fetchall()


# ---------------------------------------------------------------------------
# Maç bazlı ortak hesaplar (maç başına BİR kez; 10 oyuncu paylaşır)
# ---------------------------------------------------------------------------
def _mvp_key(row: sqlite3.Row) -> tuple:
    """MVP kırılımı: perf ↓ → kills ↓ → assists ↓ → deaths ↑ → player_id ↑.

    NULL k/d/a contract'ta kırılım girdisi olarak tanımlı değildir; burada EN
    KÖTÜ değer sayılır (kills/assists için -1'in altı, deaths için sonsuz), son
    anahtar player_id olduğu için sonuç her hâlükârda deterministiktir.
    """
    return (
        -row["perf_score"],
        -(row["kills"] if row["kills"] is not None else -1),
        -(row["assists"] if row["assists"] is not None else -1),
        row["deaths"] if row["deaths"] is not None else float("inf"),
        row["player_id"],
    )


def _mvp_player(participants: list[sqlite3.Row], winner_team: int) -> int | None:
    """Kazanan takımın en yüksek perf_score'lusu; perf'i NULL satır aday değil.

    Kazanan takımda hiç perf yoksa o maçta MVP yoktur.
    """
    candidates = [
        row
        for row in participants
        if row["team"] == winner_team and row["perf_score"] is not None
    ]
    if not candidates:
        return None
    return min(candidates, key=_mvp_key)["player_id"]


def _sole_extreme(
    participants: list[sqlite3.Row], team: int, highest: bool
) -> int | None:
    """Takımın TEK BAŞINA en yüksek/en düşük perf'lisi (bench_2 / tragic_hero).

    Karşılaştırılabilirlik şartı: takımın 5 oyuncusunun da perf'i non-null
    olmalı. Şart sağlanmıyorsa ya da uçta eşitlik varsa None döner (kırılım
    UYGULANMAZ — bench_2 için bu seriyi kıran durumla aynı sonuçtur).
    """
    own = [row for row in participants if row["team"] == team]
    if len(own) != TEAM_SIZE:
        return None
    if any(row["perf_score"] is None for row in own):
        return None
    pick = max if highest else min
    target = pick(row["perf_score"] for row in own)
    at_target = [row["player_id"] for row in own if row["perf_score"] == target]
    if len(at_target) > 1:
        return None
    return at_target[0]


def _stat_values(
    participants: list[sqlite3.Row], column: str
) -> dict[int, float]:
    """player_id → stat değeri; NULL statlılar dışarıda (aday değil)."""
    return {
        row["player_id"]: row[column]
        for row in participants
        if row[column] is not None
    }


def _cs_per_min_values(
    participants: list[sqlite3.Row], duration_s: int | None
) -> dict[int, float]:
    """player_id → cs/dk; `duration_s` yok ya da <= 0 ise maç dışıdır.

    Bölen tüm katılımcılarda aynı olduğundan eşitlik karşılaştırması float
    gürültüsünden etkilenmez (eşit cs → bit-bit eşit cs/dk).
    """
    if duration_s is None or duration_s <= 0:
        return {}
    minutes = duration_s / _SECONDS_PER_MINUTE
    return {
        row["player_id"]: row["cs"] / minutes
        for row in participants
        if row["cs"] is not None
    }


def _record_tables(
    participants: list[sqlite3.Row], duration_s: int | None
) -> dict[str, dict[int, float]]:
    """Rekor rozeti → {player_id: değer} (maç başına bir kez kurulur)."""
    tables = {
        key: _stat_values(participants, column)
        for key, column in RECORD_STATS.items()
    }
    tables["cs_per_min"] = _cs_per_min_values(participants, duration_s)
    return tables


def _leaders(values: dict[int, float]) -> set[int]:
    """Maçın en yüksek değerli oyuncuları — EŞİTLİKTE hepsi rozeti alır."""
    if not values:
        return set()
    top = max(values.values())
    return {pid for pid, value in values.items() if value == top}


def _is_comeback(participants: list[sqlite3.Row], winner_team: int) -> bool:
    """İki takımın da 5 gold'u non-null + KAZANANIN toplamı küçük mü?

    Oyuncu bazlı ek şart (kazanan takımda olmak) çağırandadır.
    """
    totals = {100: 0, 200: 0}
    sizes = {100: 0, 200: 0}
    for row in participants:
        if row["team"] not in totals or row["gold"] is None:
            return False
        totals[row["team"]] += row["gold"]
        sizes[row["team"]] += 1
    if sizes[100] != TEAM_SIZE or sizes[200] != TEAM_SIZE:
        return False
    loser_team = 200 if winner_team == 100 else 100
    return totals[winner_team] < totals[loser_team]


def _role_duel_ratios(participants: list[sqlite3.Row]) -> dict[int, float]:
    """player_id → kendi rolündeki rakibine göre perf oranı (role_duel).

    Şartlar (api_contract §2): o maçta ilgili rolde KARŞI takımlarda tam 2
    non-NULL `position` slotu olmalı (aksi hâlde o maç×rol bu rozetin
    dışındadır; diğer roller etkilenmez), iki oyuncunun da perf'i non-NULL
    olmalı, rakip perf'i <= 0 ise oran tanımsızdır → kayıt yok.
    """
    by_role: dict[str, list[sqlite3.Row]] = {}
    for row in participants:
        if row["position"] is not None:
            by_role.setdefault(row["position"], []).append(row)
    ratios: dict[int, float] = {}
    for pair in by_role.values():
        if len(pair) != 2:
            continue
        first, second = pair
        if first["team"] == second["team"]:
            continue
        for me, opponent in ((first, second), (second, first)):
            if me["perf_score"] is None or opponent["perf_score"] is None:
                continue
            if opponent["perf_score"] <= 0:
                continue
            ratios[me["player_id"]] = me["perf_score"] / opponent["perf_score"]
    return ratios


def _kda(row: sqlite3.Row) -> float | None:
    """(kills + assists) / max(1, deaths); k/d/a üçü de non-NULL olmalı."""
    if row["kills"] is None or row["deaths"] is None or row["assists"] is None:
        return None
    return (row["kills"] + row["assists"]) / max(1, row["deaths"])


def _damage_per_min(row: sqlite3.Row, duration_s: int | None) -> float | None:
    """pr_damage metriği: damage_to_champs / (duration_s/60); yoksa None."""
    if row["damage_to_champs"] is None or duration_s is None or duration_s <= 0:
        return None
    return row["damage_to_champs"] / (duration_s / _SECONDS_PER_MINUTE)


# ---------------------------------------------------------------------------
# Kronolojik tek geçiş
# ---------------------------------------------------------------------------
def _personal_record(
    st: _PlayerState, key: str, value: float | None, match_id: int
) -> None:
    """Kişisel rekor sınıfı (pr_perf / pr_damage), api_contract §2.

    Kesin aşma (`>`) yeter (marj yok), ancak en az PERSONAL_RECORD_MIN_PRIOR
    önceki HESAPLANABİLİR maç gerekir — aksi hâlde ilk maçlar otomatik rekor
    olurdu. Metriği hesaplanamayan maç ne rekor adayıdır ne de sayaca girer.
    Karşılaştırma MAÇ-ÖNCESİ snapshot'ladır: snapshot bu maçtan SONRA güncellenir.
    """
    if value is None:
        return
    best = st.pr_max.get(key)
    if st.pr_count.get(key, 0) >= PERSONAL_RECORD_MIN_PRIOR and (
        best is None or value > best
    ):
        st.award(key, match_id, value)
    st.pr_count[key] = st.pr_count.get(key, 0) + 1
    if best is None or value > best:
        st.pr_max[key] = value


def _award_relational(
    st: _PlayerState,
    counters: dict[int, int],
    others: list[int],
    key: str,
    match_id: int,
) -> None:
    """nemesis_6 / duo_6: aynı rakibe/arkadaşa karşı N galibiyet — TEK SEFERLİK.

    `last_match_id` eşiği İLK dolduran maçtır (aynı maçta birden çok kişi eşiği
    doldurursa maç aynıdır, rozet bir kez verilir).
    """
    reached = False
    for other in others:
        counters[other] = counters.get(other, 0) + 1
        if counters[other] >= RELATIONAL_THRESHOLD:
            reached = True
    if reached and not st.has(key):
        st.award(key, match_id)


def compute_badges(
    conn: sqlite3.Connection, engine_version: str
) -> dict[int, _PlayerState]:
    """TÜM oyuncuların rozetleri — tek toplu geçiş (player_id → _PlayerState).

    Valid maçlar kronolojik yürünür; her maçta ortak hesaplar (rekor tabloları,
    MVP, bench/tragic uçları, comeback, koridor düelloları) BİR kez yapılır ve
    o maçın katılımcıları için paylaşılır. Rol rekoru snapshot'ı maç bittikten
    SONRA güncellenir (ileriye bakma yasağı). Rulet üçlüsü ayrı geçiştedir:
    kaynağı yalnız `status='roulette'` maçlardır, valid sayaçlarına dokunmaz.
    """
    states = _States()
    matches = _valid_matches(conn)
    by_match = _valid_participants(conn, engine_version)

    # role_record için grup snapshot'ı: rol → (karşılaştırılabilir slot sayısı,
    # görülmüş en yüksek perf). MAÇ-ÖNCESİ okunur, maç sonrası yazılır.
    role_prior_count: dict[str, int] = {}
    role_prior_max: dict[str, float] = {}

    for match in matches:
        match_id = match["match_id"]
        duration_s = match["duration_s"]
        winner_team = match["winner_team"]
        loser_team = 200 if winner_team == 100 else 100
        participants = by_match.get(match_id, [])

        records = _record_tables(participants, duration_s)
        leaders = {key: _leaders(values) for key, values in records.items()}
        mvp_id = _mvp_player(participants, winner_team)
        tragic_id = _sole_extreme(participants, loser_team, highest=True)
        bench_by_team = {
            team: _sole_extreme(participants, team, highest=False)
            for team in (100, 200)
        }
        comeback = _is_comeback(participants, winner_team)
        duels = _role_duel_ratios(participants)
        by_team: dict[int, list[int]] = {100: [], 200: []}
        for row in participants:
            if row["team"] in by_team:
                by_team[row["team"]].append(row["player_id"])

        for row in participants:
            player_id = row["player_id"]
            st = states.state(player_id)
            st.matches_played += 1
            won = row["team"] == winner_team
            perf = row["perf_score"]

            # --- Rekor rozetleri (kademeli sınıf) ---
            if player_id == mvp_id:
                st.award("mvp", match_id, perf)
            for key, winners in leaders.items():
                if player_id in winners:
                    st.award(key, match_id, records[key][player_id])

            # --- Rol sınıfı ---
            ratio = duels.get(player_id)
            if ratio is not None and ratio >= ROLE_DUEL_RATIO:
                st.award("role_duel", match_id, ratio)
            position = row["position"]
            if position is not None and perf is not None:
                prior_best = role_prior_max.get(position)
                if (
                    role_prior_count.get(position, 0) >= ROLE_RECORD_MIN_PRIOR
                    and prior_best is not None
                    and perf > prior_best
                ):
                    st.award("role_record", match_id, perf)

            # --- Kişisel rekorlar ---
            _personal_record(st, "pr_perf", perf, match_id)
            _personal_record(
                st, "pr_damage", _damage_per_min(row, duration_s), match_id
            )

            # --- Anlatısal rozetler ---
            if row["kills"] is not None and row["kills"] >= KILL_THRESHOLD:
                st.award("kill_20", match_id)
            kda = _kda(row)
            if kda is not None and kda >= KDA_THRESHOLD:
                st.award("kda_10", match_id)
            if row["deaths"] == 0:
                st.award("deathless", match_id)
            if won and comeback:
                st.award("comeback", match_id)
            if player_id == tragic_id:
                st.award("tragic_hero", match_id)
            if match["night"] is not None:
                st.nights.setdefault(match["night"], []).append(match_id)

            # --- Blok rozetleri (ayrık bloklar; kronoloji şart) ---
            if won:
                st.lose_streak = 0
                st.win_streak += 1
                if st.win_streak == WIN_STREAK_BLOCK:
                    st.award("win_streak_3", match_id)
                    st.win_streak = 0
            else:
                st.win_streak = 0
                st.lose_streak += 1
                if st.lose_streak == LOSE_STREAK_BLOCK:
                    st.award("lose_streak_3", match_id)
                    st.lose_streak = 0

            if player_id == bench_by_team.get(row["team"]):
                st.bench_streak += 1
                if st.bench_streak == BENCH_BLOCK:
                    st.award("bench_2", match_id)
                    st.bench_streak = 0
            else:
                st.bench_streak = 0

            # --- İlişkisel rozetler (tek seferlik) ---
            if won:
                _award_relational(
                    st, st.wins_vs, by_team[loser_team], "nemesis_6", match_id
                )
                _award_relational(
                    st,
                    st.wins_with,
                    [pid for pid in by_team[winner_team] if pid != player_id],
                    "duo_6",
                    match_id,
                )

            # --- Kimlik / kilometre taşları ---
            if position is not None:
                st.roles.add(position)
            if len(st.roles) >= len(ROLES) and not st.has("versatile"):
                st.award("versatile", match_id)
            for key, threshold in VETERAN_THRESHOLDS.items():
                if st.matches_played == threshold:
                    st.award(key, match_id)

        # Rol rekoru snapshot'ı maç İŞLENDİKTEN SONRA güncellenir: aynı maçtaki
        # iki slot da maç-öncesi rekorla karşılaştırılır (ileriye bakma yasak).
        for row in participants:
            position = row["position"]
            perf = row["perf_score"]
            if position is None or perf is None:
                continue
            role_prior_count[position] = role_prior_count.get(position, 0) + 1
            prior_best = role_prior_max.get(position)
            if prior_best is None or perf > prior_best:
                role_prior_max[position] = perf

    # --- marathon_5: gece bazlı, geçiş sonrası (nitelikli her gece 1 rozet) ---
    # `nights` kronolojik eklendiği için sıra doğaldır; last_match_id o gecenin
    # replay sırasındaki SON maçıdır.
    for st in states.values():
        for night_matches in st.nights.values():
            if len(night_matches) >= MARATHON_MIN_MATCHES:
                st.award("marathon_5", night_matches[-1])

    _award_roulette_badges(conn, states)
    return states


def _award_roulette_badges(
    conn: sqlite3.Connection, states: _States
) -> None:
    """roulette_complete / roulette_winner / gambler (api_contract §2, GÖREV 23).

    `bought` mantığı maç yanıtındaki `roulette` alanıyla BİREBİR aynıdır
    (roulette.assignment_bought — tek doğruluk noktası): atanan 2 eşyanın
    ikisi de final envanterde, karşılaştırma KÜME bazlı; `items` NULL ise
    doğrulanamaz → rozet yok. winner = complete + oyuncunun MAÇTAKİ takımı
    kazanan; gambler = 5. winner'ı tamamlayan maçta tek seferlik.
    """
    for row in _roulette_rows(conn):
        bought = assignment_bought(
            json.loads(row["item_ids_json"]), row["items_json"]
        )
        if bought is not True:
            continue
        st = states.state(row["player_id"])
        st.award("roulette_complete", row["match_id"])
        if row["team"] == row["winner_team"]:
            st.award("roulette_winner", row["match_id"])
            st.roulette_winners += 1
            if st.roulette_winners == GAMBLER_THRESHOLD:
                st.award("gambler", row["match_id"])


# ---------------------------------------------------------------------------
# Yanıt katmanı (yuvarlama YALNIZ burada)
# ---------------------------------------------------------------------------
def _tier(count: int, rate: float | None, matches_played: int) -> str | None:
    """bronz/gümüş/altın (api_contract §2 "Kademe"); kazanılmamışsa None.

    Gümüş ve altın için EK ŞART `matches_played >= 8` — az oynayanın tek
    rozetle altın olmaması için. Karşılaştırma HAM oranla yapılır.
    """
    if count <= 0 or rate is None:
        return None
    if matches_played >= TIER_MIN_MATCHES:
        if rate >= TIER_GOLD_RATE:
            return "gold"
        if rate >= TIER_SILVER_RATE:
            return "silver"
    return "bronze"


def _next_tier_rate(tier: str | None) -> float | None:
    """Bir üst kademenin eşiği; altındaysa (`gold`) None."""
    if tier == "gold":
        return None
    if tier == "silver":
        return TIER_GOLD_RATE
    return TIER_SILVER_RATE  # bronz ya da henüz kazanılmamış


def _progress(st: _PlayerState, key: str) -> dict[str, int] | None:
    """`{"current","target"}` — yalnız ilerlemesi tanımlı sınıflarda."""
    target = PROGRESS_TARGETS.get(key)
    if target is None:
        return None
    if key == "versatile":
        current = len(st.roles)
    elif key == "win_streak_3":
        current = st.win_streak
    elif key == "lose_streak_3":
        current = st.lose_streak
    elif key == "bench_2":
        current = st.bench_streak
    elif key == "nemesis_6":
        current = max(st.wins_vs.values(), default=0)
    elif key == "duo_6":
        current = max(st.wins_with.values(), default=0)
    elif key == "gambler":
        current = st.count("roulette_winner")
    else:  # veteran_*
        current = st.matches_played
    return {"current": current, "target": target}


def _badge_entry(st: _PlayerState, definition: BadgeDef) -> dict:
    """Tek rozetin yanıt kaydı (api_contract §2 örneğiyle birebir alanlar)."""
    key = definition.key
    count = st.count(key)
    best_value = st.best_value.get(key)
    tier = rate = next_rate = None
    if definition.tiered:
        if st.matches_played > 0:
            rate = count / st.matches_played
        tier = _tier(count, rate, st.matches_played)
        next_rate = _next_tier_rate(tier)
    return {
        "key": key,
        "count": count,
        "last_match_id": st.last_match.get(key),
        "best_match_id": st.best_match.get(key),
        "best_value": None if best_value is None else round(best_value, 2),
        "tier": tier,
        "rate": None if rate is None else round(rate, 2),
        "next_tier_rate": next_rate,
        "progress": _progress(st, key),
    }


def _badge_list(st: _PlayerState, include_locked: bool) -> list[dict]:
    """Katalog sırasında rozet listesi; kilitliler yalnız istenirse."""
    return [
        _badge_entry(st, definition)
        for definition in CATALOG
        if include_locked or st.count(definition.key) > 0
    ]


def player_badges(
    conn: sqlite3.Connection,
    player_id: int,
    engine_version: str,
    include_locked: bool = False,
) -> dict | None:
    """Oyuncunun rozetleri (api_contract §2); bilinmeyen oyuncuda None.

    `include_locked=False` (varsayılan) yalnız `count > 0` rozetleri döndürür —
    mevcut yanıt şekli korunur; `True` katalogdaki 27 anahtarın hepsini döndürür
    (kilitli rozetin ilerlemesini göstermek için).
    """
    if (
        conn.execute(
            "SELECT 1 FROM players WHERE id = ?", (player_id,)
        ).fetchone()
        is None
    ):
        return None
    states = compute_badges(conn, engine_version)
    st = states.get(player_id) or _PlayerState()
    return {
        "player_id": player_id,
        "matches_played": st.matches_played,
        "badges": _badge_list(st, include_locked),
    }


def badge_catalog(conn: sqlite3.Connection, engine_version: str) -> dict:
    """`GET /badges` (api_contract §2): katalog + `holders` nadirliği.

    Salt-okur ve türetilmiştir; per-player hesapların SAF TOPLAMI olduğu için
    replay-deterministiktir. `roster_size` = en az 1 VALID maçı olan oyuncu
    sayısı (hiç oynamamış kayıt nadirliği şişirmesin). Roster boşken oran
    tanımsızdır → `holders_pct` NULL (yalnız rulet maçı olan oyuncu rozet
    taşıyabilir ama roster'a girmez).
    """
    states = compute_badges(conn, engine_version)
    roster_size = sum(1 for st in states.values() if st.matches_played > 0)
    badges = []
    for definition in CATALOG:
        holders = sum(1 for st in states.values() if st.count(definition.key) > 0)
        badges.append(
            {
                "id": definition.id,
                "key": definition.key,
                "class": definition.cls,
                "source": definition.source,
                "tiered": definition.tiered,
                "one_time": definition.one_time,
                "holders": holders,
                "holders_pct": (
                    round(holders * 100 / roster_size, 1) if roster_size else None
                ),
            }
        )
    return {"roster_size": roster_size, "badges": badges}
