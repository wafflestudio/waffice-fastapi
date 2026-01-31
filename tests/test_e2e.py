"""
End-to-End test scenarios covering all critical flows.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import MemberRole, Qualification, User
from app.services import ProjectService, UserService


class TestUserApprovalFlow:
    """Test 1: 회원가입 → 승인 플로우"""

    def test_pending_to_approved(
        self, client: TestClient, db: Session, admin_token: str, admin_user: User
    ):
        """Pending user can be approved by admin"""
        # Create pending user
        pending = UserService.create(
            db,
            email="newuser@example.com",
            name="New User",
            generation="26",
            qualification=Qualification.PENDING,
        )

        # Admin approves to associate
        response = client.post(
            f"/users/{pending.id}/approve",
            json={"qualification": "associate"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["data"]["qualification"] == "associate"

        # Check history was logged
        history_response = client.get(
            f"/users/{pending.id}/history",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert history_response.status_code == 200
        histories = history_response.json()["data"]
        assert len(histories) > 0
        assert histories[0]["action"] == "qualification_changed"
        assert histories[0]["payload"]["from"] == "pending"
        assert histories[0]["payload"]["to"] == "associate"

    def test_cannot_approve_to_pending(
        self, client: TestClient, db: Session, admin_token: str, admin_user: User
    ):
        """Cannot approve user to pending status"""
        pending = UserService.create(
            db,
            email="newuser2@example.com",
            name="New User 2",
            generation="26",
            qualification=Qualification.PENDING,
        )

        response = client.post(
            f"/users/{pending.id}/approve",
            json={"qualification": "pending"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 400
        assert response.json()["error"] == "INVALID_QUALIFICATION"


class TestProjectCreationAndMemberManagement:
    """Test 2: 프로젝트 생성 → 멤버 관리 플로우"""

    def test_create_project_with_members(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        admin_user: User,
        regular_user: User,
    ):
        """Admin can create project with members"""
        response = client.post(
            "/projects",
            json={
                "name": "Test Project",
                "description": "A test project",
                "status": "active",
                "started_at": str(date.today()),
                "members": [
                    {"user_id": admin_user.id, "role": "leader", "position": "PM"},
                    {"user_id": regular_user.id, "role": "member", "position": "BE"},
                ],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["data"]["name"] == "Test Project"
        assert len(data["data"]["members"]) == 2

        project_id = data["data"]["id"]

        # Check history was logged for both members
        admin_history = client.get(
            f"/users/{admin_user.id}/history",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert admin_history.status_code == 200
        histories = admin_history.json()["data"]
        assert any(h["action"] == "project_joined" for h in histories)

    def test_cannot_create_project_without_leader(
        self, client: TestClient, db: Session, admin_token: str, regular_user: User
    ):
        """Cannot create project without at least one leader"""
        response = client.post(
            "/projects",
            json={
                "name": "No Leader Project",
                "started_at": str(date.today()),
                "members": [
                    {"user_id": regular_user.id, "role": "member"},
                ],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 400
        assert response.json()["error"] == "NO_LEADER_IN_PROJECT"

    def test_add_member_to_project(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        admin_user: User,
        regular_user: User,
        active_user: User,
    ):
        """Can add member to project"""
        # Create project
        project_response = client.post(
            "/projects",
            json={
                "name": "Team Project",
                "started_at": str(date.today()),
                "members": [
                    {"user_id": admin_user.id, "role": "leader"},
                ],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        project_id = project_response.json()["data"]["id"]

        # Add member
        response = client.post(
            f"/projects/{project_id}/members",
            json={"user_id": active_user.id, "role": "member", "position": "FE"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]["members"]) == 2

    def test_change_member_role(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        admin_user: User,
        regular_user: User,
    ):
        """Can change member role and position"""
        # Create project
        project_response = client.post(
            "/projects",
            json={
                "name": "Role Change Project",
                "started_at": str(date.today()),
                "members": [
                    {"user_id": admin_user.id, "role": "leader"},
                    {"user_id": regular_user.id, "role": "member", "position": "BE"},
                ],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        project_id = project_response.json()["data"]["id"]

        # Change role
        response = client.patch(
            f"/projects/{project_id}/members/{regular_user.id}",
            json={"role": "leader", "position": "Tech Lead"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        members = response.json()["data"]["members"]
        regular_member = next(m for m in members if m["user"]["id"] == regular_user.id)
        assert regular_member["role"] == "leader"
        assert regular_member["position"] == "Tech Lead"

    def test_remove_member_from_project(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        admin_user: User,
        regular_user: User,
        active_user: User,
    ):
        """Can remove member from project"""
        # Create project with multiple leaders
        project_response = client.post(
            "/projects",
            json={
                "name": "Member Removal Project",
                "started_at": str(date.today()),
                "members": [
                    {"user_id": admin_user.id, "role": "leader"},
                    {"user_id": active_user.id, "role": "leader"},
                    {"user_id": regular_user.id, "role": "member"},
                ],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        project_id = project_response.json()["data"]["id"]

        # Remove member
        response = client.delete(
            f"/projects/{project_id}/members/{regular_user.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        members = response.json()["data"]["members"]
        # Member should be marked as left (left_at not None)
        assert len([m for m in members if m["left_at"] is None]) == 2


class TestPermissionSystem:
    """Test 3: 권한 체계 검증"""

    def test_pending_cannot_access_projects(
        self, client: TestClient, pending_token: str
    ):
        """Pending users cannot access project list"""
        response = client.get(
            "/projects", headers={"Authorization": f"Bearer {pending_token}"}
        )
        assert response.status_code == 403

    def test_associate_cannot_access_projects(
        self, client: TestClient, associate_token: str
    ):
        """Associate users cannot access project list"""
        response = client.get(
            "/projects", headers={"Authorization": f"Bearer {associate_token}"}
        )
        assert response.status_code == 403

    def test_regular_can_access_projects(self, client: TestClient, regular_token: str):
        """Regular users can access project list"""
        response = client.get(
            "/projects", headers={"Authorization": f"Bearer {regular_token}"}
        )
        assert response.status_code == 200

    def test_leader_can_modify_project(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        admin_user: User,
        regular_user: User,
    ):
        """Project leader can modify project"""
        from tests.conftest import create_access_token

        # Create project with regular_user as leader
        project_response = client.post(
            "/projects",
            json={
                "name": "Leader Test Project",
                "started_at": str(date.today()),
                "members": [
                    {"user_id": regular_user.id, "role": "leader"},
                ],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        project_id = project_response.json()["data"]["id"]

        # Leader can modify
        leader_token = create_access_token(
            regular_user.id, regular_user.email, regular_user.google_id
        )
        response = client.patch(
            f"/projects/{project_id}",
            json={"description": "Updated by leader"},
            headers={"Authorization": f"Bearer {leader_token}"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["description"] == "Updated by leader"

    def test_non_leader_cannot_modify_project(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        admin_user: User,
        regular_user: User,
        active_user: User,
    ):
        """Non-leader regular user cannot modify project"""
        from tests.conftest import create_access_token

        # Create project with admin as leader, active_user as member
        project_response = client.post(
            "/projects",
            json={
                "name": "Non-Leader Test Project",
                "started_at": str(date.today()),
                "members": [
                    {"user_id": admin_user.id, "role": "leader"},
                    {"user_id": active_user.id, "role": "member"},
                ],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        project_id = project_response.json()["data"]["id"]

        # Member (not leader) cannot modify
        member_token = create_access_token(
            active_user.id, active_user.email, active_user.google_id
        )
        response = client.patch(
            f"/projects/{project_id}",
            json={"description": "Attempt to update"},
            headers={"Authorization": f"Bearer {member_token}"},
        )
        assert response.status_code == 403


class TestErrorCases:
    """Test 4: 에러 케이스 검증"""

    def test_cannot_remove_last_leader(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        admin_user: User,
    ):
        """Cannot remove the last leader from project"""
        # Create project with single leader
        project_response = client.post(
            "/projects",
            json={
                "name": "Single Leader Project",
                "started_at": str(date.today()),
                "members": [
                    {"user_id": admin_user.id, "role": "leader"},
                ],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        project_id = project_response.json()["data"]["id"]

        # Try to remove the only leader
        response = client.delete(
            f"/projects/{project_id}/members/{admin_user.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 400
        assert response.json()["error"] == "LAST_LEADER_CANNOT_BE_REMOVED"

    def test_cannot_remove_self(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        admin_user: User,
        regular_user: User,
    ):
        """Cannot remove oneself from project"""
        from tests.conftest import create_access_token

        # Create project
        project_response = client.post(
            "/projects",
            json={
                "name": "Self Remove Project",
                "started_at": str(date.today()),
                "members": [
                    {"user_id": admin_user.id, "role": "leader"},
                    {"user_id": regular_user.id, "role": "leader"},
                ],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        project_id = project_response.json()["data"]["id"]

        # Regular user tries to remove themselves
        regular_token = create_access_token(
            regular_user.id, regular_user.email, regular_user.google_id
        )
        response = client.delete(
            f"/projects/{project_id}/members/{regular_user.id}",
            headers={"Authorization": f"Bearer {regular_token}"},
        )

        assert response.status_code == 400
        assert response.json()["error"] == "CANNOT_REMOVE_SELF"


class TestCriticalSecurityFixes:
    """Tests for critical security and logic fixes"""

    def test_cannot_demote_last_leader(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        admin_user: User,
    ):
        """Cannot demote the last leader to member role (Issue #3)"""
        # Create project with single leader
        project_response = client.post(
            "/projects",
            json={
                "name": "Last Leader Demotion Test",
                "started_at": str(date.today()),
                "members": [
                    {"user_id": admin_user.id, "role": "leader"},
                ],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        project_id = project_response.json()["data"]["id"]

        # Try to demote the only leader to member
        response = client.patch(
            f"/projects/{project_id}/members/{admin_user.id}",
            json={"role": "member"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 400
        assert response.json()["error"] == "LAST_LEADER_CANNOT_BE_REMOVED"

    def test_project_creation_transaction_rollback(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        admin_user: User,
    ):
        """Project creation with invalid member should not leave partial data (Issue #4)"""
        from app.services import ProjectService

        # Count projects before
        initial_count = len(ProjectService.list(db, limit=100)[0])

        # Try to create project with non-existent user
        response = client.post(
            "/projects",
            json={
                "name": "Transaction Test Project",
                "started_at": str(date.today()),
                "members": [
                    {"user_id": admin_user.id, "role": "leader"},
                    {"user_id": 999999, "role": "member"},  # Non-existent user
                ],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 404

        # Verify no partial project was created
        final_count = len(ProjectService.list(db, limit=100)[0])
        assert final_count == initial_count

    def test_project_name_length_validation(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        admin_user: User,
    ):
        """Project name must be between 1-200 characters (Issue #5)"""
        # Empty name should fail
        response = client.post(
            "/projects",
            json={
                "name": "",
                "started_at": str(date.today()),
                "members": [{"user_id": admin_user.id, "role": "leader"}],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 422  # Validation error

        # Name too long should fail
        response = client.post(
            "/projects",
            json={
                "name": "x" * 201,
                "started_at": str(date.today()),
                "members": [{"user_id": admin_user.id, "role": "leader"}],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 422  # Validation error

    def test_project_description_length_validation(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        admin_user: User,
    ):
        """Project description must be <= 5000 characters (Issue #5)"""
        # Description too long should fail
        response = client.post(
            "/projects",
            json={
                "name": "Valid Name",
                "description": "x" * 5001,
                "started_at": str(date.today()),
                "members": [{"user_id": admin_user.id, "role": "leader"}],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 422  # Validation error

    def test_project_requires_at_least_one_member(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
    ):
        """Project must have at least one member (Issue #5)"""
        response = client.post(
            "/projects",
            json={
                "name": "No Members Project",
                "started_at": str(date.today()),
                "members": [],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 422  # Validation error


class TestIdempotency:
    """Test 5: 멱등성 검증"""

    def test_add_member_idempotent(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        admin_user: User,
        regular_user: User,
    ):
        """Adding the same member twice returns existing member"""
        # Create project
        project_response = client.post(
            "/projects",
            json={
                "name": "Idempotent Project",
                "started_at": str(date.today()),
                "members": [
                    {"user_id": admin_user.id, "role": "leader"},
                    {"user_id": regular_user.id, "role": "member"},
                ],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        project_id = project_response.json()["data"]["id"]
        initial_members = project_response.json()["data"]["members"]

        # Try to add the same member again
        response = client.post(
            f"/projects/{project_id}/members",
            json={"user_id": regular_user.id, "role": "member"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        # Should return same number of active members
        active_members = [
            m for m in response.json()["data"]["members"] if m["left_at"] is None
        ]
        assert len(active_members) == 2


class TestSoftDelete:
    """Test 6: Soft Delete 검증"""

    def test_deleted_user_not_found(
        self, client: TestClient, db: Session, admin_token: str, admin_user: User
    ):
        """Deleted user returns 404"""
        # Create user
        user = UserService.create(
            db,
            email="delete_me@example.com",
            name="Delete Me",
            generation="26",
            qualification=Qualification.REGULAR,
        )

        # Delete user
        response = client.delete(
            f"/users/{user.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200

        # Try to get deleted user
        response = client.get(
            f"/users/{user.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 404

    def test_deleted_project_not_found(
        self, client: TestClient, db: Session, admin_token: str, admin_user: User
    ):
        """Deleted project returns 404"""
        # Create project
        project_response = client.post(
            "/projects",
            json={
                "name": "Delete Me Project",
                "started_at": str(date.today()),
                "members": [
                    {"user_id": admin_user.id, "role": "leader"},
                ],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        project_id = project_response.json()["data"]["id"]

        # Delete project
        response = client.delete(
            f"/projects/{project_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200

        # Try to get deleted project (need regular user to access projects)
        from tests.conftest import create_access_token

        regular = UserService.create(
            db,
            email="regular_test@example.com",
            name="Regular Test",
            generation="26",
            qualification=Qualification.REGULAR,
        )
        regular_token = create_access_token(regular.id, regular.email)

        response = client.get(
            f"/projects/{project_id}",
            headers={"Authorization": f"Bearer {regular_token}"},
        )
        assert response.status_code == 404
