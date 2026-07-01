"""Tests for the temporary member roster import endpoint (POST /users/temporary)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Qualification, User
from app.services import UserService


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_import_creates_temporary_members(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """Admin import creates temp records with only name/student_id populated."""
    response = client.post(
        "/users/temporary",
        json={
            "members": [
                {"name": "홍길동", "student_id": "2021-10001"},
                {"name": "김철수", "student_id": "2021-10002"},
            ]
        },
        headers=_auth(admin_token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["created_count"] == 2
    assert data["skipped_count"] == 0
    assert {m["name"] for m in data["created"]} == {"홍길동", "김철수"}
    assert all(m["email"] is None for m in data["created"])
    assert data["skipped"] == []

    # Verify the persisted record: temp flag set, only name/student_id filled.
    user = UserService.get_by_student_id(db, "2021-10001")
    assert user is not None
    assert user.is_temporary is True
    assert user.name == "홍길동"
    assert user.student_id == "2021-10001"
    assert user.email is None
    assert user.google_id is None
    assert user.qualification == Qualification.PENDING


def test_import_skips_existing_student_id(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """A row whose student_id already belongs to a member is skipped."""
    UserService.create(
        db,
        email="existing@example.com",
        name="기존회원",
        generation="26",
        qualification=Qualification.ACTIVE,
        google_id="existing_google_id",
        student_id="2021-20001",
    )

    response = client.post(
        "/users/temporary",
        json={
            "members": [
                {"name": "기존회원", "student_id": "2021-20001"},
                {"name": "신규회원", "student_id": "2021-20002"},
            ]
        },
        headers=_auth(admin_token),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["created_count"] == 1
    assert data["skipped_count"] == 1
    assert data["created"][0]["name"] == "신규회원"
    assert data["skipped"][0]["student_id"] == "2021-20001"
    assert data["skipped"][0]["reason"] == "already_exists"


def test_import_dedupes_within_request(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """The same student_id appearing twice in one request creates one record."""
    response = client.post(
        "/users/temporary",
        json={
            "members": [
                {"name": "중복1", "student_id": "2021-30001"},
                {"name": "중복2", "student_id": "2021-30001"},
            ]
        },
        headers=_auth(admin_token),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["created_count"] == 1
    assert data["skipped_count"] == 1
    assert data["skipped"][0]["reason"] == "duplicate_in_request"


def test_import_is_idempotent_on_retry(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """Re-importing the same roster creates nothing the second time."""
    payload = {"members": [{"name": "재시도", "student_id": "2021-40001"}]}

    first = client.post("/users/temporary", json=payload, headers=_auth(admin_token))
    assert first.json()["data"]["created_count"] == 1

    second = client.post("/users/temporary", json=payload, headers=_auth(admin_token))
    body = second.json()["data"]
    assert body["created_count"] == 0
    assert body["skipped_count"] == 1
    assert body["skipped"][0]["reason"] == "already_exists"


def test_import_requires_admin(
    client: TestClient, regular_token: str, regular_user: User
):
    """Non-admins cannot import members."""
    response = client.post(
        "/users/temporary",
        json={"members": [{"name": "홍길동", "student_id": "2021-50001"}]},
        headers=_auth(regular_token),
    )
    assert response.status_code == 403


def test_import_requires_authentication(client: TestClient):
    """Unauthenticated requests are rejected."""
    response = client.post(
        "/users/temporary",
        json={"members": [{"name": "홍길동", "student_id": "2021-60001"}]},
    )
    assert response.status_code == 401


def test_import_rejects_empty_roster(
    client: TestClient, admin_token: str, admin_user: User
):
    """An empty roster fails validation."""
    response = client.post(
        "/users/temporary",
        json={"members": []},
        headers=_auth(admin_token),
    )
    assert response.status_code == 422


def test_import_rejects_whitespace_only_name(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """A whitespace-only name is rejected (not silently stored as empty)."""
    response = client.post(
        "/users/temporary",
        json={"members": [{"name": "   ", "student_id": "2021-70001"}]},
        headers=_auth(admin_token),
    )
    assert response.status_code == 422
    # Nothing should have been persisted.
    assert UserService.get_by_student_id(db, "2021-70001") is None


def test_import_strips_surrounding_whitespace(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """Leading/trailing whitespace is trimmed on both name and student_id."""
    response = client.post(
        "/users/temporary",
        json={"members": [{"name": "  홍길동  ", "student_id": "  2021-70002  "}]},
        headers=_auth(admin_token),
    )
    assert response.status_code == 200
    assert response.json()["data"]["created_count"] == 1

    user = UserService.get_by_student_id(db, "2021-70002")
    assert user is not None
    assert user.name == "홍길동"
    assert user.student_id == "2021-70002"

    # Re-importing the trimmed value is recognized as already existing.
    again = client.post(
        "/users/temporary",
        json={"members": [{"name": "홍길동", "student_id": "2021-70002"}]},
        headers=_auth(admin_token),
    )
    assert again.json()["data"]["skipped"][0]["reason"] == "already_exists"


def test_import_rejects_oversized_roster(
    client: TestClient, admin_token: str, admin_user: User
):
    """A roster exceeding the max_length cap fails validation."""
    members = [{"name": f"M{i}", "student_id": f"2021-8{i:04d}"} for i in range(2001)]
    response = client.post(
        "/users/temporary",
        json={"members": members},
        headers=_auth(admin_token),
    )
    assert response.status_code == 422


def test_import_mixed_roster_classifies_each_row(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """A single request can create, skip-existing, and skip-duplicate together."""
    UserService.create(
        db,
        email="mixed-existing@example.com",
        name="기존",
        generation="26",
        qualification=Qualification.ACTIVE,
        google_id="mixed_existing_google_id",
        student_id="2021-90001",
    )

    response = client.post(
        "/users/temporary",
        json={
            "members": [
                {"name": "신규", "student_id": "2021-90002"},  # created
                {"name": "기존", "student_id": "2021-90001"},  # already_exists
                {"name": "신규복제1", "student_id": "2021-90003"},  # created
                {
                    "name": "신규복제2",
                    "student_id": "2021-90003",
                },  # duplicate_in_request
            ]
        },
        headers=_auth(admin_token),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["created_count"] == 2
    assert data["skipped_count"] == 2
    reasons = {(s["student_id"], s["reason"]) for s in data["skipped"]}
    assert ("2021-90001", "already_exists") in reasons
    assert ("2021-90003", "duplicate_in_request") in reasons


def test_temporary_members_excluded_from_pending(
    client: TestClient,
    db: Session,
    admin_token: str,
    admin_user: User,
    pending_user: User,
):
    """Imported temp members default to PENDING but must not pollute /users/pending."""
    client.post(
        "/users/temporary",
        json={"members": [{"name": "임시", "student_id": "2021-95001"}]},
        headers=_auth(admin_token),
    )

    response = client.get("/users/pending", headers=_auth(admin_token))
    assert response.status_code == 200
    names = {u["name"] for u in response.json()["data"]}
    # The real OAuth signup awaiting approval is present...
    assert pending_user.name in names
    # ...but the roster placeholder is not.
    assert "임시" not in names


def test_is_temporary_and_null_email_exposed_via_get_user(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """A created temp member reads back with is_temporary=true and email=null."""
    created = client.post(
        "/users/temporary",
        json={"members": [{"name": "조회대상", "student_id": "2021-96001"}]},
        headers=_auth(admin_token),
    ).json()["data"]["created"]
    user_id = created[0]["id"]

    response = client.get(f"/users/{user_id}", headers=_auth(admin_token))
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["is_temporary"] is True
    assert body["email"] is None
    assert body["student_id"] == "2021-96001"


def test_temporary_member_cannot_be_approved(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """A temporary member must not be approvable via /{user_id}/approve."""
    created = client.post(
        "/users/temporary",
        json={"members": [{"name": "임시승인", "student_id": "2021-97001"}]},
        headers=_auth(admin_token),
    ).json()["data"]["created"]
    user_id = created[0]["id"]

    response = client.post(
        f"/users/{user_id}/approve",
        json={"qualification": "regular"},
        headers=_auth(admin_token),
    )
    assert response.status_code == 400
    assert response.json()["error"] == "TEMPORARY_MEMBER_CANNOT_BE_APPROVED"

    # Qualification is unchanged: still a PENDING temporary member.
    user = UserService.get_by_student_id(db, "2021-97001")
    assert user.qualification == Qualification.PENDING
    assert user.is_temporary is True


def _import_one(
    client: TestClient, admin_token: str, name: str, student_id: str
) -> int:
    """Import a single temp member and return its new user id."""
    created = client.post(
        "/users/temporary",
        json={"members": [{"name": name, "student_id": student_id}]},
        headers=_auth(admin_token),
    ).json()["data"]["created"]
    return created[0]["id"]


def test_import_rejects_whitespace_only_student_id(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """A whitespace-only student_id is rejected (symmetric to the name case)."""
    response = client.post(
        "/users/temporary",
        json={"members": [{"name": "홍길동", "student_id": "   "}]},
        headers=_auth(admin_token),
    )
    assert response.status_code == 422


def test_import_rejects_zero_width_only_value(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """A value made only of zero-width/format characters is rejected, not stored."""
    response = client.post(
        "/users/temporary",
        # Two zero-width spaces — visually blank.
        json={"members": [{"name": "\u200b\u200b", "student_id": "2021-98000"}]},
        headers=_auth(admin_token),
    )
    assert response.status_code == 422
    assert UserService.get_by_student_id(db, "2021-98000") is None


def test_import_trims_bom_so_match_key_is_consistent(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """A BOM-prefixed student_id is normalized so dedup/matching still works."""
    response = client.post(
        "/users/temporary",
        json={"members": [{"name": "BOM", "student_id": "\ufeff2021-98001"}]},
        headers=_auth(admin_token),
    )
    assert response.status_code == 200
    assert response.json()["data"]["created_count"] == 1
    # Stored under the trimmed key...
    assert UserService.get_by_student_id(db, "2021-98001") is not None
    # ...so a clean re-import is recognized as already existing (no duplicate).
    again = client.post(
        "/users/temporary",
        json={"members": [{"name": "BOM", "student_id": "2021-98001"}]},
        headers=_auth(admin_token),
    )
    assert again.json()["data"]["skipped"][0]["reason"] == "already_exists"


def test_temporary_member_cannot_be_approved_even_to_pending(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """The temp guard wins over the PENDING-target rejection (precedence pinned)."""
    user_id = _import_one(client, admin_token, "임시펜딩", "2021-97002")
    response = client.post(
        f"/users/{user_id}/approve",
        json={"qualification": "pending"},
        headers=_auth(admin_token),
    )
    assert response.status_code == 400
    assert response.json()["error"] == "TEMPORARY_MEMBER_CANNOT_BE_APPROVED"


def test_temporary_member_cannot_be_added_to_project(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """A temp member cannot be added to an existing project."""
    project = client.post(
        "/projects",
        json={
            "name": "Temp Guard Project",
            "started_at": "2026-01-01",
            "members": [{"user_id": admin_user.id, "role": "leader"}],
        },
        headers=_auth(admin_token),
    ).json()["data"]
    temp_id = _import_one(client, admin_token, "임시프로젝트", "2021-99001")

    response = client.post(
        f"/projects/{project['id']}/members",
        json={"user_id": temp_id, "role": "member"},
        headers=_auth(admin_token),
    )
    assert response.status_code == 400
    assert response.json()["error"] == "TEMPORARY_MEMBER_CANNOT_JOIN_PROJECT"


def test_create_project_rejects_temporary_member(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """A temp member in the initial roster blocks project creation."""
    temp_id = _import_one(client, admin_token, "임시생성", "2021-99002")

    response = client.post(
        "/projects",
        json={
            "name": "Should Fail",
            "started_at": "2026-01-01",
            "members": [
                {"user_id": admin_user.id, "role": "leader"},
                {"user_id": temp_id, "role": "member"},
            ],
        },
        headers=_auth(admin_token),
    )
    assert response.status_code == 400
    assert response.json()["error"] == "TEMPORARY_MEMBER_CANNOT_JOIN_PROJECT"
