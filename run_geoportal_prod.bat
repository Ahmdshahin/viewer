@echo off
setlocal enabledelayedexpansion
title Taqnen Geoprotal - Production Server
cd /d "%~dp0"

REM ============================================================
REM  Taqnen Geoprotal - Production one-command launcher
REM  Start your app from a single desktop shortcut.
REM  - Ensures PostgreSQL service is running
REM  - Builds the frontend if dist is missing
REM  - Serves API + built web app on 0.0.0.0:8000
REM ============================================================

set "APP_DIR=%CD%\backend"
set "HOST=0.0.0.0"
set "PORT=8000"

echo.
echo   ============================================
echo    Taqnen Geoprotal - Production Server
echo    %APP_DIR%
echo    http://%HOST%:%PORT%
echo   ============================================
echo.

REM ---- 1. Free the port: kill anything listening on %PORT% ----
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R ":%PORT% .*LISTENING"') do (
    echo [*] Killing PID %%P holding port %PORT% ...
    taskkill /F /PID %%P >nul 2>&1
)
taskkill /IM uvicorn.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul
netstat -ano | findstr /R ":%PORT% .*LISTENING" >nul 2>&1
if "!errorlevel!"=="0" (
    echo [ERROR] Port %PORT% is still occupied after terminating the process.
    echo         Close the program using this port manually, then run this file again.
    goto done
)

REM ---- 2. Make sure PostgreSQL is up ----
sc query postgresql-x64-16 | findstr /I "RUNNING" >nul 2>&1
if "!errorlevel!"=="0" goto pg_ok
echo [*] PostgreSQL service is not running, starting it...
net start postgresql-x64-16
:pg_ok

REM ---- 3. Build frontend if not built yet ----
if exist "%CD%\frontend\dist\index.html" goto fend_ok
echo [*] frontend\dist missing - building web app (first run only)...
pushd "%CD%\frontend"
call npm.cmd run build
popd
:fend_ok

REM ---- 4. Locate uvicorn (venv preferred) ----
set "UV="
if exist "%CD%\venv\Scripts\uvicorn.exe" set "UV=%CD%\venv\Scripts\uvicorn.exe"
if not defined UV if exist "%CD%\backend\venv\Scripts\uvicorn.exe" set "UV=%CD%\backend\venv\Scripts\uvicorn.exe"
if not defined UV if exist "%CD%\..\venv\Scripts\uvicorn.exe" set "UV=%CD%\..\venv\Scripts\uvicorn.exe"
if not defined UV (
    where uvicorn >nul 2>&1
    if "!errorlevel!"=="0" set "UV=uvicorn"
)

cd /d "%APP_DIR%"

echo [*] Starting server on %HOST%:%PORT% ...
if defined UV (
    start "Taqnen Geoprotal Server" cmd /k ""!UV!" app.main:app --host %HOST% --port %PORT%"
) else (
    start "Taqnen Geoprotal Server" cmd /k "python -m uvicorn app.main:app --host %HOST% --port %PORT%"
)

REM ---- 5. Open on this PC once it is up ----
for /l %%i in (1,1,15) do (
    timeout /t 1 /nobreak >nul
    netstat -ano | findstr /R ":%PORT% .*LISTENING" >nul 2>&1
    if "!errorlevel!"=="0" ( start "" "http://127.0.0.1:%PORT%" & goto done )
)

echo [*] Server is starting... open http://127.0.0.1:%PORT%

:done
echo.
echo   Access from this PC :  http://127.0.0.1:%PORT%
echo   Access from network :  http://<this-PC-IP>:%PORT%   (firewall: allow port %PORT%)
echo.
pause
