from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import ActivityStatus, MemberRole, User, UserActivity
from app.services import MemberService, ProjectService


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_project_with_leader(db: Session, leader: User):
    project = ProjectService.create(
        db,
        name="Approval Project",
        started_at=date.today(),
    )
    MemberService.add(
        db=db,
        project_id=project.id,
        user_id=leader.id,
        role=MemberRole.LEADER,
        position=MemberRole.LEADER.value,
        actor_id=leader.id,
    )
    db.commit()
    return project


def create_activity(db: Session, user: User, project_id: int | None = None):
    activity = UserActivity(
        user_id=user.id,
        project_id=project_id,
        position=MemberRole.MEMBER.value,
        start_date=1,
        end_date=2,
        status=ActivityStatus.ACTIVE,
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity


def request_payload(project_id: int, user_id: int, *, kind: str = "create") -> dict:
    payload = {
        "request_kind": kind,
        "target_user_id": user_id,
        "reason": "활동 이력 반영 요청",
    }
    if kind != "delete":
        payload["after"] = {
            "project_id": project_id,
            "position": "leader",
            "start_date": 10,
            "end_date": 20,
            "status": "active",
            "description": "활동 설명",
        }
    return payload


class TestActivityApprovalRequests:
    def test_regular_user_can_create_project_activity_request(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        regular_token: str,
        active_user: User,
    ):
        project = create_project_with_leader(db, active_user)

        response = client.post(
            "/requests",
            json=request_payload(project.id, regular_user.id),
            headers=auth(regular_token),
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["status"] == "pending"
        assert data["body"]["after"]["project_id"] == project.id
        assert data["body"]["before"] is None

    def test_update_request_stores_before_snapshot(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        regular_token: str,
        active_user: User,
    ):
        project = create_project_with_leader(db, active_user)
        activity = create_activity(db, regular_user, project.id)
        payload = request_payload(project.id, regular_user.id, kind="update")
        payload["activity_id"] = activity.id

        response = client.post(
            "/requests",
            json=payload,
            headers=auth(regular_token),
        )

        assert response.status_code == 200
        body = response.json()["data"]["body"]
        assert body["activity_id"] == activity.id
        assert body["before"]["position"] == "member"
        assert body["before"]["project_id"] == project.id

    def test_update_request_cannot_change_activity_project(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        regular_token: str,
        active_user: User,
    ):
        original_project = create_project_with_leader(db, active_user)
        other_project = create_project_with_leader(db, active_user)
        activity = create_activity(db, regular_user, original_project.id)
        payload = request_payload(other_project.id, regular_user.id, kind="update")
        payload["activity_id"] = activity.id

        response = client.post(
            "/requests",
            json=payload,
            headers=auth(regular_token),
        )

        assert response.status_code == 400
        assert response.json()["error"] == "INVALID_APPROVAL_REQUEST"

    def test_pending_update_request_cannot_be_moved_to_other_project(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        regular_token: str,
        active_user: User,
    ):
        original_project = create_project_with_leader(db, active_user)
        other_project = create_project_with_leader(db, active_user)
        activity = create_activity(db, regular_user, original_project.id)
        payload = request_payload(original_project.id, regular_user.id, kind="update")
        payload["activity_id"] = activity.id
        create_response = client.post(
            "/requests",
            json=payload,
            headers=auth(regular_token),
        )
        request_id = create_response.json()["data"]["id"]

        response = client.patch(
            f"/requests/{request_id}",
            json={
                "after": {
                    "project_id": other_project.id,
                    "position": "leader",
                    "start_date": 10,
                    "end_date": 20,
                    "status": "active",
                    "description": "활동 설명",
                }
            },
            headers=auth(regular_token),
        )

        assert response.status_code == 400
        assert response.json()["error"] == "INVALID_APPROVAL_REQUEST"

    def test_project_leader_can_list_received_requests(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        regular_token: str,
        active_user: User,
        active_token: str,
    ):
        project = create_project_with_leader(db, active_user)
        client.post(
            "/requests",
            json=request_payload(project.id, regular_user.id),
            headers=auth(regular_token),
        )

        response = client.get("/requests", headers=auth(active_token))

        assert response.status_code == 200
        items = response.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["requester"]["id"] == regular_user.id

    def test_unrelated_user_cannot_access_detail(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        regular_token: str,
        active_user: User,
        associate_token: str,
    ):
        project = create_project_with_leader(db, active_user)
        create_response = client.post(
            "/requests",
            json=request_payload(project.id, regular_user.id),
            headers=auth(regular_token),
        )
        request_id = create_response.json()["data"]["id"]

        response = client.get(f"/requests/{request_id}", headers=auth(associate_token))

        assert response.status_code == 403

    def test_approve_creates_activity(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        regular_token: str,
        active_user: User,
        active_token: str,
    ):
        project = create_project_with_leader(db, active_user)
        create_response = client.post(
            "/requests",
            json=request_payload(project.id, regular_user.id),
            headers=auth(regular_token),
        )
        request_id = create_response.json()["data"]["id"]

        response = client.post(
            f"/requests/{request_id}/approve",
            json={"comment": "확인했습니다"},
            headers=auth(active_token),
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["status"] == "approved"
        assert data["body"]["review"]["final"]["position"] == "leader"
        activities = db.query(UserActivity).filter_by(user_id=regular_user.id).all()
        assert len(activities) == 1
        assert activities[0].position == "leader"

    def test_approve_with_edits_updates_activity_and_stores_diff(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        regular_token: str,
        active_user: User,
        active_token: str,
    ):
        project = create_project_with_leader(db, active_user)
        activity = create_activity(db, regular_user, project.id)
        payload = request_payload(project.id, regular_user.id, kind="update")
        payload["activity_id"] = activity.id
        create_response = client.post(
            "/requests",
            json=payload,
            headers=auth(regular_token),
        )
        request_id = create_response.json()["data"]["id"]

        response = client.post(
            f"/requests/{request_id}/approve-with-edits",
            json={
                "comment": "기간만 조정합니다",
                "reviewer_patch": {"position": "member", "end_date": 30},
            },
            headers=auth(active_token),
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["body"]["review"]["final"]["position"] == "member"
        assert data["body"]["review"]["diff"]["position"]["requested"] == "leader"
        db.refresh(activity)
        assert activity.position == "member"
        assert activity.end_date == 30

    def test_reject_requires_comment_and_does_not_change_activity(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        regular_token: str,
        active_user: User,
        active_token: str,
    ):
        project = create_project_with_leader(db, active_user)
        activity = create_activity(db, regular_user, project.id)
        payload = request_payload(project.id, regular_user.id, kind="update")
        payload["activity_id"] = activity.id
        create_response = client.post(
            "/requests",
            json=payload,
            headers=auth(regular_token),
        )
        request_id = create_response.json()["data"]["id"]

        invalid = client.post(
            f"/requests/{request_id}/reject",
            json={"comment": ""},
            headers=auth(active_token),
        )
        assert invalid.status_code == 422

        response = client.post(
            f"/requests/{request_id}/reject",
            json={"comment": "증빙 부족"},
            headers=auth(active_token),
        )

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "rejected"
        db.refresh(activity)
        assert activity.position == "member"

    def test_approve_delete_request_deletes_activity(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        regular_token: str,
        active_user: User,
        active_token: str,
    ):
        project = create_project_with_leader(db, active_user)
        activity = create_activity(db, regular_user, project.id)
        payload = request_payload(project.id, regular_user.id, kind="delete")
        payload["activity_id"] = activity.id

        create_response = client.post(
            "/requests",
            json=payload,
            headers=auth(regular_token),
        )

        assert create_response.status_code == 200
        request_data = create_response.json()["data"]
        assert request_data["body"]["before"]["position"] == "member"
        assert request_data["body"]["after"] is None

        response = client.post(
            f"/requests/{request_data['id']}/approve",
            json={"comment": "삭제 승인"},
            headers=auth(active_token),
        )

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "approved"
        assert db.query(UserActivity).filter_by(id=activity.id).first() is None

    def test_processed_request_cannot_be_processed_again(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        regular_token: str,
        active_user: User,
        active_token: str,
    ):
        project = create_project_with_leader(db, active_user)
        create_response = client.post(
            "/requests",
            json=request_payload(project.id, regular_user.id),
            headers=auth(regular_token),
        )
        request_id = create_response.json()["data"]["id"]
        client.post(
            f"/requests/{request_id}/approve",
            json={"comment": "ok"},
            headers=auth(active_token),
        )

        response = client.post(
            f"/requests/{request_id}/reject",
            json={"comment": "late"},
            headers=auth(active_token),
        )

        assert response.status_code == 400
        assert response.json()["error"] == "REQUEST_ALREADY_PROCESSED"

    def test_project_request_visible_to_explicit_approver(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        regular_token: str,
        active_user: User,
        active_token: str,
    ):
        project = ProjectService.create(
            db,
            name="Explicit Approver Project",
            started_at=date.today(),
        )
        db.commit()

        response = client.post(
            "/requests",
            json={
                "request_kind": "create",
                "target_user_id": regular_user.id,
                "reviewer_ids": [active_user.id],
                "after": {
                    "project_id": project.id,
                    "position": "member",
                    "start_date": 10,
                    "end_date": None,
                    "status": "active",
                    "description": None,
                },
                "reason": "프로젝트 활동 추가",
            },
            headers=auth(regular_token),
        )
        assert response.status_code == 200

        list_response = client.get("/requests", headers=auth(active_token))

        assert list_response.status_code == 200
        assert len(list_response.json()["data"]["items"]) == 1
