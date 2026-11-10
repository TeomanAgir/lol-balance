"""Uygulama ayarları — .env / ortam değişkenlerinden okunur."""
from __future__ import annotations

import logging
import os
import re
import secrets
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Optional

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent

logger = logging.getLogger(__name__)

# api_contract "Çoklu grup" (GÖREV 35): ek grup = GROUP_<AD>_API_KEY (+ isteğe
# bağlı GROUP_<AD>_ADMIN_KEY), <AD> = [A-Z0-9]{1,32}.
GROUP_ENV_PREFIX = "GROUP_"
_GROUP_API_RE = re.compile(r"^GROUP_(.+)_API_KEY$")
_GROUP_ADMIN_RE = re.compile(r"^GROUP_(.+)_ADMIN_KEY$")
_GROUP_NAME_RE = re.compile(r"^[A-Z0-9]{1,32}$")


@dataclass(frozen=True)
class Group:
    """Bir arkadaş grubu: kendi API anahtarı, admin anahtarı ve SQLite dosyası.

    `name` ana grup için None, ek gruplar için <AD>'ın küçük harfli hâlidir.
    `admin_env` 503 detail'ında hangi env değişkeninin eksik olduğunu söyler.
    """
    name: Optional[str]
    api_key: str
    admin_key: Optional[str]
    db_path: str
    admin_env: str = "ADMIN_KEY"

    @property
    def is_main(self) -> bool:
        return self.name is None


@dataclass(frozen=True)
class Settings:
    api_key: str
    db_path: str
    engine_version: str
    webui_dir: str
    # İdari uçların İKİNCİ anahtarı (api_contract "Admin anahtarı", fix-2).
    # None = yapılandırılmamış → o uçlar 503 döner (API_KEY'in aksine
    # yokluğu uygulamayı başlatmaz, yalnız idari yüzeyi kapatır).
    # Değer YALNIZ ortamdan gelir; repo public olduğu için hiçbir dosyada
    # varsayılan/örnek gerçek değer bulunmaz.
    admin_key: str | None = None
    # X-Forwarded-For'una güvenilecek proxy adresleri (GÖREV 30b). Uygulama
    # içi ProxyHeadersMiddleware'e verilir (main.create_app); admin hız
    # sınırının "istemci IP'si başına" sayacı (api_contract "Hız sınırı")
    # ancak böyle gerçek istemciyi görür. "*" = her bağlanana güven; boş
    # liste = header tamamen yok sayılır (soket adresi kullanılır).
    forwarded_allow_ips: tuple[str, ...] = ("*",)
    # Ek gruplar (GÖREV 35). Ana grup bu demette YOKTUR; `groups` özelliği
    # ana grubu (api_key/admin_key/db_path alanlarından) başa ekler.
    extra_groups: tuple[Group, ...] = field(default=())

    @property
    def main_group(self) -> Group:
        return Group(None, self.api_key, self.admin_key, self.db_path)

    @property
    def groups(self) -> tuple[Group, ...]:
        return (self.main_group, *self.extra_groups)

    def resolve_group(self, api_key: Optional[str]) -> Optional[Group]:
        """X-API-Key → grup; eşleşme yoksa None.

        Sabit zamanlı: her grubun anahtarı (eşleşme bulunsa bile) karşılaştırılır,
        erken çıkış yoktur — hangi grubun/kaçıncı anahtarın eşleştiği zamanlamadan
        sızmasın. Byte'a çevrilir: compare_digest str'de yalnız ASCII kabul eder.
        """
        if api_key is None:
            return None
        given = api_key.encode("utf-8")
        found: Optional[Group] = None
        for group in self.groups:
            if secrets.compare_digest(given, group.api_key.encode("utf-8")):
                found = group
        return found


