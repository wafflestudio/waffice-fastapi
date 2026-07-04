"""Tests for user-related features: name search and current_projects."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import MemberRole, Qualification, User
from app.services import MemberService, ProjectService, UserService


@pytest.fixture
def users(db: Session) -> list[User]:
    """Create multiple users with different names for search testing."""
    return [
        UserService.create(
            db,
            email="kim@example.com",
            name="김와플",
            generation="26",
            qualification=Qualification.ACTIVE,
        ),
        UserService.create(
            db,
            email="lee@example.com",
            name="이와플",
            generation="26",
            qualification=Qualification.ACTIVE,
        ),
        UserService.create(
            db,
            email="park@example.com",
            name="박철수",
            generation="26",
            qualification=Qualification.ACTIVE,
        ),
    ]


class TestUserSearchByName:
    def test_search_returns_matching_users(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        admin_user: User,
        users: list[User],
    ):
        """이름 부분 일치로 유저 목록을 반환한다."""
        response = client.get(
            "/users?name=와플",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        names = [u["name"] for u in data["data"]["items"]]
        assert "김와플" in names
        assert "이와플" in names
        assert "박철수" not in names

    def test_search_exact_name(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        admin_user: User,
        users: list[User],
    ):
        """정확한 이름으로 검색하면 해당 유저만 반환된다."""
        response = client.get(
            "/users?name=김와플",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        items = data["data"]["items"]
        assert len(items) == 1
        assert items[0]["name"] == "김와플"

    def test_search_no_match_returns_empty(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        admin_user: User,
        users: list[User],
    ):
        """매칭되는 유저가 없으면 빈 리스트를 반환한다."""
        response = client.get(
            "/users?name=존재하지않는이름",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["items"] == []
        assert data["data"]["next_cursor"] is None

    def test_search_without_name_returns_all(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        admin_user: User,
        users: list[User],
    ):
        """name 파라미터 없이 호출하면 전체 유저를 반환한다."""
        response = client.get(
            "/users",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        # admin_user + 3 users
        assert len(data["data"]["items"]) == 4

    def test_search_requires_admin(
        self, client: TestClient, regular_token: str, users: list[User]
    ):
        """어드민이 아니면 이름 검색이 거부된다."""
        response = client.get(
            "/users?name=와플",
            headers={"Authorization": f"Bearer {regular_token}"},
        )

        assert response.status_code == 403

    def test_search_requires_auth(self, client: TestClient, users: list[User]):
        """인증 없이 이름 검색을 하면 거부된다."""
        response = client.get("/users?name=와플")

        assert response.status_code == 401

    def test_search_case_insensitive(
        self, client: TestClient, db: Session, admin_token: str, admin_user: User
    ):
        """영문 이름 검색은 대소문자를 구분하지 않는다."""
        UserService.create(
            db,
            email="john@example.com",
            name="John Kim",
            generation="26",
            qualification=Qualification.ACTIVE,
        )

        response = client.get(
            "/users?name=john",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        names = [u["name"] for u in data["data"]["items"]]
        assert "John Kim" in names

    def test_search_excludes_deleted_users(
        self, client: TestClient, db: Session, admin_token: str, admin_user: User
    ):
        """삭제된 유저는 검색 결과에 포함되지 않는다."""
        user = UserService.create(
            db,
            email="deleted@example.com",
            name="삭제될유저",
            generation="26",
            qualification=Qualification.ACTIVE,
        )
        UserService.delete(db, user)

        response = client.get(
            "/users?name=삭제될유저",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["items"] == []

    def test_search_combined_with_pagination(
        self, client: TestClient, db: Session, admin_token: str, admin_user: User
    ):
        """name과 limit을 함께 사용할 수 있다."""
        for i in range(5):
            UserService.create(
                db,
                email=f"waffle{i}@example.com",
                name=f"와플유저{i}",
                generation="26",
                qualification=Qualification.ACTIVE,
            )

        response = client.get(
            "/users?name=와플유저&limit=3",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]["items"]) == 3
        assert data["data"]["next_cursor"] is not None


@pytest.fixture
def project(db: Session, admin_user: User):
    p = ProjectService.create(
        db,
        name="테스트 프로젝트",
        status="active",
        started_at=date(2024, 1, 1),
    )
    db.commit()
    return p


@pytest.fixture
def another_project(db: Session, admin_user: User):
    p = ProjectService.create(
        db,
        name="두번째 프로젝트",
        status="active",
        started_at=date(2024, 3, 1),
    )
    db.commit()
    return p


class TestCurrentProjectsInUserDetail:
    def test_user_with_no_projects(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        admin_user: User,
        active_user: User,
    ):
        """프로젝트가 없는 유저는 current_projects가 빈 리스트다."""
        response = client.get(
            f"/users/{active_user.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        assert response.json()["data"]["current_projects"] == []

    def test_user_with_active_project(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        admin_user: User,
        active_user: User,
        project,
    ):
        """현재 소속된 프로젝트가 current_projects에 포함된다."""
        MemberService.add(
            db,
            project_id=project.id,
            user_id=active_user.id,
            role=MemberRole.MEMBER,
            position=None,
            actor_id=admin_user.id,
        )
        db.commit()

        response = client.get(
            f"/users/{active_user.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        current_projects = response.json()["data"]["current_projects"]
        assert len(current_projects) == 1
        assert current_projects[0]["id"] == project.id
        assert current_projects[0]["name"] == "테스트 프로젝트"

    def test_user_with_multiple_projects(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        admin_user: User,
        active_user: User,
        project,
        another_project,
    ):
        """여러 프로젝트에 소속된 경우 모두 반환된다."""
        MemberService.add(
            db,
            project_id=project.id,
            user_id=active_user.id,
            role=MemberRole.MEMBER,
            position=None,
            actor_id=admin_user.id,
        )
        MemberService.add(
            db,
            project_id=another_project.id,
            user_id=active_user.id,
            role=MemberRole.LEADER,
            position=None,
            actor_id=admin_user.id,
        )
        db.commit()

        response = client.get(
            f"/users/{active_user.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        current_projects = response.json()["data"]["current_projects"]
        assert len(current_projects) == 2
        project_ids = [p["id"] for p in current_projects]
        assert project.id in project_ids
        assert another_project.id in project_ids

    def test_left_project_not_included(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        admin_user: User,
        active_user: User,
        project,
        another_project,
    ):
        """탈퇴한 프로젝트는 current_projects에 포함되지 않는다."""
        MemberService.add(
            db,
            project_id=project.id,
            user_id=active_user.id,
            role=MemberRole.MEMBER,
            position=None,
            actor_id=admin_user.id,
        )
        MemberService.add(
            db,
            project_id=another_project.id,
            user_id=active_user.id,
            role=MemberRole.MEMBER,
            position=None,
            actor_id=admin_user.id,
        )
        # another_project에서 active_user 제거하려면 리더가 필요
        MemberService.add(
            db,
            project_id=another_project.id,
            user_id=admin_user.id,
            role=MemberRole.LEADER,
            position=None,
            actor_id=admin_user.id,
        )
        db.commit()

        member = MemberService.get_active(db, another_project.id, active_user.id)
        MemberService.remove(db, member, actor_id=admin_user.id)
        db.commit()

        response = client.get(
            f"/users/{active_user.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        current_projects = response.json()["data"]["current_projects"]
        assert len(current_projects) == 1
        assert current_projects[0]["id"] == project.id

    def test_current_projects_in_user_list(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        admin_user: User,
        active_user: User,
        project,
    ):
        """유저 목록 조회 시에도 current_projects가 포함된다."""
        MemberService.add(
            db,
            project_id=project.id,
            user_id=active_user.id,
            role=MemberRole.MEMBER,
            position=None,
            actor_id=admin_user.id,
        )
        db.commit()

        response = client.get(
            "/users",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        users = response.json()["data"]["items"]
        target = next(u for u in users if u["id"] == active_user.id)
        assert len(target["current_projects"]) == 1
        assert target["current_projects"][0]["id"] == project.id

    def test_current_projects_in_my_profile(
        self,
        client: TestClient,
        db: Session,
        active_token: str,
        active_user: User,
        admin_user: User,
        project,
    ):
        """본인 프로필 조회 시에도 current_projects가 포함된다."""
        MemberService.add(
            db,
            project_id=project.id,
            user_id=active_user.id,
            role=MemberRole.MEMBER,
            position=None,
            actor_id=admin_user.id,
        )
        db.commit()

        response = client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {active_token}"},
        )

        assert response.status_code == 200
        current_projects = response.json()["data"]["current_projects"]
        assert len(current_projects) == 1
        assert current_projects[0]["name"] == "테스트 프로젝트"
