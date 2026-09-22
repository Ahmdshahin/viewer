"""
Pytest configuration and shared fixtures for GeoPortal E2E Test Suite.
Provides database connections, HTTP clients, auth tokens, and synthetic cadastral test data.
"""

import os
import sys
import io
import json
import zipfile
import tempfile
import pytest
import psycopg2
from psycopg2.extras import RealDictCursor
import httpx
import geopandas as gpd
import shapely.geometry as sg

# Ensure backend root is in sys.path so 'backend.app' can be imported if needed
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(TEST_DIR)
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Database Configuration Defaults
DB_HOST = os.getenv("GEOPORTAL_DB_HOST", "localhost")
DB_PORT = int(os.getenv("GEOPORTAL_DB_PORT", "5432"))
DB_USER = os.getenv("GEOPORTAL_DB_USER", "postgres")
DB_PASSWORD = os.getenv("GEOPORTAL_DB_PASSWORD", "postgres")
DB_NAME = os.getenv("GEOPORTAL_DB_NAME", "Taqnen_data")

# API Configuration Defaults
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
GPKG_PATH = os.path.join(PROJECT_ROOT, "Unified_Database.gpkg")


@pytest.fixture(scope="session")
def db_params():
    """Return dictionary of PostgreSQL connection parameters."""
    return {
        "host": DB_HOST,
        "port": DB_PORT,
        "user": DB_USER,
        "password": DB_PASSWORD,
        "dbname": DB_NAME,
    }


def is_db_available(params=None):
    """Check if PostgreSQL geoportal database is currently reachable."""
    if params is None:
        params = {
            "host": DB_HOST,
            "port": DB_PORT,
            "user": DB_USER,
            "password": DB_PASSWORD,
            "dbname": DB_NAME,
        }
    try:
        conn = psycopg2.connect(**params, connect_timeout=3)
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def check_db_available(db_params):
    """Fixture that verifies DB availability before running DB-dependent tests."""
    if not is_db_available(db_params):
        pytest.skip(
            f"Database '{db_params['dbname']}' on {db_params['host']}:{db_params['port']} "
            "is not accessible. Ensure PostgreSQL is running and M1 migration has been executed."
        )


@pytest.fixture(scope="function")
def db_conn(db_params, check_db_available):
    """
    Yields an active psycopg2 connection to the 'geoportal' database.
    Rolls back any uncommitted changes on teardown to maintain isolation.
    """
    conn = psycopg2.connect(**db_params)
    conn.autocommit = False
    try:
        yield conn
    finally:
        try:
            conn.rollback()
        except Exception:
            pass
        conn.close()


@pytest.fixture(scope="function")
def db_cursor(db_conn):
    """Yields a RealDictCursor for readable dictionary query results."""
    cursor = db_conn.cursor(cursor_factory=RealDictCursor)
    try:
        yield cursor
    finally:
        cursor.close()


def is_live_server_running(url=API_BASE_URL):
    """Check if a live GeoPortal FastAPI server is responding with expected OpenAPI paths."""
    try:
        r = httpx.get(f"{url}/openapi.json", timeout=1.5)
        if r.status_code == 200:
            data = r.json()
            paths = data.get("paths", {})
            # Confirm it's the GeoPortal backend API with /auth/login or /layers
            return "/auth/login" in paths or any("/layers/" in p for p in paths)
        return False
    except Exception:
        return False


def get_asgi_app():
    """Attempt to import the FastAPI app for in-process testing."""
    candidates = [
        "backend.app.main",
        "app.main",
    ]
    for candidate in candidates:
        try:
            mod = __import__(candidate, fromlist=["app"])
            if hasattr(mod, "app"):
                return getattr(mod, "app")
        except ImportError:
            continue
    return None


