# Project: GeoPortal Web Application

## Architecture
- **Backend**: FastAPI (Python 3.10) with SQLAlchemy / GeoAlchemy2 and psycopg2-binary.
- **Database**: PostgreSQL 16.9 with PostGIS 3.5.3 extension on `localhost:5432`.
- **Database Storage CRS**: `EPSG:32636` (WGS 84 / UTM Zone 36N).
- **GeoJSON Output CRS**: `EPSG:4326` (WGS 84 Lon/Lat).
- **Frontend**: React (TypeScript) initialized with Vite, using WebGL hardware-accelerated MapLibre GL JS (`maplibre-gl`).
- **Basemaps**: Esri World Imagery (satellite) and OpenStreetMap (raster/vector).
- **Localization**: Bilingual English / Arabic with zero-reload toggle, dynamic RTL/LTR direction, `Cairo` font, and LTR BiDi isolation for cadastral IDs.
- **Testing**: Dual-track architecture with independent opaque-box E2E testing track (Tiers 1-4) and white-box adversarial coverage hardening (Tier 5).
- **Startup**: Single Windows batch script `run_geoportal.bat` launching backend on port 8000 and frontend on port 3000.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F01 | PostgreSQL DB & PostGIS Extension | Create `geoportal` database on localhost:5432, enable PostGIS 3.5.3 | M1 | R1, survey |
| F02 | PostGIS Database Schema | Tables for `users`, `land_parcels`, `eshghalat`, `points`, `audit_trail` with 2D geometries & GiST spatial indexes | M1 | R1, survey |
| F03 | GPKG Data Migration | Migrate all 152 Land, 71 Eshghalat, 973 Point features from `Unified_Database.gpkg` | M1 | R1, survey |
| F04 | Accurate UTM Area Calculation | Calculate `area_sqm` in EPSG:32636 and `area_feddan` with Egyptian constant 4200.8333 (fix Bug 1) | M1 | Bug 1, R1 |
| F05 | Geometry Normalization & Repair | Force 2D (`ST_Force2D`), MultiPolygon normalization (`ST_Multi`), repair self-intersections (`ST_MakeValid`) (fix Bugs 4 & 5) | M1 | Bugs 4, 5 |
| F06 | Interior Coordinates | Use `ST_PointOnSurface` / `representative_point()` instead of centroid for concave parcels (fix Bug 7) | M1 | Bug 7 |
| F07 | Audit Trail Schema | Immutable table tracking table, action, record_id, user_id, timestamp, old_data, new_data | M1 | R1, R5 |
| F08 | Seed Admin User | Seed initial user `admin` with password `admin123` and role `admin` | M1 | R1 |
| F09 | JWT Auth & Password Hashing | Passlib/bcrypt hashing, PyJWT bearer token generation and verification | M2 | R1, R5 |
| F10 | Role-Based Access Control | Enforce admin, editor, viewer permissions with 401/403 HTTP statuses | M2 | R1, R5 |
| F11 | Auth Endpoints | `POST /auth/login` and `GET /auth/me` endpoints | M2 | R1 |
| F12 | User Management Endpoints | Admin CRUD for users: `GET /users`, `POST /users`, `PUT /users/{id}`, `DELETE /users/{id}` | M2 | R5 |
| F13 | Layer GeoJSON Serving | `GET /layers/{name}/geojson` with optional `bbox` query param filter in EPSG:4326 | M2 | R1 |
| F14 | Paginated Attribute Table API | `GET /layers/{name}/attributes` with pagination (limit/offset), sorting, filtering, total count | M2 | R1, R3 |
| F15 | Layer Summary Stats API | `GET /layers/{name}/stats` returning total counts, total area in SQM and Feddan | M2 | R2 |
| F16 | Audit Logging Service | Automatically record inserts, updates, and deletes with actor username and diffs | M2 | R1, R5 |
| F17 | Cadastral Search API | `GET /search?q=...` real-time search by request number or owner name | M3 | R3 |
| F18 | Draw AOI Intersection API | `POST /analysis/intersect` finding all features intersecting a user-supplied polygon | M3 | R3 |
| F19 | Duplication Detection API | `POST /analysis/duplicates` identifying overlapping parcels within the same layer | M3 | R3 |
| F20 | Inter-Layer Intersection API | `POST /analysis/layer-intersect` comparing two layers to find spatial intersections | M3 | R3 |
| F21 | Topology Gap & Overlap API | `POST /analysis/topology` detecting sliver gaps and overlaps within layer boundaries | M3 | R3 |
| F22 | Feature Identify & History API | `GET /features/{layer}/{id}` returning feature attributes and audit edit history | M3 | R3, R5 |
| F23 | Upload Pipeline: Ingestion | Step 1: ZIP/SHP drag-and-drop file upload handler | M3 | R4 |
| F24 | Upload Pipeline: Validation & PRJ Fix | Step 2: Validate CRS, inherit PRJ from polygon if missing on points (fix Bug 2), preview GeoJSON | M3 | Bug 2, R4 |
| F25 | Upload Pipeline: Classification | Step 3: Layer auto-classification by filename priority + area fallback with manual override (fix Bug 6) | M3 | Bug 6, R4 |
| F26 | Upload Pipeline: PostGIS Commit | Step 4: Normalization, UTM area calculation, PostGIS write, audit log entry | M3 | R4 |
| F27 | React App Architecture & Routing | Vite + React + TypeScript setup with clean routing (Login, Dashboard, Map) | M4 | R2 |
| F28 | Auth Context & Login Page | Professional login view storing JWT in localStorage/memory with redirection | M4 | R2 |
| F29 | Dashboard Statistics View | Summary cards: total parcels, total area (sqm/feddan), total points, recent uploads | M4 | R2 |
| F30 | WebGL MapLibre Map Viewer | 60 FPS WebGL map displaying Land, Eshghalat, and Point layers over basemaps | M4 | R2 |
| F31 | Satellite & OSM Basemaps | Basemap switcher between Esri World Imagery (satellite) and OpenStreetMap | M4 | R2 |
| F32 | Layer Symbology Sidebar | Visibility toggles, opacity sliders, and color pickers for each layer | M4 | R2, R3 |
| F33 | Bilingual Engine & Switcher | English/Arabic language switcher without page reload, dynamic text dictionary | M4 | R2 |
| F34 | Arabic RTL Layout & Typography | `dir="rtl"` dynamic switching, Cairo font, LTR BiDi isolation for request numbers | M4 | R2 |
| F35 | Real-time Search UI | Search bar querying `/search`, zoom to result extent (`fitBounds`), feature highlight | M4 | R3 |
| F36 | Draw AOI Tool UI | Interactive polygon drawing on map sending geometry to `/analysis/intersect` with results panel | M4 | R3 |
| F37 | Feature Identify Popup | Click map feature to display popup with attributes and audit trail history | M4 | R3 |
| F38 | Attribute Table Component | Full paginated, sortable, filterable modal/drawer table with layer selector | M4 | R3 |
| F39 | 4-Step Upload Wizard UI | Modal wizard: 1. Upload ZIP/SHP, 2. Preview & Validate, 3. Classify & Override, 4. Commit | M4 | R4 |
| F40 | Admin User Management Panel | Admin interface for listing, creating, editing, and deactivating user accounts | M4 | R5 |
| F41 | Spatial Analysis Panels UI | Dedicated panels for Duplication Detection, Topology Checks, and Inter-layer intersections | M4 | R3 |
| F42 | E2E Test Suite (Tiers 1-4) | Comprehensive opaque-box test suite passing 100% across all requirements | M5 | Acceptance |
| F43 | Adversarial Coverage Hardening | Tier 5 white-box stress testing, race conditions, edge-case coverage | M5 | Methodology |
| F44 | Windows Startup Script | `run_geoportal.bat` automating db check, backend uvicorn launch, frontend vite launch | M6 | Startup |
| F45 | Final Acceptance Verification | End-to-end verification of all 25 acceptance criteria checklist items | M6 | Acceptance |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Database Setup & PostGIS Migration | Create `geoportal` db, enable PostGIS, create tables, migrate all 152 Land, 71 Eshghalat, 973 Points from GPKG with UTM EPSG:32636 area recalculation, geometry repair, seed admin user | none | DONE |
| M2 | FastAPI Backend Core, Auth & Layer APIs | FastAPI app, JWT auth, RBAC, User CRUD, GeoJSON layer serving with bbox filter, paginated attribute tables, stats, audit logging | M1 | PLANNED |
| M3 | GIS Spatial Analysis & Upload Pipeline | Real-time search, Draw AOI intersect, duplication detection, topology check, identify history, 4-step upload wizard endpoints | M2 | PLANNED |
| M4 | React Frontend, WebGL Map Viewer & Bilingual UI | Vite React TS app, MapLibre GL JS, satellite/OSM basemaps, symbology controls, bilingual EN/AR with zero-reload switcher, search, draw AOI, attribute table, upload wizard UI, admin panel | M2, M3 | PLANNED |
| M5 | E2E Test Pass (Tiers 1-4) & Adversarial Hardening (Tier 5) | Execute test suite from E2E Testing Track; resolve all issues until 100% pass; run adversarial stress testing | M1, M2, M3, M4 | PLANNED |
| M6 | Windows Startup Script & Acceptance Verification | Create `run_geoportal.bat`, verify concurrent startup, verify all 25 acceptance criteria | M5 | PLANNED |

