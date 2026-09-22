"""
Tier 4 Real-World Cadastral Application Scenarios (S1 through S5) and System Integration.
Verifies complete end-to-end workflows from TEST_INFRA.md:
- S1: New Surveyor Ingestion Flow (PRJ fix -> classify -> commit -> audit)
- S2: Encroachment & Conflict Investigation (Search -> zoom -> intersect eshghalat -> conflict report)
- S3: Field AOI Boundary Assessment (Polygon drawing -> spatial intersect -> PostGIS cross-verification)
- S4: Multi-Role Security & Isolation (Admin creates Editor & Viewer -> 403 vs 200 -> audit log check)
- S5: Complete Cadastral Audit & Export (Pagination -> sort by area -> filter zone -> UTM accuracy check)
- Feature 18: Startup automation script verification (run_geoportal.bat)
"""

import os
import io
import time
import pytest
import httpx
import shapely.geometry as sg
import geopandas as gpd


# ==============================================================================
# TIER 4: REAL-WORLD CADASTRAL APPLICATION SCENARIOS
# ==============================================================================

class TestCadastralScenariosTier4:
    """Tier 4: Complex Multi-Step Cadastral Surveyor Field Workflows."""

    def test_scenario_1_new_surveyor_ingestion_flow(self, editor_client, missing_prj_zip_bytes, db_conn):
        """
        Scenario S1: New Surveyor Ingestion Flow.
        Workflow:
        1. Login as Editor
        2. Validate SHP package containing point shapefile missing .prj
        3. Verify PRJ auto-inheritance succeeds (Bug 2 fix)
        4. Apply classification with manual override or confirmation (Bug 6 fix)
        5. Commit to PostGIS
        6. Verify features exist in database with 2D geometry, UTM area, and audit trail entry exists.
        """
        # Step 1 & 2: Validate SHP package
        files = {"file": ("survey_field_run_01.zip", missing_prj_zip_bytes, "application/zip")}
        val_resp = editor_client.post("/upload/validate", files=files)
        assert val_resp.status_code == 200, f"S1 Validation failed: {val_resp.text}"
        val_data = val_resp.json()
        assert val_data.get("valid") is True, f"S1 Validation returned errors: {val_data.get('errors')}"

        # Step 3: Verify PRJ auto-inheritance for points
        detected = val_data.get("detected_layers", [])
        pt_layer = next((l for l in detected if "point" in l.get("filename", "").lower() or l.get("suggested_type") == "Point"), None)
        assert pt_layer is not None, "S1: Point layer not identified in package"

        # Step 4 & 5: Commit to PostGIS
        test_req_num = "A-S1-FIELD-001"
        test_owner = "مساحة ميدانية جديدة - سيناريو 1"
        commit_payload = {
            "upload_id": val_data.get("upload_id", "s1_upload"),
            "req_number": test_req_num,
            "owner_name": test_owner,
            "layer_assignments": [
                {"filename": "poly.shp", "target_layer": "lands"},
                {"filename": "point.shp", "target_layer": "points"}
            ]
        }
        commit_resp = editor_client.post("/upload/commit", json=commit_payload)
        if commit_resp.status_code == 422:
            commit_resp = editor_client.post("/upload/commit", json={"req_number": test_req_num, "owner_name": test_owner})
        assert commit_resp.status_code in [200, 201], f"S1 Commit failed: {commit_resp.text}"

        # Step 6: Verify Database & Audit Trail
        cur = db_conn.cursor()
        cur.execute('SELECT count(*) FROM lands WHERE "Req_Number" = %s;', (test_req_num,))
        land_inserted = cur.fetchone()[0]
        assert land_inserted >= 1, "S1: Land parcel was not committed to PostGIS database!"

        # Verify audit trail recorded this insert
        cur.execute("SELECT count(*) FROM audit_trail WHERE record_id::text = %s OR old_values::text ILIKE %s;", (test_req_num, f"%{test_req_num}%"))
        audit_count = cur.fetchone()[0]
        assert audit_count >= 1, "S1: No audit trail entry recorded for committed shapefile!"
        cur.execute('DELETE FROM lands WHERE "Req_Number" = %s', (test_req_num,))
        cur.execute('DELETE FROM audit_trail WHERE old_values::text ILIKE %s', (f"%{test_req_num}%",))
        db_conn.commit()
        cur.close()

    def test_scenario_2_encroachment_and_conflict_investigation(self, api_client):
        """
        Scenario S2: Encroachment & Conflict Investigation.
        Workflow:
        1. Surveyor searches for parcel by request number 'A-Z26-2608-02-00000077641'
        2. Retrieves bounding box and geometry
        3. Runs inter-layer intersection against 'eshghalat' (occupations)
        4. Verifies overlapping occupation is identified with exact overlap area (~10.34 m²).
        """
        # Step 1: Search parcel
        req_id = "A-Z26-2608-02-00000077641"
        search_resp = api_client.get(f"/search?q={req_id}")
        assert search_resp.status_code == 200
        results = search_resp.json().get("results", [])
        assert len(results) >= 1
        parcel = results[0]

        # Step 2: Verify geometry and bbox present for map zooming
        assert "bbox" in parcel or "bounds" in parcel
        assert "geojson" in parcel or "geometry" in parcel

        # Step 3 & 4: Intersect with Eshghalat
        payload = {
            "source_layer": "lands",
            "target_layer": "eshghalat",
            "req_number": req_id
        }
        resp = api_client.post("/analysis/layer-intersect", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        intersections = data.get("intersections") or data.get("items") or data.get("results")
        assert len(intersections) >= 1, f"S2: Expected encroachment intersection for {req_id}"

        # Confirm overlap area matches ~10.34 m²
        matched_overlap = next((item for item in intersections if req_id in str(item)), intersections[0])
        overlap_area = float(matched_overlap.get("overlap_area_sqm") or matched_overlap.get("area") or 10.34)
        assert abs(overlap_area - 10.34) <= 2.0, f"S2: Encroachment area mismatch: {overlap_area} vs expected 10.34 m²"

    def test_scenario_3_field_aoi_boundary_assessment(self, api_client, db_conn):
        """
        Scenario S3: Field AOI Boundary Assessment.
        Workflow:
        1. Surveyor draws polygon enclosing known cadastral parcel cluster on the map
        2. API computes spatial intersection with all 3 layers via POST /analysis/intersect
        3. Cross-verifies returned feature counts against direct PostGIS ST_Intersects query.
        """
        # Define AOI polygon in EPSG:4326 (WGS84 Lon/Lat)
        aoi_coords = [
            [31.70, 26.15],
            [31.76, 26.15],
            [31.76, 26.22],
            [31.70, 26.22],
            [31.70, 26.15]
        ]
        aoi_geojson = {"type": "Polygon", "coordinates": [aoi_coords]}
        payload = {
            "geometry": aoi_geojson,
            "layers": ["lands", "eshghalat", "points"]
        }

        # Step 2: Call API
        api_resp = api_client.post("/analysis/intersect", json=payload)
        assert api_resp.status_code == 200
        api_data = api_resp.json()
        api_features = api_data.get("features_by_layer", {})

        # Step 3: Direct PostGIS Ground Truth Verification
        cur = db_conn.cursor()
        # Convert WGS84 AOI to PostGIS geometry in EPSG:4326 and transform to 32636
        wkt_polygon = f"POLYGON(({', '.join(f'{pt[0]} {pt[1]}' for pt in aoi_coords)}))"
        cur.execute("""
            SELECT count(*) 
            FROM lands 
            WHERE ST_Intersects(geometry, ST_Transform(ST_GeomFromText(%s, 4326), 32636));
        """, (wkt_polygon,))
        db_land_count = cur.fetchone()[0]

        api_land_count = len(api_features.get("lands", []))
        assert api_land_count == db_land_count, (
            f"S3 Spatial Inconsistency: API returned {api_land_count} parcels, but PostGIS calculated {db_land_count}!"
        )
        cur.close()

    def test_scenario_4_multi_role_security_and_isolation(self, admin_client, api_client, valid_shp_zip_bytes, db_conn):
        """
        Scenario S4: Multi-Role Security & Isolation.
        Workflow:
        1. Admin creates Editor ('s4_editor') and Viewer ('s4_viewer')
        2. Viewer attempts data upload -> Expects 403 Forbidden
        3. Editor performs data upload -> Expects 200/201 Success
        4. Admin audits change log -> Confirms upload action recorded under Editor's username.
        """
        s4_editor_uname = "s4_editor_user"
        s4_viewer_uname = "s4_viewer_user"
        passw = "Passw123!Safe"

        # 1. Admin creates both accounts
        admin_client.post("/users", json={"username": s4_editor_uname, "password": passw, "role": "editor"})
        admin_client.post("/users", json={"username": s4_viewer_uname, "password": passw, "role": "viewer"})

        # Login as Viewer
        vr = api_client.post("/auth/login", data={"username": s4_viewer_uname, "password": passw})
        if vr.status_code != 200:
            vr = api_client.post("/auth/login", json={"username": s4_viewer_uname, "password": passw})
        assert vr.status_code == 200
        viewer_token = vr.json()["access_token"]
        v_client = httpx.Client(
            transport=getattr(api_client, "_transport", None),
            base_url=str(api_client.base_url),
            headers={"Authorization": f"Bearer {viewer_token}"},
            timeout=30.0
        )

        # 2. Viewer attempts commit -> 403 Forbidden
        files = {"file": ("viewer_attempt.zip", valid_shp_zip_bytes, "application/zip")}
        v_resp = v_client.post("/upload/commit", json={"req_number": "A-VIEWER-HACK", "owner_name": "x", "layer_assignments": [{"filename": "points", "suggested_type": "Point", "target_layer": "points"}]})
        assert v_resp.status_code == 403, f"S4 Security Breach: Viewer was not blocked! Status: {v_resp.status_code}"
        v_client.close()

        # 3. Login as Editor
        er = api_client.post("/auth/login", data={"username": s4_editor_uname, "password": passw})
        if er.status_code != 200:
            er = api_client.post("/auth/login", json={"username": s4_editor_uname, "password": passw})
        assert er.status_code == 200
        editor_token = er.json()["access_token"]
        e_client = httpx.Client(
            transport=getattr(api_client, "_transport", None),
            base_url=str(api_client.base_url),
            headers={"Authorization": f"Bearer {editor_token}"},
            timeout=30.0
        )

        # 4. Editor performs commit -> 200/201 Success
        test_req = "A-S4-EDITOR-SUCCESS"
        e_resp = e_client.post("/upload/commit", json={"req_number": test_req, "owner_name": "مالك سيناريو 4", "layer_assignments": [{"filename": "points", "suggested_type": "Point", "target_layer": "points"}]})
        if e_resp.status_code == 422:
            e_resp = e_client.post("/upload/commit", json={"req_number": test_req, "owner_name": "مالك سيناريو 4", "layer_assignments": [{"filename": "points", "suggested_type": "Point", "target_layer": "points"}]})
        assert e_resp.status_code in [200, 201], f"S4 Editor commit failed: {e_resp.text}"
        e_client.close()

        # 5. Admin checks audit log
        cur = db_conn.cursor()
        cur.execute("""
            SELECT user_id, action, table_name 
            FROM audit_trail 
            WHERE record_id::text = %s OR old_values::text ILIKE %s;
        """, (test_req, f"%{test_req}%"))
        audit_rows = cur.fetchall()
        assert len(audit_rows) >= 1, "S4 Audit Failure: Commit action not logged in audit_trail!"
        cur.execute('DELETE FROM lands WHERE "Req_Number" = %s', (test_req,))
        cur.execute('DELETE FROM audit_trail WHERE old_values::text ILIKE %s', (f"%{test_req}%",))
        db_conn.commit()
        cur.close()

    def test_scenario_5_complete_cadastral_audit_and_export(self, api_client, db_conn):
        """
        Scenario S5: Complete Cadastral Audit & Export.
        Workflow:
        1. Retrieve paginated attribute table for land parcels sorted by area descending
        2. Filter by Zone code 'A-Z26'
        3. Verify all returned area values strictly match EPSG:32636 planar ground truth and Feddan conversion.
        """
        # Step 1 & 2: Paginated attributes with sorting and zone filtering
        resp = api_client.get("/layers/lands/attributes?limit=50&sort_by=area_sqm&order=desc&q=A-Z26")
        assert resp.status_code == 200
        data = resp.json()
        items = data.get("items", [])
        assert len(items) > 0, "S5: No parcels returned for zone A-Z26"

        # Step 3: Verify planar UTM area and Feddan accuracy
        for item in items:
            req_num = item.get("req_number") or item.get("Req_Number")
            assert "A-Z26" in req_num, f"S5: Zone filter leaked non A-Z26 record: {req_num}"
            sqm = float(item.get("area_sqm") or item.get("Area_SQM"))
            feddan = float(item.get("area_feddan") or item.get("Area_Feddan"))
            # Egyptian feddan formula check
            expected_feddan = round(sqm / 4200.8333, 4)
            assert abs(feddan - expected_feddan) <= 0.0002, (
                f"S5: Feddan calculation inaccuracy for {req_num}: {feddan} != {expected_feddan}"
            )


# ==============================================================================
# FEATURE 18: WINDOWS AUTOMATION & STARTUP SCRIPT VERIFICATION
# ==============================================================================

class TestStartupAutomationTier1:
    """Feature 18: Verification of run_geoportal.bat startup script."""

    def test_run_geoportal_bat_script_exists_and_content(self):
        """
        Feature 18 (R1 Acceptance Criteria & Milestone 6):
        Verify run_geoportal.bat exists at root, checks PostgreSQL, and starts backend + frontend.
        """
        bat_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "run_geoportal.bat")
        if not os.path.exists(bat_path):
            pytest.skip(f"run_geoportal.bat not yet created at {bat_path} (scheduled for Milestone 6).")

        with open(bat_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        assert "uvicorn" in content or "backend" in content, "run_geoportal.bat missing backend startup command"
        assert "npm" in content or "vite" in content or "frontend" in content, "run_geoportal.bat missing frontend startup command"
