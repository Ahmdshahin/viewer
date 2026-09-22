# GeoPortal Test Suite Ready (`TEST_READY.md`)

## Overview
The comprehensive, opaque-box, requirement-driven E2E test suite for **GeoPortal** has been created in `backend/tests/` using `pytest`. The suite tests all system behaviors from public interfaces, database contracts, and HTTP endpoints without coupling to internal module implementations.

## Test Execution Command
To execute the complete GeoPortal test suite:
```bash
# From repository root (d:\Systems\MapViewer):
pytest -v backend/tests/

# Or run specific feature modules:
pytest -v backend/tests/test_db_migration.py
pytest -v backend/tests/test_auth_api.py
pytest -v backend/tests/test_layers_api.py
pytest -v backend/tests/test_analysis_api.py
pytest -v backend/tests/test_upload_pipeline.py
pytest -v backend/tests/test_e2e_scenarios.py
```

## Test Suite Architecture & Tier Breakdown
Total Test Cases: **85 tests**

| Test Module | Primary Targets | Tier 1 | Tier 2 | Tier 3/4 | Total |
|-------------|-----------------|:------:|:------:|:--------:|:-----:|
| `test_db_migration.py` | Schema, PostGIS, Counts, SRID, Area, GiST, Admin, Audit | 14 | 6 | - | 20 |
| `test_auth_api.py` | JWT Auth, /auth/login, /auth/me, RBAC, User CRUD | 9 | 8 | 1 | 18 |
| `test_layers_api.py` | GeoJSON EPSG:4326, BBox Filter, Attributes, Stats | 11 | 6 | - | 17 |
| `test_analysis_api.py` | Search (Req/Owner), AOI Intersect, Duplicates, Topology, Identify | 8 | 6 | - | 14 |
| `test_upload_pipeline.py` | ZIP Ingestion, PRJ Inheritance, Classification, Commit | 4 | 6 | - | 10 |
| `test_e2e_scenarios.py` | Cadastral Field Workflows (S1 to S5), Startup Script | - | - | 6 | 6 |
| **Total** | | **46** | **32** | **7** | **85** |

## Feature Coverage Matrix
| # | Feature | Target Endpoint / Contract | Test Module & Functions | Tier Coverage |
|---|---------|----------------------------|-------------------------|:-------------:|
| 1 | DB & PostGIS Schema | PostgreSQL connection, tables, PostGIS 3.5.3 | `test_db_migration.py` (`test_database_connection_and_postgis_extension`, `test_layer_tables_exist_in_public_schema`) | T1, T2 |
| 2 | Data Migration | 152 Land, 71 Eshghalat, 973 Points | `test_db_migration.py` (`test_feature_counts_exact_gpkg_migration`) | T1, T2 |
| 3 | Area Calculation | EPSG:32636 vs 3857, Feddan 4200.8333 constant | `test_db_migration.py` (`test_utm_planar_area_calculation_accuracy`, `test_egyptian_feddan_constant_conversion`, `test_total_dataset_area_reconciliation`) | T1, T2 |
| 4 | Geometry Normalization | Force 2D, MultiPolygon, MakeValid | `test_db_migration.py` (`test_spatial_storage_srid_is_utm_32636`, `test_geometry_types_normalized_to_multipolygon_and_point`, `test_geometry_forced_to_2d`, `test_geometry_validity_makevalid`) | T1, T2 |
| 5 | Seed Admin User | Login with `admin` / `admin123` | `test_db_migration.py` (`test_seed_admin_user_exists`), `test_auth_api.py` (`test_admin_login_success`) | T1, T2 |
| 6 | JWT Authentication | `POST /auth/login`, `GET /auth/me` | `test_auth_api.py` (`test_admin_login_success`, `test_get_current_user_profile`, `test_jwt_token_format_and_claims`, invalid credentials tests) | T1, T2 |
| 7 | Role-Based Access Control | 401 unauth, 403 viewer upload/edit | `test_auth_api.py` (`test_admin_has_full_administrative_access`, `test_editor_forbidden_from_user_management`, `test_viewer_forbidden_from_data_upload`) | T1, T2, T3 |
| 8 | User Management CRUD | `GET/POST/PUT/DELETE /users` | `test_auth_api.py` (`test_admin_user_crud_lifecycle`, `test_duplicate_username_creation_rejected`) | T1, T2 |
| 9 | GeoJSON Layer Serving | `GET /layers/{name}/geojson` with bbox | `test_layers_api.py` (`test_get_land_parcels_geojson`, `test_get_eshghalat_geojson`, `test_get_points_geojson`, `test_geojson_bbox_filtering`) | T1, T2 |
| 10 | Paginated Attributes | `GET /layers/{name}/attributes` sort/filter | `test_layers_api.py` (`test_paginated_attributes_default_limit`, `test_paginated_attributes_page_navigation`, `test_attribute_sorting_by_area`, `test_attribute_filtering_by_request_number`) | T1, T2 |
| 11 | Cadastral Search | `GET /search?q=...` request/owner | `test_analysis_api.py` (`test_search_by_exact_request_number`, `test_search_by_partial_request_number`, `test_search_by_arabic_owner_name`, injection resilience) | T1, T2 |
| 12 | Draw AOI Intersect | `POST /analysis/intersect` polygon | `test_analysis_api.py` (`test_draw_aoi_intersect_with_cadastral_cluster`, empty/invalid geometry tests) | T1, T2 |
| 13 | Duplication Detection | `POST /analysis/duplicates` overlap | `test_analysis_api.py` (`test_duplication_detection_in_land_parcels`) | T1, T2 |
| 14 | Topology Check | `POST /analysis/topology` gaps/overlaps | `test_analysis_api.py` (`test_topology_gap_and_overlap_check`) | T1, T2 |
| 15 | Upload Pipeline Ingestion | `POST /upload/validate` zip/shp parsing | `test_upload_pipeline.py` (`test_upload_validate_complete_shp_package`, missing sidecar tests) | T1, T2 |
| 16 | Upload PRJ Inheritance | Inherit polygon PRJ for point shp | `test_upload_pipeline.py` (`test_upload_validate_prj_inheritance_for_points`) | T1, T2 |
| 17 | Upload Commit & Audit | `POST /upload/commit` with audit log | `test_upload_pipeline.py` (`test_upload_commit_ingestion_and_audit_log`, rollback & role tests) | T1, T2 |
| 18 | Batch Startup Script | `run_geoportal.bat` accessibility | `test_e2e_scenarios.py` (`test_run_geoportal_bat_script_exists_and_content`) | T1 |

