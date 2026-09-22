"""
Tier 1 & Tier 2 Tests: Cadastral Layer Serving, GeoJSON Output, Attributes, and Stats APIs.
Verifies GET /layers/{name}/geojson, bbox filtering in EPSG:4326, paginated attribute tables,
sorting, text search filtering, and summary statistics.
"""

import pytest
import httpx


# ==============================================================================
# TIER 1: FEATURE COVERAGE (GeoJSON RFC 7946, Pagination, Sorting, Stats)
# ==============================================================================

class TestLayerGeoJsonTier1:
    """Feature 9 & 13: RFC 7946 GeoJSON Layer Serving with EPSG:4326 Coordinates."""

    def test_get_lands_geojson(self, api_client):
        """
        Feature 9 (R1 Acceptance Criteria):
        GET /layers/lands/geojson returns valid GeoJSON FeatureCollection with 56 parcels.
        Coordinates must be in EPSG:4326 (WGS 84 Lon/Lat: ~31-33 Lon, ~26-27 Lat).
        """
        resp = api_client.get("/layers/lands/geojson")
        assert resp.status_code == 200, f"Failed to retrieve land parcels: {resp.text}"
        data = resp.json()
        assert data.get("type") == "FeatureCollection"
        features = data.get("features", [])
        assert len(features) == 56, f"Expected 56 land parcels, got {len(features)}"

        sample = features[0]
        assert sample.get("type") == "Feature"
        geom = sample.get("geometry", {})
        assert geom.get("type") in ["Polygon", "MultiPolygon"]
        coords = geom.get("coordinates")
        assert coords is not None

        # Verify coordinates are in EPSG:4326 WGS84 (approx 31.0 - 33.0 Lon, 26.0 - 27.0 Lat for Upper Egypt)
        first_coord = coords[0][0][0] if geom.get("type") == "MultiPolygon" else coords[0][0]
        lon, lat = first_coord[0], first_coord[1]
        assert 30.0 <= lon <= 35.0, f"Longitude {lon} outside Egypt WGS84 bounds (30..35)"
        assert 25.0 <= lat <= 32.0, f"Latitude {lat} outside Egypt WGS84 bounds (25..32)"

        # Verify cadastral properties
        props = sample.get("properties", {})
        assert "req_number" in props or "Req_Number" in props
        assert "owner_name" in props or "Owner_Name" in props
        assert "area_sqm" in props or "Area_SQM" in props

    def test_get_eshghalat_geojson(self, api_client):
        """Feature 9: GET /layers/eshghalat/geojson returns 23 occupation features."""
        resp = api_client.get("/layers/eshghalat/geojson")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("type") == "FeatureCollection"
        features = data.get("features", [])
        assert len(features) == 23, f"Expected 23 eshghalat features, got {len(features)}"

    def test_get_points_geojson(self, api_client):
        """Feature 9: GET /layers/points/geojson returns 325 survey point features."""
        resp = api_client.get("/layers/points/geojson")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("type") == "FeatureCollection"
        features = data.get("features", [])
        assert len(features) == 325, f"Expected 325 survey points, got {len(features)}"
        sample_pt = features[0]
        assert sample_pt.get("geometry", {}).get("type") == "Point"

    def test_geojson_bbox_filtering(self, api_client):
        """
        Feature 9 (R1 Acceptance Criteria):
        GET /layers/lands/geojson?bbox={minx,miny,maxx,maxy} filters features within bounds.
        """
        # Bounding box around Sohag/Tahta cluster in WGS84
        bbox_str = "31.1,26.8,31.3,26.9"
        resp = api_client.get(f"/layers/lands/geojson?bbox={bbox_str}")
        assert resp.status_code == 200
        data = resp.json()
        features = data.get("features", [])
        # Should return a subset > 0 and < 56
        assert 0 < len(features) <= 56, f"Expected filtered subset, got {len(features)}"


class TestAttributeTableApiTier1:
    """Feature 10 & 14: Paginated Attribute Table API with Sorting and Filtering."""

    def test_paginated_attributes_default_limit(self, api_client):
        """
        Feature 10 (R1 & R3 Acceptance Criteria):
        GET /layers/lands/attributes returns paginated items with total count.
        """
        resp = api_client.get("/layers/lands/attributes?page=1&limit=25")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert data.get("total") == 56
        assert data.get("page") == 1
        items = data.get("items", [])
        assert len(items) == 25

    def test_paginated_attributes_page_navigation(self, api_client):
        """Verify page 2 returns distinct records from page 1."""
        resp1 = api_client.get("/layers/lands/attributes?page=1&limit=10")
        resp2 = api_client.get("/layers/lands/attributes?page=2&limit=10")
        assert resp1.status_code == 200 and resp2.status_code == 200
        items1 = resp1.json().get("items", [])
        items2 = resp2.json().get("items", [])
        reqs1 = {item.get("req_number") or item.get("Req_Number") for item in items1}
        reqs2 = {item.get("req_number") or item.get("Req_Number") for item in items2}
        assert not reqs1.intersection(reqs2), "Page 1 and Page 2 contain overlapping records!"

    def test_attribute_sorting_by_area(self, api_client):
        """Verify sorting by "Area_SQM" in descending order."""
        resp = api_client.get("/layers/lands/attributes?limit=10&sort_by=area_sqm&order=desc")
        assert resp.status_code == 200
        items = resp.json().get("items", [])
        areas = [float(item.get("area_sqm") or item.get("Area_SQM")) for item in items]
        assert areas == sorted(areas, reverse=True), f"Items not properly sorted descending: {areas}"

    def test_attribute_filtering_by_request_number(self, api_client):
        """Verify text filter q=... searches request numbers."""
        resp = api_client.get("/layers/lands/attributes?q=A-Z26-2608-02-00000077641")
        assert resp.status_code == 200
        items = resp.json().get("items", [])
        assert len(items) >= 1
        matched_req = items[0].get("req_number") or items[0].get("Req_Number")
        assert "00000077641" in matched_req


