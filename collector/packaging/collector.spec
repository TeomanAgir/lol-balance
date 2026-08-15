# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — tek dosya (onefile) PENCERE uygulaması: LoLBalanceCollector.exe

Build:  collector/packaging/build.bat   (çıktı: collector/packaging/dist/)

GÖREV 16 Faz C: exe artık `--windowed` (console=False) derlenir — çift tıklayan
kullanıcı siyah konsol yerine tkinter penceresini görür. Sonuçları:
- `tkinter` excludes listesinden ÇIKARILDI (arayüzün tek bağımlılığı).
- Konsol YOKTUR: `sys.stdout`/`sys.stdin` `None` olabilir. `print()` bu durumda
  sessizdir; `input()` çağrılmaz (`__main__._pause_if_frozen` kontrol eder).
- CLI komutları (`LoLBalanceCollector.exe backfill` vb.) çalışmaya DEVAM eder,
  yalnız çıktıları görünmez — bkz. collector/packaging/README.md.

Not: onefile'da paket dosyaları her çalıştırmada geçici `sys._MEIPASS` dizinine
açılır. Bu yüzden .env / raw_archive / outbox oraya DEĞİL, exe'nin yanına yazılır —
bkz. `collector/config.py: app_dir()` ve docs/CHANGE_REQUESTS.md (GÖREV 5).
"""

from pathlib import Path

SPEC_DIR = Path(SPECPATH).resolve()          # collector/packaging
REPO_ROOT = SPEC_DIR.parent.parent           # repo kökü ('collector' paketi buradan import edilir)

a = Analysis(
    [str(SPEC_DIR / "entry.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "collector",
        "collector.__main__",
        "collector.i18n",
        # Arayüz gecikmeli import edilir (gui.py fonksiyon gövdelerinde):
        # PyInstaller statik analizde göremez, elle bildirilir.
        "collector.gui",
        "tkinter",
        "tkinter.messagebox",
        "tkinter.scrolledtext",
        "tkinter.simpledialog",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "unittest",
        "pytest",
        "numpy",
        "matplotlib",
        "PIL",
        "PyQt5",
        "PySide6",
        "IPython",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="LoLBalanceCollector",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,              # --windowed: log artık pencerenin İÇİNDE (GÖREV 16)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
