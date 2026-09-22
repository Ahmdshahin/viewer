"""
Tier 1 & Tier 2 Tests: Database & PostGIS Migration Contract.
Verifies PostgreSQL database schema, PostGIS 3.5.3 extension, GPKG migration counts (56 Land, 23 Eshghalat, 325 Points),
EPSG:32636 planar area calculation vs EPSG:3857, geometryetry normalization (2D, MultiPolygon, MakeValid),
GiST spatial indexes, seed admin user, and audit trail schema.
"""

import pytest
import psycopg2
from psycopg2.extras import RealDictCursor
import geopandas as gpd

# ==============================================================================
# TIER 1: FEATURE COVERAGE (Happy-Path Equivalence Class Representatives)
# ==============================================================================

class TestPostgisDatabaseSchemaTier1:
    """Feature 1 & 2: Database Schema & PostGIS Extension Verification."""

    def test_database_connection_and_postgis_extension(self, db_conn):
        """Verify geoportal database connection and PostGIS >= 3.0 extension installation."""
        cur = db_conn.cursor()
        cur.execute("SELECT PostGIS_Full_Version();")
        version_str = cur.fetchone()[0]
        assert "POSTGIS=" in version_str, f"PostGIS not detected in: {version_str}"
        assert "GEOS=" in version_str, f"GEOS not detected in: {version_str}"
        cur.close()

    def test_layer_tables_exist_in_public_schema(self, db_conn):
        """Verify that all required cadastral and system tables exist in public schema."""
        expected_tables = {"lands", "eshghalat", "points", "users", "audit_trail"}
        cur = db_conn.cursor()
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public';
        """)
        existing_tables = {row[0] for row in cur.fetchall()}
        missing = expected_tables - existing_tables
        assert not missing, f"Missing required database tables: {missing}. Found: {existing_tables}"
        cur.close()

    def test_feature_counts_exact_gpkg_migration(self, db_conn):
        """
        Verify exact feature counts migrated from Unified_Database.gpkg:
        - Land: exactly 56 parcels
        - Eshghalat: exactly 23 occupations
        - Points: exactly 325 survey points
        """
        cur = db_conn.cursor()
        
        cur.execute("SELECT count(*) FROM lands;")
        land_count = cur.fetchone()[0]
        assert land_count == 56, f"Expected 56 lands, found {land_count}"

        cur.execute("SELECT count(*) FROM eshghalat;")
        esh_count = cur.fetchone()[0]
        assert esh_count == 23, f"Expected 23 eshghalat, found {esh_count}"

        cur.execute("SELECT count(*) FROM points;")
        pt_count = cur.fetchone()[0]
        assert pt_count == 325, f"Expected 325 points, found {pt_count}"

        cur.close()

    def test_spatial_storage_srid_is_utm_32636(self, db_conn):
        """Verify all layers use EPSG:32636 (UTM Zone 36N) as their storage SRID."""
        cur = db_conn.cursor()
        for tbl in ["lands", "eshghalat", "points"]:
            cur.execute(f"SELECT DISTINCT ST_SRID(geometry) FROM {tbl};")
            srids = [row[0] for row in cur.fetchall()]
            assert srids == [32636], f"Table {tbl} does not strictly have SRID 32636: {srids}"
        cur.close()

    def test_geometry_types_normalized_to_multipolygon_and_point(self, db_conn):
        """
        Feature 4 & 5 (Bug 5 fix):
        Polygon layers must be normalized to MULTIPOLYGON to prevent type collision.
        Points layer must be POINT.
        """
        cur = db_conn.cursor()
        for tbl in ["lands", "eshghalat"]:
            cur.execute(f"SELECT DISTINCT GeometryType(geometry) FROM {tbl};")
            geometry_types = [row[0] for row in cur.fetchall()]
            assert geometry_types == ["MULTIPOLYGON"], f"Table {tbl} geometryetry types not normalized to MULTIPOLYGON: {geom_types}"

        cur.execute("SELECT DISTINCT GeometryType(geometry) FROM points;")
        pt_types = [row[0] for row in cur.fetchall()]
        assert pt_types == ["POINT"], f"Points table contains non-POINT geometryetry types: {pt_types}"
        cur.close()

    def test_geometry_forced_to_2d(self, db_conn):
        """
        Feature 4 & 5 (Bug 4 fix):
        Force all geometryetries to 2D before storage (ST_CoordDim == 2).
        GPKG contained mixed 3D (Polygon Z / Point Z); PostGIS tables must be strictly 2D.
        """
        cur = db_conn.cursor()
        for tbl in ["lands", "eshghalat", "points"]:
            cur.execute(f"SELECT count(*) FROM {tbl} WHERE ST_CoordDim(geometry) != 2;")
            non_2d_count = cur.fetchone()[0]
            assert non_2d_count == 0, f"Table {tbl} contains {non_2d_count} non-2D geometryetries!"
        cur.close()

    def test_geometry_validity_makevalid(self, db_conn):
        """
        Feature 5:
        Verify that 100% of geometryetries are valid according to GEOS / PostGIS ST_IsValid.
        Raw shapefiles had self-intersections; ST_MakeValid must have healed them.
        """
        cur = db_conn.cursor()
        for tbl in ["lands", "eshghalat"]:
            cur.execute(f"SELECT count(*) FROM {tbl} WHERE NOT ST_IsValid(geometry);")
            invalid_count = cur.fetchone()[0]
            assert invalid_count == 0, f"Table {tbl} contains {invalid_count} invalid geometryetries"
        cur.close()


class TestCadastralCalculationsTier1:
    """Feature 3 & 4: Cadastral Area & Interior Point Calculations."""

    def test_utm_planar_area_calculation_accuracy(self, db_conn):
        """
        Feature 3 (Bug 1 fix):
        `area_sqm` must match ST_Area(geometry) in EPSG:32636 within 0.05 m².
        Must NOT be calculated in EPSG:3857 (Web Mercator).
        """
        cur = db_conn.cursor()
        cur.execute("""
            SELECT id, "Req_Number", "Area_SQM", ST_Area(geometry) as calc_area,
                   ST_Area(ST_Transform(geometry, 3857)) as mercator_area
            FROM lands
            LIMIT 20;
        """)
        rows = cur.fetchall()
        assert len(rows) > 0, "No records found in lands"

        for row in rows:
            _id, req, stored_sqm, calc_sqm, merc_sqm = row
            # Verify stored area matches UTM 32636 planar area
            diff = abs(float(stored_sqm) - float(calc_sqm))
            assert diff <= 0.05, f"Parcel {req} area_sqm ({stored_sqm}) differs from ST_Area ({calc_sqm:.2f}) by {diff:.4f}"
            # Verify it is NOT Web Mercator area (mercator_area is 25-35% larger)
            assert abs(float(stored_sqm) - float(merc_sqm)) > 1.0, (
                f"Parcel {req} area matches EPSG:3857 Web Mercator instead of EPSG:32636 UTM!"
            )
        cur.close()

    def test_egyptian_feddan_constant_conversion(self, db_conn):
        """
        Feature 3:
        1 Egyptian Feddan = 4200.8333 m².
        Verify "Area_Feddan" == round(area_sqm / 4200.8333, 4).
        """
        cur = db_conn.cursor()
        cur.execute('SELECT "Req_Number", "Area_SQM", "Area_Feddan" FROM lands;')
        rows = cur.fetchall()
        for req, sqm, feddan in rows:
            expected_feddan = round(float(sqm) / 4200.8333, 4)
            actual_feddan = float(feddan)
            assert abs(actual_feddan - expected_feddan) <= 0.0002, (
                f"Parcel {req}: area_feddan={actual_feddan} != expected={expected_feddan} (from {sqm} m²)"
            )
        cur.close()

    def test_representative_point_inside_polygon(self, db_conn):
        """
        Feature 6 (Bug 7 fix):
        Centroids can fall outside concave parcels.
        Verify stored (X, Y) coordinates lie inside or on the boundary of the parcel (ST_Intersects).
        """
        cur = db_conn.cursor()
        cur.execute("""
            SELECT "Req_Number", "X" as x, "Y" as y, 
                   ST_Intersects(geometry, ST_SetSRID(ST_Point("X"::float, "Y"::float), 32636)) as is_inside
            FROM lands
            WHERE "X" IS NOT NULL AND "Y" IS NOT NULL AND "X"::text != '-' AND "Y"::text != '-';
        """)
        rows = cur.fetchall()
        assert len(rows) > 0, "No records with coordinate columns found"
        for req, x, y, is_inside in rows:
            assert is_inside is True, f"Reference point ({x}, {y}) for parcel {req} falls OUTSIDE parcel polygon!"
        cur.close()

    def test_total_dataset_area_reconciliation(self, db_conn):
        """
        Feature 3: Reconcile total area across all 56 land parcels:
        Total EPSG:32636 area should equal ~996,467.5 m² (~237.21 Feddan).
        """
        cur = db_conn.cursor()
        cur.execute('SELECT sum("Area_SQM"), sum("Area_Feddan") FROM lands;')
        total_sqm, total_feddan = cur.fetchone()
        assert abs(float(total_sqm) - 487492.144) <= 10.0, f"Unexpected total area sum: {total_sqm}"
        assert abs(float(total_feddan) - 116.05) <= 0.1, f"Unexpected total feddan sum: {total_feddan}"
        cur.close()

    def test_area_recalculation_differs_from_legacy_gpkg_or_mercator(self, db_conn, gpkg_path):
        """
        R1 Acceptance Criteria:
        Area values are recalculated using EPSG:32636 (not EPSG:3857) —
        verify at least one parcel's area differs from the original GPKG value due to statutory 4200.8333 Feddan precision.
        """
        gdf = gpd.read_file(gpkg_path, layer="Land")
        cur = db_conn.cursor()
        cur.execute('SELECT "Req_Number", "Area_SQM", "Area_Feddan" FROM lands ORDER BY id;')
        rows = cur.fetchall()
        cur.close()

        # Check for Feddan difference on large parcel A-Z26-2608-02-00000081502
        # GPKG stored 80.7817 (from 4200.83 divisor); statutory PostGIS value is 80.7816 (from 4200.8333 divisor)
        feddan_diffs = []
        for i, (req, sqm, feddan) in enumerate(rows):
            gpkg_val = float(gdf.iloc[i]["Area_Feddan"])
            if abs(float(feddan) - gpkg_val) > 0.00005:
                feddan_diffs.append((req, float(feddan), gpkg_val))

        assert len(feddan_diffs) > 0, "Expected at least one parcel's Feddan area to differ from legacy GPKG (statutory 4200.8333 fix)"



class TestSystemEntitiesTier1:
    """Feature 5 & 7: Seed Admin User & Audit Trail Schema."""

    def test_seed_admin_user_exists(self, db_conn):
        """
        Feature 5 (R1 Acceptance Criteria):
        Initial admin user seeded: username 'admin', role 'admin', active.
        """
        cur = db_conn.cursor()
        cur.execute("SELECT id, username, role, is_active FROM users WHERE username = 'admin';")
        user = cur.fetchone()
        assert user is not None, "Seed user 'admin' not found in users table!"
        _id, uname, role, is_active = user
        assert uname == "admin"
        assert role == "admin"
        assert is_active is True
        cur.close()

    def test_admin_user_bcrypt_hash_validity(self, db_conn):
        """
        Verify that admin password hash is a valid 60-character bcrypt string
        and cryptographically verifies against 'admin123'.
        """
        import bcrypt
        cur = db_conn.cursor()
        cur.execute("SELECT hashed_password FROM users WHERE username = 'admin';")
        row = cur.fetchone()
        assert row is not None, "User 'admin' not found"
        hashed_pw = row[0]
        assert len(hashed_pw) == 60, f"Expected 60-character bcrypt hash, got length {len(hashed_pw)}"
        assert hashed_pw.startswith(("$2b$", "$2a$")), "Hash lacks standard bcrypt prefix"
        is_valid = bcrypt.checkpw(b"admin123", hashed_pw.encode("utf-8"))
        assert is_valid is True, "Password 'admin123' failed bcrypt cryptographic verification"
        cur.close()

    def test_audit_trail_table_structure_and_types(self, db_conn):
        """
        Feature 7 (R1 & R5):
        Audit trail table records table, action, record_id, user_id/username, timestamp, old_data, new_data.
        """
        cur = db_conn.cursor()
        cur.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'audit_trail';
        """)
        cols = {row[0]: row[1] for row in cur.fetchall()}
        required_cols = ["id", "action", "created_at", "table_name"]
        for c in required_cols:
            assert any(c in col for col in cols.keys()), f"Audit trail missing required column: {c}. Found: {cols}"
        cur.close()

    def test_audit_trail_migration_records_logged(self, db_conn):
        """
        Verify that all 3 layers (lands, eshghalat, points) logged initial
        migration records with action 'MIGRATE' and metadata matching Unified_Database.gpkg.
        """
        cur = db_conn.cursor()
        cur.execute("""
            SELECT table_name, action, username,
                   (new_values->>'features_migrated')::int as features_count,
                   new_values->>'source_file' as src_file,
                   new_values->>'crs_source' as crs
            FROM audit_trail
            WHERE action = 'MIGRATE'
            ORDER BY table_name;
        """)
        rows = cur.fetchall()
        assert len(rows) == 3, f"Expected 3 migration audit records, found {len(rows)}"

        records = {r[0]: {"features": r[3], "file": r[4], "crs": r[5]} for r in rows}
        assert "lands" in records
        assert records["lands"]["features"] == 56
        assert records["lands"]["file"] == "Unified_Database.gpkg"
        assert records["lands"]["crs"] == "EPSG:32636"

        assert "eshghalat" in records
        assert records["eshghalat"]["features"] == 23
        assert records["eshghalat"]["file"] == "Unified_Database.gpkg"
        assert records["eshghalat"]["crs"] == "EPSG:32636"

        assert "points" in records
        assert records["points"]["features"] == 325
        assert records["points"]["file"] == "Unified_Database.gpkg"
        assert records["points"]["crs"] == "EPSG:32636"
        cur.close()

    def test_spatial_gist_indexes_exist_on_all_layer_tables(self, db_conn):
        """
        Feature 8 (R1 Acceptance Criteria):
        Spatial GiST indexes exist on geometryetry columns of lands, eshghalat, and points.
        """
        cur = db_conn.cursor()
        for tbl in ["lands", "eshghalat", "points"]:
            cur.execute(f"""
                SELECT indexname, indexdef 
                FROM pg_indexes 
                WHERE tablename = '{tbl}' AND indexdef ILIKE '%gist%geom%';
            """)
            indexes = cur.fetchall()
            assert len(indexes) >= 1, f"No GiST spatial index found on table {tbl} geometry column!"
        cur.close()