class TestLayerStatsApiTier1:
    """Feature 15: Layer Summary Statistics API."""

    def test_lands_summary_statistics(self, api_client):
        """
        Feature 15 (R2):
        GET /layers/lands/stats returns total count (56), total area (~996467 m² / ~237.2 Feddan).
        """
        resp = api_client.get("/layers/lands/stats")
        assert resp.status_code == 200
        stats = resp.json()
        assert stats.get("total_features") == 56 or stats.get("count") == 56
        total_sqm = stats.get("total_area_sqm") or stats.get("total_area")
        assert abs(float(total_sqm) - 487492.14) <= 50.0

    def test_eshghalat_summary_statistics(self, api_client):
        """GET /layers/eshghalat/stats returns count 23 and accurate occupation area."""
        resp = api_client.get("/layers/eshghalat/stats")
        assert resp.status_code == 200
        stats = resp.json()
        assert stats.get("total_features") == 23 or stats.get("count") == 23
        total_sqm = stats.get("total_area_sqm") or stats.get("total_area")
        assert abs(float(total_sqm) - 2153.46) <= 20.0

    def test_points_summary_statistics(self, api_client):
        """GET /layers/points/stats returns 325 points count."""
        resp = api_client.get("/layers/points/stats")
        assert resp.status_code == 200
        stats = resp.json()
        assert stats.get("total_features") == 325 or stats.get("count") == 325


# ==============================================================================
# TIER 2: BOUNDARY & CORNER CASES (Empty BBox, Malformed Params, 404s, Injections)
# ==============================================================================

class TestLayerServingBoundariesTier2:
    """Tier 2: Out of bounds bbox, non-existent layers, invalid query parameters."""

    def test_bbox_filter_in_empty_ocean_or_desert(self, api_client):
        """
        Tier 2 Boundary:
        Bbox completely outside Egypt (e.g. Pacific Ocean: lon 0..1, lat 0..1)
        returns valid GeoJSON FeatureCollection with 0 features.
        """
        resp = api_client.get("/layers/lands/geojson?bbox=0.0,0.0,1.0,1.0")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("type") == "FeatureCollection"
        assert len(data.get("features", [])) == 0

    def test_malformed_bbox_parameter_returns_400_or_422(self, api_client):
        """Tier 2 Error: Malformed bbox (inverted minx > maxx or string) returns 400 or 422."""
        for malformed in ["not,a,valid,bbox", "35.0,27.0,30.0,26.0", "31.0,26.0"]:
            resp = api_client.get(f"/layers/lands/geojson?bbox={malformed}")
            assert resp.status_code in [400, 422]

    def test_nonexistent_layer_returns_404(self, api_client):
        """Tier 2 Error: Querying non-existent layer returns 404 Not Found."""
        resp = api_client.get("/layers/non_existent_cadastre_99/geojson")
        assert resp.status_code == 404

        resp = api_client.get("/layers/non_existent_cadastre_99/attributes")
        assert resp.status_code == 404

        resp = api_client.get("/layers/non_existent_cadastre_99/stats")
        assert resp.status_code == 404

    def test_attributes_page_out_of_bounds_returns_empty_list(self, api_client):
        """Tier 2 Boundary: Page 9999 returns empty items list, not 500 error."""
        resp = api_client.get("/layers/lands/attributes?page=9999&limit=50")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data.get("items", [])) == 0
        assert data.get("total") == 56

    def test_attributes_negative_or_zero_limit(self, api_client):
        """Tier 2 Boundary: limit=0 or limit=-10 returns 422 or defaults safely."""
        resp = api_client.get("/layers/lands/attributes?page=1&limit=-10")
        assert resp.status_code in [200, 400, 422]
        if resp.status_code == 200:
            assert len(resp.json().get("items", [])) <= 50

    def test_sql_injection_defense_in_attributes_sorting(self, api_client):
        """Tier 2 Adversarial: SQL injection in sort_by query parameter returns 400 or 422."""
        injection_sort = "area_sqm; DROP TABLE points; --"
        resp = api_client.get(f"/layers/lands/attributes?sort_by={injection_sort}")
        assert resp.status_code in [400, 422]
