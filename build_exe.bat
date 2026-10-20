@echo off
rem ORGBRO X3 Studio - Windows 11 x64 builder
rem   build_exe.bat           -> dist\ORGBRO_X3_Studio\ORGBRO_X3_Studio.exe (folder build, recommended)
rem   build_exe.bat onefile   -> dist\ORGBRO_X3_Studio.exe (single portable file, slower to start)
setlocal EnableExtensions
cd /d "%~dp0"

echo ==========================================
echo   ORGBRO X3 Studio - Windows 11 x64 Builder
echo ==========================================
echo.

for %%F in (orgbro_x3_studio.py orgbro_x3_protocol.py editor.html fonts vendor assets\icon.ico) do (
    if not exist "%%F" (
        echo ERROR: %%F was not found next to this BAT file.
        pause
        exit /b 1
    )
)

set "MODE=--onedir"
if /i "%~1"=="onefile" set "MODE=--onefile"

rem ---- Pick a 64-bit Python (3.12 preferred; pythonnet/pywebview support it best)
set "PY="
for %%V in (3.12-64 3.13-64 3.11-64 3.10-64) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
    )
)
if not defined PY (
    echo ERROR: No 64-bit Python 3.10 - 3.13 found.
    echo Install Python 3.12 x64 from https://www.python.org/downloads/windows/
    echo and tick "Add python.exe to PATH" during setup, then run this again.
    pause
    exit /b 1
)
echo Using: %PY%
%PY% --version

echo.
echo [1/5] Creating build environment (.venv)...
if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv
    if errorlevel 1 goto :error
)
set "VPY=%CD%\.venv\Scripts\python.exe"

echo.
echo [2/5] Installing packages...
"%VPY%" -m pip install --upgrade pip
"%VPY%" -m pip install --upgrade pyinstaller -r requirements.txt
if errorlevel 1 goto :error

echo.
echo [3/5] Running tests...
"%VPY%" -m unittest discover -s tests
if errorlevel 1 goto :error

echo.
echo [4/5] Cleaning old build...
if exist build rmdir /s /q build
if exist dist\ORGBRO_X3_Studio rmdir /s /q dist\ORGBRO_X3_Studio
if exist dist\ORGBRO_X3_Studio.exe del /q dist\ORGBRO_X3_Studio.exe
if exist ORGBRO_X3_Studio.spec del /q ORGBRO_X3_Studio.spec

echo.
echo [5/5] Building (%MODE%)...
"%VPY%" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  %MODE% ^
  --windowed ^
  --name "ORGBRO_X3_Studio" ^
  --icon "assets\icon.ico" ^
  --add-data "editor.html;." ^
  --add-data "fonts;fonts" ^
  --add-data "vendor;vendor" ^
  --add-data "assets;assets" ^
  --hidden-import serial.tools.list_ports ^
  --collect-all PIL ^
  --collect-all webview ^
  --collect-all clr_loader ^
  --collect-all pythonnet ^
  orgbro_x3_studio.py
if errorlevel 1 goto :error

echo.
echo ==========================================
echo   Finished!
if "%MODE%"=="--onefile" (
    echo   %CD%\dist\ORGBRO_X3_Studio.exe
) else (
    echo   %CD%\dist\ORGBRO_X3_Studio\ORGBRO_X3_Studio.exe
    echo   Keep the whole ORGBRO_X3_Studio folder together.
)
echo ==========================================
explorer "%CD%\dist"
pause
exit /b 0

:error
echo.
echo ==========================================
echo BUILD FAILED - scroll up for the first error.
echo ==========================================
pause
exit /b 1
