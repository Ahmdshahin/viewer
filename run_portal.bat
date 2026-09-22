@echo off
echo ===================================================
echo     GeoData Processor and Portal Setup
echo ===================================================

if exist venv goto skip_venv
echo [1/3] Creating Virtual Environment...
python -m venv venv

:skip_venv
echo [2/3] Activating and installing requirements...
call venv\Scripts\activate
pip install streamlit geopandas pandas folium streamlit-folium shapely pyogrio -q

echo [3/3] Starting Portal...
streamlit run geo_processor_app.py --server.address 127.0.0.1 --server.port 8501 --server.enableCORS false --server.enableXsrfProtection false
pause
