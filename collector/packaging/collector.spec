# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — tek dosya (onefile) konsol uygulaması: LoLBalanceCollector.exe

Build:  collector/packaging/build.bat   (çıktı: collector/packaging/dist/)

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
    hiddenimports=["collector", "collector.__main__"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
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
    console=True,               # kullanıcı ne olduğunu görsün
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
