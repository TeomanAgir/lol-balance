"""Çoklu grup (GÖREV 36) — grup profilleri, kalıcılık, otomatik yönlendirme.

Spec: docs/ingest_contract.md "Çoklu grup — collector tarafı". Backend'de grup = API
anahtarı; collector birden fazla grubun anahtarını saklar ve her maçı "oyuncularını
tanıyan" gruba gönderir. Payload şeması ve uçlar DEĞİŞMEZ.

Saklama biçimi (bilinçli seçimler):

- **İlk profil = `.env`'deki `API_KEY`.** `.env`'e DOKUNULMAZ; eski tek anahtarlı
  kurulum `groups.json` olmadan birebir eskisi gibi çalışır, sihirbaz yeniden açılmaz.
  İlk profil silinemez (anahtarı `--setup`/Ayarlar ile değişir), yeniden adlandırılabilir.
- **Ek profiller + etiketler + seçili grup** `app_dir()/groups.json`'dadır (exe-bitişiği
  kalıcı yol; `.env` gibi gitignore'lu). Dosya yalnız kullanıcı grup eklediğinde/
  adlandırdığında/seçtiğinde yazılır.
- Profil kimliği (`id`) etiketten ve anahtardan BAĞIMSIZ rastgele bir dizgedir: outbox
  kayıtları bu kimlikle eşlenir (yeniden adlandırma kayıtları etkilemez; silinen bir
  profilin kimliği yeni profile asla devredilmez).
- **Outbox:** ilk profilin kayıtları bugünkü `outbox/*.json` yerindedir (hedefsiz eski
  kayıtlar = ilk profil); ek profillerinkiler `outbox/groups/<id>/`. Hedef, kaydın
  dizinidir — böylece eski bir exe (yalnız `outbox/*.json`'a bakar) başka grubun kaydını
  YANLIŞ anahtarla asla göndermez.
- Anahtar değeri hiçbir `repr`/log satırına girmez (`GroupProfile.api_key` repr=False,
  ekranda `mask_key`).
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

import httpx

from .config import Config
from .i18n import msg
from .roster import KnownRoster, fetch_players, load_seed_roster, roster_from_players
from .sender import Sender, SendOutcome

log = logging.getLogger("collector.groups")

#: İlk profilin (.env API_KEY) sabit kimliği; hedefsiz outbox kayıtları buna aittir.
FIRST_PROFILE_ID = "default"
GROUPS_FILE_NAME = "groups.json"
GROUPS_FILE_VERSION = 1
#: Ek profillerin outbox kök dizini (`outbox/groups/<id>/`).
GROUP_OUTBOX_SUBDIR = "groups"
LABEL_MAX_LEN = 40
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


class GroupError(ValueError):
    """Kullanıcı girdisi hatası; `key` i18n anahtarıdır (arayüz `msg` ile gösterir)."""

    def __init__(self, key: str, **params: object):
        self.key = key
        self.params = params
        super().__init__(key)

    def message(self) -> str:
        return msg(self.key, **self.params)


def mask_key(api_key: str) -> str:
    """Ekranda gösterilecek maskeli anahtar (sihirbazın özetiyle aynı biçim)."""
    key = api_key or ""
    return key[:3] + "*" * max(0, len(key) - 3)


def default_label(number: int) -> str:
    return msg("groups.default_label", number=number)


@dataclass
class GroupProfile:
    id: str
    label: str
    api_key: str = field(repr=False)

    @property
    def is_first(self) -> bool:
        return self.id == FIRST_PROFILE_ID


@dataclass
class GroupSettings:
    """Profil listesi (sıra = profil sırası; ilk eleman HER ZAMAN ilk profil) + seçili grup."""

    profiles: list[GroupProfile]
    selected_id: str = FIRST_PROFILE_ID
    #: İlk profile kullanıcı ad verdi mi? (vermediyse etiket dile göre varsayılandır)
    first_label_custom: bool = False

    # --- erişim ---

    @property
    def first(self) -> GroupProfile:
        return self.profiles[0]

    @property
    def is_multi(self) -> bool:
        return len(self.profiles) > 1

    def ids(self) -> list[str]:
        return [profile.id for profile in self.profiles]

    def get(self, profile_id: str) -> Optional[GroupProfile]:
        return next((p for p in self.profiles if p.id == profile_id), None)

    @property
    def selected(self) -> GroupProfile:
        return self.get(self.selected_id) or self.first

    def label_of(self, profile_id: str) -> str:
        profile = self.get(profile_id)
        return profile.label if profile is not None else profile_id

    # --- düzenleme (hepsi doğrular; hata = GroupError) ---

    def next_default_label(self) -> str:
        used = {p.label.casefold() for p in self.profiles}
        number = 1
        while default_label(number).casefold() in used:
            number += 1
        return default_label(number)

    def _clean_label(self, label: str, *, ignore_id: Optional[str] = None) -> str:
        cleaned = " ".join((label or "").split())
        if not cleaned:
            raise GroupError("groups.error.label_empty")
        if len(cleaned) > LABEL_MAX_LEN:
            raise GroupError("groups.error.label_too_long", max=LABEL_MAX_LEN)
        for profile in self.profiles:
            if profile.id != ignore_id and profile.label.casefold() == cleaned.casefold():
                raise GroupError("groups.error.label_taken", label=cleaned)
        return cleaned

    def add(self, label: str, api_key: str) -> GroupProfile:
        key = (api_key or "").strip()
        if not key:
            raise GroupError("groups.error.key_empty")
        if any(p.api_key == key for p in self.profiles):
            raise GroupError("groups.error.key_taken")
        cleaned = self._clean_label(label)
        new_id = uuid.uuid4().hex[:12]
        while self.get(new_id) is not None:  # pratikte olmaz; yine de garanti
            new_id = uuid.uuid4().hex[:12]
        profile = GroupProfile(id=new_id, label=cleaned, api_key=key)
        self.profiles.append(profile)
        return profile

    def rename(self, profile_id: str, label: str) -> GroupProfile:
        profile = self.get(profile_id)
        if profile is None:
            raise GroupError("groups.error.unknown")
        profile.label = self._clean_label(label, ignore_id=profile_id)
        if profile.is_first:
            self.first_label_custom = True
        return profile

    def delete(self, profile_id: str) -> GroupProfile:
        profile = self.get(profile_id)
        if profile is None:
            raise GroupError("groups.error.unknown")
        if profile.is_first:
            raise GroupError("groups.error.first_not_deletable")
        self.profiles.remove(profile)
        if self.selected_id == profile_id:
            self.selected_id = FIRST_PROFILE_ID
        return profile

    def select(self, profile_id: str) -> GroupProfile:
        profile = self.get(profile_id)
        if profile is None:
            raise GroupError("groups.error.unknown")
        self.selected_id = profile_id
        return profile


# --------------------------------------------------------------------------- #
# Kalıcılık
# --------------------------------------------------------------------------- #


def groups_path(config: Config) -> Path:
    return config.groups_path


def load_groups(config: Config) -> GroupSettings:
    """`.env` anahtarı (ilk profil) + `groups.json` (varsa). Bozuk dosya akışı DURDURMAZ."""
    path = groups_path(config)
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("top level must be an object")
            data = loaded
        except (OSError, ValueError) as exc:
            log.warning("Could not read %s, using only the .env group: %s", path.name, exc)
            _set_aside(path)
            data = {}

    first_label = data.get("first_label")
    custom = isinstance(first_label, str) and bool(first_label.strip())
    profiles = [
        GroupProfile(
            id=FIRST_PROFILE_ID,
            label=" ".join(first_label.split()) if custom else default_label(1),
            api_key=config.api_key,
        )
    ]
    settings = GroupSettings(profiles=profiles, first_label_custom=custom)
    for raw in data.get("profiles") or []:
        if not isinstance(raw, dict):
            continue
        profile_id = str(raw.get("id") or "")
        key = str(raw.get("api_key") or "").strip()
        label = " ".join(str(raw.get("label") or "").split())
        if (
            not _ID_RE.match(profile_id)
            or profile_id == FIRST_PROFILE_ID
            or settings.get(profile_id) is not None
            or not key
            or any(p.api_key == key for p in settings.profiles)
        ):
            log.warning("Ignoring an invalid group entry in %s", path.name)
            continue
        settings.profiles.append(
            GroupProfile(id=profile_id, label=label or settings.next_default_label(), api_key=key)
        )
    selected = data.get("selected")
    if isinstance(selected, str) and settings.get(selected) is not None:
        settings.selected_id = selected
    return settings


def _set_aside(path: Path) -> None:
    """Okunamayan dosya silinmez: `.bad` uzantısıyla kenara alınır (anahtar kaybolmasın)."""
    try:
        path.replace(path.with_name(path.name + ".bad"))
    except OSError:
        pass


def save_groups(config: Config, settings: GroupSettings) -> Path:
    """Ek profilleri + etiketleri + seçimi yazar. İlk profilin ANAHTARI yazılmaz (.env'de)."""
    path = groups_path(config)
    body = {
        "version": GROUPS_FILE_VERSION,
        "selected": settings.selected_id,
        "first_label": settings.first.label if settings.first_label_custom else None,
        "profiles": [
            {"id": p.id, "label": p.label, "api_key": p.api_key}
            for p in settings.profiles
            if not p.is_first
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    log.info("Group settings saved (%d groups)", len(settings.profiles))
    return path


# --------------------------------------------------------------------------- #
# Profil başına config / outbox
# --------------------------------------------------------------------------- #


def group_outbox_root(config: Config) -> Path:
    return config.outbox_dir / GROUP_OUTBOX_SUBDIR


def profile_outbox_dir(config: Config, profile_id: str) -> Path:
    if profile_id == FIRST_PROFILE_ID:
        return config.outbox_dir
    return group_outbox_root(config) / profile_id


def profile_config(config: Config, profile: GroupProfile) -> Config:
    """Profilin anahtarı ve outbox'ıyla config kopyası (ilk profil = config'in kendisi)."""
    if profile.is_first:
        return config
    return replace(
        config,
        api_key=profile.api_key,
        outbox_dir=profile_outbox_dir(config, profile.id),
    )


def selected_profile_config(config: Config, settings: Optional[GroupSettings] = None) -> Config:
    """`backfill-positions` / `backfill-items` için: seçili grubun config'i."""
    settings = settings or load_groups(config)
    return profile_config(config, settings.selected)


def orphan_outbox_counts(config: Config, settings: GroupSettings) -> dict[str, int]:
    """Profili SİLİNMİŞ grupların bekleyen kayıt sayıları (gönderilmez, silinmez)."""
    root = group_outbox_root(config)
    counts: dict[str, int] = {}
    if not root.is_dir():
        return counts
    known = set(settings.ids())
    try:
        for directory in sorted(root.iterdir()):
            if not directory.is_dir() or directory.name in known:
                continue
            pending = sum(1 for path in directory.glob("*.json") if path.is_file())
            if pending:
                counts[directory.name] = pending
    except OSError as exc:
        log.debug("Could not scan group outbox: %s", exc)
    return counts


# --------------------------------------------------------------------------- #
# Yönlendirme kuralı (saf)
# --------------------------------------------------------------------------- #


def choose_group(
    known_by_group: Sequence[tuple[str, int]], min_known: int, selected_id: Optional[str]
) -> Optional[str]:
    """Contract kuralı. `known_by_group` PROFİL SIRASIYLA (grup kimliği, tanınan oyuncu).

    Tam bir grup filtreyi geçerse o; birden fazlası geçerse seçili grup geçenler
    arasındaysa o, değilse en çok tanınanı olan (eşitlikte profil sırası); hiçbiri
    geçmezse None (maç atlanır). Sonuç her zaman EN FAZLA bir gruptur.
    """
    passing = [(gid, known) for gid, known in known_by_group if known >= min_known]
    if not passing:
        return None
    if len(passing) == 1:
        return passing[0][0]
    if selected_id is not None and any(gid == selected_id for gid, _ in passing):
        return selected_id
    best = max(known for _, known in passing)
    return next(gid for gid, known in passing if known == best)


# --------------------------------------------------------------------------- #
# Yönlendirici: profil başına Sender + roster
# --------------------------------------------------------------------------- #


class GroupRouter:
    """Sender'ın çoklu grup karşılığı. Tek profilde davranış bugünküyle birebir aynıdır.

    `flush_outbox` / `send_heartbeat` / `close` Sender ile aynı imzadadır (yetişme ve
    komut katmanı ikisini de aynı biçimde çağırır); gönderim hedefi açıkça verilir
    (`send_or_outbox(payload, group_id)`), yönlendirme `route_pairs`/`route_live` iledir.
    """

    def __init__(
        self,
        config: Config,
        settings: Optional[GroupSettings] = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ):
        self.config = config
        self.settings = settings if settings is not None else load_groups(config)
        self._transport = transport
        self._senders: dict[str, Sender] = {
            profile.id: Sender(profile_config(config, profile), transport=transport)
            for profile in self.settings.profiles
        }
        self._roster_cache: dict[str, KnownRoster] = {}
        self._warned_orphans: set[str] = set()

    # --- erişim ---

    @property
    def is_multi(self) -> bool:
        return self.settings.is_multi

    @property
    def first_id(self) -> str:
        return self.settings.first.id

    @property
    def selected_id(self) -> str:
        return self.settings.selected.id

    def sender_for(self, group_id: str) -> Sender:
        return self._senders[group_id]

    # --- roster ---

    def build_rosters(self) -> dict[str, KnownRoster]:
        """Grup başına bilinen oyuncu kümesi (kendi anahtarıyla `GET /players`).

        `seed_roster.json` yalnız İLK profile eklenir. Bir grubun roster'ı çekilemezse
        o grubun son başarılı roster'ı (yoksa boş küme) kullanılır.
        """
        rosters: dict[str, KnownRoster] = {}
        for profile in self.settings.profiles:
            cfg = profile_config(self.config, profile)
            try:
                fetched = roster_from_players(fetch_players(cfg, self._transport))
                self._roster_cache[profile.id] = fetched
            except (httpx.HTTPError, ValueError) as exc:
                fetched = self._roster_cache.get(profile.id) or KnownRoster()
                log.warning(
                    "Could not fetch the roster of group '%s'%s: %s",
                    profile.label,
                    " (using the last known one)" if profile.id in self._roster_cache else "",
                    exc,
                )
            roster = KnownRoster(puuids=set(fetched.puuids), riot_ids=set(fetched.riot_ids))
            seed: set[str] = set()
            if profile.is_first:
                seed = load_seed_roster(self.config.seed_roster_path)
                roster.riot_ids |= seed
            log.info(
                "Known player set of group '%s': %d puuids, %d riot_ids (seed: %d)",
                profile.label, len(roster.puuids), len(roster.riot_ids), len(seed),
            )
            rosters[profile.id] = roster
        return rosters

    def known_counts(
        self,
        pairs: Iterable[tuple[Optional[str], Optional[str]]],
        rosters: dict[str, KnownRoster],
    ) -> list[tuple[str, int]]:
        pairs = list(pairs)
        return [
            (profile.id, rosters.get(profile.id, KnownRoster()).count_known(pairs))
            for profile in self.settings.profiles
        ]

    def route_pairs(
        self,
        pairs: Iterable[tuple[Optional[str], Optional[str]]],
        rosters: dict[str, KnownRoster],
    ) -> Optional[str]:
        counts = self.known_counts(pairs, rosters)
        return choose_group(counts, self.config.min_known, self.selected_id)

    def route_live(self, payload: dict[str, Any]) -> Optional[str]:
        """Canlı EOG / MH fallback hedefi.

        Tek profilde canlı modda roster filtresi YOKTUR (bugünkü davranış): maç ilk
        profile gider. Birden fazla profilde contract'taki otomatik yönlendirme uygulanır.
        """
        if not self.is_multi:
            return self.first_id
        rosters = self.build_rosters()
        pairs = [
            (participant.get("puuid"), participant.get("riot_id"))
            for participant in payload.get("participants") or []
        ]
        counts = self.known_counts(pairs, rosters)
        target = choose_group(counts, self.config.min_known, self.selected_id)
        log.info(
            "Group routing for %s: %s -> %s",
            payload.get("source_game_id", "?"),
            ", ".join(f"'{self.settings.label_of(gid)}'={n}" for gid, n in counts),
            f"'{self.settings.label_of(target)}'" if target else "none",
        )
        return target

    # --- gönderim (Sender ile aynı adlar) ---

    def send_or_outbox(self, payload: dict[str, Any], group_id: Optional[str] = None) -> SendOutcome:
        target = group_id or self.first_id
        if self.is_multi:
            log.info(
                "Sending %s to group '%s'",
                payload.get("source_game_id", "?"), self.settings.label_of(target),
            )
        return self._senders[target].send_or_outbox(payload)

    def flush_outbox(self) -> None:
        """Her profilin outbox'ı YALNIZ kendi anahtarıyla denenir; silinmiş profilin
        kayıtları gönderilmez/silinmez, uyarılır (her grup için bir kez)."""
        for profile in self.settings.profiles:
            try:
                self._senders[profile.id].flush_outbox()
            except Exception as exc:  # noqa: BLE001 — bir grubun hatası diğerini durdurmaz
                log.warning("Outbox flush failed for group '%s': %s", profile.label, exc)
        for orphan_id, count in orphan_outbox_counts(self.config, self.settings).items():
            if orphan_id in self._warned_orphans:
                continue
            self._warned_orphans.add(orphan_id)
            log.warning(
                "%d outbox record(s) belong to a deleted group (%s): kept, not sent",
                count, orphan_id,
            )

    def outbox_pending_count(self) -> int:
        return sum(sender.outbox_pending_count() for sender in self._senders.values())

    def send_heartbeat(self, reason: str = "") -> bool:
        """Her profile ayrı heartbeat; biri hata verse diğerleri etkilenmez."""
        results = []
        for profile in self.settings.profiles:
            try:
                results.append(self._senders[profile.id].send_heartbeat(reason))
            except Exception as exc:  # noqa: BLE001 — send_heartbeat zaten yutar; kemer-askı
                log.warning("Heartbeat failed for group '%s': %s", profile.label, exc)
                results.append(False)
        return any(results)

    def close(self) -> None:
        for sender in self._senders.values():
            try:
                sender.close()
            except Exception:  # noqa: BLE001
                pass


def needs_router(config: Config, settings: GroupSettings) -> bool:
    """Router gerekli mi? Tek profil ve sahipsiz outbox yoksa düz `Sender` yeterlidir
    (eski tek anahtarlı kurulumda kod yolu bugünküyle birebir aynı kalır)."""
    return settings.is_multi or bool(orphan_outbox_counts(config, settings))
