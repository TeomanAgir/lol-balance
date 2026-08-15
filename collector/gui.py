"""tkinter arayüzü (GÖREV 16 Faz C) — collector'ın çift tıklanan yüzü.

Pencere: durum bandı (bağlantı/canlı durum + son işlenen maç) · GÖMÜLÜ log alanı ·
düğmeler (Canlı Başlat/Durdur · Maçları Tara · Eşyaları Doldur · Rolleri Doldur ·
Ayarlar) · yeni sürüm çıktıysa sarı bilgi bandı (GÖREV 16 Faz B).

Mimari kurallar (bunlar bilinçli sınırlardır, "iyileştirme" ile bozulmaz):

1. **tkinter YALNIZ bu modüldedir** ve modül düzeyinde İMPORT EDİLMEZ — import
   fonksiyon gövdelerindedir. Böylece `import collector.gui` ekransız/tkinter'sız
   bir CI'da bile çalışır ve pytest bu dosyayı toplayabilir.
2. **İş mantığı burada yoktur.** Canlı döngü ve match-history backfill'i
   `commands.py`'den, eşya/rol backfill'leri kendi modüllerinden, kurulum
   sihirbazı `wizard.py`'den ÇAĞRILIR. Soru akışı/doğrulama tek kopyadır:
   sihirbazın `input_fn`/`print_fn` uçları `DialogConsole` ile tkinter
   diyaloglarına bağlanır.
3. **Saf parçalar test edilebilir**: `QueueLogHandler`, `drain_queue`,
   `excess_lines`, `UiState`, `DialogConsole`, `format_*_summary`. Bunların
   hiçbiri tkinter'a dokunmaz.
4. **İşler arka plan thread'inde**, arayüz donmaz; aynı anda TEK iş çalışır.
   Worker thread'ler widget'a DOKUNMAZ: log satırları ve bitiş geri çağrıları
   kuyruklara yazılır, `root.after` ile arayüz thread'inde tüketilir.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import webbrowser
from typing import Any, Callable, Optional

from . import __version__
from .backfill import BackfillStats
from .backfill_items import ItemsBackfillStats, run_items_backfill
from .backfill_positions import PositionBackfillStats, run_position_backfill
from .commands import run_backfill_command, run_live_command
from .config import REQUIRED_ENV_KEYS, Config, find_env_file, load_config
from .i18n import msg
from .lockfile import LockfileNotFound
from .sender import Sender
from .updates import RELEASES_PAGE_URL, UpdateInfo, check_for_update
from .wizard import report_backend_check, run_wizard

log = logging.getLogger("collector.gui")

#: Log kuyruğu üst sınırı — dolarsa satır DÜŞÜRÜLÜR (collector asla beklemez).
LOG_QUEUE_SIZE = 5000
#: Text widget'ında tutulan azami satır (üstten kırpılır).
MAX_LOG_LINES = 1500
#: Kuyruk tüketim aralığı (ms) ve tek turda alınacak azami satır.
PUMP_INTERVAL_MS = 150
PUMP_BATCH = 400

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
LOG_DATEFMT = "%H:%M:%S"

# --- iş kimlikleri (düğme durumları ve i18n anahtarları bunlara bağlı) ---
JOB_LIVE = "live"
JOB_BACKFILL = "backfill"
JOB_ITEMS = "items"
JOB_POSITIONS = "positions"
JOB_SETTINGS = "settings"
JOBS = (JOB_LIVE, JOB_BACKFILL, JOB_ITEMS, JOB_POSITIONS, JOB_SETTINGS)

#: Sihirbazın evet/hayır sorusuna verilecek dilden bağımsız yanıtlar (wizard.py
#: hem "y/yes" hem "e/evet" kabul eder; "y"/"n" iki dilde de doğru çalışır).
YES_ANSWER = "y"
NO_ANSWER = "n"


# --------------------------------------------------------------------------- #
# Saf parçalar (tkinter YOK — testler bunları ekransız koşturur)
# --------------------------------------------------------------------------- #


class QueueLogHandler(logging.Handler):
    """Logging kayıtlarını thread-safe kuyruğa yazar; arayüz kuyruğu tüketir.

    Kuyruk dolarsa satır sessizce düşürülür: log yazımı HİÇBİR koşulda
    collector'ın iş thread'ini bloklamaz ya da hata fırlatmaz.
    """

    def __init__(self, sink: "queue.Queue[str]", level: int = logging.INFO):
        super().__init__(level)
        self.sink = sink
        self.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.sink.put_nowait(self.format(record))
        except Exception:  # noqa: BLE001 — queue.Full dahil her şey yutulur
            pass


def drain_queue(source: "queue.Queue[Any]", limit: int = PUMP_BATCH) -> list[Any]:
    """Kuyruktan en fazla `limit` öğe alır (boşsa boş liste; asla bloklamaz)."""
    items: list[Any] = []
    for _ in range(max(0, limit)):
        try:
            items.append(source.get_nowait())
        except queue.Empty:
            break
    return items


def excess_lines(total: int, maximum: int = MAX_LOG_LINES) -> int:
    """Log alanında `maximum` satırı aşan (üstten silinecek) satır sayısı."""
    return max(0, total - maximum)


class UiState:
    """Düğme durumlarının tek kaynağı: aynı anda TEK iş çalışır.

    Canlı mod tek istisnadır — koşarken kendi düğmesi "Durdur" olarak AÇIK
    kalır (durdurma isteği gönderildikten sonra o da kilitlenir), diğer tüm
    düğmeler kilitlidir.
    """

    def __init__(self) -> None:
        self.active: Optional[str] = None
        self.stopping = False

    @property
    def busy(self) -> bool:
        return self.active is not None

    def can_start(self, job: str) -> bool:
        return self.active is None

    def start(self, job: str) -> None:
        if self.active is not None:
            raise RuntimeError(f"already running: {self.active}")
        self.active = job
        self.stopping = False

    def finish(self) -> None:
        self.active = None
        self.stopping = False

    def request_stop(self) -> bool:
        """Canlı mod koşuyorsa durdurma isteğini işaretler; işaretlediyse True."""
        if self.active != JOB_LIVE or self.stopping:
            return False
        self.stopping = True
        return True

    def button_enabled(self, job: str) -> bool:
        if self.active is None:
            return True
        return job == JOB_LIVE and self.active == JOB_LIVE and not self.stopping

    def button_states(self) -> dict[str, bool]:
        return {job: self.button_enabled(job) for job in JOBS}

    def live_button_key(self) -> str:
        return "gui.btn.live_stop" if self.active == JOB_LIVE else "gui.btn.live_start"


class WizardCancelled(Exception):
    """Kullanıcı sihirbaz diyaloglarından birini iptal etti (hata değildir)."""


def is_yes_no_prompt(prompt: str) -> bool:
    """Sihirbazın tek evet/hayır sorusu (LoL klasörü onayı) mu?

    Eşleşmezse metin kutusu kullanılır — yani i18n metni değişse bile akış
    bozulmaz, yalnızca diyalog tipi değişir.
    """
    return prompt.strip() == msg("wizard.lol_dir_confirm").strip()


class DialogConsole:
    """`wizard.run_wizard`'ın input/print uçlarını diyaloglara bağlayan adaptör.

    Sihirbaz mantığı (soru sırası, doğrulama, `.env` yazımı, backend kontrolü)
    KOPYALANMAZ; yalnızca G/Ç değişir. `ask(prompt, context)` iptalde `None`
    döndürürse akış `WizardCancelled` ile kesilir.

    Sihirbazın yazdığı bilgi satırları (uyarılar, "boş olamaz" gibi) bir sonraki
    sorunun diyalog metnine bağlam olarak taşınır; kalanlar `flush()` ile tek
    bilgi kutusunda gösterilir. Kullanıcının VERDİĞİ yanıtlar (API anahtarı!)
    asla log'a yazılmaz.
    """

    def __init__(
        self,
        ask: Callable[[str, str], Optional[str]],
        show: Callable[[str], None],
        echo: Optional[Callable[[str], None]] = None,
    ):
        self._ask = ask
        self._show = show
        self._echo = echo or (lambda text: None)
        self._pending: list[str] = []

    def read(self, prompt: str) -> str:
        context = "\n".join(self._pending).strip()
        self._pending.clear()
        answer = self._ask(prompt, context)
        if answer is None:
            raise WizardCancelled()
        return answer

    def write(self, text: str = "") -> None:
        line = str(text)
        self._echo(line)
        if line.strip():
            self._pending.append(line)

    def flush(self) -> None:
        """Kalan çıktıyı (özet + backend doğrulaması) tek kutuda gösterir."""
        if not self._pending:
            return
        text = "\n".join(self._pending)
        self._pending.clear()
        self._show(text)


# --- iş özetleri (dry-run onayında ve bitişte gösterilir) ------------------- #


def format_backfill_summary(stats: BackfillStats) -> str:
    return msg(
        "gui.summary.backfill",
        scanned=stats.scanned,
        customs=stats.customs,
        sent=stats.sent,
        errors=len(stats.errors),
    )


def format_items_summary(stats: ItemsBackfillStats) -> str:
    return msg(
        "gui.summary.items",
        archives=stats.archives,
        matched=stats.matched,
        updated=stats.updated,
        participants=stats.participants_sent,
        errors=len(stats.errors),
    )


def format_positions_summary(stats: PositionBackfillStats) -> str:
    return msg(
        "gui.summary.positions",
        archives=stats.archives,
        matched=stats.matched,
        updated=stats.updated,
        positions=stats.positions_sent,
        unresolved=stats.unresolved,
        errors=len(stats.errors),
    )


def status_text(status_key: str, last_match: Optional[str] = None) -> str:
    """Durum bandı metni: `<durum> · Son maç: <id>`."""
    state = msg(f"gui.status.{status_key}")
    match = last_match or msg("gui.last_match_none")
    return msg("gui.status_line", state=state, match=match)


def tkinter_available() -> bool:
    """tkinter import edilebiliyor mu? (Windows exe'de her zaman evet.)"""
    try:
        import tkinter  # noqa: F401
    except Exception:  # noqa: BLE001 — ImportError + egzotik kurulum hataları
        return False
    return True


# --------------------------------------------------------------------------- #
# Pencere
# --------------------------------------------------------------------------- #


class CollectorApp:
    """Ana pencere. Tüm tkinter kullanımı bu sınıfın içindedir."""

    def __init__(
        self,
        root: Any = None,
        *,
        update_checker: Callable[..., Optional[UpdateInfo]] = check_for_update,
        open_url: Callable[[str], Any] = webbrowser.open,
    ):
        import tkinter as tk
        from tkinter import scrolledtext

        self._update_checker = update_checker
        self._open_url = open_url

        self.log_queue: "queue.Queue[str]" = queue.Queue(maxsize=LOG_QUEUE_SIZE)
        self.ui_queue: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self.state = UiState()
        self.stop_event = threading.Event()
        self.config: Optional[Config] = None
        self._status_key = "idle"
        self._last_match: Optional[str] = None

        self.root = root if root is not None else tk.Tk()
        self.root.title(msg("gui.title", version=__version__))
        self.root.minsize(760, 480)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # --- sarı güncelleme bandı (başta gizli) ---
        self.update_bar = tk.Frame(self.root, bg="#f7e08a", padx=8, pady=5)
        self.update_label = tk.Label(self.update_bar, text="", bg="#f7e08a", anchor="w")
        self.update_label.pack(side="left", fill="x", expand=True)
        self.update_button = tk.Button(
            self.update_bar, text=msg("gui.update.button"), command=self._open_releases
        )
        self.update_button.pack(side="right")

        # --- durum bandı ---
        self.status_var = tk.StringVar(value=status_text(self._status_key))
        self.status_label = tk.Label(
            self.root, textvariable=self.status_var, anchor="w", padx=8, pady=6
        )
        self.status_label.pack(fill="x")

        # --- gömülü log alanı ---
        self.log_text = scrolledtext.ScrolledText(
            self.root, height=18, wrap="word", state="disabled"
        )
        self.log_text.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        # --- düğmeler ---
        bar = tk.Frame(self.root, padx=8, pady=8)
        bar.pack(fill="x")
        self.buttons: dict[str, Any] = {
            JOB_LIVE: tk.Button(bar, text=msg("gui.btn.live_start"), command=self.on_live),
            JOB_BACKFILL: tk.Button(bar, text=msg("gui.btn.backfill"), command=self.on_backfill),
            JOB_ITEMS: tk.Button(bar, text=msg("gui.btn.items"), command=self.on_items),
            JOB_POSITIONS: tk.Button(
                bar, text=msg("gui.btn.positions"), command=self.on_positions
            ),
            JOB_SETTINGS: tk.Button(bar, text=msg("gui.btn.settings"), command=self.on_settings),
        }
        for job in JOBS:
            self.buttons[job].pack(side="left", padx=(0, 6))

        self.log_handler = QueueLogHandler(self.log_queue)
        logging.getLogger().addHandler(self.log_handler)

    # ------------------------------------------------------------------ #
    # Arayüz yardımcıları (yalnız arayüz thread'inden çağrılır)
    # ------------------------------------------------------------------ #

    def append_log(self, line: str) -> None:
        try:
            self.log_text.configure(state="normal")
            self.log_text.insert("end", line.rstrip("\n") + "\n")
            total = int(self.log_text.index("end-1c").split(".")[0])
            extra = excess_lines(total)
            if extra:
                self.log_text.delete("1.0", f"{extra + 1}.0")
            self.log_text.configure(state="disabled")
            self.log_text.see("end")
        except Exception:  # noqa: BLE001 — pencere kapanırken widget yok olabilir
            pass

    def set_status(self, status_key: str) -> None:
        self._status_key = status_key
        self._refresh_status()

    def set_last_match(self, game_id: str) -> None:
        self._last_match = game_id
        self._refresh_status()

    def _refresh_status(self) -> None:
        try:
            self.status_var.set(status_text(self._status_key, self._last_match))
        except Exception:  # noqa: BLE001
            pass

    def refresh_buttons(self) -> None:
        states = self.state.button_states()
        for job, enabled in states.items():
            try:
                self.buttons[job].configure(state="normal" if enabled else "disabled")
            except Exception:  # noqa: BLE001
                pass
        try:
            self.buttons[JOB_LIVE].configure(text=msg(self.state.live_button_key()))
        except Exception:  # noqa: BLE001
            pass

    def post(self, action: Callable[[], None]) -> None:
        """Worker thread'den arayüz thread'ine iş gönderir (widget'a dokunmadan)."""
        self.ui_queue.put(action)

    def pump(self) -> None:
        """Kuyrukları tüketir; `root.after` ile kendini yeniden zamanlar."""
        for line in drain_queue(self.log_queue):
            self.append_log(line)
        for action in drain_queue(self.ui_queue, limit=64):
            try:
                action()
            except Exception:  # noqa: BLE001 — tek bir geri çağrı arayüzü düşürmez
                log.exception("GUI callback failed")
        try:
            self.root.after(PUMP_INTERVAL_MS, self.pump)
        except Exception:  # noqa: BLE001 — pencere kapandı
            pass

    # ------------------------------------------------------------------ #
    # Diyaloglar
    # ------------------------------------------------------------------ #

    def _ask_wizard(self, prompt: str, context: str) -> Optional[str]:
        from tkinter import messagebox, simpledialog

        title = msg("gui.wizard.title")
        text = f"{context}\n\n{prompt}".strip() if context else prompt.strip()
        if is_yes_no_prompt(prompt):
            answer = messagebox.askyesnocancel(title, text, parent=self.root)
            if answer is None:
                return None
            return YES_ANSWER if answer else NO_ANSWER
        return simpledialog.askstring(title, text, parent=self.root)

    def _show_info(self, text: str) -> None:
        from tkinter import messagebox

        messagebox.showinfo(msg("gui.wizard.title"), text, parent=self.root)

    def _ask_yes_no(self, title: str, question: str) -> bool:
        from tkinter import messagebox

        return bool(messagebox.askyesno(title, question, parent=self.root))

    # ------------------------------------------------------------------ #
    # Açılış
    # ------------------------------------------------------------------ #

    def bootstrap(self) -> None:
        """Pencere açıldıktan sonra: ayar yoksa sihirbaz, config, sürüm kontrolü."""
        self.append_log(msg("gui.banner", version=__version__))
        if find_env_file() is None and not all(os.environ.get(k) for k in REQUIRED_ENV_KEYS):
            self.append_log(msg("gui.first_run"))
            self.on_settings()
        else:
            self.reload_config(check_backend=True)
        self.start_update_check()

    def reload_config(self, *, check_backend: bool = False) -> Optional[Config]:
        try:
            self.config = load_config()
        except SystemExit as exc:  # eksik alan → sihirbaz gerekiyor
            self.config = None
            self.append_log(str(exc.code))
            return None
        except Exception as exc:  # noqa: BLE001
            self.config = None
            self.append_log(msg("gui.config_error", error=exc))
            return None
        if check_backend:
            self._check_backend_async(self.config)
        return self.config

    def _check_backend_async(self, config: Config) -> None:
        """Açılıştaki hızlı backend doğrulaması — arayüzü bloklamaz."""

        def work() -> None:
            try:
                report_backend_check(
                    config.backend_url, config.api_key, print_fn=lambda t: self.post(
                        lambda text=t: self.append_log(text)
                    )
                )
            except Exception as exc:  # noqa: BLE001 — doğrulama arayüzü etkilemez
                log.debug("Backend check failed (ignored): %s", exc)

        threading.Thread(target=work, daemon=True, name="collector-check").start()

    def start_update_check(self) -> None:
        """Açılışta TEK istek; her hata `check_for_update` içinde yutulur."""

        def work() -> None:
            info = self._update_checker(__version__)
            if info is not None:
                self.post(lambda: self.show_update(info))

        threading.Thread(target=work, daemon=True, name="collector-update").start()

    def show_update(self, info: UpdateInfo) -> None:
        try:
            self.update_label.configure(text=msg("gui.update.banner", version=info.version))
            self.update_bar.pack(fill="x", before=self.status_label)
        except Exception:  # noqa: BLE001
            pass
        self.append_log(msg("gui.update.banner", version=info.version))

    def _open_releases(self) -> None:
        try:
            self._open_url(RELEASES_PAGE_URL)
        except Exception as exc:  # noqa: BLE001 — tarayıcı açılamazsa adresi log'a yaz
            self.append_log(msg("gui.update.open_failed", url=RELEASES_PAGE_URL, error=exc))

    # ------------------------------------------------------------------ #
    # İş yürütme
    # ------------------------------------------------------------------ #

    def require_config(self) -> Optional[Config]:
        if self.config is None:
            self.reload_config()
        if self.config is None:
            self.append_log(msg("gui.need_setup"))
        return self.config

    def start_job(
        self,
        job: str,
        work: Callable[[], Any],
        *,
        status_key: Optional[str] = None,
        on_done: Optional[Callable[[Any], None]] = None,
    ) -> bool:
        """İşi arka plan thread'inde başlatır. Meşgulken çağrı yok sayılır."""
        if not self.state.can_start(job):
            return False
        self.state.start(job)
        self.refresh_buttons()
        self.set_status(status_key or job)
        self.append_log(msg("gui.job.started", job=msg(f"gui.job.name.{job}")))

        def target() -> None:
            try:
                result = work()
            except Exception as exc:  # noqa: BLE001 — hata arayüzde raporlanır
                log.exception("Job failed: %s", job)
                self.post(lambda: self._job_failed(job, exc))
                return
            self.post(lambda: self._job_finished(job, result, on_done))

        threading.Thread(target=target, daemon=True, name=f"collector-{job}").start()
        return True

    def _job_failed(self, job: str, error: BaseException) -> None:
        self.state.finish()
        self.refresh_buttons()
        self.set_status("idle")
        self.append_log(msg("gui.job.failed", job=msg(f"gui.job.name.{job}"), error=error))

    def _job_finished(
        self, job: str, result: Any, on_done: Optional[Callable[[Any], None]]
    ) -> None:
        self.state.finish()
        self.refresh_buttons()
        self.set_status("idle")
        self.append_log(msg("gui.job.done", job=msg(f"gui.job.name.{job}")))
        if on_done is not None:
            on_done(result)

    def _with_sender(self, config: Config, work: Callable[[Sender], Any]) -> Any:
        sender = Sender(config)
        try:
            return work(sender)
        finally:
            sender.close()

    # --- Canlı ---

    def on_live(self) -> None:
        if self.state.active == JOB_LIVE:
            if self.state.request_stop():
                self.stop_event.set()
                self.set_status("stopping")
                self.refresh_buttons()
                self.append_log(msg("gui.live.stopping"))
            return

        config = self.require_config()
        if config is None:
            return
        self.stop_event.clear()

        def work() -> None:
            self._with_sender(
                config,
                lambda sender: run_live_command(
                    config,
                    sender,
                    stop=self.stop_event,
                    on_status=lambda key: self.post(lambda k=key: self.set_status(k)),
                    on_match=lambda game_id: self.post(
                        lambda gid=game_id: self.set_last_match(gid)
                    ),
                ),
            )

        self.start_job(JOB_LIVE, work, status_key="waiting_client")

    # --- Maçları Tara (match history backfill) ---

    def on_backfill(self) -> None:
        config = self.require_config()
        if config is None:
            return

        def work() -> BackfillStats:
            try:
                return self._with_sender(
                    config, lambda sender: run_backfill_command(config, sender)
                )
            except LockfileNotFound as exc:
                # Client kapalıysa yığın izi yerine eyleme dönük mesaj göster.
                raise RuntimeError(msg("gui.backfill.no_lockfile", path=config.lol_dir)) from exc

        self.start_job(
            JOB_BACKFILL,
            work,
            on_done=lambda stats: self.append_log(format_backfill_summary(stats)),
        )

    # --- Dry-run → Uygula deseni (eşya + rol) ---

    def _start_dry_run_job(
        self,
        job: str,
        run: Callable[[bool, Config], Any],
        summarize: Callable[[Any], str],
    ) -> None:
        """ÖNCE dry-run koşar, özeti gösterir, "Uygula" onayıyla gerçeğini koşar."""
        config = self.require_config()
        if config is None:
            return

        def after_dry_run(stats: Any) -> None:
            summary = summarize(stats)
            self.append_log(summary)
            question = msg("gui.dry_run.question", summary=summary)
            if not self._ask_yes_no(msg("gui.dry_run.title"), question):
                self.append_log(msg("gui.dry_run.cancelled"))
                return
            self.start_job(
                job,
                lambda: run(False, config),
                on_done=lambda applied: self.append_log(
                    msg("gui.dry_run.applied", summary=summarize(applied))
                ),
            )

        self.append_log(msg("gui.dry_run.started"))
        self.start_job(job, lambda: run(True, config), on_done=after_dry_run)

    def on_items(self) -> None:
        self._start_dry_run_job(
            JOB_ITEMS,
            lambda dry, config: run_items_backfill(config, dry_run=dry),
            format_items_summary,
        )

    def on_positions(self) -> None:
        self._start_dry_run_job(
            JOB_POSITIONS,
            lambda dry, config: run_position_backfill(config, dry_run=dry),
            format_positions_summary,
        )

    # --- Ayarlar (sihirbaz; diyaloglar arayüz thread'inde koşmalıdır) ---

    def on_settings(self) -> None:
        if not self.state.can_start(JOB_SETTINGS):
            return
        self.state.start(JOB_SETTINGS)
        self.refresh_buttons()
        self.set_status(JOB_SETTINGS)
        console = DialogConsole(
            ask=self._ask_wizard, show=self._show_info, echo=self.append_log
        )
        try:
            run_wizard(input_fn=console.read, print_fn=console.write)
            console.flush()
            self.reload_config()
        except WizardCancelled:
            self.append_log(msg("gui.wizard.cancelled"))
        except SystemExit as exc:  # sihirbazın kontrollü iptali (ör. anahtar girilmedi)
            self.append_log(str(exc.code))
        except Exception as exc:  # noqa: BLE001
            log.exception("Wizard failed")
            self.append_log(msg("gui.job.failed", job=msg("gui.job.name.settings"), error=exc))
        finally:
            self.state.finish()
            self.refresh_buttons()
            self.set_status("idle")

    # ------------------------------------------------------------------ #
    # Kapanış
    # ------------------------------------------------------------------ #

    def on_close(self) -> None:
        if self.state.busy:
            job_name = msg(f"gui.job.name.{self.state.active}")
            if not self._ask_yes_no(
                msg("gui.close.title"), msg("gui.close.question", job=job_name)
            ):
                return
            self.stop_event.set()
        self.shutdown()

    def shutdown(self) -> None:
        logging.getLogger().removeHandler(self.log_handler)
        try:
            self.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def run(self) -> None:
        self.root.after(0, self.bootstrap)
        self.root.after(PUMP_INTERVAL_MS, self.pump)
        self.root.mainloop()


def run_gui() -> int:
    """Argümansız çalıştırmanın giriş noktası. tkinter yoksa `tkinter_available` False'tur."""
    app = CollectorApp()
    app.run()
    return 0
