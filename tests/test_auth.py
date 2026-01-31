"""Tests for the auth flow with auth_token."""

import time

import pytest
from jose import jwt

from app.deps.auth import JWT_ALGORITHM
from app.models import Qualification
from app.routes.auth import create_access_token, create_auth_token, decode_auth_token


class TestAuthTokenCreation:
    """Tests for auth token creation and decoding."""

    def test_create_auth_token_new_user(self):
        """Auth token for new user should have is_new=True."""
        token = create_auth_token("google123", "test@example.com", is_new=True)

        from app.config.secrets import JWT_SECRET_KEY

        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])

        assert payload["type"] == "auth"
        assert payload["google_id"] == "google123"
        assert payload["email"] == "test@example.com"
        assert payload["is_new"] is True
        assert "iat" in payload
        assert "exp" in payload

    def test_create_auth_token_existing_user(self):
        """Auth token for existing user should have is_new=False."""
        token = create_auth_token("google456", "existing@example.com", is_new=False)

        from app.config.secrets import JWT_SECRET_KEY

        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])

        assert payload["is_new"] is False
        assert payload["google_id"] == "google456"
        assert payload["email"] == "existing@example.com"

    def test_decode_auth_token_valid(self):
        """Valid auth token should decode successfully."""
        token = create_auth_token("google123", "test@example.com", is_new=True)
        payload = decode_auth_token(token)

        assert payload["type"] == "auth"
        assert payload["google_id"] == "google123"
        assert payload["email"] == "test@example.com"

    def test_decode_auth_token_expired(self):
        """Expired auth token should raise InvalidAuthTokenError."""
        from datetime import datetime, timezone

        from app.config.secrets import JWT_SECRET_KEY
        from app.exceptions import InvalidAuthTokenError

        # Create an expired token
        now = datetime.now(timezone.utc)
        expired_payload = {
            "type": "auth",
            "google_id": "google123",
            "email": "test@example.com",
            "is_new": True,
            "iat": int(now.timestamp()) - 3600,
            "exp": int(now.timestamp()) - 60,  # Expired 60 seconds ago
        }
        token = jwt.encode(expired_payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

        with pytest.raises(InvalidAuthTokenError):
            decode_auth_token(token)

    def test_decode_auth_token_wrong_type(self):
        """Token with wrong type should raise InvalidAuthTokenError."""
        from datetime import datetime, timedelta, timezone

        from app.config.secrets import JWT_SECRET_KEY
        from app.exceptions import InvalidAuthTokenError

        # Create a token with wrong type
        now = datetime.now(timezone.utc)
        wrong_type_payload = {
            "type": "access",  # Wrong type
            "google_id": "google123",
            "email": "test@example.com",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=10)).timestamp()),
        }
        token = jwt.encode(wrong_type_payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

        with pytest.raises(InvalidAuthTokenError):
            decode_auth_token(token)


class TestSigninEndpoint:
    """Tests for the /auth/signin endpoint."""

    def test_signin_existing_user(self, client, db, active_user):
        """Signin with valid auth token for existing user should return JWT."""
        auth_token = create_auth_token(
            active_user.google_id, active_user.email, is_new=False
        )

        response = client.post("/auth/signin", json={"auth_token": auth_token})

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["data"]["status"] == "active"
        assert data["data"]["user"]["id"] == active_user.id
        # Token is set via HttpOnly cookie, not in response body
        assert "waffice_access_token" in response.cookies

    def test_signin_pending_user(self, client, db, pending_user):
        """Signin with pending user should return pending status."""
        auth_token = create_auth_token(
            pending_user.google_id, pending_user.email, is_new=False
        )

        response = client.post("/auth/signin", json={"auth_token": auth_token})

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["status"] == "pending"

    def test_signin_new_user_token_fails(self, client, db):
        """Signin with auth token for new user should fail."""
        auth_token = create_auth_token("new_google_id", "new@example.com", is_new=True)

        response = client.post("/auth/signin", json={"auth_token": auth_token})

        assert response.status_code == 400
        data = response.json()
        assert data["ok"] is False
        assert data["error"] == "USER_NOT_REGISTERED"

    def test_signin_invalid_token(self, client, db):
        """Signin with invalid auth token should fail."""
        response = client.post("/auth/signin", json={"auth_token": "invalid_token"})

        assert response.status_code == 400
        data = response.json()
        assert data["ok"] is False
        assert data["error"] == "INVALID_AUTH_TOKEN"


class TestSignupEndpoint:
    """Tests for the /auth/signup endpoint."""

    def test_signup_new_user(self, client, db):
        """Signup with valid auth token should create user and return JWT."""
        auth_token = create_auth_token(
            "new_google_id_signup", "newuser@example.com", is_new=True
        )

        response = client.post(
            "/auth/signup",
            json={
                "auth_token": auth_token,
                "name": "New User",
                "phone": "010-1234-5678",
                "bio": "A new user",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["data"]["status"] == "pending"  # New users start as pending
        assert data["data"]["user"]["name"] == "New User"
        assert data["data"]["user"]["email"] == "newuser@example.com"
        # Token is set via HttpOnly cookie, not in response body
        assert "waffice_access_token" in response.cookies

    def test_signup_idempotent_existing_user(self, client, db, active_user):
        """Signup with existing user's google_id should return existing user."""
        auth_token = create_auth_token(
            active_user.google_id, active_user.email, is_new=True
        )

        response = client.post(
            "/auth/signup",
            json={
                "auth_token": auth_token,
                "name": "Different Name",  # Should be ignored for existing user
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        # Should return existing user, not create new one
        assert data["data"]["user"]["id"] == active_user.id
        assert data["data"]["user"]["name"] == active_user.name  # Name unchanged

    def test_signup_invalid_token(self, client, db):
        """Signup with invalid auth token should fail."""
        response = client.post(
            "/auth/signup",
            json={
                "auth_token": "invalid_token",
                "name": "Test User",
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert data["ok"] is False
        assert data["error"] == "INVALID_AUTH_TOKEN"


class TestGetAuthStatus:
    """Tests for the /auth/me endpoint."""

    def test_get_auth_status_active(self, client, active_token, active_user):
        """Get auth status for active user."""
        response = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {active_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["data"]["status"] == "active"
        assert data["data"]["user"]["id"] == active_user.id
        # Token is no longer refreshed or returned in response body

    def test_get_auth_status_pending(self, client, pending_token, pending_user):
        """Get auth status for pending user."""
        response = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {pending_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["status"] == "pending"

    def test_get_auth_status_unauthorized(self, client):
        """Get auth status without token should fail."""
        response = client.get("/auth/me")

        assert response.status_code == 401


class TestCookieAuth:
    """Tests for HTTP cookie-based authentication."""

    def test_signin_sets_cookie(self, client, db, active_user):
        """Signin should set authentication cookie."""
        auth_token = create_auth_token(
            active_user.google_id, active_user.email, is_new=False
        )

        response = client.post("/auth/signin", json={"auth_token": auth_token})

        assert response.status_code == 200
        assert "waffice_access_token" in response.cookies

    def test_auth_me_with_cookie(self, client, db, active_user):
        """Auth me should work with cookie."""
        auth_token = create_auth_token(
            active_user.google_id, active_user.email, is_new=False
        )

        # First signin to get cookie
        signin_response = client.post("/auth/signin", json={"auth_token": auth_token})
        assert signin_response.status_code == 200

        # Now call /auth/me without Authorization header (uses cookie)
        me_response = client.get("/auth/me")
        assert me_response.status_code == 200
        data = me_response.json()
        assert data["ok"] is True
        assert data["data"]["user"]["id"] == active_user.id

    def test_logout_clears_cookie(self, client, db, active_user):
        """Logout should clear authentication cookie."""
        auth_token = create_auth_token(
            active_user.google_id, active_user.email, is_new=False
        )

        # First signin to get cookie
        signin_response = client.post("/auth/signin", json={"auth_token": auth_token})
        assert signin_response.status_code == 200
        assert "waffice_access_token" in signin_response.cookies

        # Logout
        logout_response = client.post("/auth/logout")
        assert logout_response.status_code == 200
        data = logout_response.json()
        assert data["ok"] is True

        # Verify cookie is cleared (session no longer valid)
        me_response = client.get("/auth/me")
        assert me_response.status_code == 401
