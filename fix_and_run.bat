@echo off
echo ===================================================
echo     إصلاح وإعادة بناء البوابة (Fixing Environment)
echo ===================================================

echo [1/4] إغلاق أي عمليات بايثون معلقة...
taskkill /F /IM python.exe /T >nul 2>&1

echo [2/4] مسح بيئة العمل القديمة التالفة...
if exist venv rmdir /S /Q venv

echo [3/4] إنشاء بيئة جديدة وتثبيت المكتبات بشكل نظيف...
python -m venv venv
call venv\Scripts\activate
pip install streamlit geopandas pandas folium streamlit-folium shapely pyogrio -q

echo [4/4] جاري تشغيل البوابة...
streamlit run geo_processor_app.py --server.address 127.0.0.1 --server.port 8501 --server.enableCORS false --server.enableXsrfProtection false
pause