## Real-World Cadastral Application Scenarios (Tier 4)
| # | Scenario | Workflows Verified | Status |
|---|----------|---------------------|:------:|
| S1 | New Surveyor Ingestion Flow | Validate SHP package -> PRJ auto-inheritance -> Layer classification override -> Commit to PostGIS -> Verify Audit Trail | Ready |
| S2 | Encroachment & Conflict Investigation | Search parcel by owner name -> Zoom to bbox -> Identify overlapping Eshghalat (occupations) -> Run duplication detection | Ready |
| S3 | Field AOI Boundary Assessment | Draw polygon enclosing 10+ parcels -> Run `/analysis/intersect` -> Cross-verify against direct PostGIS `ST_Intersects` query | Ready |
| S4 | Multi-Role Security & Isolation | Admin creates Editor & Viewer -> Viewer attempts upload (403) -> Editor performs upload (200) -> Admin audits change log | Ready |
| S5 | Complete Cadastral Audit & Export | Retrieve paginated attribute table -> Sort by Area -> Filter by Zone code -> Verify area values against EPSG:32636 planar ground truth | Ready |

## Authoritative Test Oracle Ground Truth
The test assertions are backed by empirical values derived from `Unified_Database.gpkg`:
- **Land Parcels**: 152 features, total planar area = 996,467.54 m² (237.2071 Feddan).
- **Eshghalat (Occupations)**: 71 features, total planar area = 5,485.84 m² (1.3059 Feddan).
- **Survey Points**: 973 features.
- **Inter-layer Intersections**: 132 known intersections between `land_parcels` and `eshghalat`.
- **Known Overlap Test Vectors**:
  - `A-Z26-2608-02-00000069651` (overlaps itself by 349.29 m²)
  - `A-A27-2701-01-00000107390` with `A-A27-2701-01-00000107457` (overlaps by 158.84 m²)
- **Known Encroachment Test Vector**:
  - `A-A27-2701-01-00000011237` (37.05 m² intersection between Land and Eshghalat)

## Progressive Testability
During milestone execution (M1 through M6):
- If a subsystem has not yet been deployed, tests cleanly skip via fixtures without breaking the test runner.
- As M1 (DB migration) is completed, all 20 DB migration tests turn GREEN.
- As M2 (FastAPI backend core) is completed, auth and layer tests turn GREEN.
- As M3 (GIS analysis & upload) is completed, analysis, upload, and scenario tests turn GREEN.
- At Milestone 5 completion, 100% of the 85 tests execute and pass.
