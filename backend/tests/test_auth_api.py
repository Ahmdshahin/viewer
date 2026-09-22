"""
Tier 1, 2, & 3 Tests: Authentication, JWT Security, Role-Based Access Control (RBAC), and User Management.
Verifies POST /auth/login, GET /auth/me, user CRUD operations, token lifecycle, and role permissions.
"""

import time
import pytest
import httpx


# ==============================================================================
# TIER 1: FEATURE COVERAGE (Auth Endpoints, Token Verification, RBAC, User CRUD)
# ==============================================================================

class TestAuthTier1:
    """Feature 5, 6, 7: JWT Authentication and Profile Verification."""

    def test_admin_login_success(self, api_client, admin_credentials):
        """
        Feature 5 & 6 (R1 Acceptance Criteria):
        POST /auth/login with valid seed admin credentials returns 200, JWT access token,
        token_type bearer, role admin, and username admin.
        """
        # Supports either form-data (standard OAuth2) or JSON payload
        resp = api_client.post("/auth/login", data=admin_credentials)
        if resp.status_code != 200:
            resp = api_client.post("/auth/login", json=admin_credentials)

        assert resp.status_code == 200, f"Login failed: {resp.status_code} - {resp.text}"
        data = resp.json()
        assert "access_token" in data, "Response missing 'access_token'"
        assert data.get("token_type", "").lower() == "bearer"
        assert data.get("role") == "admin"
        assert data.get("username") == "admin"

    def test_get_current_user_profile(self, admin_client):
        """Feature 6 & 11: GET /auth/me with valid Bearer token returns current user profile."""
        resp = admin_client.get("/auth/me")
        assert resp.status_code == 200, f"Failed to get current user: {resp.text}"
        data = resp.json()
        assert data.get("username") == "admin"
        assert data.get("role") == "admin"
        assert data.get("is_active") is True

    def test_jwt_token_format_and_claims(self, admin_token):
        """
        Feature 6 & 9:
        Verify JWT token follows RFC 7519 structure (3 base64url segments separated by dots).
        """
        parts = admin_token.split(".")
        assert len(parts) == 3, f"JWT token does not have 3 parts: {admin_token}"
        assert len(parts[0]) > 0
        assert len(parts[1]) > 0
        assert len(parts[2]) > 0

    def test_admin_user_crud_lifecycle(self, admin_client, api_client):
        """
        Feature 8 (R5 Acceptance Criteria):
        Full CRUD lifecycle for cadastral surveyor users:
        1. Admin creates new editor user
        2. Admin lists users and verifies new user is present
        3. New editor can log in
        4. Admin updates user details
        5. Admin deactivates/deletes user
        """
        test_username = "surveyor_e2e_01"
        test_password = "SurveyorPass123!"

        # 1. Create User
        create_payload = {
            "username": test_username,
            "password": test_password,
            "role": "editor",
            "full_name": "مساح ميداني تجريبي"
        }
        create_resp = admin_client.post("/users", json=create_payload)
        assert create_resp.status_code in [200, 201], f"User creation failed: {create_resp.text}"
        created_user = create_resp.json()
        user_id = created_user.get("id")
        assert created_user.get("username") == test_username
        assert created_user.get("role") == "editor"

        # 2. List Users
        list_resp = admin_client.get("/users")
        assert list_resp.status_code == 200
        users_list = list_resp.json()
        if isinstance(users_list, dict) and "items" in users_list:
            users_list = users_list["items"]
        assert any(u.get("username") == test_username for u in users_list)

        # 3. New User Login
        login_resp = api_client.post("/auth/login", data={"username": test_username, "password": test_password})
        if login_resp.status_code != 200:
            login_resp = api_client.post("/auth/login", json={"username": test_username, "password": test_password})
        assert login_resp.status_code == 200
        assert login_resp.json().get("role") == "editor"

        # 4. Update User
        update_payload = {"full_name": "مساح أول محدث", "role": "editor"}
        update_resp = admin_client.put(f"/users/{user_id}", json=update_payload)
        assert update_resp.status_code in [200, 204]

        # 5. Delete or Deactivate User
        del_resp = admin_client.delete(f"/users/{user_id}")
        assert del_resp.status_code in [200, 204]


class TestRoleBasedAccessControlTier1:
    """Feature 7 & 10: Role-Based Permissions Enforcement."""

    def test_admin_has_full_administrative_access(self, admin_client):
        """Admin can access user management endpoints."""
        resp = admin_client.get("/users")
        assert resp.status_code == 200

    def test_editor_can_access_analysis_endpoints(self, editor_client):
        """Editor can access spatial search and analysis endpoints."""
        resp = editor_client.get("/search?q=A-A27")
        assert resp.status_code in [200, 404]  # 200 if records found, 404/200 if empty

    def test_editor_forbidden_from_user_management(self, editor_client):
        """Editor cannot create or list users (must return 403 Forbidden)."""
        resp = editor_client.get("/users")
        assert resp.status_code == 403, f"Expected 403 Forbidden for editor on /users, got {resp.status_code}"

    def test_viewer_can_read_layer_data(self, viewer_client):
        """Viewer role can query layer GeoJSON and attributes."""
        resp = viewer_client.get("/layers/lands/attributes")
        assert resp.status_code in [200, 404]

    def test_viewer_forbidden_from_data_upload(self, viewer_client, valid_shp_zip_bytes):
        """
        Viewer role CANNOT upload or commit data (R5 & Acceptance Criteria: 403 Forbidden).
        """
        files = {"file": ("test.zip", valid_shp_zip_bytes, "application/zip")}
        resp = viewer_client.post("/upload/commit", files=files, data={"layer": "lands"})
        assert resp.status_code == 403, f"Expected 403 Forbidden for viewer on /upload/commit, got {resp.status_code}"


