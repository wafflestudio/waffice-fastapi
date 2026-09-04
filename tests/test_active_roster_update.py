"""Tests for the active-member roster update endpoints:
POST /users/active-roster/preview and POST /users/active-roster/apply.

Both accept an .xlsx or .csv upload (same 이름/학번 format as /users/temporary)
plus an optional `reference_date` form field, diff it against who is currently
Qualification.ACTIVE, and either just report the diff (preview) or apply it
(apply): unmatched student_ids become temporary members, newly-matched members
are promoted to ACTIVE ("활동회원 등록"), members dropped from the roster are
demoted to REGULAR ("활동 기간 종료"), and members present in both keep ACTIVE.

Note: there is no self-exclusion for the acting admin (by design, matching the
spec -- unlike the project-roster bulk replace, which blocks removing oneself).
`admin_user` is itself ACTIVE with no student_id, so it can never be matched by
an uploaded roster and is demoted to REGULAR by every apply/preview call in
this file -- `demoted_count` assertions below account for that +1 baseline.
"""

import io

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.models import AuditAction, Qualification, User
from app.services import AuditLogService, UserService

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


def _post_bytes(
    client, token, path, data, *, reference_date=None, filename="roster.xlsx"
):
    form = {} if reference_date is None else {"reference_date": str(reference_date)}
    return client.post(
        path,
        files={"file": (filename, data, XLSX_CT)},
        data=form,
        headers=_auth(token),
    )


def _preview(client, token, rows=None, *, reference_date=None):
    return _post_bytes(
        client,
        token,
        "/users/active-roster/preview",
        _xlsx(rows or []),
        reference_date=reference_date,
    )


def _apply(client, token, rows=None, *, reference_date=None):
    return _post_bytes(
        client,
        token,
        "/users/active-roster/apply",
        _xlsx(rows or []),
        reference_date=reference_date,
    )


def _make_user(db: Session, *, name, student_id, qualification, **extra) -> User:
    return UserService.create(
        db,
        email=extra.pop("email", f"{student_id}@example.com"),
        name=name,
        generation="26",
        qualification=qualification,
        google_id=extra.pop("google_id", f"google_{student_id}"),
        student_id=student_id,
        **extra,
    )


# === Validation (shared by preview and apply) ===
def test_rejects_invalid_file(client: TestClient, admin_token: str, admin_user: User):
    response = _post_bytes(
        client,
        admin_token,
        "/users/active-roster/preview",
        b"PK\x03\x04 not really a zip",
    )
    assert response.status_code == 400
    assert response.json()["error"] == "INVALID_ROSTER_FILE"


def test_rejects_missing_student_id_header(
    client: TestClient, admin_token: str, admin_user: User
):
    response = _post_bytes(
        client,
        admin_token,
        "/users/active-roster/preview",
        _xlsx([("홍길동", "010-0000-0000")], headers=("이름", "전화번호")),
    )
    assert response.status_code == 400
    assert response.json()["message"] == "학번 헤더를 찾을 수 없습니다."