## Interface Contracts

### Backend API ↔ Database (PostGIS)
- **Geometry Storage**: Always 2D, SRID `32636`: `geometry(MultiPolygon, 32636)` for `land_parcels` and `eshghalat`, `geometry(Point, 32636)` for `points`.
- **Area Calculation**: `ST_Area(geom)` in square meters; `ROUND((ST_Area(geom) / 4200.8333)::numeric, 4)` in Feddan.
- **Coordinates**: `ST_X(ST_PointOnSurface(geom))` and `ST_Y(ST_PointOnSurface(geom))` for polygon reference points.
- **Spatial Index**: `CREATE INDEX idx_<table_name>_geom ON <table_name> USING GIST (geom);`.

### Frontend ↔ Backend REST API
- **Auth**: `POST /auth/login` with form data `username`, `password`. Returns `{"access_token": "<jwt>", "token_type": "bearer", "role": "admin|editor|viewer", "username": "admin"}`.
- **Protected Calls**: Header `Authorization: Bearer <jwt>`. Unauthenticated: 401. Unauthorized role: 403.
- **Layer GeoJSON**: `GET /layers/{layer_name}/geojson?bbox={minx,miny,maxx,maxy}`.
  Returns standard RFC 7946 GeoJSON `FeatureCollection` with coordinates in `EPSG:4326` (WGS84 Lon/Lat).
