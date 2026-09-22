# E2E Test Infra: GeoPortal Web Application

## Test Philosophy
- Opaque-box, requirement-driven. Derived strictly from `ORIGINAL_REQUEST.md` and user-facing specifications.
- Complete coverage: Test every feature in `PROJECT.md § Feature Inventory`.
- Interface-compatible: Exercises HTTP REST endpoints, CLI, and database contracts without coupling to internal module implementations.
- Methodology: 4-Tier Opaque-Box Suite + Tier 5 Adversarial Coverage Hardening:
  - **Tier 1: Feature Coverage** (>=5 test cases per feature covering happy-path equivalence class representatives)
  - **Tier 2: Boundary & Corner Cases** (>=5 test cases per feature covering empty inputs, max sizes, coordinates out of UTM zone, invalid geometries, missing files)
  - **Tier 3: Cross-Feature Interactions** (pairwise coverage: auth + layer serving, upload + deduplication, search + intersect, role permissions across all endpoints)
  - **Tier 4: Real-World Cadastral Application Scenarios** (realistic field surveyor workflows, multi-user concurrent edits, bulk import, conflict identification)
  - **Tier 5: Adversarial Coverage Hardening** (white-box stress testing, race conditions, memory leaks, SQL injection, schema corruption resilience)

## Feature Inventory & Test Target Mapping
| # | Feature | Target Endpoint / Channel | Tier 1 | Tier 2 | Tier 3 |
|---|---------|---------------------------|:------:|:------:|:------:|
| 1 | DB & PostGIS Schema | PostgreSQL connection, tables, PostGIS ext | 5 | 5 | ✓ |
| 2 | Data Migration | 152 Land, 71 Eshghalat, 973 Point counts | 5 | 5 | ✓ |
| 3 | Area Calculation | EPSG:32636 vs 3857, Feddan 4200.8333 | 5 | 5 | ✓ |
| 4 | Geometry Normalization | Force 2D, MultiPolygon, MakeValid | 5 | 5 | ✓ |
| 5 | Seed Admin User | Login with `admin` / `admin123` | 5 | 5 | ✓ |
| 6 | JWT Authentication | POST /auth/login valid/invalid tokens | 5 | 5 | ✓ |
| 7 | Role-Based Access Control | 401 unauth, 403 viewer upload/edit | 5 | 5 | ✓ |
| 8 | User Management CRUD | GET/POST/PUT/DELETE /users | 5 | 5 | ✓ |
| 9 | GeoJSON Layer Serving | GET /layers/{name}/geojson with bbox | 5 | 5 | ✓ |
| 10 | Paginated Attributes | GET /layers/{name}/attributes sort/filter | 5 | 5 | ✓ |
| 11 | Cadastral Search | GET /search?q=... request/owner | 5 | 5 | ✓ |
| 12 | Draw AOI Intersect | POST /analysis/intersect polygon | 5 | 5 | ✓ |
| 13 | Duplication Detection | POST /analysis/duplicates overlap | 5 | 5 | ✓ |
| 14 | Topology Check | POST /analysis/topology gaps/overlaps | 5 | 5 | ✓ |
| 15 | Upload Pipeline Ingestion | POST /upload/validate zip/shp parsing | 5 | 5 | ✓ |
| 16 | Upload PRJ Inheritance | Inherit polygon PRJ for point shp | 5 | 5 | ✓ |
| 17 | Upload Commit & Audit | POST /upload/commit with audit log | 5 | 5 | ✓ |
| 18 | Batch Startup Script | run_geoportal.bat accessibility | 5 | 5 | ✓ |

## Test Architecture
- **Runner**: `pytest` run from backend test suite (`pytest -v backend/tests/`).
- **HTTP Client**: `httpx.AsyncClient` or `requests` hitting `http://localhost:8000` (or in-process ASGI TestClient).
- **Database Client**: `psycopg2` directly verifying PostGIS tables, GiST indexes, and audit log entries.
- **Pass/Fail Semantics**: 100% pass required; exit code 0.

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| S1 | New Surveyor Ingestion Flow | Login -> Validate SHP package -> PRJ auto-inheritance -> Layer classification override -> Commit to PostGIS -> Verify Audit Trail | High |
| S2 | Encroachment & Conflict Investigation | Login -> Search parcel by owner name -> Zoom to bbox -> Identify overlapping Eshghalat (occupations) -> Run duplication detection | High |
| S3 | Field AOI Boundary Assessment | Login -> Draw polygon enclosing 10+ parcels -> Run /analysis/intersect -> Verify returned feature counts and properties match spatial query | Medium |
| S4 | Multi-Role Security & Isolation | Admin creates Editor & Viewer -> Viewer attempts upload (403) -> Editor performs upload (200) -> Admin audits change log | High |
| S5 | Complete Cadastral Audit & Export | Retrieve paginated attribute table -> Sort by Area -> Filter by Zone code -> Verify area values against EPSG:32636 planar ground truth | Medium |

## Coverage Thresholds
- Tier 1: >=5 per feature
- Tier 2: >=5 per feature (boundary and error conditions)
- Tier 3: Pairwise combinations across auth, layers, analysis, and uploads
- Tier 4: >=5 realistic end-to-end application scenarios
- Tier 5: Adversarial stress and integrity verification
