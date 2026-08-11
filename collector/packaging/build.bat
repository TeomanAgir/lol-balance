@echo off
REM ===================================================================
REM  LoL Balance Collector — tek .exe derleme (GOREV 5)
REM  Kullanim:  collector\packaging\build.bat
REM  Cikti:     collector\packaging\dist\LoLBalanceCollector.exe
REM  Not: build venv'i AYRIDIR; backend\.venv'e PyInstaller kurulmaz.
REM ===================================================================
setlocal enabledelayedexpansion

set "HERE=%~dp0"
set "BUILD_VENV=%HERE%.build_venv"
set "REPO_ROOT=%HERE%..\.."
set "VENV_PY=%BUILD_VENV%\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo [1/3] Build venv olusturuluyor: %BUILD_VENV%
    set "BASE_PY=%REPO_ROOT%\backend\.venv\Scripts\python.exe"
    if not exist "!BASE_PY!" set "BASE_PY=python"
    "!BASE_PY!" -m venv "%BUILD_VENV%" || goto :fail
    "%VENV_PY%" -m pip install --upgrade pip || goto :fail
    "%VENV_PY%" -m pip install pyinstaller -r "%REPO_ROOT%\collector\requirements.txt" || goto :fail
) else (
    echo [1/3] Build venv hazir: %BUILD_VENV%
)

echo [2/3] Testler kosuluyor...
pushd "%REPO_ROOT%"
"%VENV_PY%" -m pytest collector -q || (popd & goto :fail)
popd

echo [3/3] PyInstaller (onefile) calisiyor...
"%VENV_PY%" -m PyInstaller --noconfirm --clean ^
    --distpath "%HERE%dist" ^
    --workpath "%HERE%build" ^
    "%HERE%collector.spec" || goto :fail

echo.
echo BITTI: %HERE%dist\LoLBalanceCollector.exe
for %%F in ("%HERE%dist\LoLBalanceCollector.exe") do echo Boyut: %%~zF bayt
echo Bu tek dosyayi arkadaslara gonderebilirsin (yanina .env KOYMA).
exit /b 0

:fail
echo.
echo HATA: derleme basarisiz (yukaridaki cikti).
exit /b 1