# ==============================================================================
# TIER 2: BOUNDARY & CORNER CASES (Authentication & Security Edge Cases)
# ==============================================================================

class TestAuthBoundariesTier2:
    """Tier 2: Invalid logins, Tampered tokens, Empty inputs, Injection resilience."""

    def test_login_with_incorrect_password(self, api_client):
        """POST /auth/login with wrong password returns 401 Unauthorized."""
        resp = api_client.post("/auth/login", data={"username": "admin", "password": "WRONG_PASSWORD_XYZ"})
        if resp.status_code == 422:
            resp = api_client.post("/auth/login", json={"username": "admin", "password": "WRONG_PASSWORD_XYZ"})
        assert resp.status_code == 401, f"Expected 401 Unauthorized, got {resp.status_code}"

    def test_login_with_nonexistent_user(self, api_client):
        """POST /auth/login with non-existent user returns 401 Unauthorized."""
        resp = api_client.post("/auth/login", data={"username": "ghost_surveyor", "password": "password"})
        if resp.status_code == 422:
            resp = api_client.post("/auth/login", json={"username": "ghost_surveyor", "password": "password"})
        assert resp.status_code == 401, f"Expected 401 Unauthorized, got {resp.status_code}"

    def test_login_with_empty_credentials(self, api_client):
        """POST /auth/login with empty strings returns 400, 401, or 422 Unprocessable Entity."""
        resp = api_client.post("/auth/login", json={"username": "", "password": ""})
        assert resp.status_code in [400, 401, 422]

    def test_unauthenticated_request_returns_401(self, api_client):
        """Requests without Authorization header to protected endpoints return 401."""
        resp = api_client.get("/auth/me")
        assert resp.status_code == 401

        resp = api_client.get("/users")
        assert resp.status_code == 401

    def test_tampered_jwt_token_signature_returns_401(self, api_client, admin_token):
        """Modifying the signature segment of the JWT token must trigger 401 Unauthorized."""
        parts = admin_token.split(".")
        tampered_token = f"{parts[0]}.{parts[1]}.CORRUPTED_SIGNATURE_999"
        headers = {"Authorization": f"Bearer {tampered_token}"}
        resp = api_client.get("/auth/me", headers=headers)
        assert resp.status_code == 401

    def test_malformed_authorization_header(self, api_client):
        """Malformed authorization headers (missing Bearer prefix, nonsense string) return 401."""
        for malformed in ["Basic dXNlcjpwYXNz", "NotBearer 12345", "Bearer", ""]:
            resp = api_client.get("/auth/me", headers={"Authorization": malformed})
            assert resp.status_code == 401

    def test_duplicate_username_creation_rejected(self, admin_client):
        """Attempting to create a user with an existing username returns 400 or 409 Conflict."""
        payload = {
            "username": "admin",  # Already exists
            "password": "new_password",
            "role": "editor"
        }
        resp = admin_client.post("/users", json=payload)
        assert resp.status_code in [400, 409, 422], f"Expected failure for duplicate user, got {resp.status_code}"

    def test_sql_injection_in_login_username(self, api_client):
        """SQL injection attempt in username field must fail with 401, not bypass auth or throw 500."""
        payload = {"username": "' OR '1'='1' --", "password": "password"}
        resp = api_client.post("/auth/login", data=payload)
        if resp.status_code == 422:
            resp = api_client.post("/auth/login", json=payload)
        assert resp.status_code == 401


# ==============================================================================
# TIER 3: CROSS-FEATURE INTERACTIONS (Pairwise Security & Session State)
# ==============================================================================

class TestAuthCrossFeatureTier3:
    """Tier 3: Pairwise validation across Auth, Roles, and Data endpoints."""

    def test_deactivated_user_cannot_access_api(self, admin_client, api_client):
        """
        Pairwise: User lifecycle + Auth.
        When an admin deactivates a user, that user's subsequent requests or logins must fail.
        """
        import uuid
        temp_user = "deac_" + str(uuid.uuid4())[:8]
        temp_pass = "temp_pass_123"
        # 1. Create user
        cr = admin_client.post("/users", json={"username": temp_user, "password": temp_pass, "role": "viewer"})
        assert cr.status_code in [200, 201]
        user_id = cr.json().get("id")

        # 2. Verify user can login
        lr = api_client.post("/auth/login", data={"username": temp_user, "password": temp_pass})
        if lr.status_code != 200:
            lr = api_client.post("/auth/login", json={"username": temp_user, "password": temp_pass})
        assert lr.status_code == 200

        # 3. Deactivate user
        admin_client.put(f"/users/{user_id}", json={"is_active": False})

        # 4. Attempt login with deactivated user
        lr_after = api_client.post("/auth/login", data={"username": temp_user, "password": temp_pass})
        if lr_after.status_code != 401 and lr_after.status_code != 403:
            lr_after = api_client.post("/auth/login", json={"username": temp_user, "password": temp_pass})
        assert lr_after.status_code in [401, 403], f"Deactivated user was allowed to log in! Status: {lr_after.status_code}"

        # Clean up
        admin_client.delete(f"/users/{user_id}")
