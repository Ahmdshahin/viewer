"""
Tier 1 & Tier 2 Tests: GIS Analysis Tools and Cadastral Search APIs.
Verifies GET /search, POST /analysis/intersect, POST /analysis/duplicates,
POST /analysis/layer-intersect, POST /analysis/topology, and GET /features/{layer}/{id}.
"""

import pytest
import httpx


# ==============================================================================
# TIER 1: FEATURE COVERAGE (Cadastral Search, AOI Intersect, Duplication, Topology)
# ==============================================================================

class TestCadastralSearchTier1:
    """Feature 11 & 17: Real-time Cadastral Search API."""

    def test_search_by_exact_request_number(self, api_client):
        """
        Feature 11 (R3 Acceptance Criteria):
        Search by exact cadastral request number returns matching feature with bbox and GeoJSON.
        """
        req_query = "A-Z26-2608-02-00000077641"
        resp = api_client.get(f"/search?q={req_query}")
        assert resp.status_code == 200, f"Search failed: {resp.text}"
        data = resp.json()
        results = data.get("results", []) if isinstance(data, dict) else data
        assert len(results) >= 1, f"Expected at least 1 match for {req_query}"
        first = results[0]
        assert first.get("req_number") == req_query
        assert "bbox" in first or "bounds" in first
        assert "geojson" in first or "geometry" in first
        # Verify area matches ~523.55 m²
        assert abs(float(first.get("area_sqm", 0)) - 523.55) <= 1.0

    def test_search_by_partial_request_number(self, api_client):
        """Search by partial request number returns all matching parcels."""
        resp = api_client.get("/search?q=00000077641")
        assert resp.status_code == 200
        data = resp.json()
        results = data.get("results", []) if isinstance(data, dict) else data
        assert len(results) >= 1

    def test_search_by_arabic_owner_name(self, api_client):
        """
        Feature 11:
        Search by Arabic owner name (e.g. 'محمود') returns matching records with UTF-8 fidelity.
        """
        resp = api_client.get("/search?q=محمود")
        assert resp.status_code == 200
        data = resp.json()
        results = data.get("results", []) if isinstance(data, dict) else data
        assert len(results) >= 1
        for res in results:
            assert "محمود" in res.get("owner_name", "")


