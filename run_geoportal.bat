@echo off
echo Starting GeoPortal...
cd backend
start cmd /k "..\venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000"
cd ..\frontend
start cmd /k "npm run dev"
echo GeoPortal is starting! API on :8000, Web on :3000

