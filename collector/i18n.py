"""Collector i18n (GÖREV 6) — docs/i18n_contract.md §1/§3/§4.

Kullanıcıya görünen TÜM print/input metinleri buradaki `msg()` üzerinden akar.
Log/debug satırları (geliştiriciye dönük) kapsam dışıdır ve İngilizce'dir.

Dil çözümü (contract §1):
- Config'de (`.env`) `LANGUAGE` alanı varsa sessizce kullanılır.
- Yoksa, sihirbazın diğer sorularından ÖNCE İngilizce sorulur:
  ``Select language / Dil secin [tr/en]: `` — geçersiz girişte aynı soru
  tekrarlanır, yanıt aynı config dosyasına yazılır (mevcut alanların yanına;
  dosya yeniden yapılandırılmaz).
- Varsayılan: ``tr``.

Sözlük kuralları (contract §4): tr/en anahtar kümeleri birebir aynı, boş değer
yok, `en` değerlerinde Türkçe'ye özgü karakter yok — `tests/test_i18n.py` zorlar.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from .config import _load_env_file, find_env_file

log = logging.getLogger("collector.i18n")

DEFAULT_LANGUAGE = "tr"
SUPPORTED_LANGUAGES = ("tr", "en")

#: Config anahtarı (.env'de mevcut alanların yanına yazılır).
LANGUAGE_KEY = "LANGUAGE"

#: Contract §1: dil bilinmeden sorulur, bu yüzden tek ve sabit metin.
LANGUAGE_PROMPT = "Select language / Dil secin [tr/en]: "

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        # -- language selection (identical in both languages by design) --
        "lang.prompt": LANGUAGE_PROMPT,
        # -- CLI banner / modes --
        "cli.banner": "LoL Balance Collector v{version} — {mode}",
        "cli.workdir": "Working folder: {path}",
        "cli.mode.setup": "setup wizard",
        "cli.mode.backfill_positions": "role backfill",
        "cli.mode.backfill": "match history backfill",
        "cli.mode.live": "live mode",
        "cli.mode.dry_run_suffix": " (dry-run)",
        # -- argparse texts --
        "cli.description": "LoL custom match collector",
        "cli.help.command": "backfill: same as --backfill; backfill-positions: infers "
                            "roles for the matches in raw_archive and writes them to "
                            "the backend",
        "cli.help.backfill": "Scan match history backwards (with the roster filter)",
        "cli.help.since": "During backfill, ignore matches older than this date",
        "cli.help.dry_run": "backfill-positions: print what would be sent, do not send",
        "cli.help.setup": "Re-run the setup wizard (rewrites .env)",
        "cli.since_format": "--since must be in YYYY-MM-DD format: {value}",
        # -- CLI runtime --
        "cli.setup_done": "Setup complete. To start collecting, run the program "
                          "normally (without arguments).",
        "cli.live_hint": "Open the LoL client and play custom matches — each match "
                         "is sent automatically as soon as it ends.",
        "cli.live_stop_hint": "To stop: Ctrl+C (or close the window).",
        # -- auto catch-up (limited backfill before the live loop) --
        "catchup.start": "Catching up: scanning the last {days} days of match history "
                         "(since {since}) for matches played while the collector was "
                         "closed...",
        "catchup.done": "Catch-up finished: {scanned} matches scanned, {sent} sent. "
                        "Switching to live mode.",
        "catchup.failed": "Catch-up could not be completed ({error}) - live mode starts "
                          "anyway; you can run it later with `--backfill`.",
        "cli.stopped": "Stopped.",
        "cli.press_enter": "\nPress Enter to close...",
        "cli.no_env_no_tty": "No settings file ({path}) and the setup wizard cannot "
                             "run (stdin is closed). Copy .env.example and fill it in.",
        # -- config --
        "config.missing": "Missing config: {keys}. Fill in {path} "
                          "(see collector/.env.example).",
        # -- first-run wizard --
        "wizard.title": " LoL Balance Collector — first-time setup",
        "wizard.target": "Settings will be written to: {path}",
        "wizard.enter_hint": "(Press Enter to accept the default shown in brackets.)",
        "wizard.ask_backend_url": "Backend address [{default}]: ",
        "wizard.scheme_added": "  (scheme was missing, https:// added → {url})",
        "wizard.ask_api_key": "API key (ask Teoman): ",
        "wizard.api_key_empty": "  API key cannot be empty, try again.",
        "wizard.api_key_aborted": "No API key entered, setup aborted.",
        "wizard.lol_dir_found": "LoL folder found ({source}): {path}",
        "wizard.lol_dir_confirm": "  Is this correct? [Y/n]: ",
        "wizard.lol_dir_unclear": "  (answer not understood, using the detected folder)",
        "wizard.lol_dir_manual": "  OK, enter the folder manually.",
        "wizard.lol_dir_not_found": "Could not find the LoL folder automatically.",
        "wizard.ask_lol_dir": "LoL folder (e.g. C:\\Riot Games\\League of Legends): ",
        "wizard.lol_dir_empty": "  Cannot be empty, try again.",
        "wizard.lol_dir_no_marker": "  WARNING: the folder exists but contains no marker "
                                    "like LeagueClient.exe / lockfile. Saving anyway — "
                                    "fix .env if it is wrong.",
        "wizard.lol_dir_missing": "  No such folder: {path}",
        "wizard.lol_dir_aborted": "No valid LoL folder entered, setup aborted.",
        "wizard.saved": "Saved:",
        "wizard.saved_file": "  file        : {path}",
        "wizard.saved_language": "  LANGUAGE    : {lang}",
        "wizard.saved_backend": "  BACKEND_URL : {url}",
        "wizard.saved_api_key": "  API_KEY     : {masked}",
        "wizard.saved_lol_dir": "  LOL_DIR     : {path}",
        "wizard.fix_hint": "To fix the settings you can edit the .env file by hand "
                           "or run the program again with `--setup`.",
        # -- LOL_DIR detection source labels --
        "wizard.source.registry": "registry",
        "wizard.source.riot_metadata": "Riot metadata",
        "wizard.source.known_paths": "known paths",
        # -- .env file comments written by the wizard --
        "env.header": "# LoL Balance Collector — created by the first-run setup wizard",
        "env.comment_language": "# UI language (tr|en)",
        "env.comment_lol_dir": "# LoL install folder (the 'lockfile' appears here "
                               "while the client is running)",
        "env.comment_backend": "# Backend address (without trailing /) and the shared API key",
        "env.comment_optional": "# Optional:",
        # -- backend check --
        "check.ok_prefix": "OK  ",
        "check.fail_prefix": "ERROR  ",
        "check.ok": "Backend verified ({url}): {count} registered players.",
        "check.unreachable": "Could NOT reach the backend ({url}): {error}\n"
                             "  → Is BACKEND_URL correct, do you have an internet "
                             "connection? You can open the address in a browser to check.",
        "check.not_json": "The backend responded but not with JSON (HTTP {status}) — "
                          "BACKEND_URL may not belong to this system: {url}",
        "check.key_rejected": "API key REJECTED (HTTP {status}). "
                              "→ API_KEY in .env is wrong; ask Teoman for the correct key.",
        "check.not_found": "Address not found (HTTP 404): {url}{path}\n"
                           "  → BACKEND_URL may be wrong (it must NOT end with /api/v1).",
        "check.unexpected": "The backend returned an unexpected response "
                            "(HTTP {status}): {body}",
    },
    "tr": {
        # -- dil seçimi (bilerek iki dilde de aynı) --
        "lang.prompt": LANGUAGE_PROMPT,
        # -- CLI banner / modlar --
        "cli.banner": "LoL Balance Collector v{version} — {mode}",
        "cli.workdir": "Çalışma klasörü: {path}",
        "cli.mode.setup": "kurulum sihirbazı",
        "cli.mode.backfill_positions": "rol backfill",
        "cli.mode.backfill": "geçmiş maç backfill",
        "cli.mode.live": "canlı mod",
        "cli.mode.dry_run_suffix": " (dry-run)",
        # -- argparse metinleri --
        "cli.description": "LoL custom maç toplayıcı",
        "cli.help.command": "backfill: --backfill ile aynı; backfill-positions: "
                            "raw_archive'daki maçların rollerini tahmin edip "
                            "backend'e yazar",
        "cli.help.backfill": "Match history'yi geriye tara (roster filtresiyle)",
        "cli.help.since": "Backfill'de bu tarihten eski maçlara bakma",
        "cli.help.dry_run": "backfill-positions: ne gönderileceğini yazdır, gönderme",
        "cli.help.setup": "Kurulum sihirbazını yeniden çalıştır (.env'i yeniden yazar)",
        "cli.since_format": "--since YYYY-MM-DD formatında olmalı: {value}",
        # -- CLI çalışma zamanı --
        "cli.setup_done": "Kurulum bitti. Toplamayı başlatmak için programı normal "
                          "(argümansız) çalıştır.",
        "cli.live_hint": "LoL client'ini aç ve custom maç oyna — maç biter bitmez "
                         "otomatik gönderilir.",
        "cli.live_stop_hint": "Durdurmak için: Ctrl+C (ya da pencereyi kapat).",
        # -- oto-yetişme (canlı döngüden önceki sınırlı backfill) --
        "catchup.start": "Yetişiliyor: son {days} günün maç geçmişi taranıyor "
                         "({since} sonrası) — collector kapalıyken oynanan maçlar "
                         "için...",
        "catchup.done": "Yetişme bitti: {scanned} maç tarandı, {sent} maç gönderildi. "
                        "Canlı moda geçiliyor.",
        "catchup.failed": "Yetişme tamamlanamadı ({error}) — canlı mod yine de "
                          "başlıyor; daha sonra `--backfill` ile çalıştırabilirsin.",
        "cli.stopped": "Durduruldu.",
        "cli.press_enter": "\nKapatmak için Enter'a bas...",
        "cli.no_env_no_tty": "Ayar dosyası yok ({path}) ve kurulum sihirbazı "
                             "çalıştırılamıyor (stdin kapalı). .env.example'ı "
                             "kopyalayıp doldurun.",
        # -- config --
        "config.missing": "Eksik config: {keys}. {path} dosyasını doldurun "
                          "(bkz. collector/.env.example).",
        # -- ilk açılış sihirbazı --
        "wizard.title": " LoL Balance Collector — ilk kurulum",
        "wizard.target": "Ayarlar buraya yazılacak: {path}",
        "wizard.enter_hint": "(Köşeli parantezdeki varsayılanı kabul etmek için "
                             "Enter'a bas.)",
        "wizard.ask_backend_url": "Backend adresi [{default}]: ",
        "wizard.scheme_added": "  (şema eksikti, https:// eklendi → {url})",
        "wizard.ask_api_key": "API anahtarı (Teoman'dan al): ",
        "wizard.api_key_empty": "  API anahtarı boş olamaz, tekrar dene.",
        "wizard.api_key_aborted": "API anahtarı girilmedi, kurulum iptal edildi.",
        "wizard.lol_dir_found": "LoL klasörü bulundu ({source}): {path}",
        "wizard.lol_dir_confirm": "  Doğru mu? [E/h]: ",
        "wizard.lol_dir_unclear": "  (cevap anlaşılmadı, bulunan klasör kullanılıyor)",
        "wizard.lol_dir_manual": "  Tamam, klasörü elle gir.",
        "wizard.lol_dir_not_found": "LoL klasörü otomatik bulunamadı.",
        "wizard.ask_lol_dir": "LoL klasörü (ör. C:\\Riot Games\\League of Legends): ",
        "wizard.lol_dir_empty": "  Boş olamaz, tekrar dene.",
        "wizard.lol_dir_no_marker": "  UYARI: klasör var ama içinde LeagueClient.exe / "
                                    "lockfile gibi bir işaret yok. Yine de kaydediliyor "
                                    "— yanlışsa .env'i düzelt.",
        "wizard.lol_dir_missing": "  Böyle bir klasör yok: {path}",
        "wizard.lol_dir_aborted": "Geçerli bir LoL klasörü girilmedi, kurulum iptal edildi.",
        "wizard.saved": "Kaydedildi:",
        "wizard.saved_file": "  dosya       : {path}",
        "wizard.saved_language": "  LANGUAGE    : {lang}",
        "wizard.saved_backend": "  BACKEND_URL : {url}",
        "wizard.saved_api_key": "  API_KEY     : {masked}",
        "wizard.saved_lol_dir": "  LOL_DIR     : {path}",
        "wizard.fix_hint": "Ayarları düzeltmek için .env dosyasını elle düzenleyebilir "
                           "ya da programı `--setup` ile yeniden çalıştırabilirsin.",
        # -- LOL_DIR arama kaynağı etiketleri --
        "wizard.source.registry": "kayıt defteri",
        "wizard.source.riot_metadata": "Riot metadata",
        "wizard.source.known_paths": "bilinen yollar",
        # -- sihirbazın yazdığı .env yorumları --
        "env.header": "# LoL Balance Collector — ilk açılış sihirbazı tarafından oluşturuldu",
        "env.comment_language": "# Arayüz dili (tr|en)",
        "env.comment_lol_dir": "# LoL kurulum dizini (içinde client açıkken 'lockfile' oluşur)",
        "env.comment_backend": "# Backend adresi (sondaki / olmadan) ve paylaşılan API anahtarı",
        "env.comment_optional": "# Opsiyonel:",
        # -- backend doğrulaması --
        "check.ok_prefix": "OK  ",
        "check.fail_prefix": "HATA  ",
        "check.ok": "Backend doğrulandı ({url}): {count} kayıtlı oyuncu.",
        "check.unreachable": "Backend'e ULAŞILAMADI ({url}): {error}\n"
                             "  → BACKEND_URL doğru mu, internet bağlantın var mı? "
                             "Adresi tarayıcıda açıp kontrol edebilirsin.",
        "check.not_json": "Backend yanıt verdi ama JSON değil (HTTP {status}) — "
                          "BACKEND_URL bu sisteme ait olmayabilir: {url}",
        "check.key_rejected": "API anahtarı REDDEDİLDİ (HTTP {status}). "
                              "→ .env içindeki API_KEY yanlış; Teoman'dan doğru anahtarı iste.",
        "check.not_found": "Adres bulunamadı (HTTP 404): {url}{path}\n"
                           "  → BACKEND_URL yanlış olabilir (sonunda /api/v1 OLMAMALI).",
        "check.unexpected": "Backend beklenmedik yanıt verdi (HTTP {status}): {body}",
    },
}

_current_language: str = DEFAULT_LANGUAGE


# --------------------------------------------------------------------------- #
# Sözlük erişimi
# --------------------------------------------------------------------------- #


def get_language() -> str:
    return _current_language


def set_language(lang: str) -> str:
    """Geçerli dili ayarlar (tr|en, büyük/küçük harf duyarsız)."""
    global _current_language
    normalized = (lang or "").strip().lower()
    if normalized not in SUPPORTED_LANGUAGES:
        raise ValueError(f"unsupported language: {lang!r}")
    _current_language = normalized
    return normalized


def reset_language() -> None:
    """Testler için: dili varsayılana döndürür."""
    global _current_language
    _current_language = DEFAULT_LANGUAGE


def msg(key: str, **params: object) -> str:
    """Geçerli dildeki metin; `{ad}` yer tutucuları `params`'tan doldurulur.

    Contract §2 ile aynı davranış: anahtar yoksa uyarı loglanır ve anahtarın
    kendisi döner (asla boş string değil).
    """
    text = MESSAGES.get(_current_language, MESSAGES[DEFAULT_LANGUAGE]).get(key)
    if text is None:
        log.warning("missing i18n key: %s (lang=%s)", key, _current_language)
        return key
    return text.format(**params) if params else text


# --------------------------------------------------------------------------- #
# Dil çözümü (contract §1/§3)
# --------------------------------------------------------------------------- #


def language_from_env_file(path: Path) -> Optional[str]:
    """Config dosyasındaki geçerli `LANGUAGE` değeri; yoksa/geçersizse None."""
    raw = (_load_env_file(path).get(LANGUAGE_KEY) or "").strip().lower()
    return raw if raw in SUPPORTED_LANGUAGES else None


def persist_language(lang: str, env_path: Path) -> None:
    """`LANGUAGE`'i mevcut config dosyasına ekler (dosya yeniden yapılandırılmaz).

    Var olan bir `LANGUAGE=` satırı yerinde güncellenir; yoksa dosyanın sonuna
    tek satır eklenir. Dosya yoksa hiçbir şey yapılmaz (sihirbaz `.env`'i kendi
    yazar, dil satırı oraya `render_env` ile girer).
    """
    if not env_path.is_file():
        return
    lines = env_path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.split("=", 1)[0].strip() == LANGUAGE_KEY:
            lines[index] = f"{LANGUAGE_KEY}={lang}"
            break
    else:
        lines.append(f"{LANGUAGE_KEY}={lang}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def prompt_language(input_fn: Optional[Callable[[str], str]] = None) -> str:
    """Contract §1'deki İngilizce soru; tr/en dışındaki her girişte tekrar sorar.

    Girdi tükenirse (EOF) sonsuz döngüye girmemek için varsayılan dil döner.
    `input_fn` verilmezse `input` ÇAĞRI anında çözülür (geç bağlama) — böylece
    testler `builtins.input`'u monkeypatch'leyebilir, import sırası fark etmez.
    """
    read = input_fn if input_fn is not None else input
    while True:
        try:
            answer = read(LANGUAGE_PROMPT)
        except EOFError:
            return DEFAULT_LANGUAGE
        normalized = (answer or "").strip().lower()
        if normalized in SUPPORTED_LANGUAGES:
            return normalized


def resolve_language(
    env_path: Optional[Path] = None,
    input_fn: Optional[Callable[[str], str]] = None,
    *,
    allow_prompt: bool = True,
) -> str:
    """Dil çözümü: config'deki `LANGUAGE` → yoksa (izin varsa) prompt + persist.

    - Config dosyasında geçerli bir `LANGUAGE` varsa sessizce kullanılır.
    - Dosya var ama alan yoksa ve `allow_prompt` ise soru sorulur, yanıt aynı
      dosyaya yazılır.
    - Dosya hiç yoksa geçerli dil (varsayılan `tr`) korunur — ilk `.env`'i
      sihirbaz yazar ve dil sorusunu ilk soru olarak kendisi sorar.
    """
    path = env_path if env_path is not None else find_env_file()
    if path is not None and path.is_file():
        existing = language_from_env_file(path)
        if existing:
            return set_language(existing)
        if allow_prompt:
            lang = set_language(prompt_language(input_fn))
            persist_language(lang, path)
            return lang
    return get_language()
