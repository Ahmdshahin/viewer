#Requires -Version 5.1
<#
.SYNOPSIS  One-command MapViewer dev-server bootstrap (Windows).
.DESCRIPTION
  Installs Python/Node/Git via winget, clones the repo, builds everything,
  creates + restores the database, and generates SECRET_KEY.
  Run as Administrator. PostgreSQL 16 + PostGIS must already be installed
  (GUI installer + Stack Builder) because they need interactive setup.
.EXAMPLE
  .\bootstrap.ps1 -Backup C:\backups\Taqnen_data.dump -DbPassword "secret" -Target C:\Taqnen_System
#>
param(
  [Parameter(Mandatory = $true)][string]$Backup,
  [Parameter(Mandatory = $true)][string]$DbPassword,
  [string]$Target = "C:\Taqnen_System",
  [string]$Repo = "https://github.com/Ahmdshahin/viewer.git",
  [string]$DbHost = "localhost",
  [string]$DbPort = "5432",
  [string]$DbUser = "postgres",
  [string]$DbName = "Taqnen_data"
)

$ErrorActionPreference = "Stop"

function Have($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
              [Environment]::GetEnvironmentVariable("Path", "User")
}

Write-Host "[1/8] Prerequisites (winget)..."
if (-not (Have "python")) { winget install --id Python.Python.3.10 -e --accept-package-agreements --accept-source-agreements }
if (-not (Have "node"))   { winget install --id OpenJS.NodeJS.LTS -e --accept-package-agreements --accept-source-agreements }
if (-not (Have "git"))    { winget install --id Git.Git -e --accept-package-agreements --accept-source-agreements }
Refresh-Path
if (-not (Have "psql")) {
  $pg = Get-ChildItem "C:\Program Files\PostgreSQL" -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending | Select-Object -First 1
  if ($pg) { $env:Path += ";$($pg.FullName)\bin" }
}
foreach ($c in @("python", "node", "git", "psql")) {
  if (-not (Have $c)) { Write-Host "ERROR: $c not found. Install it, restart this shell, rerun."; exit 1 }
}
try { Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force } catch { }
$env:PGPASSWORD = $DbPassword

Write-Host "[2/8] Code..."
if (-not (Test-Path (Join-Path $Target ".git"))) {
  git clone $Repo $Target
}
Set-Location $Target
git pull --ff-only

Write-Host "[3/8] Python venv + requirements..."
if (-not (Test-Path "venv\Scripts\python.exe")) { python -m venv venv }
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r backend\requirements.txt

Write-Host "[4/8] Frontend build..."
Set-Location (Join-Path $Target "frontend")
& "$env:ProgramFiles\nodejs\npm.cmd" ci
& "$env:ProgramFiles\nodejs\npm.cmd" run build
Set-Location $Target

Write-Host "[5/8] Database..."
$exists = psql -h $DbHost -p $DbPort -U $DbUser -d postgres -tA -c "SELECT 1 FROM pg_database WHERE datname='$DbName'"
if ($exists -ne "1") { psql -h $DbHost -p $DbPort -U $DbUser -d postgres -c "CREATE DATABASE `"$DbName`"" }
psql -h $DbHost -p $DbPort -U $DbUser -d $DbName -c "CREATE EXTENSION IF NOT EXISTS postgis"
if ($Backup -like "*.sql") {
  psql -h $DbHost -p $DbPort -U $DbUser -d $DbName -f $Backup
} else {
  pg_restore -h $DbHost -p $DbPort -U $DbUser -d $DbName --clean --if-exists $Backup
}

Write-Host "[6/8] Admin seed..."
Set-Location (Join-Path $Target "backend")
..\venv\Scripts\python.exe seed_admin.py
Set-Location $Target

Write-Host "[7/8] SECRET_KEY..."
$secret = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 48 | ForEach-Object { [char]$_ })
[Environment]::SetEnvironmentVariable("SECRET_KEY", $secret, "User")

Write-Host "[8/8] Verify..."
$reqs = psql -h $DbHost -p $DbPort -U $DbUser -d $DbName -tA -c "SELECT count(*) FROM requests"
Write-Host "requests table rows: $reqs (expect ~10612 from your backup)"

Write-Host ""
Write-Host "Done. Start with: .\run_geoportal_prod.bat  ->  http://SERVER-IP:8000"
Write-Host "Login admin/admin123 and change the password immediately."