def test_rejects_missing_field_records(
    client: TestClient, admin_token: str, admin_user: User
):
    """Unlike /users/temporary, a missing name/student_id blocks the whole file."""
    response = _preview(
        client,
        admin_token,
        [("김와플", "2021-23456"), ("김스튜디오", "")],
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "INVALID_ACTIVE_ROSTER"
    errors = body["data"]["errors"]
    assert errors[0]["code"] == "missing_student_id"
    assert errors[0]["message"] == '"김스튜디오"의 학번을 찾을 수 없습니다.'


def test_rejects_duplicate_student_id_in_file(
    client: TestClient, admin_token: str, admin_user: User
):
    response = _preview(
        client, admin_token, [("중복1", "2021-30001"), ("중복2", "2021-30001")]
    )
    assert response.status_code == 400
    errors = response.json()["data"]["errors"]
    assert errors[0]["code"] == "duplicate_student_id"


def test_rejects_associate_conflict(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    _make_user(
        db,
        name="준회원",
        student_id="2021-40001",
        qualification=Qualification.ASSOCIATE,
    )
    response = _preview(client, admin_token, [("준회원", "2021-40001")])
    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "INVALID_ACTIVE_ROSTER"
    error = body["data"]["errors"][0]
    assert error["code"] == "associate_conflict"
    assert "준회원 준회원이 존재합니다" in error["message"]


def test_rejects_pending_conflict(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    _make_user(
        db, name="대기중", student_id="2021-40002", qualification=Qualification.PENDING
    )
    response = _preview(client, admin_token, [("대기중", "2021-40002")])
    assert response.status_code == 400
    error = response.json()["data"]["errors"][0]
    assert error["code"] == "pending_conflict"
    assert "대기 회원 대기중이 존재합니다" in error["message"]


def test_rejects_ambiguous_student_id(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """Two non-deleted users sharing a student_id (no DB uniqueness constraint)."""
    _make_user(
        db,
        name="모호1",
        student_id="2021-40003",
        qualification=Qualification.REGULAR,
        email="ambiguous1@example.com",
        google_id="ambiguous1",
    )
    _make_user(
        db,
        name="모호2",
        student_id="2021-40003",
        qualification=Qualification.REGULAR,
        email="ambiguous2@example.com",
        google_id="ambiguous2",
    )
    response = _preview(client, admin_token, [("모호1", "2021-40003")])
    assert response.status_code == 400
    assert response.json()["data"]["errors"][0]["code"] == "ambiguous_student_id"


def test_rejects_empty_roster(client: TestClient, admin_token: str, admin_user: User):
    response = _preview(client, admin_token, [])
    assert response.status_code == 422
    assert response.json()["error"] == "EMPTY_ROSTER"


def test_rejects_oversized_file(client: TestClient, admin_token: str, admin_user: User):
    data = b"PK\x03\x04" + b"0" * (5 * 1024 * 1024 + 1)
    response = _post_bytes(client, admin_token, "/users/active-roster/preview", data)
    assert response.status_code == 413
    assert response.json()["error"] == "ROSTER_FILE_TOO_LARGE"


def test_requires_admin(client: TestClient, regular_token: str, regular_user: User):
    assert _preview(client, regular_token, [("홍길동", "2021-50001")]).status_code == 403


def test_requires_authentication(client: TestClient):
    response = client.post(
        "/users/active-roster/preview",
        files={"file": ("roster.xlsx", _xlsx([("홍길동", "2021-60001")]), XLSX_CT)},
    )
    assert response.status_code == 401


# === Preview: counts only, no writes ===
def test_preview_counts_new_student_as_promoted_and_new_temporary(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    response = _preview(client, admin_token, [("신입", "2021-70001")])
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["promoted_count"] == 1
    assert data["new_temporary_count"] == 1
    assert data["demoted_count"] == 1  # admin_user itself (see module docstring)
    assert data["maintained_count"] == 0
    # Preview must not write anything.
    assert UserService.get_by_student_id(db, "2021-70001") is None


def test_preview_counts_regular_as_promoted(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    regular = _make_user(
        db, name="정회원", student_id="2021-70002", qualification=Qualification.REGULAR
    )
    response = _preview(client, admin_token, [("정회원", "2021-70002")])
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["promoted_count"] == 1
    assert data["new_temporary_count"] == 0
    db.refresh(regular)
    assert regular.qualification == Qualification.REGULAR  # unchanged by preview


def test_preview_counts_dropped_active_as_demoted(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    active = _make_user(
        db, name="탈락", student_id="2021-70003", qualification=Qualification.ACTIVE
    )
    response = _preview(client, admin_token, [("다른사람", "2021-70004")])
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["demoted_count"] == 2  # 탈락 + admin_user itself
    db.refresh(active)
    assert active.qualification == Qualification.ACTIVE  # unchanged by preview


def test_preview_counts_retained_active_as_maintained(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    _make_user(
        db, name="유지", student_id="2021-70005", qualification=Qualification.ACTIVE
    )
    response = _preview(client, admin_token, [("유지", "2021-70005")])
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["maintained_count"] == 1
    assert data["promoted_count"] == 0
    assert data["demoted_count"] == 1  # admin_user itself (see module docstring)


# === Apply: actually writes, logs audit entries ===
def test_apply_creates_temporary_member_and_activates(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    response = _apply(client, admin_token, [("신규활동", "2021-80001")])
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["new_temporary_count"] == 1
    assert data["promoted_count"] == 1
    assert len(data["created_temporary"]) == 1

    user = UserService.get_by_student_id(db, "2021-80001")
    assert user is not None
    assert user.is_temporary is True
    assert user.qualification == Qualification.ACTIVE

    logs = AuditLogService.list_by_user(db, user.id)
    assert len(logs) == 1
    assert logs[0].action == AuditAction.QUALIFICATION_CHANGED
    assert logs[0].payload == {
        "from": "pending",
        "to": "active",
        "reason": "활동회원 등록",
    }


def test_apply_promotes_regular_to_active(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    regular = _make_user(
        db,
        name="승격대상",
        student_id="2021-80002",
        qualification=Qualification.REGULAR,
    )
    response = _apply(client, admin_token, [("승격대상", "2021-80002")])
    assert response.status_code == 200

    db.refresh(regular)
    assert regular.qualification == Qualification.ACTIVE
    logs = AuditLogService.list_by_user(db, regular.id)
    assert logs[0].payload["from"] == "regular"
    assert logs[0].payload["to"] == "active"
    assert logs[0].payload["reason"] == "활동회원 등록"


def test_apply_demotes_dropped_active_to_regular(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    active = _make_user(
        db, name="탈락예정", student_id="2021-80003", qualification=Qualification.ACTIVE
    )
    response = _apply(client, admin_token, [("다른사람", "2021-80004")])
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["demoted_count"] == 2  # 탈락예정 + admin_user itself
    assert any(u["name"] == "탈락예정" for u in data["demoted"])

    db.refresh(active)
    assert active.qualification == Qualification.REGULAR
    logs = AuditLogService.list_by_user(db, active.id)
    assert logs[0].payload == {
        "from": "active",
        "to": "regular",
        "reason": "활동 기간 종료",
    }


def test_apply_maintains_active_without_new_audit_log(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    active = _make_user(
        db, name="유지대상", student_id="2021-80005", qualification=Qualification.ACTIVE
    )
    response = _apply(client, admin_token, [("유지대상", "2021-80005")])
    assert response.status_code == 200
    assert response.json()["data"]["maintained_count"] == 1

    db.refresh(active)
    assert active.qualification == Qualification.ACTIVE
    assert AuditLogService.list_by_user(db, active.id) == []


def test_apply_backdates_audit_log_to_reference_date(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    regular = _make_user(
        db,
        name="소급대상",
        student_id="2021-80006",
        qualification=Qualification.REGULAR,
    )
    reference_date = 1700000000
    response = _apply(
        client, admin_token, [("소급대상", "2021-80006")], reference_date=reference_date
    )
    assert response.status_code == 200
    assert response.json()["data"]["reference_date"] == reference_date

    logs = AuditLogService.list_by_user(db, regular.id)
    assert logs[0].created_at == reference_date


def test_apply_full_roster_transition(
    client: TestClient, db: Session, admin_token: str, admin_user: User
):
    """One upload can promote, demote, maintain, and create-temp together."""
    _make_user(
        db, name="유지자", student_id="2021-90001", qualification=Qualification.ACTIVE
    )
    _make_user(
        db, name="탈락자", student_id="2021-90002", qualification=Qualification.ACTIVE
    )
    _make_user(
        db, name="승격자", student_id="2021-90003", qualification=Qualification.REGULAR
    )

    response = _apply(
        client,
        admin_token,
        [
            ("유지자", "2021-90001"),
            ("승격자", "2021-90003"),
            ("신규자", "2021-90004"),
        ],
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["maintained_count"] == 1
    assert data["demoted_count"] == 2  # 탈락자 + admin_user itself
    assert data["promoted_count"] == 2  # 승격자 + 신규자
    assert data["new_temporary_count"] == 1

    assert UserService.get_by_student_id(db, "2021-90001").qualification == (
        Qualification.ACTIVE
    )
    assert UserService.get_by_student_id(db, "2021-90002").qualification == (
        Qualification.REGULAR
    )
    assert UserService.get_by_student_id(db, "2021-90003").qualification == (
        Qualification.ACTIVE
    )
    new_user = UserService.get_by_student_id(db, "2021-90004")
    assert new_user.is_temporary is True
    assert new_user.qualification == Qualification.ACTIVE
