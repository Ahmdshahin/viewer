# Original User Request

## 2026-09-19T13:36:33Z

# Teamwork Project Prompt — Draft

> Status: Step 9 — Ready for launch — awaiting user approval
> Goal: Craft prompt → get user approval → delegate to teamwork_preview
> Requested team: Full team (multi-component: backend, frontend, database, GIS tools, auth)

Build a production-grade **GeoPortal** web application for an Egyptian land survey team. The portal replaces an existing Streamlit prototype with a professional FastAPI + React stack backed by PostgreSQL/PostGIS. The system will be used concurrently by an entire team of about 20 individuals, so it must handle concurrent edits and queries efficiently. The UI must be bilingual (English + Arabic with a language switcher).

Working directory: d:\Systems\MapViewer
Integrity mode: development

### Existing Infrastructure (confirmed available)

- **PostgreSQL 16.9** running on `localhost:5432`, user: `postgres`, password: `postgres`
- **PostGIS 3.5.3** extension installed
- **Node.js v24.15.0** + npm 11.12.1
- **Python 3.10** at `C:\Program Files\Python310`
- **Existing data**: `Unified_Database.gpkg` at `d:\Systems\MapViewer\Unified_Database.gpkg` — a GeoPackage containing 3 layers:
  - `Land` — 152 MultiPolygon Z features (land parcels)
  - `Eshghalat` — 71 Polygon features (occupations)
  - `Point` — 973 Point Z features (survey points)
  - CRS: EPSG:32636 (WGS 84 / UTM zone 36N)
  - Columns: `Req_Number`, `Owner_Name`, `Layer_Type`, `Area_SQM`, `Area_Feddan`, `X`, `Y`
- **Original shapefile folders** at `d:\Systems\MapViewer\SHP_Files(2)` (58 folders) and `d:\Systems\MapViewer\SHP_Files(22)` (95 folders)
  - Folder naming: `A-{zone}-{code} - {owner_arabic_name}`
  - Files within: `land.shp`, `eshghalat.shp`, `POINT.shp` (with naming variants like `1land.shp .shp`)
- **Windows OS** — all scripts must work on Windows with PowerShell
- **Area units**: m² and Feddan (1 Feddan = 4200.833 m²)

### Known Bugs in Current Code (must be fixed in the rebuild)

1. Area calculation uses EPSG:3857 (Web Mercator) which inflates areas 28-35% at Egypt's latitude. Must use EPSG:32636 (UTM Zone 36N).
2. Point shapefiles missing `.prj` files — inherit CRS from polygon `.prj` in same folder.
3. Silent `except Exception: pass` in database append — must log errors properly.
4. Mixed 2D/3D geometries in same layer — force all to 2D before storage.
5. Polygon vs MultiPolygon type conflicts — normalize all polygons to MultiPolygon.
6. Layer classification uses area-only heuristic (largest = Land) — should also check filenames (`land.shp`, `eshghalat.shp`).
7. Centroid calculation can place point outside concave polygons — use `representative_point()`.
8. No data caching — recalculates on every page load.
9. "Mark as Fixed" conflict resolution doesn't actually re-validate data.

## Requirements

### R1. Database and Backend API

Create a PostgreSQL database called `geoportal` on `localhost:5432` with PostGIS extension. Build a FastAPI backend that provides:
- JWT authentication with role-based access (admin, editor, viewer)
- REST API endpoints for: user CRUD, layer data serving (GeoJSON with bbox filter), paginated attribute tables, spatial search, file upload, and spatial analysis
- Data migration from the existing `Unified_Database.gpkg` into PostGIS tables (land_parcels, eshghalat, points) with correct area calculations using EPSG:32636
- An audit trail table that records every data insert/update/delete with user, timestamp, and old/new values
- Seed an initial admin user: username `admin`, password `admin123`

### R2. React Frontend with Map Viewer