- **Attribute Table**: `GET /layers/{layer_name}/attributes?page=1&limit=50&sort_by=req_number&order=asc&q=search_term`.
  Returns `{"items": [...], "total": int, "page": int, "pages": int}`.
- **Search**: `GET /search?q={query}`.
  Returns `{"results": [{"id": int, "layer": str, "req_number": str, "owner_name": str, "area_sqm": float, "area_feddan": float, "bbox": [minx, miny, maxx, maxy], "geojson": {...}}]}`.
- **Draw AOI**: `POST /analysis/intersect` with body `{"geometry": <GeoJSON polygon>, "layers": ["land_parcels", "eshghalat", "points"]}`.
  Returns `{"total_features": int, "features_by_layer": {"land_parcels": [...], "eshghalat": [...], "points": [...]}}`.
- **Upload Validate**: `POST /upload/validate` (multipart/form-data with zip or shp files).
  Returns `{"valid": bool, "files": [...], "detected_crs": str, "detected_layers": [{"filename": str, "suggested_type": "Land"|"Eshghalat"|"Point", "feature_count": int, "has_prj": bool, "preview_geojson": {...}}], "errors": [...]}`.
- **Upload Commit**: `POST /upload/commit` with classified layer assignments.
  Returns `{"success": bool, "imported_counts": {"land_parcels": int, "eshghalat": int, "points": int}, "audit_id": int}`.

