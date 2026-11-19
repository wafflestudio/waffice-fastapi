"""Access and contact privacy for member profiles and activity listings."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Qualification, User, UserActivity
from app.services import UserService
from tests.test_activity_history_management import (
    auth,
    create_activity,
    create_project_with_leader,
)

STUDENT_ID = "2024-12345"
PHONE = "010-1234-5678"
LOGIN_EMAIL = "contact-member@example.com"
CONTACT_EMAIL = "contact-private@example.org"
VISIBILITY_FLAGS = (
    "is_student_id_public",
    "is_phone_public",
    "is_contact_email_public",
)


@pytest.fixture
def contact_member(db: Session) -> User:
    return UserService.create(
        db,
        email=LOGIN_EMAIL,
        name="Contact Member",
        qualification=Qualification.ACTIVE,
        student_id=STUDENT_ID,
        phone=PHONE,
        contact_email=CONTACT_EMAIL,
    )


@pytest.fixture
def member_activity(db: Session, contact_member: User) -> UserActivity:
    project = create_project_with_leader(db, contact_member)
    return create_activity(
        db,
        user=contact_member,
        project_id=project.id,
        position="Developer",
        start_date=100,
    )


@pytest.fixture
def associate_admin_token(
    db: Session, associate_user: User, associate_token: str
) -> str:
    UserService.update(db, associate_user, is_admin=True)
    return associate_token


@pytest.fixture
def associate_president_token(
    db: Session, open_president_term: User, president_token: str
) -> str:
    # Exercise the presidency bypass with a qualification that cannot read on its own.
    UserService.update(db, open_president_term, qualification=Qualification.ASSOCIATE)
    return president_token


def user_views(client: TestClient, token: str, user_id: int) -> tuple[dict, dict]:
    listing = client.get("/users", headers=auth(token))
    assert listing.status_code == 200
    item = next(
        item for item in listing.json()["data"]["items"] if item["id"] == user_id
    )

    detail = client.get(f"/users/{user_id}", headers=auth(token))
    assert detail.status_code == 200
    profile = detail.json()["data"]
    assert profile["id"] == user_id
    return item, profile


@pytest.mark.parametrize(
    ("token_fixture", "expected_status"),
    [
        ("regular_token", 200),
        ("active_token", 200),
        ("associate_token", 403),
        ("pending_token", 403),
        ("associate_admin_token", 200),
        ("associate_president_token", 200),
    ],
)
def test_member_read_access_by_role(
    client: TestClient,
    request: pytest.FixtureRequest,
    contact_member: User,
    member_activity: UserActivity,
    token_fixture: str,
    expected_status: int,
):
    headers = auth(request.getfixturevalue(token_fixture))
    user_url = f"/users/{contact_member.id}"
    users = client.get("/users", params={"name": contact_member.name}, headers=headers)
    profile = client.get(user_url, headers=headers)
    user_activities = client.get(f"{user_url}/activities", headers=headers)
    all_activities = client.get("/activities", headers=headers)
    for response in (users, profile, user_activities, all_activities):
        assert response.status_code == expected_status, response.request.url.path

    if expected_status == 200:
        assert [item["id"] for item in users.json()["data"]["items"]] == [
            contact_member.id
        ]
        assert profile.json()["data"]["id"] == contact_member.id
        assert [item["id"] for item in user_activities.json()["data"]] == [
            member_activity.id
        ]
        assert [item["id"] for item in all_activities.json()["data"]["items"]] == [
            member_activity.id
        ]


def test_widened_gets_send_private_no_store_cache_control(
    client: TestClient,
    regular_token: str,
    contact_member: User,
    member_activity: UserActivity,
):
    user_url = f"/users/{contact_member.id}"
    headers = auth(regular_token)
    for path in ("/users", user_url, f"{user_url}/activities", "/activities"):
        response = client.get(path, headers=headers)
        assert response.status_code == 200, f"GET {path}"
        assert "cache-control" in response.headers, f"GET {path} missing Cache-Control"
        assert response.headers["cache-control"] == "private, no-store", f"GET {path}"


def test_regular_read_views_hide_applicants_and_deleted_users(
    client: TestClient,
    db: Session,
    regular_token: str,
    admin_token: str,
    contact_member: User,
    pending_user: User,
    member_activity: UserActivity,
):
    deleted_user = UserService.create(
        db,
        email="deleted-member@example.com",
        name="Deleted Member",
        qualification=Qualification.ACTIVE,
    )
    pending_activity = create_activity(
        db,
        user=pending_user,
        project_id=member_activity.project_id,
        position="Applicant activity",
        start_date=101,
    )
    deleted_activity = create_activity(
        db,
        user=deleted_user,
        project_id=member_activity.project_id,
        position="Deleted member activity",
        start_date=102,
    )
    UserService.delete(db, deleted_user)

    response = client.get("/users", headers=auth(regular_token))
    assert response.status_code == 200
    visible_ids = {item["id"] for item in response.json()["data"]["items"]}
    assert contact_member.id in visible_ids
    assert {pending_user.id, deleted_user.id}.isdisjoint(visible_ids)

    for user in (pending_user, deleted_user):
        for path in (f"/users/{user.id}", f"/users/{user.id}/activities"):
            response = client.get(path, headers=auth(regular_token))
            assert response.status_code == 404, path

    # The hidden activities have newer IDs. Filtering must happen before pagination.
    response = client.get("/activities?size=1", headers=auth(regular_token))
    assert response.status_code == 200
    page = response.json()["data"]
    assert page["total"] == len(page["items"]) == 1
    assert [item["id"] for item in page["items"]] == [member_activity.id]

    for profile in user_views(client, admin_token, pending_user.id):
        assert profile["qualification"] == Qualification.PENDING.value

    response = client.get(
        f"/users/{pending_user.id}/activities", headers=auth(admin_token)
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]] == [pending_activity.id]

    response = client.get("/activities", headers=auth(admin_token))
    assert response.status_code == 200
    page = response.json()["data"]
    assert page["total"] == len(page["items"]) == 3
    assert {item["id"] for item in page["items"]} == {
        member_activity.id,
        pending_activity.id,
        deleted_activity.id,
    }


def test_regular_can_read_pending_temporary_member(
    client: TestClient, db: Session, regular_token: str, member_activity: UserActivity
):
    temporary = UserService.create(
        db, name="Roster Placeholder", student_id="2024-98765", is_temporary=True
    )
    activity = create_activity(
        db,
        user=temporary,
        project_id=member_activity.project_id,
        position="Temporary member activity",
        start_date=105,
    )

    for profile in user_views(client, regular_token, temporary.id):
        assert profile["qualification"] == Qualification.PENDING.value
        assert profile["is_temporary"] is True

    response = client.get(
        f"/users/{temporary.id}/activities", headers=auth(regular_token)
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]] == [activity.id]

    response = client.get("/activities", headers=auth(regular_token))
    assert response.status_code == 200
    assert activity.id in {item["id"] for item in response.json()["data"]["items"]}


@pytest.mark.parametrize("public_field", ["student_id", "phone", "contact_email"])
def test_contact_flags_mask_independently_without_changing_stored_values(
    client: TestClient,
    db: Session,
    regular_token: str,
    contact_member: User,
    public_field: str,
):
    target_id = contact_member.id
    student_id_public = public_field == "student_id"
    phone_public = public_field == "phone"
    contact_email_public = public_field == "contact_email"
    UserService.update(
        db,
        contact_member,
        is_student_id_public=student_id_public,
        is_phone_public=phone_public,
        is_contact_email_public=contact_email_public,
    )

    for profile in user_views(client, regular_token, target_id):
        assert profile["student_id"] == (STUDENT_ID if student_id_public else None)
        assert profile["phone"] == (PHONE if phone_public else None)
        assert profile["contact_email"] == (
            CONTACT_EMAIL if contact_email_public else None
        )
        assert profile["email"] == LOGIN_EMAIL

    with Session(bind=db.get_bind()) as read_db:
        stored = read_db.get(User, target_id)
        assert stored.student_id == STUDENT_ID
        assert stored.phone == PHONE
        assert stored.contact_email == CONTACT_EMAIL
        assert stored.email == LOGIN_EMAIL
        assert stored.is_student_id_public is student_id_public
        assert stored.is_phone_public is phone_public
        assert stored.is_contact_email_public is contact_email_public

    UserService.update(
        db,
        contact_member,
        is_student_id_public=False,
        is_phone_public=False,
        is_contact_email_public=False,
    )
    for profile in user_views(client, regular_token, target_id):
        assert profile["student_id"] is None
        assert profile["phone"] is None
        assert profile["contact_email"] is None
        assert profile["email"] == LOGIN_EMAIL

    with Session(bind=db.get_bind()) as read_db:
        stored = read_db.get(User, target_id)
        assert stored.student_id == STUDENT_ID
        assert stored.phone == PHONE
        assert stored.contact_email == CONTACT_EMAIL
        assert stored.email == LOGIN_EMAIL
        assert stored.is_student_id_public is False
        assert stored.is_phone_public is False
        assert stored.is_contact_email_public is False


def test_user_detail_routes_mask_private_contact_fields_for_other_members(
    client: TestClient,
    regular_token: str,
    admin_token: str,
    contact_member: User,
):
    for profile in user_views(client, regular_token, contact_member.id):
        assert profile["student_id"] is None
        assert profile["phone"] is None
        assert profile["contact_email"] is None
        assert profile["email"] == LOGIN_EMAIL

    for profile in user_views(client, admin_token, contact_member.id):
        assert profile["student_id"] == STUDENT_ID
        assert profile["phone"] == PHONE
        assert profile["contact_email"] == CONTACT_EMAIL
        assert profile["email"] == LOGIN_EMAIL


def test_self_and_admin_view_private_contact_values(
    client: TestClient,
    db: Session,
    active_user: User,
    active_token: str,
    admin_token: str,
):
    UserService.update(
        db, active_user, student_id=STUDENT_ID, phone=PHONE, contact_email=CONTACT_EMAIL
    )

    for token in (active_token, admin_token):
        for profile in user_views(client, token, active_user.id):
            assert profile["is_student_id_public"] is False
            assert profile["is_phone_public"] is False
            assert profile["is_contact_email_public"] is False
            assert profile["student_id"] == STUDENT_ID
            assert profile["phone"] == PHONE
            assert profile["contact_email"] == CONTACT_EMAIL


def test_patch_me_toggles_visibility_and_preserves_omitted_flags(
    client: TestClient, db: Session, regular_user: User, regular_token: str
):
    user_id = regular_user.id
    updates = [
        ("is_student_id_public", True, (True, False, False)),
        ("is_phone_public", True, (True, True, False)),
        ("is_contact_email_public", True, (True, True, True)),
        ("is_student_id_public", False, (False, True, True)),
        ("is_phone_public", False, (False, False, True)),
        ("is_contact_email_public", False, (False, False, False)),
    ]
    for flag, value, expected_flags in updates:
        student_id_public, phone_public, contact_email_public = expected_flags
        response = client.patch(
            "/users/me", json={flag: value}, headers=auth(regular_token)
        )
        assert response.status_code == 200

        response = client.get("/users/me", headers=auth(regular_token))
        assert response.status_code == 200
        profile = response.json()["data"]
        assert profile["is_student_id_public"] is student_id_public
        assert profile["is_phone_public"] is phone_public
        assert profile["is_contact_email_public"] is contact_email_public

        with Session(bind=db.get_bind()) as read_db:
            stored = read_db.get(User, user_id)
            assert stored.is_student_id_public is student_id_public
            assert stored.is_phone_public is phone_public
            assert stored.is_contact_email_public is contact_email_public


@pytest.mark.parametrize("flag", VISIBILITY_FLAGS)
def test_patch_me_rejects_null_visibility_flags(
    client: TestClient, regular_token: str, flag: str
):
    response = client.patch("/users/me", json={flag: None}, headers=auth(regular_token))

    assert response.status_code == 422
    assert [error["loc"] for error in response.json()["detail"]] == [["body", flag]]


def test_admin_patch_ignores_visibility_flags(
    client: TestClient, db: Session, admin_token: str, contact_member: User
):
    target_id = contact_member.id
    UserService.update(db, contact_member, is_student_id_public=True)

    response = client.patch(
        f"/users/{target_id}",
        headers=auth(admin_token),
        json={
            "name": "Renamed Member",
            "is_student_id_public": False,
            "is_phone_public": True,
            "is_contact_email_public": True,
        },
    )
    assert response.status_code == 200

    with Session(bind=db.get_bind()) as read_db:
        stored = read_db.get(User, target_id)
        assert stored.name == "Renamed Member"
        assert stored.is_student_id_public is True
        assert stored.is_phone_public is False
        assert stored.is_contact_email_public is False


def test_admin_patch_request_schema_excludes_visibility_flags(client: TestClient):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    openapi = response.json()
    request_body = openapi["paths"]["/users/{user_id}"]["patch"]["requestBody"]
    schema_ref = request_body["content"]["application/json"]["schema"]["$ref"]
    schema_name = schema_ref.rsplit("/", 1)[-1]
    properties = openapi["components"]["schemas"][schema_name]["properties"]
    assert "name" in properties
    assert set(VISIBILITY_FLAGS).isdisjoint(properties)


def test_profile_update_schema_flags_are_plain_boolean_without_default(
    client: TestClient,
):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    openapi = response.json()
    request_body = openapi["paths"]["/users/me"]["patch"]["requestBody"]
    schema_ref = request_body["content"]["application/json"]["schema"]["$ref"]
    schema_name = schema_ref.rsplit("/", 1)[-1]
    schema = openapi["components"]["schemas"][schema_name]
    properties = schema["properties"]
    for flag in VISIBILITY_FLAGS:
        assert properties[flag]["type"] == "boolean"
        assert "default" not in properties[flag]
        assert "anyOf" not in properties[flag]
        assert flag not in schema.get("required", [])


def test_regular_cannot_access_admin_only_user_endpoints(
    client: TestClient,
    regular_token: str,
    contact_member: User,
    member_activity: UserActivity,
):
    user_url = f"/users/{contact_member.id}"
    activities_url = f"{user_url}/activities"
    activity_url = f"{activities_url}/{member_activity.id}"
    requests = [
        ("GET", f"{user_url}/audit-log", None),
        ("GET", "/users/pending", None),
        ("PATCH", user_url, {"name": "Renamed Member"}),
        (
            "POST",
            activities_url,
            {
                "project_id": member_activity.project_id,
                "position": "New",
                "start_date": 110,
            },
        ),
        ("PATCH", activity_url, {"position": "Changed"}),
        ("DELETE", activity_url, None),
        ("DELETE", user_url, None),
    ]
    for method, path, payload in requests:
        response = client.request(
            method, path, json=payload, headers=auth(regular_token)
        )
        assert response.status_code == 403, f"{method} {path}"
        assert response.json()["detail"] == "Admin permission required"
