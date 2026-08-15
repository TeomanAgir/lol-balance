"""Güncelleme bildirimi (GÖREV 16 Faz B) — bildir + indirme linki, oto-güncelleme YOK.

Açılışta TEK istek atılır: GitHub Releases `latest` API'si. Yanıttaki `tag_name`
(`vX.Y.Z`) çalışan sürümden yeniyse arayüz sarı bir bant gösterir ve "İndir"
tarayıcıda sabit indirme adresini açar.

Tasarım kuralları:
- **Her hata sessizce yutulur.** İnternet yok, GitHub 403 veriyor, JSON bozuk,
  repo private — hiçbiri collector'ı etkilemez, sonuç `None`'dır.
- **Kısa timeout** (varsayılan 4 sn): açılış hiçbir koşulda beklemez.
- **Açılan adres SABİTTİR** (`RELEASES_PAGE_URL`); API yanıtındaki `html_url`
  kullanılmaz — dış veriden gelen bir URL'i tarayıcıda açmayız.
- Sürüm karşılaştırması saf fonksiyondur (`parse_version` / `is_newer`), ağ
  gerekmeden test edilir.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from . import __version__

log = logging.getLogger("collector.updates")

#: Sürüm bilgisinin okunduğu tek uç (tek istek, açılışta).
LATEST_RELEASE_API = "https://api.github.com/repos/TeomanAgir/lol-balance/releases/latest"

#: "İndir" düğmesinin açtığı sabit adres (her sürümde aynı kalır).
RELEASES_PAGE_URL = "https://github.com/TeomanAgir/lol-balance/releases/latest"

#: Açılışı bekletmeyecek kadar kısa.
DEFAULT_TIMEOUT_S = 4.0

_VERSION_RE = re.compile(r"\s*v?(\d+(?:\.\d+)*)")


@dataclass(frozen=True)
class UpdateInfo:
    """Yeni sürüm bulunduğunda arayüze dönen bilgi."""

    version: str  # baştaki "v" olmadan, ör. "0.3.0"
    url: str = RELEASES_PAGE_URL


# --------------------------------------------------------------------------- #
# Sürüm karşılaştırma (saf)
# --------------------------------------------------------------------------- #


def parse_version(text: Any) -> Optional[tuple[int, ...]]:
    """`"v0.3.0"` → `(0, 3, 0)`. Sayısal bir önek yoksa `None`.

    Etiketlerdeki ek son ekler (`0.3.0-beta`, `0.3.0+win`) yok sayılır: yalnızca
    baştaki sayı dizisi karşılaştırmaya girer.
    """
    if text is None:
        return None
    match = _VERSION_RE.match(str(text))
    if not match:
        return None
    try:
        return tuple(int(part) for part in match.group(1).split("."))
    except ValueError:  # pragma: no cover — regex zaten sayı garantiliyor
        return None


def _padded(left: tuple[int, ...], right: tuple[int, ...]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """`(0, 3)` ile `(0, 3, 0)` eşit sayılsın diye kısa olan sıfırla doldurulur."""
    size = max(len(left), len(right))
    return left + (0,) * (size - len(left)), right + (0,) * (size - len(right))


def is_newer(candidate: Any, current: Any) -> bool:
    """Aday sürüm, çalışan sürümden KESİN olarak yeni mi? Ayrıştırılamayan taraf → False."""
    parsed_candidate = parse_version(candidate)
    parsed_current = parse_version(current)
    if parsed_candidate is None or parsed_current is None:
        return False
    left, right = _padded(parsed_candidate, parsed_current)
    return left > right


def normalize_version(text: Any) -> str:
    """Gösterim için: baştaki `v` ve boşluklar atılır (`"v0.3.0"` → `"0.3.0"`)."""
    parsed = parse_version(text)
    return ".".join(str(part) for part in parsed) if parsed else str(text or "").strip()


# --------------------------------------------------------------------------- #
# Kontrol (ağ; her hata yutulur)
# --------------------------------------------------------------------------- #

#: `opener(url, timeout)` → `.read()` sunan bağlam yöneticisi (testler sahtesini verir).
Opener = Callable[[str, float], Any]


def _urlopen(url: str, timeout: float) -> Any:
    import urllib.request

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"lol-balance-collector/{__version__}",
        },
    )
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 — sabit https adres


def check_for_update(
    current_version: str = __version__,
    *,
    opener: Optional[Opener] = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    api_url: str = LATEST_RELEASE_API,
) -> Optional[UpdateInfo]:
    """Yeni sürüm varsa `UpdateInfo`, yoksa/erişilemezse `None`.

    HİÇBİR koşulda istisna fırlatmaz — çağıran taraf (arayüz açılışı) korunmasız
    çağırabilsin diye tüm hata sınıfları burada yutulur.
    """
    open_url = opener or _urlopen
    try:
        with open_url(api_url, timeout) as response:
            raw = response.read()
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="replace")
        data = json.loads(raw)
        tag = data.get("tag_name") if isinstance(data, dict) else None
        if not is_newer(tag, current_version):
            return None
        return UpdateInfo(version=normalize_version(tag))
    except Exception as exc:  # noqa: BLE001 — güncelleme kontrolü ASLA collector'ı etkilemez
        log.debug("Update check failed (ignored): %s", exc)
        return None
