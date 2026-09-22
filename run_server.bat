@echo off
REM ===================================================
REM  GeoPortal backend launcher.
REM  Used by the Windows startup task (runs hidden).
REM  Portable: resolves paths from this file's location.
REM ===================================================
cd /d "%~dp0backend"
"%~dp0venv\Scripts\uvicorn.exe" app.main:app --host 0.0.0.0 --port 8000 >> "%~dp0backend\server.log" 2>&1
