@echo off
REM ============================================================
REM  MapViewer - local development stack.
REM  Starts the FastAPI backend on :8000 and the Vite dev server
REM  on :5173 in their own windows, waits for both, then opens
REM  the app in the browser.
REM  Usage: run_dev.cmd   (from the repo root)
REM  Logs: %TEMP%\mapviewer-dev\backend.log, frontend.log
REM ============================================================
setlocal
set "ROOT=%~dp0"
set "LOGS=%TEMP%\mapviewer-dev"
if not exist "%LOGS%" mkdir "%LOGS%"

REM --- free the ports first (a previous run may still hold them)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do taskkill /PID %%p /F >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":5173 " ^| findstr "LISTENING"') do taskkill /PID %%p /F >nul 2>&1
timeout /t 1 /nobreak >nul

REM --- backend
start "MapViewer API" cmd /c "cd /d %ROOT%backend && %ROOT%venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload > %LOGS%\backend.log 2>&1"

REM --- frontend
start "MapViewer UI" cmd /c "cd /d %ROOT%frontend && npm run dev > %LOGS%\frontend.log 2>&1"

echo Waiting for the dev stack...
for /l %%i in (1,1,60) do (
  curl -s -o NUL http://127.0.0.1:8000/docs && curl -s -o NUL http://localhost:5173/ && goto ready
  timeout /t 1 /nobreak >nul
)
echo [ERROR] The stack did not come up - see %LOGS%
exit /b 1

:ready
echo.
echo   Backend : http://127.0.0.1:8000   (docs at /docs)
echo   Frontend: http://localhost:5173
echo   Login   : admin / admin123
echo.
start "" http://localhost:5173
endlocal