class TestSpatialAnalysisToolsTier1:
    """Feature 12, 13, 14: Spatial Intersect, Duplication, and Topology Checks."""

    def test_draw_aoi_intersect_with_cadastral_cluster(self, api_client):
        """
        Feature 12 (R3 Acceptance Criteria):
        POST /analysis/intersect with a polygon bounding known parcels
        returns intersecting features categorized by layer.
        """
        # Bounding polygon in WGS84 (EPSG:4326) covering cluster near lon 31.73, lat 26.19
        aoi_geojson = {
            "type": "Polygon",
            "coordinates": [[
                [31.20, 26.80],
                [31.40, 26.80],
                [31.40, 26.90],
                [31.20, 26.90],
                [31.20, 26.80]
            ]]
        }
        payload = {
            "geometry": aoi_geojson,
            "layers": ["lands", "eshghalat", "points"]
        }
        resp = api_client.post("/analysis/intersect", json=payload)
        assert resp.status_code == 200, f"Intersect analysis failed: {resp.text}"
        data = resp.json()
        assert "features_by_layer" in data or "results" in data
        total_features = data.get("total_features", 0)
        assert total_features > 0, "Expected intersecting features within cadastral cluster"

    def test_duplication_detection_in_lands(self, api_client):
        """
        Feature 13:
        POST /analysis/duplicates detects overlapping parcels within the same layer.
        Oracle verified: Land has overlapping pairs (e.g. A-Z26-2608-02-00000069651).
        """
        payload = {"layer": "lands", "min_overlap_sqm": 0.1}
        resp = api_client.post("/analysis/duplicates", json=payload)
        assert resp.status_code == 200, f"Duplicates check failed: {resp.text}"
        data = resp.json()
        duplicates = data.get("duplicates") or data.get("overlapping_pairs") or data.get("items")
        assert duplicates is not None
        assert len(duplicates) >= 1, "Expected known overlapping parcels to be detected"
        # Verify overlap structure
        sample = duplicates[0]
        assert "overlap_area_sqm" in sample or "overlap_area" in sample or "area" in sample

    def test_inter_layer_intersection_analysis(self, api_client):
        """
        Feature 20:
        POST /analysis/layer-intersect finds spatial intersections between Land and Eshghalat.
        Oracle verified: 132 intersections exist between Land and Eshghalat.
        """
        payload = {
            "source_layer": "lands",
            "target_layer": "eshghalat"
        }
        resp = api_client.post("/analysis/layer-intersect", json=payload)
        assert resp.status_code == 200, f"Layer intersect failed: {resp.text}"
        data = resp.json()
        intersections = data.get("intersections") or data.get("items") or data.get("results")
        assert intersections is not None
        assert len(intersections) > 0, "Expected intersections between Land and Eshghalat"

    def test_topology_gap_and_overlap_check(self, api_client):
        """
        Feature 14:
        POST /analysis/topology detects topological gaps and overlaps within layer boundaries.
        """
        payload = {"layer": "lands"}
        resp = api_client.post("/analysis/topology", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "overlaps" in data or "gaps" in data or "issues" in data

    def test_same_layer_overlap_and_self_intersection_detection(self, api_client):
        """
        Feature 12 (R3) 'Select by Location' same-layer option:
        POST /analysis/same-layer-overlaps detects pairs that overlap each other
        within ONE layer, plus invalid/self-intersecting geometries.
        """
        payload = {"layer": "lands", "min_overlap_sqm": 1.0}
        resp = api_client.post("/analysis/same-layer-overlaps", json=payload)
        assert resp.status_code == 200, f"Same-layer overlap check failed: {resp.text}"
        data = resp.json()
        assert "overlaps" in data and "invalid" in data
        for pair in data["overlaps"]:
            # Structure of each overlapping pair
            assert "id1" in pair and "id2" in pair
            assert "overlap_area_sqm" in pair
            assert "feature1" in pair and "feature2" in pair
            assert "geom" in pair  # intersection geometry for zooming
            assert float(pair["overlap_area_sqm"]) > 0
        for iv in data["invalid"]:
            assert "id" in iv and "reason" in iv and "geom" in iv

    def test_same_layer_overlap_rejects_unknown_layer(self, api_client):
        """Unknown layer name is rejected with 404 (defends SQL interpolation)."""
        resp = api_client.post("/analysis/same-layer-overlaps",
                               json={"layer": "users; DROP TABLE lands; --"})
        assert resp.status_code == 404

    def test_feature_identify_and_history(self, api_client):
        """
        Feature 22 (R3 Acceptance Criteria):
        GET /features/{layer}/{id} returns feature attributes and edit audit trail.
        """
        # First query search to obtain a valid feature ID
        search_resp = api_client.get("/search?q=A-Z26-2608-02-00000077641")
        assert search_resp.status_code == 200
        results = search_resp.json().get("results", [])
        assert len(results) > 0
        feature_id = results[0].get("id")

        resp = api_client.get(f"/features/lands/{feature_id}")
        assert resp.status_code == 200
        feature_data = resp.json()
        assert "attributes" in feature_data or "properties" in feature_data or "req_number" in feature_data
        assert "history" in feature_data or "audit_trail" in feature_data or "edits" in feature_data


# ==============================================================================
# TIER 2: BOUNDARY & CORNER CASES (No Results, Injections, Invalid Geometries)
# ==============================================================================

class TestSpatialAnalysisBoundariesTier2:
    """Tier 2: Empty searches, Invalid AOI GeoJSON, Out-of-bounds queries."""

    def test_search_nonexistent_request_number_returns_empty_results(self, api_client):
        """Tier 2 Boundary: Nonexistent cadastral request returns 200 with empty results array."""
        resp = api_client.get("/search?q=NONEXISTENT_REQ_999999999")
        assert resp.status_code == 200
        data = resp.json()
        results = data.get("results", []) if isinstance(data, dict) else data
        assert len(results) == 0

    def test_search_empty_or_whitespace_query(self, api_client):
        """Tier 2 Boundary: Query with only whitespace returns empty or 400."""
        resp = api_client.get("/search?q=   ")
        assert resp.status_code in [200, 400, 422]
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", []) if isinstance(data, dict) else data
            assert len(results) == 0

    def test_search_sql_injection_payload_defense(self, api_client):
        """Tier 2 Adversarial: SQL injection payloads in search query are neutralized."""
        injections = [
            "'; DROP TABLE points; --",
            "' UNION SELECT * FROM users --",
            "1' OR '1'='1"
        ]
        for inj in injections:
            resp = api_client.get(f"/search?q={inj}")
            assert resp.status_code in [200, 400, 422]
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", []) if isinstance(data, dict) else data
                # Must not dump all records
                assert len(results) == 0

    def test_draw_aoi_intersect_outside_egypt_returns_zero_features(self, api_client):
        """Tier 2 Boundary: AOI polygon in Pacific Ocean returns zero intersecting features."""
        ocean_polygon = {
            "type": "Polygon",
            "coordinates": [[
                [10.0, 10.0],
                [11.0, 10.0],
                [11.0, 11.0],
                [10.0, 11.0],
                [10.0, 10.0]
            ]]
        }
        payload = {
            "geometry": ocean_polygon,
            "layers": ["lands", "eshghalat", "points"]
        }
        resp = api_client.post("/analysis/intersect", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        total = data.get("total_features", 0)
        assert total == 0

    def test_draw_aoi_intersect_with_malformed_geojson(self, api_client):
        """Tier 2 Error: Malformed GeoJSON geometry returns 400 or 422 Unprocessable Entity."""
        malformed_cases = [
            {"type": "Polygon", "coordinates": "invalid_coordinates_string"},
            {"type": "InvalidType", "coordinates": []},
            {"type": "Polygon", "coordinates": [[[31.0, 26.0]]]}  # Unclosed, incomplete ring
        ]
        for bad_geom in malformed_cases:
            payload = {"geometry": bad_geom, "layers": ["lands"]}
            resp = api_client.post("/analysis/intersect", json=payload)
            assert resp.status_code in [400, 422]

    def test_identify_nonexistent_feature_returns_404(self, api_client):
        """Tier 2 Error: Requesting feature ID 9999999 returns 404 Not Found."""
        resp = api_client.get("/features/lands/9999999")
        assert resp.status_code == 404