def _parse_extra_groups(env: Mapping[str, str], main_db_path: str) -> tuple[Group, ...]:
    """GROUP_<AD>_API_KEY / GROUP_<AD>_ADMIN_KEY env'lerinden ek grupları kurar.

    - Değeri boş API anahtarı grubu TANIMLAMAZ (uyarı log'u, yok sayılır).
    - <AD> `[A-Z0-9]{1,32}` değilse değişken grup tanımı DEĞİLDİR (uyarı log'u,
      yok sayılır).
    - API anahtarı olmayan ADMIN_KEY tek başına grup tanımlamaz (uyarı log'u).
    DB dosyası env'den alınmaz: DB_PATH ile AYNI dizinde group_<ad>.db.
    """
    db_dir = Path(main_db_path).parent
    groups: list[Group] = []
    defined: set[str] = set()
    for key in sorted(env):
        m = _GROUP_API_RE.match(key)
        if not m:
            continue
        ad = m.group(1)
        if not _GROUP_NAME_RE.match(ad):
            logger.warning(
                "Ignoring env %s: group name %r must match [A-Z0-9]{1,32}", key, ad
            )
            continue
        api_key = env[key]
        if not api_key.strip():
            logger.warning("Ignoring group %s: %s is empty", ad, key)
            continue
        admin_env = f"GROUP_{ad}_ADMIN_KEY"
        name = ad.lower()
        groups.append(Group(
            name=name,
            api_key=api_key,
            # Ana grupla aynı kural: boş = yapılandırılmamış (idari uçlar 503).
            admin_key=env.get(admin_env, "").strip() or None,
            db_path=str(db_dir / f"group_{name}.db"),
            admin_env=admin_env,
        ))
        defined.add(ad)
    for key in sorted(env):
        m = _GROUP_ADMIN_RE.match(key)
        if m and m.group(1) not in defined and _GROUP_NAME_RE.match(m.group(1)):
            logger.warning(
                "Ignoring env %s: no non-empty GROUP_%s_API_KEY defines this group",
                key, m.group(1),
            )
    return tuple(groups)


def _validate_groups(settings: Settings) -> None:
    """Belirsiz yönlendirmeye yol açan yapılandırmada uygulama BAŞLAMAZ."""
    seen_keys: dict[str, str] = {}
    seen_paths: dict[str, str] = {}
    for group in settings.groups:
        label = "ana grup (API_KEY)" if group.is_main else f"GROUP_{group.name.upper()}"
        other = seen_keys.get(group.api_key)
        if other is not None:
            raise RuntimeError(
                f"Yinelenen API anahtarı: {other} ile {label} aynı anahtarı kullanıyor; "
                "istek hangi gruba ait belirsiz olurdu. Her grubun API anahtarı farklı olmalı."
            )
        seen_keys[group.api_key] = label
        # İki grubun aynı dosyaya düşmesi (ör. DB_PATH'in kendisi group_x.db)
        # izolasyonu sessizce bozardı.
        path = os.path.normcase(os.path.abspath(group.db_path))
        other = seen_paths.get(path)
        if other is not None:
            raise RuntimeError(
                f"{other} ile {label} aynı DB dosyasını kullanıyor ({group.db_path}); "
                "DB_PATH'i group_<ad>.db adlarıyla çakışmayacak şekilde ayarlayın."
            )
        seen_paths[path] = label


@lru_cache
def get_settings() -> Settings:
    load_dotenv(BACKEND_DIR / ".env")
    api_key = os.environ.get("API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "API_KEY tanımlı değil. backend/.env dosyasına API_KEY=<secret> ekleyin "
            "(bkz. .env.example)."
        )
    db_path = os.environ.get("DB_PATH", str(BACKEND_DIR / "data" / "lol_balance.db"))
    settings = Settings(
        api_key=api_key,
        db_path=db_path,
        engine_version=os.environ.get("ENGINE_VERSION", "openskill-pl-blend25-v1"),
        webui_dir=os.environ.get("WEBUI_DIR", str(BACKEND_DIR.parent / "webui")),
        # Boş string de "yapılandırılmamış" sayılır (k8s secret'ta anahtar
        # tanımlı ama değeri boşsa idari uçlar herkese açılmasın).
        admin_key=os.environ.get("ADMIN_KEY", "").strip() or None,
        # Varsayılan "*": prod pod'u yalnız ClusterIP Service üzerinden
        # nginx ingress'ten erişilebilir, yani bağlanan her zaman ingress'tir.
        # UYARI: pod'a/porta doğrudan erişilebilen bir dağıtımda bunu proxy
        # adresine DARALTIN — yoksa istemci sahte X-Forwarded-For ile hız
        # sınırı sayacını seyreltebilir. Değişken TANIMLI ama boşsa hiçbir
        # proxy'ye güvenilmez.
        forwarded_allow_ips=_parse_forwarded_allow_ips(
            os.environ.get("FORWARDED_ALLOW_IPS", "*")
        ),
        extra_groups=_parse_extra_groups(os.environ, db_path),
    )
    _validate_groups(settings)
    return settings


def _parse_forwarded_allow_ips(raw: str) -> tuple[str, ...]:
    """Virgülle ayrılmış listeyi (uvicorn `--forwarded-allow-ips` biçimi) ayrıştırır."""
    return tuple(item.strip() for item in raw.split(",") if item.strip())
