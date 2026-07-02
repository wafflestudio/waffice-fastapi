"""Tests for user search by name (GET /users?name=...)"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Qualification, User
from app.services import UserService


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
