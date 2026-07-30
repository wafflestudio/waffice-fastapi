"""Tests for member detail page features: UserActivity CRUD, AuditLog, profile update."""

import time
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Qualification, User
from app.services import UserService


@pytest.fixture
def project(client: TestClient, admin_token: str, admin_user: User) -> dict:
    """Create a test project and return its data."""
    response = client.post(
        "/projects",
        json={
            "name": "Test Project",
            "started_at": str(date.today()),
            "members": [{"user_id": admin_user.id, "role": "leader"}],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    return response.json()["data"]


class TestUserActivityCRUD:
    """Tests for UserActivity CRUD endpoints."""

    def test_admin_can_list_activities(
        self,
        client: TestClient,
        admin_token: str,
        regular_user: User,
    ):
        """Admin can list a user's activities (empty list initially)."""
        response = client.get(
            f"/users/{regular_user.id}/activities",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        assert response.json()["data"] == []

    def test_admin_can_create_activity(
        self,
        client: TestClient,
        admin_token: str,
        regular_user: User,
        project: dict,
    ):
        """Admin can create an activity for a user with a valid project_id."""
        now = int(time.time())
        response = client.post(
            f"/users/{regular_user.id}/activities",
            json={
                "project_id": project["id"],
                "position": "백엔드 개발자",
                "start_date": now,
                "status": "active",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["project_id"] == project["id"]
        assert data["project_name"] == project["name"]
        assert data["position"] == "백엔드 개발자"

    def test_create_activity_with_invalid_project_returns_404(
        self,
        client: TestClient,
        admin_token: str,
        regular_user: User,
    ):
        """Creating an activity with a non-existent project_id returns 404."""
        response = client.post(
            f"/users/{regular_user.id}/activities",
            json={
                "project_id": 999999,
                "position": "개발자",
                "start_date": int(time.time()),
                "status": "active",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 404

    def test_create_activity_null_required_field_returns_422(
        self,
        client: TestClient,
        admin_token: str,
        regular_user: User,
        project: dict,
    ):
        """Sending null for a required field returns 422."""
        response = client.post(
            f"/users/{regular_user.id}/activities",
            json={
                "project_id": project["id"],
                "position": None,
                "start_date": int(time.time()),
                "status": "active",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 422

    def test_admin_can_update_activity(
        self,
        client: TestClient,
        admin_token: str,
        regular_user: User,
        project: dict,
    ):
        """Admin can update an existing activity."""
        now = int(time.time())
        create_response = client.post(
            f"/users/{regular_user.id}/activities",
            json={
                "project_id": project["id"],
                "position": "백엔드 개발자",
                "start_date": now,
                "status": "active",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        activity_id = create_response.json()["data"]["id"]

        response = client.patch(
            f"/users/{regular_user.id}/activities/{activity_id}",
            json={"position": "프론트엔드 개발자", "status": "inactive"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["position"] == "프론트엔드 개발자"
        assert data["status"] == "inactive"

    def test_update_activity_null_required_field_returns_422(
        self,
        client: TestClient,
        admin_token: str,
        regular_user: User,
        project: dict,
    ):
        """Sending explicit null on a required field in update returns 422."""
        now = int(time.time())
        create_response = client.post(
            f"/users/{regular_user.id}/activities",
            json={
                "project_id": project["id"],
                "position": "개발자",
                "start_date": now,
                "status": "active",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        activity_id = create_response.json()["data"]["id"]

        response = client.patch(
            f"/users/{regular_user.id}/activities/{activity_id}",
            json={"position": None},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 422

    def test_update_activity_with_invalid_project_returns_404(
        self,
        client: TestClient,
        admin_token: str,
        regular_user: User,
        project: dict,
    ):
        """Updating activity with a non-existent project_id returns 404."""
        now = int(time.time())
        create_response = client.post(
            f"/users/{regular_user.id}/activities",
            json={
                "project_id": project["id"],
                "position": "개발자",
                "start_date": now,
                "status": "active",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        activity_id = create_response.json()["data"]["id"]

        response = client.patch(
            f"/users/{regular_user.id}/activities/{activity_id}",
            json={"project_id": 999999},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 404

    def test_admin_can_delete_activity(
        self,
        client: TestClient,
        admin_token: str,
        regular_user: User,
        project: dict,
    ):
        """Admin can delete an activity."""
        now = int(time.time())
        create_response = client.post(
            f"/users/{regular_user.id}/activities",
            json={
                "project_id": project["id"],
                "position": "개발자",
                "start_date": now,
                "status": "active",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        activity_id = create_response.json()["data"]["id"]

        response = client.delete(
            f"/users/{regular_user.id}/activities/{activity_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200

        list_response = client.get(
            f"/users/{regular_user.id}/activities",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert list_response.json()["data"] == []

    def test_non_admin_cannot_access_activities(
        self,
        client: TestClient,
        regular_token: str,
        regular_user: User,
    ):
        """Non-admin cannot access activity endpoints."""
        response = client.get(
            f"/users/{regular_user.id}/activities",
            headers={"Authorization": f"Bearer {regular_token}"},
        )
        assert response.status_code == 403

    def test_activity_of_other_user_returns_404(
        self,
        client: TestClient,
        admin_token: str,
        regular_user: User,
        active_user: User,
        project: dict,
    ):
        """Cannot access/modify an activity that belongs to another user."""
        now = int(time.time())
        create_response = client.post(
            f"/users/{regular_user.id}/activities",
            json={
                "project_id": project["id"],
                "position": "개발자",
                "start_date": now,
                "status": "active",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        activity_id = create_response.json()["data"]["id"]

        response = client.patch(
            f"/users/{active_user.id}/activities/{activity_id}",
            json={"position": "디자이너"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 404


class TestAuditLog:
    """Tests for AuditLog endpoints."""

    def test_user_can_get_own_audit_log(
        self,
        client: TestClient,
        regular_token: str,
    ):
        """Any authenticated user can get their own audit log."""
        response = client.get(
            "/users/me/audit-log",
            headers={"Authorization": f"Bearer {regular_token}"},
        )
        assert response.status_code == 200
        assert isinstance(response.json()["data"], list)

    def test_admin_can_get_any_user_audit_log(
        self,
        client: TestClient,
        admin_token: str,
        regular_user: User,
    ):
        """Admin can get any user's audit log."""
        response = client.get(
            f"/users/{regular_user.id}/audit-log",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200

    def test_non_admin_cannot_get_other_user_audit_log(
        self,
        client: TestClient,
        regular_token: str,
        active_user: User,
    ):
        """Non-admin cannot get another user's audit log."""
        response = client.get(
            f"/users/{active_user.id}/audit-log",
            headers={"Authorization": f"Bearer {regular_token}"},
        )
        assert response.status_code == 403

    def test_approve_creates_audit_log(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
    ):
        """Approving a user creates a qualification_changed audit log entry."""
        pending = UserService.create(
            db,
            email="audittest@example.com",
            name="Audit Test",
            generation="26",
            qualification=Qualification.PENDING,
        )

        client.post(
            f"/users/{pending.id}/approve",
            json={"qualification": "associate"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        response = client.get(
            f"/users/{pending.id}/audit-log",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        logs = response.json()["data"]
        assert len(logs) > 0
        assert logs[0]["action"] == "qualification_changed"
        assert logs[0]["payload"]["from"] == "pending"
        assert logs[0]["payload"]["to"] == "associate"

    def test_qualification_change_with_reason_stores_reason_in_audit_log(
        self,
        client: TestClient,
        admin_token: str,
        regular_user: User,
    ):
        """qualification_change_reason is stored on the qualification_changed log entry."""
        client.patch(
            f"/users/{regular_user.id}",
            json={
                "qualification": "active",
                "qualification_change_reason": "활동 실적 우수로 활동회원 승급",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        response = client.get(
            f"/users/{regular_user.id}/audit-log",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        logs = response.json()["data"]
        qual_log = next(log for log in logs if log["action"] == "qualification_changed")
        assert qual_log["payload"]["reason"] == "활동 실적 우수로 활동회원 승급"

    def test_qualification_change_without_reason_stores_null(
        self,
        client: TestClient,
        admin_token: str,
        regular_user: User,
    ):
        """Omitting qualification_change_reason stores a null reason in the audit log."""
        client.patch(
            f"/users/{regular_user.id}",
            json={"qualification": "active"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        response = client.get(
            f"/users/{regular_user.id}/audit-log",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        logs = response.json()["data"]
        qual_log = next(log for log in logs if log["action"] == "qualification_changed")
        assert qual_log["payload"]["reason"] is None


class TestProfileUpdate:
    """Tests for profile update with new fields."""

    def test_user_can_update_new_profile_fields(
        self,
        client: TestClient,
        regular_token: str,
    ):
        """User can update student_id and department."""
        response = client.patch(
            "/users/me",
            json={"student_id": "2021-14205", "department": "컴퓨터공학과"},
            headers={"Authorization": f"Bearer {regular_token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["student_id"] == "2021-14205"
        assert data["department"] == "컴퓨터공학과"

    def test_user_cannot_update_qualification(
        self,
        client: TestClient,
        regular_token: str,
    ):
        """Regular user cannot update qualification via profile endpoint."""
        response = client.patch(
            "/users/me",
            json={"qualification": "active"},
            headers={"Authorization": f"Bearer {regular_token}"},
        )
        # qualification is not in ProfileUpdateRequest so it's ignored or rejected
        assert response.status_code in (200, 422)
        if response.status_code == 200:
            assert response.json()["data"]["qualification"] == "regular"

    def test_admin_can_update_qualification(
        self,
        client: TestClient,
        admin_token: str,
        regular_user: User,
    ):
        """Admin can update a user's qualification."""
        response = client.patch(
            f"/users/{regular_user.id}",
            json={"qualification": "active"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["qualification"] == "active"

    def test_qualification_change_reason_is_not_persisted_on_user(
        self,
        client: TestClient,
        admin_token: str,
        regular_user: User,
    ):
        """qualification_change_reason is audit-log-only, not a user field."""
        response = client.patch(
            f"/users/{regular_user.id}",
            json={
                "qualification": "active",
                "qualification_change_reason": "활동 실적 우수",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["qualification"] == "active"
        assert "qualification_change_reason" not in data

    def test_pending_user_cannot_update_profile(
        self,
        client: TestClient,
        pending_token: str,
    ):
        """Pending user cannot update their own profile."""
        response = client.patch(
            "/users/me",
            json={"department": "컴퓨터공학과"},
            headers={"Authorization": f"Bearer {pending_token}"},
        )
        assert response.status_code == 403

    def test_user_can_update_notification_fields(
        self,
        client: TestClient,
        regular_token: str,
    ):
        """User can update contact_email and notification_channel."""
        response = client.patch(
            "/users/me",
            json={
                "contact_email": "contact@example.com",
                "notification_channel": "sms",
            },
            headers={"Authorization": f"Bearer {regular_token}"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["contact_email"] == "contact@example.com"
        assert data["notification_channel"] == "sms"

    def test_invalid_notification_channel_returns_422(
        self,
        client: TestClient,
        regular_token: str,
    ):
        """Invalid notification_channel value returns 422."""
        response = client.patch(
            "/users/me",
            json={"notification_channel": "kakao"},
            headers={"Authorization": f"Bearer {regular_token}"},
        )
        assert response.status_code == 422


class TestProfileImageUpload:
    def test_public_url_uses_default_when_base_url_is_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Empty OCI_PUBLIC_BASE_URL should not produce a relative URL."""
        from app.services.object_storage import OCIObjectStorageService

        monkeypatch.setenv("OCI_PUBLIC_BASE_URL", "")
        storage = OCIObjectStorageService.__new__(OCIObjectStorageService)
        storage.region = "ap-chuncheon-1"
        storage.namespace = "namespace"
        storage.bucket = "bucket"

        assert storage.public_url("profiles/1/avatar.png") == (
            "https://objectstorage.ap-chuncheon-1.oraclecloud.com/n/namespace/b/bucket/o/"
            "profiles%2F1%2Favatar.png"
        )

    def test_user_can_upload_profile_image(
        self,
        client: TestClient,
        regular_token: str,
        regular_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """User can upload a profile image."""
        deleted = []

        class FakeStorage:
            def upload_profile_image(self, user_id, file, body):
                assert user_id == regular_user.id
                assert file.content_type == "image/png"
                assert body == b"image"
                return "https://cdn.example.com/profiles/1/new.png"

            def delete_profile_image(self, user_id, url):
                deleted.append((user_id, url))

        monkeypatch.setattr(
            "app.routes.profile_image.OCIObjectStorageService", FakeStorage
        )

        response = client.post(
            "/profile-image/upload",
            files={"file": ("avatar.png", b"image", "image/png")},
            headers={"Authorization": f"Bearer {regular_token}"},
        )

        assert response.status_code == 200
        assert response.json()["data"]["avatar_url"] == (
            "https://cdn.example.com/profiles/1/new.png"
        )
        assert deleted == [(regular_user.id, None)]

    def test_upload_rejects_non_image(
        self,
        client: TestClient,
        regular_token: str,
    ):
        """Profile image upload accepts only configured image types."""
        response = client.post(
            "/profile-image/upload",
            files={"file": ("avatar.txt", b"text", "text/plain")},
            headers={"Authorization": f"Bearer {regular_token}"},
        )

        assert response.status_code == 400
        assert response.json()["error"] == "INVALID_PROFILE_IMAGE"

    def test_upload_rejects_large_image(
        self,
        client: TestClient,
        regular_token: str,
    ):
        """Profile image upload rejects files larger than 5MB."""
        response = client.post(
            "/profile-image/upload",
            files={"file": ("avatar.png", b"0" * (5 * 1024 * 1024 + 1), "image/png")},
            headers={"Authorization": f"Bearer {regular_token}"},
        )

        assert response.status_code == 413
        assert response.json()["error"] == "PROFILE_IMAGE_TOO_LARGE"

    def test_pending_user_cannot_upload_profile_image(
        self,
        client: TestClient,
        pending_token: str,
    ):
        """Pending users cannot upload profile images."""
        response = client.post(
            "/profile-image/upload",
            files={"file": ("avatar.png", b"image", "image/png")},
            headers={"Authorization": f"Bearer {pending_token}"},
        )

        assert response.status_code == 403