Build a React frontend with:
- Login page with JWT authentication
- Dashboard showing summary statistics (total parcels, total area, recent uploads)
- Interactive map viewer using a WebGL-based mapping library, displaying PostGIS layers over satellite and OpenStreetMap basemaps
- Layer controls: toggle visibility, change color/opacity per layer
- Bilingual UI (English + Arabic) with a language switcher

### R3. GIS Analysis Tools

Implement these spatial tools accessible from the map interface:
- **Search**: real-time search by request number or owner name — results highlight on map and zoom to extent
- **Draw AOI**: draw a polygon on the map → find and list all features that intersect it
- **Upload Polygon**: upload SHP/GeoJSON file → overlay on map → show intersecting/duplicate features
- **Identify**: click any map feature → popup showing all attributes and edit history
- **Duplication Detection**: find geometries that overlap within the same layer
- **Intersection Analysis**: compare two layers to find spatial intersections
- **Attribute Table**: full paginated, sortable, filterable table for each layer
- **Layer Symbology**: per-layer color, opacity, and visibility controls in a sidebar panel
- **Topology Check**: detect gaps and overlaps within a layer

### R4. Data Upload Pipeline

Build a 4-step upload wizard for adding new shapefile data to the database:
1. Upload: drag-and-drop ZIP/SHP files
2. Validate: check CRS, geometry validity, preview on map
3. Classify: auto-classify layers (largest polygon = Land, remaining = Eshghalat, points = Point) with manual override
4. Commit: calculate areas in UTM, write to PostGIS, create audit log entry

### R5. User Management and Edit Tracking

- Admin panel for creating/editing/deactivating users with roles (admin, editor, viewer)
- Viewers can see data but not upload or edit
- Editors can upload data and run analysis
- Admins can manage users and all other operations
- Every data change records: who, when, what table, what changed (old → new values)

## Acceptance Criteria

### Database
- [ ] PostgreSQL database `geoportal` exists with PostGIS extension enabled
- [ ] All 152 Land, 71 Eshghalat, and 973 Point features are migrated from the GPKG
- [ ] Area values are recalculated using EPSG:32636 (not EPSG:3857) — verify at least one parcel's area differs from the original GPKG value
- [ ] Spatial indexes exist on all geometry columns

### Backend API
- [ ] `POST /auth/login` returns a valid JWT token for valid credentials
- [ ] `GET /layers/{name}/geojson` returns valid GeoJSON with correct geometry and properties
- [ ] `GET /layers/{name}/attributes` returns paginated results with total count
- [ ] `POST /upload/validate` rejects invalid shapefiles with meaningful error messages
- [ ] `POST /analysis/intersect` correctly finds features within a given polygon
- [ ] API returns 401 for unauthenticated requests and 403 for unauthorized role access

### Frontend
- [ ] Login page authenticates and stores JWT — redirects to dashboard on success
- [ ] Map displays all three layers (Land, Eshghalat, Point) with satellite basemap
- [ ] Language switcher toggles between English and Arabic without page reload
- [ ] Draw AOI tool draws a polygon and shows intersecting features in a results panel
- [ ] Search by request number returns matching features and zooms map to result
- [ ] Attribute table shows paginated data with sorting and filtering
- [ ] Layer symbology controls change map layer appearance in real-time

### User Management
- [ ] Admin can create a new user via the admin panel
- [ ] New user can log in with created credentials
- [ ] Viewer role cannot access upload or edit endpoints (403)
- [ ] Edit history table records at least one audit entry after data upload

### Startup
- [ ] A single batch file `run_geoportal.bat` starts both backend and frontend
- [ ] Application is accessible at `http://localhost:3000` after running the batch file
- [ ] Default admin login works: username `admin`, password `admin123`

### Automated Tests
- [ ] Backend includes a test suite (pytest) covering auth, layer serving, and upload endpoints
- [ ] Running `pytest` from the backend directory passes all tests