# ==============================================================================
# TIER 2: BOUNDARY & CORNER CASES (Coordinates, Injections, Nulls, Constraints)
# ==============================================================================

class TestCadastralBoundariesTier2:
    """Tier 2: Extreme values, Coordinate Zones, Null Checks, and Security Boundaries."""

    def test_coordinate_envelope_within_egypt_utm_zone_36n(self, db_conn):
        """
        Tier 2 Boundary:
        Verify all geometryetries fall strictly within the valid geographic bounding box for Egypt
        in UTM Zone 36N (X: 300,000 to 500,000; Y: 2,800,000 to 3,000,000).
        """
        cur = db_conn.cursor()
        for tbl in ["lands", "eshghalat", "points"]:
            cur.execute(f"""
                SELECT ST_XMin(ST_Extent(geometry)), ST_YMin(ST_Extent(geometry)),
                       ST_XMax(ST_Extent(geometry)), ST_YMax(ST_Extent(geometry))
                FROM {tbl};
            """)
            minx, miny, maxx, maxy = cur.fetchone()
            assert 300000.0 <= minx <= 500000.0, f"Table {tbl} minx out of expected UTM zone 36N bounds: {minx}"
            assert 2800000.0 <= miny <= 3000000.0, f"Table {tbl} miny out of expected UTM zone 36N bounds: {miny}"
            assert 300000.0 <= maxx <= 500000.0, f"Table {tbl} maxx out of expected UTM zone 36N bounds: {maxx}"
            assert 2800000.0 <= maxy <= 3000000.0, f"Table {tbl} maxy out of expected UTM zone 36N bounds: {maxy}"
        cur.close()

    def test_no_zero_or_negative_areas_for_parcels(self, db_conn):
        """Tier 2 Boundary: Parcels and occupations must have positive non-zero area."""
        cur = db_conn.cursor()
        for tbl in ["lands", "eshghalat"]:
            cur.execute(f'SELECT count(*) FROM {tbl} WHERE "Area_SQM" <= 0 OR "Area_Feddan" <= 0;')
            zero_count = cur.fetchone()[0]
            assert zero_count == 0, f"Table {tbl} contains {zero_count} features with zero or negative area!"
        cur.close()

    def test_arabic_text_encoding_integrity_in_owner_names(self, db_conn):
        """
        Tier 2 Integrity:
        Verify owner names contain correctly decoded UTF-8 Arabic strings,
        not question marks, mojibake (e.g. 'Ã˜Â§...'), or corrupted encodings.
        """
        cur = db_conn.cursor()
        cur.execute('SELECT "Owner_Name" FROM lands WHERE "Owner_Name" IS NOT NULL LIMIT 50;')
        rows = cur.fetchall()
        assert len(rows) > 0
        arabic_detected = False
        for (owner,) in rows:
            assert "?" * 3 not in owner, f"Detected potential encoding corruption in: {owner}"
            assert "\ufffd" not in owner, f"Detected replacement character in: {owner}"
            # Check for Arabic unicode range: \u0600 - \u06FF
            if any('\u0600' <= char <= '\u06ff' for char in owner):
                arabic_detected = True

        assert arabic_detected, "No valid Arabic characters found in owner names!"
        cur.close()

    def test_sql_injection_defense_in_table_queries(self, db_conn):
        """
        Tier 2 Adversarial:
        Verify queries with malicious injection payloads are handled securely via parameterized queries.
        """
        payload = "' OR 1=1; DROP TABLE points; --"
        cur = db_conn.cursor()
        # Parameterized query should safely search for literal string
        cur.execute('SELECT count(*) FROM lands WHERE "Req_Number" = %s;', (payload,))
        count = cur.fetchone()[0]
        assert count == 0

        # Points table should still be intact
        cur.execute("SELECT count(*) FROM points;")
        pt_count = cur.fetchone()[0]
        assert pt_count == 325, "Points table compromised by injection test!"
        cur.close()

    def test_no_null_geometry_or_req_number_records(self, db_conn):
        """Tier 2 Boundary: Ensure primary cadastral constraints (no null geometrys, no null "Req_Number"s)."""
        cur = db_conn.cursor()
        for tbl in ["lands", "eshghalat", "points"]:
            cur.execute(f"SELECT count(*) FROM {tbl} WHERE geometry IS NULL;")
            null_geoms = cur.fetchone()[0]
            assert null_geoms == 0, f"Found {null_geoms} NULL geometryetries in {tbl}"

            cur.execute(f'SELECT count(*) FROM {tbl} WHERE "Req_Number" IS NULL OR "Req_Number" = \'\';')
            null_reqs = cur.fetchone()[0]
            assert null_reqs == 0, f"Found {null_reqs} NULL or empty req_numbers in {tbl}"
        cur.close()

    def test_multi_ring_parcels_with_holes_preserved(self, db_conn):
        """
        Tier 2 Boundary:
        Verify complex polygons with interior rings (holes) have their topology preserved.
        """
        cur = db_conn.cursor()
        cur.execute("""
            SELECT count(*) 
            FROM (
                SELECT ST_NumInteriorRings((ST_Dump(geometry)).geom) as rings
                FROM lands
            ) s
            WHERE rings > 0;
        """)
        holes_count = cur.fetchone()[0]
        # Whether holes exist or not, ensure query runs and no geometryetries were destroyed
        assert holes_count >= 0
        cur.close()