## Code Layout
```
d:\Systems\MapViewer\
├── backend\
│   ├── app\
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI application entry
│   │   ├── core\
│   │   │   ├── config.py        # Settings & DB URI
│   │   │   ├── security.py      # JWT & password hashing
│   │   ├── db\
│   │   │   ├── session.py       # SQLAlchemy engine & session maker
│   │   │   ├── models.py        # SQLAlchemy / GeoAlchemy2 models
│   │   │   ├── init_db.py       # DB creation & postgis extension
│   │   │   ├── migrate.py       # Unified_Database.gpkg migration script
│   │   ├── api\
│   │   │   ├── deps.py          # Auth dependencies (get_current_user, require_role)
│   │   │   ├── auth.py          # /auth endpoints
│   │   │   ├── users.py         # /users endpoints
│   │   │   ├── layers.py        # /layers endpoints (geojson, attributes, stats)
│   │   │   ├── search.py        # /search endpoint
│   │   │   ├── analysis.py      # /analysis endpoints (intersect, duplicates, topology)
│   │   │   ├── upload.py        # /upload endpoints (validate, commit)
│   │   ├── services\
│   │   │   ├── gis_service.py   # PostGIS spatial queries & conversions
│   │   │   ├── upload_service.py # Shapefile inspection, PRJ fix, normalization
│   │   │   ├── audit_service.py # Audit trail recording
│   ├── tests\
│   │   ├── conftest.py          # Test fixtures & test DB client
│   │   ├── test_auth.py         # Auth & RBAC tests
│   │   ├── test_layers.py       # Layer GeoJSON & attribute serving tests
│   │   ├── test_analysis.py     # Spatial analysis & intersection tests
│   │   ├── test_upload.py       # Upload validation & ingestion tests
│   ├── requirements.txt         # Backend Python dependencies
├── frontend\
│   ├── src\
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── context\
│   │   │   ├── AuthContext.tsx    # JWT auth state & user info
│   │   │   ├── LanguageContext.tsx# Bilingual EN/AR toggle & RTL management
│   │   ├── components\
│   │   │   ├── Navbar.tsx         # Navigation, language switcher, user info
│   │   │   ├── MapViewer.tsx      # MapLibre GL JS WebGL map container
│   │   │   ├── LayerSymbology.tsx # Layer visibility, color, opacity sidebar
│   │   │   ├── SearchBar.tsx      # Live cadastral search & map zoom
│   │   │   ├── DrawAOI.tsx        # Polygon drawing tool
│   │   │   ├── AttributeTable.tsx # Paginated data table modal
│   │   │   ├── UploadWizard.tsx   # 4-step shapefile upload wizard
│   │   │   ├── AnalysisPanel.tsx  # Duplicates & topology check panels
│   │   │   ├── AdminPanel.tsx     # User management modal
│   │   ├── i18n\
│   │   │   ├── translations.ts    # Complete EN/AR cadastral dictionary
│   │   ├── api\
│   │   │   ├── client.ts          # Axios / Fetch client with auth interceptor
│   ├── package.json
│   ├── vite.config.ts
├── run_geoportal.bat              # Windows startup automation
├── PROJECT.md                     # Master project architecture & milestones
└── TEST_INFRA.md                  # E2E test suite architecture & methodology
```
