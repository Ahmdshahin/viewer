@echo off
REM ===================================================
REM  Run this ON THE SERVER inside the project folder.
REM  Pulls latest code, installs deps, rebuilds web app.
REM  Then restart the backend (service or run_geoportal.bat).
REM ===================================================

echo [1/3] Pulling latest code...
git pull
if errorlevel 1 (
  echo Git pull failed. Fix conflicts manually and re-run.
  pause
  exit /b 1
)

echo [2/3] Installing backend requirements...
call venv\Scripts\activate
pip install -r backend\requirements.txt -q

echo [3/3] Rebuilding frontend...
cd frontend
call npm install --no-audit --no-fund
call npm run build
cd ..

echo.
echo Done. Now restart the backend service (or run run_geoportal.bat).
pause
