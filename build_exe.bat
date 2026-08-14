@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo   ORGBRO X3 - Windows EXE Builder
echo ==========================================
echo.

if not exist "orgbro_x3_ui.py" (
    echo ERROR: orgbro_x3_ui.py was not found in this folder.
    echo Put this BAT file next to orgbro_x3_ui.py and run it again.
    pause
    exit /b 1
)

echo [1/4] Installing/updating required packages...
py -m pip install --upgrade pyinstaller pillow pyserial
if errorlevel 1 goto :error

echo.
echo [2/4] Cleaning old build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist ORGBRO_X3_Printer.spec del /q ORGBRO_X3_Printer.spec

echo.
echo [3/4] Building EXE...
py -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name "ORGBRO_X3_Printer" ^
  --collect-all PIL ^
  --hidden-import serial.tools.list_ports ^
  orgbro_x3_ui.py

if errorlevel 1 goto :error

echo.
echo [4/4] Finished!
echo.
echo Your EXE is here:
echo %CD%\dist\ORGBRO_X3_Printer.exe
echo.
explorer "%CD%\dist"
pause
exit /b 0

:error
echo.
echo ==========================================
echo BUILD FAILED
echo ==========================================
echo Copy the error text and send it to ChatGPT.
pause
exit /b 1
