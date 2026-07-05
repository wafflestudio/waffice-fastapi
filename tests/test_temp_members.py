"""Tests for the temporary member roster import endpoint (POST /users/temporary).

The endpoint accepts an .xlsx or .csv upload; the backend parses it (header row
locates the name / student_id columns) and bulk-creates temporary members.
"""

import csv
import io

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.models import Qualification, User
from app.services import UserService

XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _xlsx(rows, headers=("이름", "학번")) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(list(headers))
    for row in rows:
        ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _csv(rows, headers=("이름", "학번")) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(list(headers))
    for row in rows:
        writer.writerow(list(row))
    return buf.getvalue().encode("utf-8-sig")


def _post_bytes(client, token, data, filename="roster.xlsx", content_type=XLSX_CT):
    return client.post(
        "/users/temporary",
        files={"file": (filename, data, content_type)},
        headers=_auth(token),
    )


def _post_roster(client, token, rows=None, *, headers=("이름", "학번")):
    return _post_bytes(client, token, _xlsx(rows or [], headers))


def _import_one(client, token, name: str, student_id: str) -> int:
    created = _post_roster(client, token, [(name, student_id)]).json()["data"][
        "created"
    ]
    return created[0]["id"]


def test_import_creates_temporary_members(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """Admin upload creates temp records with only name/student_id populated."""
    response = _post_roster(
        client, admin_token, [("홍길동", "2021-10001"), ("김철수", "2021-10002")]
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["created_count"] == 2
    assert data["skipped_count"] == 0
    assert {m["name"] for m in data["created"]} == {"홍길동", "김철수"}
    assert all(m["email"] is None for m in data["created"])

    user = UserService.get_by_student_id(db, "2021-10001")
    assert user is not None
    assert user.is_temporary is True
    assert user.name == "홍길동"
    assert user.student_id == "2021-10001"
    assert user.email is None
    assert user.qualification == Qualification.PENDING


def test_import_accepts_csv(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """A .csv roster is parsed on the backend just like .xlsx."""
    data = _csv([("김와플", "2021-23456"), ("김스튜디오", "2021-65432")])
    response = _post_bytes(
        client, admin_token, data, filename="roster.csv", content_type="text/csv"
    )
    assert response.status_code == 200
    assert response.json()["data"]["created_count"] == 2
    assert UserService.get_by_student_id(db, "2021-23456") is not None


def test_import_accepts_english_headers_any_order(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """Columns are located by header, so English headers in any order work."""
    response = _post_roster(
        client, admin_token, [("2021-11111", "영문헤더")], headers=("student_id", "name")
    )
    assert response.status_code == 200
    user = UserService.get_by_student_id(db, "2021-11111")
    assert user is not None and user.name == "영문헤더"


def test_import_numeric_student_id_is_stringified(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """A numeric student_id cell is stored as digits, not '2021001.0'."""
    response = _post_roster(client, admin_token, [("숫자학번", 2021001)])
    assert response.status_code == 200
    assert UserService.get_by_student_id(db, "2021001") is not None


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

    response = _post_roster(
        client, admin_token, [("기존회원", "2021-20001"), ("신규회원", "2021-20002")]
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["created_count"] == 1
    assert data["skipped_count"] == 1
    assert data["skipped"][0]["reason"] == "already_exists"
    assert "이미 등록된" in data["skipped"][0]["message"]


def test_import_dedupes_within_file(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """The same student_id appearing twice in one file creates one record."""
    response = _post_roster(
        client, admin_token, [("중복1", "2021-30001"), ("중복2", "2021-30001")]
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["created_count"] == 1
    assert data["skipped"][0]["reason"] == "duplicate_in_request"
    assert "중복" in data["skipped"][0]["message"]


def test_import_is_idempotent_on_retry(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """Re-uploading the same roster creates nothing the second time."""
    rows = [("재시도", "2021-40001")]
    assert _post_roster(client, admin_token, rows).json()["data"]["created_count"] == 1

    body = _post_roster(client, admin_token, rows).json()["data"]
    assert body["created_count"] == 0
    assert body["skipped"][0]["reason"] == "already_exists"


def test_import_requires_admin(
    client: TestClient, regular_token: str, regular_user: User
):
    """Non-admins cannot import members."""
    assert (
        _post_roster(client, regular_token, [("홍길동", "2021-50001")]).status_code == 403
    )


def test_import_requires_authentication(client: TestClient):
    """Unauthenticated requests are rejected."""
    response = client.post(
        "/users/temporary",
        files={"file": ("roster.xlsx", _xlsx([("홍길동", "2021-60001")]), XLSX_CT)},
    )
    assert response.status_code == 401


def test_import_rejects_empty_roster(
    client: TestClient, admin_token: str, admin_user: User
):
    """A roster with a header but no data rows is a 422."""
    response = _post_roster(client, admin_token, [])
    assert response.status_code == 422
    assert response.json()["error"] == "EMPTY_ROSTER"


def test_import_rejects_invalid_file(
    client: TestClient, admin_token: str, admin_user: User
):
    """A corrupt/invalid file → 400 '파일 양식이 올바르지 않습니다.'"""
    response = _post_bytes(
        client, admin_token, b"PK\x03\x04 not really a zip", filename="roster.xlsx"
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "INVALID_ROSTER_FILE"
    assert body["message"] == "파일 양식이 올바르지 않습니다."


def test_import_rejects_unsupported_extension(
    client: TestClient, admin_token: str, admin_user: User
):
    """A non-.xlsx/.csv extension is rejected even if the bytes are a valid xlsx."""
    response = _post_bytes(
        client, admin_token, _xlsx([("홍길동", "2021-1")]), filename="roster.txt"
    )
    assert response.status_code == 400
    assert response.json()["message"] == "파일 양식이 올바르지 않습니다."


def test_import_rejects_missing_name_header(
    client: TestClient, admin_token: str, admin_user: User
):
    """Missing the 이름 header → 400 '이름 헤더를 찾을 수 없습니다.'"""
    response = _post_roster(
        client, admin_token, [("010-0000-0000", "2021-1")], headers=("전화번호", "학번")
    )
    assert response.status_code == 400
    assert response.json()["message"] == "이름 헤더를 찾을 수 없습니다."


def test_import_rejects_missing_student_id_header(
    client: TestClient, admin_token: str, admin_user: User
):
    """Missing the 학번 header → 400 '학번 헤더를 찾을 수 없습니다.'"""
    response = _post_roster(
        client, admin_token, [("홍길동", "010-0000-0000")], headers=("이름", "전화번호")
    )
    assert response.status_code == 400
    assert response.json()["message"] == "학번 헤더를 찾을 수 없습니다."


def test_import_reports_missing_field_records(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """Records missing name or student_id are skipped and reported per spec (3)."""
    response = _post_roster(
        client,
        admin_token,
        [
            ("김와플", "2021-23456"),  # ok
            ("김스튜디오", ""),  # missing student_id
            ("", "2021-65432"),  # missing name
        ],
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["created_count"] == 1
    assert data["skipped_count"] == 2

    by_reason = {s["reason"]: s for s in data["skipped"]}
    assert by_reason["missing_student_id"]["message"] == '"김스튜디오"의 학번을 찾을 수 없습니다.'
    assert by_reason["missing_name"]["message"] == '"2021-65432"의 이름을 찾을 수 없습니다.'
    # Nothing bad was persisted.
    assert UserService.get_by_student_id(db, "2021-65432") is None


def test_import_zero_width_name_is_missing_name(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """A name made only of zero-width chars normalizes to empty → missing_name."""
    response = _post_roster(client, admin_token, [("​​", "2021-98000")])
    assert response.status_code == 200
    assert response.json()["data"]["skipped"][0]["reason"] == "missing_name"
    assert UserService.get_by_student_id(db, "2021-98000") is None


def test_import_trims_bom_so_match_key_is_consistent(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """A BOM-prefixed student_id is normalized so dedup/matching still works."""
    response = _post_roster(client, admin_token, [("BOM", "﻿2021-98001")])
    assert response.status_code == 200
    assert response.json()["data"]["created_count"] == 1
    assert UserService.get_by_student_id(db, "2021-98001") is not None

    again = _post_roster(client, admin_token, [("BOM", "2021-98001")])
    assert again.json()["data"]["skipped"][0]["reason"] == "already_exists"


def test_import_strips_surrounding_whitespace(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """Leading/trailing whitespace is trimmed on both name and student_id."""
    response = _post_roster(client, admin_token, [("  홍길동  ", "  2021-70002  ")])
    assert response.status_code == 200
    user = UserService.get_by_student_id(db, "2021-70002")
    assert user is not None
    assert user.name == "홍길동"
    assert user.student_id == "2021-70002"


def test_import_rejects_oversized_roster(
    client: TestClient, admin_token: str, admin_user: User
):
    """A roster exceeding the max row cap → 400."""
    rows = [(f"M{i}", f"2021-8{i:04d}") for i in range(2001)]
    response = _post_roster(client, admin_token, rows)
    assert response.status_code == 400
    assert response.json()["error"] == "ROSTER_TOO_LARGE"


def test_import_mixed_roster_classifies_each_row(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """A single file can create, skip-existing, and skip-duplicate together."""
    UserService.create(
        db,
        email="mixed-existing@example.com",
        name="기존",
        generation="26",
        qualification=Qualification.ACTIVE,
        google_id="mixed_existing_google_id",
        student_id="2021-90001",
    )

    response = _post_roster(
        client,
        admin_token,
        [
            ("신규", "2021-90002"),  # created
            ("기존", "2021-90001"),  # already_exists
            ("신규복제1", "2021-90003"),  # created
            ("신규복제2", "2021-90003"),  # duplicate_in_request
        ],
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
    _post_roster(client, admin_token, [("임시", "2021-95001")])

    response = client.get("/users/pending", headers=_auth(admin_token))
    assert response.status_code == 200
    names = {u["name"] for u in response.json()["data"]}
    assert pending_user.name in names
    assert "임시" not in names


def test_is_temporary_and_null_email_exposed_via_get_user(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """A created temp member reads back with is_temporary=true and email=null."""
    user_id = _import_one(client, admin_token, "조회대상", "2021-96001")

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
    user_id = _import_one(client, admin_token, "승인대상", "2021-97001")

    response = client.post(
        f"/users/{user_id}/approve",
        json={"qualification": "regular"},
        headers=_auth(admin_token),
    )
    assert response.status_code == 400
    assert response.json()["error"] == "TEMPORARY_MEMBER_CANNOT_BE_APPROVED"

    user = UserService.get_by_student_id(db, "2021-97001")
    assert user.qualification == Qualification.PENDING
    assert user.is_temporary is True


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
