"""Tests for the auth flow with auth_token."""

import time
from datetime import date

import pytest
from jose import jwt

from app.deps.auth import JWT_ALGORITHM
from app.models import (
    ActivityStatus,
    MemberRole,
    Project,
    ProjectMember,
    Qualification,
    User,
    UserActivity,
)
from app.routes.auth import create_access_token, create_auth_token, decode_auth_token
from app.services import UserService


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

    def test_signin_bootstraps_first_admin(self, client, db, pending_user):
        pending_user.email = "master@wafflestudio.com"
        db.commit()
        auth_token = create_auth_token(
            pending_user.google_id, pending_user.email, is_new=False
        )

        response = client.post("/auth/signin", json={"auth_token": auth_token})

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "active"
        db.refresh(pending_user)
        assert pending_user.is_admin is True
        assert pending_user.qualification == Qualification.ACTIVE

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

    @staticmethod
    def signup_payload(auth_token, **overrides):
        return {
            "auth_token": auth_token,
            "name": "Test User",
            "generation": "26",
            "student_id": "2026-12345",
            "email": "contact@example.com",
            "graduation_status": "학부생",
            "qualification": "associate",
            "privacy_policy_agreed": True,
            "terms_agreed": True,
            "email_notifications_agreed": False,
            "sms_notifications_agreed": False,
            **overrides,
        }

    def test_signup_new_user(self, client, db):
        """Signup with valid auth token should create user and return JWT."""
        auth_token = create_auth_token(
            "new_google_id_signup", "newuser@example.com", is_new=True
        )

        response = client.post(
            "/auth/signup",
            json=self.signup_payload(
                auth_token,
                name="New User",
                generation="23.5",
                student_id="2021-14205",
                graduation_status="휴학생",
                qualification="regular",
                phone="010-1234-5678",
                bio="A new user",
                github_username="new-user",
                email_notifications_agreed=True,
                sms_notifications_agreed=False,
            ),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["data"]["status"] == "pending"  # New users start as pending
        assert data["data"]["user"]["name"] == "New User"
        assert data["data"]["user"]["email"] == "newuser@example.com"
        assert data["data"]["user"]["generation"] == "23.5"
        assert data["data"]["user"]["student_id"] == "2021-14205"
        assert data["data"]["user"]["contact_email"] == "contact@example.com"
        assert data["data"]["user"]["graduation_status"] == "휴학생"
        assert data["data"]["user"]["qualification"] == "pending"
        assert data["data"]["user"]["requested_qualification"] == "regular"
        assert data["data"]["user"]["github_username"] == "new-user"
        assert data["data"]["user"]["privacy_policy_agreed"] is True
        assert data["data"]["user"]["terms_agreed"] is True
        assert data["data"]["user"]["email_notifications_agreed"] is True
        assert data["data"]["user"]["sms_notifications_agreed"] is False
        # Token is set via HttpOnly cookie, not in response body
        assert "waffice_access_token" in response.cookies

    def test_signup_does_not_bootstrap_when_admin_exists(self, client, admin_user):
        auth_token = create_auth_token(
            "master_google_id", "master@wafflestudio.com", is_new=True
        )

        response = client.post(
            "/auth/signup",
            json=self.signup_payload(auth_token, student_id="2026-99999"),
        )

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "pending"
        assert response.json()["data"]["user"]["is_admin"] is False

    @pytest.mark.parametrize("field", ["privacy_policy_agreed", "terms_agreed"])
    def test_signup_requires_mandatory_agreements(self, client, field):
        auth_token = create_auth_token(
            f"missing_{field}", f"{field}@example.com", is_new=True
        )

        response = client.post(
            "/auth/signup",
            json=self.signup_payload(auth_token, **{field: False}),
        )

        assert response.status_code == 422

    def test_signup_idempotent_existing_user(self, client, db, active_user):
        """Signup with existing user's google_id should return existing user."""
        auth_token = create_auth_token(
            active_user.google_id, active_user.email, is_new=True
        )

        response = client.post(
            "/auth/signup",
            json=self.signup_payload(auth_token, name="Different Name"),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        # Should return existing user, not create new one
        assert data["data"]["user"]["id"] == active_user.id
        assert data["data"]["user"]["name"] == active_user.name  # Name unchanged

    def test_signup_claims_temporary_member(self, client, db):
        """Signup converts the matching temporary row and preserves memberships."""
        temporary_user = UserService.create(
            db,
            name="Imported Name",
            student_id="2021-77777",
            is_temporary=True,
        )
        project = Project(name="Inherited Project", started_at=date.today())
        db.add(project)
        db.flush()
        membership = ProjectMember(
            project_id=project.id,
            user_id=temporary_user.id,
            role=MemberRole.MEMBER,
            joined_at=date.today(),
        )
        db.add(membership)
        db.commit()

        auth_token = create_auth_token(
            "claimed_google_id", "claimed@example.com", is_new=True
        )
        response = client.post(
            "/auth/signup",
            json=self.signup_payload(
                auth_token,
                name="Claimed Name",
                student_id=temporary_user.student_id,
            ),
        )

        assert response.status_code == 200
        user = response.json()["data"]["user"]
        assert user["id"] == temporary_user.id
        assert user["name"] == "Claimed Name"
        assert user["email"] == "claimed@example.com"
        assert user["is_temporary"] is False
        db.refresh(membership)
        assert membership.user_id == temporary_user.id
        assert membership.left_at is None

    def test_signup_rejects_registered_student_id(self, client, db, active_user):
        """A student ID owned by a registered user cannot be signed up again."""
        active_user.student_id = "2021-88888"
        db.commit()
        auth_token = create_auth_token(
            "duplicate_student_google_id",
            "duplicate-student@example.com",
            is_new=True,
        )

        response = client.post(
            "/auth/signup",
            json=self.signup_payload(
                auth_token,
                student_id=active_user.student_id,
            ),
        )

        assert response.status_code == 409
        assert response.json()["error"] == "STUDENT_ID_ALREADY_IN_USE"
        assert UserService.get_by_google_id(db, "duplicate_student_google_id") is None

    def test_signup_restores_deleted_pending_user(self, client, db, pending_user):
        """Signup restores the original pending user instead of inserting a duplicate."""
        original_id = pending_user.id
        original_name = pending_user.name
        pending_user.phone = "010-1111-2222"
        db.commit()
        UserService.delete(db, pending_user)

        auth_token = create_auth_token(
            pending_user.google_id, pending_user.email, is_new=True
        )
        response = client.post(
            "/auth/signup",
            json=self.signup_payload(
                auth_token,
                name="Ignored New Name",
                phone="010-9999-9999",
            ),
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["status"] == "pending"
        assert data["user"]["id"] == original_id
        assert data["user"]["name"] == original_name
        assert data["user"]["phone"] == "010-1111-2222"
        assert "waffice_access_token" in response.cookies

        db.refresh(pending_user)
        assert pending_user.deleted_at is None
        assert (
            db.query(User).filter(User.google_id == pending_user.google_id).count() == 1
        )

    def test_signup_restore_preserves_active_user_state(self, client, db, active_user):
        """Restoring an active user preserves privileges, memberships, and activities."""
        active_user.is_admin = True
        project = Project(name="Preserved Project", started_at=date.today())
        db.add(project)
        db.flush()
        membership = ProjectMember(
            project_id=project.id,
            user_id=active_user.id,
            role=MemberRole.LEADER,
            joined_at=date.today(),
        )
        activity = UserActivity(
            user_id=active_user.id,
            project_id=project.id,
            position="Backend",
            start_date=int(time.time()),
            status=ActivityStatus.ACTIVE,
        )
        db.add_all([membership, activity])
        db.commit()
        UserService.delete(db, active_user)

        auth_token = create_auth_token(
            active_user.google_id, active_user.email, is_new=True
        )
        response = client.post(
            "/auth/signup",
            json=self.signup_payload(auth_token, name="Ignored New Name"),
        )

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "active"
        db.refresh(active_user)
        db.refresh(membership)
        db.refresh(activity)
        assert active_user.deleted_at is None
        assert active_user.is_admin is True
        assert membership.left_at is None
        assert membership.role == MemberRole.LEADER
        assert activity.status == ActivityStatus.ACTIVE

    def test_signup_rejects_deleted_identity_split_across_users(self, client, db):
        """Google ID and email must not restore two different deleted users."""
        google_user = UserService.create(
            db,
            google_id="deleted_google_id",
            email="first-deleted@example.com",
            name="First Deleted",
        )
        email_user = UserService.create(
            db,
            google_id="other_deleted_google_id",
            email="deleted-email@example.com",
            name="Second Deleted",
        )
        UserService.delete(db, google_user)
        UserService.delete(db, email_user)

        auth_token = create_auth_token(
            google_user.google_id, email_user.email, is_new=True
        )
        response = client.post(
            "/auth/signup",
            json=self.signup_payload(auth_token, name="Conflict"),
        )

        assert response.status_code == 409
        assert response.json()["error"] == "GOOGLE_ACCOUNT_ALREADY_LINKED"
        db.refresh(google_user)
        db.refresh(email_user)
        assert google_user.deleted_at is not None
        assert email_user.deleted_at is not None

    def test_signup_invalid_token(self, client, db):
        """Signup with invalid auth token should fail."""
        response = client.post(
            "/auth/signup",
            json=self.signup_payload("invalid_token"),
        )

        assert response.status_code == 400
        data = response.json()
        assert data["ok"] is False
        assert data["error"] == "INVALID_AUTH_TOKEN"


class TestGoogleRelinkEndpoint:
    """Tests for the /auth/google/relink endpoint."""

    def test_relink_google_account_updates_user_and_cookie(
        self, client, db, active_user, active_token
    ):
        """Authenticated users can relink to a new Google account."""
        auth_token = create_auth_token(
            "new_google_id_for_active", "new_active@example.com", is_new=True
        )

        response = client.post(
            "/auth/google/relink",
            json={"auth_token": auth_token},
            headers={"Authorization": f"Bearer {active_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["data"]["status"] == "active"
        assert data["data"]["user"]["id"] == active_user.id
        assert data["data"]["user"]["email"] == "new_active@example.com"
        assert "waffice_access_token" in response.cookies

        db.refresh(active_user)
        assert active_user.google_id == "new_google_id_for_active"
        assert active_user.email == "new_active@example.com"

        from app.config.secrets import JWT_SECRET_KEY

        cookie_token = response.cookies["waffice_access_token"]
        payload = jwt.decode(cookie_token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        assert payload["user_id"] == active_user.id
        assert payload["google_id"] == "new_google_id_for_active"
        assert payload["email"] == "new_active@example.com"

    def test_relink_google_account_same_account_noop(
        self, client, db, active_user, active_token
    ):
        """Relinking to the same Google account succeeds without changing the user."""
        auth_token = create_auth_token(
            active_user.google_id, active_user.email, is_new=False
        )

        response = client.post(
            "/auth/google/relink",
            json={"auth_token": auth_token},
            headers={"Authorization": f"Bearer {active_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["data"]["user"]["id"] == active_user.id
        assert data["data"]["user"]["email"] == active_user.email

    def test_relink_google_account_rejects_existing_google_id(
        self, client, active_token, regular_user
    ):
        """Cannot relink to a Google account already owned by another user."""
        auth_token = create_auth_token(
            regular_user.google_id, "unused@example.com", is_new=False
        )

        response = client.post(
            "/auth/google/relink",
            json={"auth_token": auth_token},
            headers={"Authorization": f"Bearer {active_token}"},
        )

        assert response.status_code == 409
        data = response.json()
        assert data["ok"] is False
        assert data["error"] == "GOOGLE_ACCOUNT_ALREADY_LINKED"

    def test_relink_google_account_rejects_existing_email(
        self, client, active_token, regular_user
    ):
        """Cannot relink to an email already owned by another user."""
        auth_token = create_auth_token(
            "unused_google_id", regular_user.email, is_new=True
        )

        response = client.post(
            "/auth/google/relink",
            json={"auth_token": auth_token},
            headers={"Authorization": f"Bearer {active_token}"},
        )

        assert response.status_code == 409
        data = response.json()
        assert data["ok"] is False
        assert data["error"] == "EMAIL_ALREADY_IN_USE"

    def test_relink_google_account_requires_auth(self, client):
        """Unauthenticated users cannot relink Google accounts."""
        auth_token = create_auth_token(
            "new_google_id_for_unauth", "unauth@example.com", is_new=True
        )

        response = client.post(
            "/auth/google/relink",
            json={"auth_token": auth_token},
        )

        assert response.status_code == 401

    def test_relink_google_account_invalid_token(self, client, active_token):
        """Invalid auth_token returns the standard invalid token error."""
        response = client.post(
            "/auth/google/relink",
            json={"auth_token": "invalid_token"},
            headers={"Authorization": f"Bearer {active_token}"},
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