@pytest.fixture(scope="session")
def api_client():
    """
    Provides an HTTP test client (httpx.Client).
    Prefers live HTTP server at API_BASE_URL.
    Falls back to in-process ASGI TestClient if FastAPI app is importable.
    Skips if neither is available.
    """
    if is_live_server_running(API_BASE_URL):
        client = httpx.Client(base_url=API_BASE_URL, timeout=30.0)
        yield client
        client.close()
    else:
        app = get_asgi_app()
        if app is not None:
            from fastapi.testclient import TestClient
            client = TestClient(app, base_url="http://testserver")
            yield client
        else:
            pytest.skip(
                f"FastAPI backend is not running at {API_BASE_URL} and backend.app.main could not be imported. "
                "Run 'uvicorn backend.app.main:app' or run M2 implementation."
            )


@pytest.fixture(scope="session")
def admin_credentials():
    """Standard initial seed admin credentials from ORIGINAL_REQUEST.md."""
    return {"username": "admin", "password": "admin123"}


@pytest.fixture(scope="function")
def admin_token(api_client, admin_credentials):
    """
    Authenticate as admin and return JWT access token.
    Supports either form-data (OAuth2 standard) or JSON body.
    """
    resp = api_client.post("/auth/login", data=admin_credentials)
    if resp.status_code != 200:
        resp = api_client.post("/auth/login", json=admin_credentials)
    if resp.status_code != 200:
        pytest.fail(f"Admin login failed with status {resp.status_code}: {resp.text}")
    data = resp.json()
    assert "access_token" in data, f"Login response missing 'access_token': {data}"
    return data["access_token"]


def _create_auth_client(api_client, token):
    if hasattr(api_client, "app"):
        # It's a TestClient
        from fastapi.testclient import TestClient
        client = TestClient(api_client.app, base_url="http://testserver")
        client.headers["Authorization"] = f"Bearer {token}"
        return client
    else:
        # It's a live httpx client
        return httpx.Client(
            base_url=str(api_client.base_url),
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )

@pytest.fixture(scope="function")
def admin_client(api_client, admin_token):
    """Client pre-authenticated with Admin Bearer token."""
    client = _create_auth_client(api_client, admin_token)
    yield client
    if not hasattr(client, "app"): client.close()


@pytest.fixture(scope="function")
def editor_client(api_client, admin_client):
    """Client authenticated with Editor role (creates temporary editor user if needed)."""
    username = "test_editor_fixture"
    password = "editor_password_123"
    # Create user if doesn't exist
    admin_client.post("/users", json={
        "username": username,
        "password": password,
        "role": "editor",
        "full_name": "Test Editor"
    })
    # Login as editor
    resp = api_client.post("/auth/login", data={"username": username, "password": password})
    if resp.status_code != 200:
        resp = api_client.post("/auth/login", json={"username": username, "password": password})
    if resp.status_code != 200:
        pytest.skip(f"Could not login as editor: {resp.text}")
    token = resp.json().get("access_token")
    client = _create_auth_client(api_client, token)
    yield client
    if not hasattr(client, "app"): client.close()


@pytest.fixture(scope="function")
def viewer_client(api_client, admin_client):
    """Client authenticated with Viewer role (creates temporary viewer user if needed)."""
    username = "test_viewer_fixture"
    password = "viewer_password_123"
    # Create user if doesn't exist
    admin_client.post("/users", json={
        "username": username,
        "password": password,
        "role": "viewer",
        "full_name": "Test Viewer"
    })
    # Login as viewer
    resp = api_client.post("/auth/login", data={"username": username, "password": password})
    if resp.status_code != 200:
        resp = api_client.post("/auth/login", json={"username": username, "password": password})
    if resp.status_code != 200:
        pytest.skip(f"Could not login as viewer: {resp.text}")
    token = resp.json().get("access_token")
    client = _create_auth_client(api_client, token)
    yield client
    if not hasattr(client, "app"): client.close()


@pytest.fixture(scope="session")
def gpkg_path():
    """Return absolute path to Unified_Database.gpkg."""
    assert os.path.exists(GPKG_PATH), f"Unified_Database.gpkg not found at {GPKG_PATH}"
    return GPKG_PATH


