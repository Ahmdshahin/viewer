@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM  MapViewer - new Windows dev-server setup (run as Administrator
REM  from the repo root after cloning).
REM  Usage: setup_dev_server.bat [backup_file] [db_password]
REM    backup_file : .dump/.backup (pg_restore) or .sql (psql)
REM    db_password : postgres password on THIS machine
REM  What it does:
REM   1. checks python / node / psql
REM   2. creates venv + installs backend requirements
REM   3. builds the frontend (backend serves dist/ on :8000)
REM   4. creates the database, enables PostGIS, restores backup
REM   5. seeds the admin user if missing
REM ============================================================

if "%~1"=="" (
  echo Usage: setup_dev_server.bat [backup_file] [db_password]
  exit /b 1
)
set "BACKUP=%~1"
set "PGPASS=%~2"
if "%PGPASS%"=="" set "PGPASS=postgres"
if not exist "%BACKUP%" (
  echo [ERROR] Backup file not found: %BACKUP%
  exit /b 1
)

set "DB_HOST=localhost"
set "DB_PORT=5432"
set "DB_USER=postgres"
set "DB_NAME=Taqnen_data"
set "PGPASSWORD=%PGPASS%"

echo [*] Checking prerequisites...
python --version >nul 2>&1
if errorlevel 1 ( echo [ERROR] Python not found. Install Python 3.10+ and retry.; exit /b 1 )
node --version >nul 2>&1
if errorlevel 1 ( echo [ERROR] Node.js not found. Install Node 20+ and retry.; exit /b 1 )
where psql >nul 2>&1
if errorlevel 1 ( echo [ERROR] psql not found. Install PostgreSQL 16 + PostGIS and retry.; exit /b 1 )
python --version
node --version
psql --version

echo [*] Python venv...
if not exist "venv\Scripts\python.exe" (
  python -m venv venv
  if errorlevel 1 ( echo [ERROR] venv creation failed.; exit /b 1 )
)
echo [*] Installing backend requirements (takes a few minutes)...
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if errorlevel 1 ( echo [ERROR] pip install failed.; exit /b 1 )

echo [*] Building frontend...
cd frontend
call npm ci
if errorlevel 1 ( echo [ERROR] npm ci failed.; exit /b 1 )
call npm run build
if errorlevel 1 ( echo [ERROR] frontend build failed.; exit /b 1 )
cd ..

echo [*] Creating database %DB_NAME% (if missing)...
psql -h %DB_HOST% -p %DB_PORT% -U %DB_USER% -d postgres -c "SELECT 1 FROM pg_database WHERE datname='%DB_NAME%'" -tA | findstr /R "^1$" >nul
if errorlevel 1 (
  psql -h %DB_HOST% -p %DB_PORT% -U %DB_USER% -d postgres -c "CREATE DATABASE %DB_NAME%"
  if errorlevel 1 ( echo [ERROR] createdb failed. Check the db password.; exit /b 1 )
) else (
  echo [i] Database already exists, restoring into it.
)
psql -h %DB_HOST% -p %DB_PORT% -U %DB_USER% -d %DB_NAME% -c "CREATE EXTENSION IF NOT EXISTS postgis"

echo [*] Restoring backup...
echo "%BACKUP%" | findstr /I "\.sql$" >nul
if errorlevel 1 (
  pg_restore -h %DB_HOST% -p %DB_PORT% -U %DB_USER% -d %DB_NAME% --clean --if-exists "%BACKUP%"
) else (
  psql -h %DB_HOST% -p %DB_PORT% -U %DB_USER% -d %DB_NAME% -f "%BACKUP%"
)
if errorlevel 1 ( echo [ERROR] Restore failed.; exit /b 1 )

echo [*] Seeding admin user if missing...
cd backend
..\venv\Scripts\python.exe seed_admin.py
cd ..

echo.
echo ============================================
echo  Setup complete. Next steps:
echo   1. Copy Unified_Database.gpkg next to the repo or set GPKG_PATH,
echo      or copy your .gpkg files to this machine.
echo   2. Set a strong SECRET_KEY env var (do NOT keep the default).
echo   3. Change the admin password after first login (admin/admin123).
echo   4. Start: run_geoportal_prod.bat  -^> http://SERVER-IP:8000
echo ============================================
