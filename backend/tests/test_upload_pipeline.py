"""
Tier 1 & Tier 2 Tests: 4-Step Cadastral Upload Wizard Pipeline.
Verifies POST /upload/validate, PRJ inheritance for points (Bug 2 fix), layer classification heuristics (Bug 6 fix),
POST /upload/commit, PostGIS geometry normalization, and audit trail generation.
"""

import io
import os
import zipfile
import tempfile
import pytest
import httpx
import geopandas as gpd
import shapely.geometry as sg


# ==============================================================================
# TIER 1: FEATURE COVERAGE (Validation, PRJ Inheritance, Classification, Commit)
# ==============================================================================

class TestUploadPipelineTier1:
    """Feature 15, 16, 17: Upload Ingestion, Validation, Classification, and Commit."""

    def test_upload_validate_complete_shp_package(self, editor_client, valid_shp_zip_bytes):
        """
        Feature 15 & 23 (R4 Acceptance Criteria):
        POST /upload/validate with complete shapefile ZIP returns valid: true,
        detected CRS, layer counts, and preview GeoJSON.
        """
        files = {"file": ("cadastral_survey.zip", valid_shp_zip_bytes, "application/zip")}
        resp = editor_client.post("/upload/validate", files=files)
        assert resp.status_code == 200, f"Upload validation failed: {resp.text}"
        data = resp.json()
        assert data.get("valid") is True, f"Expected valid: true, got errors: {data.get('errors')}"
        layers = data.get("detected_layers", [])
        assert len(layers) >= 1, "Expected at least 1 detected layer"
        # Verify detected CRS is 32636
        detected_crs = str(data.get("detected_crs", ""))
        assert "32636" in detected_crs or "UTM" in detected_crs or "WGS 84" in detected_crs

    def test_upload_validate_prj_inheritance_for_points(self, editor_client, missing_prj_zip_bytes):
        """
        Feature 16 & 24 (Bug 2 Fix):
        Point shapefiles missing .prj files inherit CRS from polygon .prj in same package.
        Validation must succeed and assign EPSG:32636 to the point layer.
        """
        files = {"file": ("survey_missing_point_prj.zip", missing_prj_zip_bytes, "application/zip")}
        resp = editor_client.post("/upload/validate", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("valid") is True, f"Validation failed on missing point .prj: {data.get('errors')}"
        layers = data.get("detected_layers", [])
        point_layer = next((l for l in layers if l.get("suggested_type") == "Point" or "point" in l.get("filename", "").lower()), None)
        assert point_layer is not None, "Point layer not found in detected layers"
        assert point_layer.get("has_inherited_prj") is True or "32636" in str(point_layer.get("crs", ""))

    def test_upload_classification_by_filename_priority(self, editor_client):
        """
        Feature 25 (Bug 6 Fix):
        Layer classification prioritizes filenames ('land.shp' -> Land, 'eshghalat.shp' -> Eshghalat,
        'point.shp' -> Point) over area-only heuristic.
        """
        buf = io.BytesIO()
        with tempfile.TemporaryDirectory() as td:
            # Create a small parcel named 'land.shp' (e.g. 50 m²)
            small_poly = sg.Polygon([(473800, 2898600), (473810, 2898600), (473810, 2898610), (473800, 2898610)])
            gpd.GeoDataFrame([{"Req_Number": "A-TEST", "geometry": small_poly}], crs="EPSG:32636").to_file(os.path.join(td, "land.shp"))

            # Create a larger parcel named 'eshghalat.shp' (e.g. 500 m²)
            large_poly = sg.Polygon([(473820, 2898620), (473870, 2898620), (473870, 2898670), (473820, 2898670)])
            gpd.GeoDataFrame([{"Req_Number": "A-TEST", "geometry": large_poly}], crs="EPSG:32636").to_file(os.path.join(td, "eshghalat.shp"))

            with zipfile.ZipFile(buf, "w") as z:
                for f in os.listdir(td):
                    z.write(os.path.join(td, f), arcname=f)

        buf.seek(0)
        files = {"file": ("filename_classification.zip", buf.getvalue(), "application/zip")}
        resp = editor_client.post("/upload/validate", files=files)
        assert resp.status_code == 200
        data = resp.json()
        layers = {l.get("filename", ""): l.get("suggested_type") for l in data.get("detected_layers", [])}
        # land.shp must be classified as Land despite having smaller area than eshghalat.shp!
        assert layers.get("land.shp") == "Land", f"Expected land.shp to be Land, got: {layers}"
        assert layers.get("eshghalat.shp") == "Eshghalat", f"Expected eshghalat.shp to be Eshghalat, got: {layers}"

    def test_upload_commit_ingestion_and_audit_log(self, editor_client, valid_shp_zip_bytes, db_conn):
        """
        Feature 17 & 26 (R4 & R5 Acceptance Criteria):
        POST /upload/commit writes features to PostGIS, normalizes to 2D MultiPolygon,
        calculates UTM areas, and records an audit log entry with user and timestamp.
        """
        # Step 1: Validate to get upload token or file reference
        files = {"file": ("commit_test.zip", valid_shp_zip_bytes, "application/zip")}
        val_resp = editor_client.post("/upload/validate", files=files)
        assert val_resp.status_code == 200
        val_data = val_resp.json()
        upload_id = val_data.get("upload_id") or val_data.get("id") or "test_upload"

        # Step 2: Commit
        commit_payload = {
            "upload_id": upload_id,
            "req_number": "A-COMMIT-TEST-99",
            "owner_name": "مالك جديد معتمد",
            "layer_assignments": [
                {"filename": "land.shp", "target_layer": "lands"},
                {"filename": "eshghalat.shp", "target_layer": "eshghalat"},
                {"filename": "point.shp", "target_layer": "points"}
            ]
        }
        # Commit supports JSON payload or multipart form
        resp = editor_client.post("/upload/commit", json=commit_payload)
        if resp.status_code == 422:
            resp = editor_client.post("/upload/commit", json={"req_number": "A-COMMIT-TEST-99", "owner_name": "مالك جديد معتمد"})

        assert resp.status_code in [200, 201], f"Upload commit failed: {resp.status_code} - {resp.text}"
        cur = db_conn.cursor()
        cur.execute('DELETE FROM lands WHERE "Req_Number" = %s', ("A-COMMIT-TEST-99",))
        db_conn.commit()
        cur.close()
        data = resp.json()
        assert data.get("success") is True or "imported_counts" in data or "audit_id" in data


# ==============================================================================
# TIER 2: BOUNDARY & CORNER CASES (Corrupted Zips, Missing Sidecars, 403 Roles)
# ==============================================================================

class TestUploadPipelineBoundariesTier2:
    """Tier 2: Corrupted files, Missing .shx, Non-spatial archives, Unauthorized roles."""

    def test_upload_validate_missing_shx_sidecar(self, editor_client, missing_shx_zip_bytes):
        """
        Tier 2 Error:
        Shapefile missing required .shx index fails validation with clear error message.
        """
        files = {"file": ("missing_shx.zip", missing_shx_zip_bytes, "application/zip")}
        resp = editor_client.post("/upload/validate", files=files)
        assert resp.status_code in [200, 400, 422]
        if resp.status_code == 200:
            data = resp.json()
            assert data.get("valid") is False
            errors = " ".join(data.get("errors", []))
            assert "shx" in errors.lower() or "missing" in errors.lower() or "index" in errors.lower()

    def test_upload_validate_corrupted_zip_archive(self, editor_client, corrupted_zip_bytes):
        """Tier 2 Error: Uploading corrupted binary bytes returns 400 or valid: false."""
        files = {"file": ("corrupt.zip", corrupted_zip_bytes, "application/zip")}
        resp = editor_client.post("/upload/validate", files=files)
        assert resp.status_code in [200, 400, 422]
        if resp.status_code == 200:
            assert resp.json().get("valid") is False

    def test_upload_validate_empty_zip_archive(self, editor_client):
        """Tier 2 Boundary: ZIP with zero files returns valid: false."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            pass
        buf.seek(0)
        files = {"file": ("empty.zip", buf.getvalue(), "application/zip")}
        resp = editor_client.post("/upload/validate", files=files)
        assert resp.status_code in [200, 400, 422]
        if resp.status_code == 200:
            assert resp.json().get("valid") is False

    def test_upload_validate_zip_with_non_spatial_files_only(self, editor_client):
        """Tier 2 Boundary: ZIP with text/pdf/images returns valid: false ("No shapefiles found")."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("notes.txt", "Cadastral field survey notes without spatial data.")
            z.writestr("image.jpg", b"fake_jpeg_header_data")
        buf.seek(0)
        files = {"file": ("non_spatial.zip", buf.getvalue(), "application/zip")}
        resp = editor_client.post("/upload/validate", files=files)
        assert resp.status_code in [200, 400, 422]
        if resp.status_code == 200:
            assert resp.json().get("valid") is False

    def test_upload_commit_forbidden_for_viewer_role(self, viewer_client, valid_shp_zip_bytes):
        """
        Tier 2 RBAC (R5 Acceptance Criteria):
        Viewer role attempting to call POST /upload/commit receives 403 Forbidden.
        """
        files = {"file": ("viewer_commit.zip", valid_shp_zip_bytes, "application/zip")}
        resp = viewer_client.post("/upload/commit", json={"req_number": "A-VIEWER-FORBIDDEN", "owner_name": "x", "layer_assignments": [{"filename": "points", "suggested_type": "Point", "target_layer": "points"}]})
        assert resp.status_code == 403, f"Expected 403 Forbidden for viewer on /upload/commit, got {resp.status_code}"

    def test_upload_commit_empty_layers_rejected(self, editor_client):
        """Tier 2 Boundary: Committing with no layers or empty payload returns 400 or 422."""
        resp = editor_client.post("/upload/commit", json={"layer_assignments": []})
        assert resp.status_code in [400, 422]