@pytest.fixture(scope="session")
def valid_shp_zip_bytes():
    """
    Generate an in-memory ZIP package containing valid shapefiles:
    - land.shp (EPSG:32636 polygon)
    - eshghalat.shp (EPSG:32636 polygon)
    - point.shp (EPSG:32636 points)
    With all standard sidecar files (.shp, .shx, .dbf, .prj, .cpg).
    """
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory() as td:
        # Land polygon
        land_poly = sg.Polygon([(473800, 2898600), (473900, 2898600), (473900, 2898700), (473800, 2898700)])
        land_gdf = gpd.GeoDataFrame([
            {"Req_Number": "A-TEST-LAND-01", "Owner_Name": "محمود تجريبي", "geometry": land_poly}
        ], crs="EPSG:32636")
        land_gdf.to_file(os.path.join(td, "land.shp"), encoding="utf-8")

        # Eshghalat polygon
        esh_poly = sg.Polygon([(473820, 2898620), (473850, 2898620), (473850, 2898650), (473820, 2898650)])
        esh_gdf = gpd.GeoDataFrame([
            {"Req_Number": "A-TEST-LAND-01", "Owner_Name": "شاغل تجريبي", "geometry": esh_poly}
        ], crs="EPSG:32636")
        esh_gdf.to_file(os.path.join(td, "eshghalat.shp"), encoding="utf-8")

        # Points
        pt = sg.Point(473850, 2898650)
        pt_gdf = gpd.GeoDataFrame([
            {"Req_Number": "A-TEST-LAND-01", "Owner_Name": "محمود تجريبي", "geometry": pt}
        ], crs="EPSG:32636")
        pt_gdf.to_file(os.path.join(td, "point.shp"), encoding="utf-8")

        # Package into ZIP
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in os.listdir(td):
                z.write(os.path.join(td, f), arcname=f)

    buf.seek(0)
    return buf.getvalue()


@pytest.fixture(scope="session")
def missing_prj_zip_bytes():
    """
    Generate an in-memory ZIP package demonstrating Bug 2:
    - land.shp has .prj file
    - point.shp is MISSING its .prj file
    The pipeline must inherit the CRS from land.prj for point.shp.
    """
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory() as td:
        # Polygon with .prj
        poly = sg.Polygon([(473800, 2898600), (473900, 2898600), (473900, 2898700), (473800, 2898700)])
        poly_gdf = gpd.GeoDataFrame([
            {"Req_Number": "A-TEST-PRJ-01", "Owner_Name": "مالك اختبار", "geometry": poly}
        ], crs="EPSG:32636")
        poly_gdf.to_file(os.path.join(td, "poly.shp"), encoding="utf-8")

        # Point shapefile created with CRS then its .prj removed
        pt = sg.Point(473850, 2898650)
        pt_gdf = gpd.GeoDataFrame([
            {"Req_Number": "A-TEST-PRJ-01", "Owner_Name": "مالك اختبار", "geometry": pt}
        ], crs="EPSG:32636")
        pt_gdf.to_file(os.path.join(td, "point.shp"), encoding="utf-8")

        # Explicitly remove point.prj
        point_prj = os.path.join(td, "point.prj")
        if os.path.exists(point_prj):
            os.remove(point_prj)

        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in os.listdir(td):
                z.write(os.path.join(td, f), arcname=f)

    buf.seek(0)
    return buf.getvalue()


@pytest.fixture(scope="session")
def corrupted_zip_bytes():
    """Generate invalid ZIP bytes for boundary error testing."""
    return b"PK\x03\x04CORRUPTED_ZIP_BINARY_DATA_NOT_VALID"


@pytest.fixture(scope="session")
def missing_shx_zip_bytes():
    """
    Generate ZIP where shapefile has .shp, .dbf, .prj but is missing required .shx index.
    Should fail validation with informative error.
    """
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory() as td:
        poly = sg.Polygon([(473800, 2898600), (473900, 2898600), (473900, 2898700), (473800, 2898700)])
        gdf = gpd.GeoDataFrame([{"Req_Number": "A-TEST-01", "geometry": poly}], crs="EPSG:32636")
        gdf.to_file(os.path.join(td, "land.shp"))
        # Remove .shx
        shx_path = os.path.join(td, "land.shx")
        if os.path.exists(shx_path):
            os.remove(shx_path)

        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in os.listdir(td):
                z.write(os.path.join(td, f), arcname=f)

    buf.seek(0)
    return buf.getvalue()
