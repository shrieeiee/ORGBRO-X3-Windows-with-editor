@echo off
rem Run ORGBRO X3 Studio from source (no EXE build needed).
setlocal EnableExtensions
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    set "PY="
    for %%V in (3.12-64 3.13-64 3.11-64 3.10-64) do (
        if not defined PY (
            py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
        )
    )
    if not defined PY (
        echo No 64-bit Python 3.10 - 3.13 found. Install Python 3.12 x64 from python.org.
        pause
        exit /b 1
    )
    call %%PY%% -m venv .venv
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

".venv\Scripts\python.exe" orgbro_x3_studio.py %*
if errorlevel 1 pause
