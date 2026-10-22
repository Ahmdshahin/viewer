@echo off
REM Run the UI smoke check against the running dev stack (see run_dev.cmd).
REM Usage: run_e2e.cmd
setlocal
cd /d "%~dp0"
"%~dp0venv\Scripts\python.exe" "%~dp0e2e\smoke_ui.py"
exit /b %errorlevel%
