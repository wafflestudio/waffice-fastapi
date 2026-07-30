from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import ActivityStatus, ApprovalRequest, MemberRole, User, UserActivity
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
        assert data["review_target"] == "project_leader"
        assert data["body"]["review_target"] == "project_leader"
        assert data["reviewers"] == []
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

    def test_patch_rejects_request_without_eligible_reviewer(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        regular_token: str,
        active_user: User,
    ):
        old_project = create_project_with_leader(db, active_user)
        new_project = create_project_with_leader(db, regular_user)
        create_response = client.post(
            "/requests",
            json=request_payload(old_project.id, regular_user.id),
            headers=auth(regular_token),
        )
        assert create_response.status_code == 200
        request_id = create_response.json()["data"]["id"]

        new_after = request_payload(new_project.id, regular_user.id)["after"]
        response = client.patch(
            f"/requests/{request_id}",
            json={"after": new_after},
            headers=auth(regular_token),
        )

        assert response.status_code == 400
        assert response.json()["error"] == "NO_ELIGIBLE_REVIEWER"

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
        assert isinstance(data["body"]["activity_id"], int)
        activities = db.query(UserActivity).filter_by(user_id=regular_user.id).all()
        assert len(activities) == 1
        assert data["body"]["activity_id"] == activities[0].id
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
        assert response.json()["data"]["review_target"] == "project_leader"
        assert len(response.json()["data"]["reviewers"]) == 1

        list_response = client.get("/requests", headers=auth(active_token))

        assert list_response.status_code == 200
        assert len(list_response.json()["data"]["items"]) == 1
        assert (
            list_response.json()["data"]["items"][0]["review_target"]
            == "project_leader"
        )

    def test_operations_request_is_routed_to_operations_only(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        regular_token: str,
        active_user: User,
        active_token: str,
        admin_user: User,
        admin_token: str,
    ):
        project = create_project_with_leader(db, active_user)
        payload = request_payload(project.id, regular_user.id)
        payload["review_target"] = "operations"

        response = client.post(
            "/requests",
            json=payload,
            headers=auth(regular_token),
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["review_target"] == "operations"
        assert data["body"]["review_target"] == "operations"
        assert data["reviewers"] == []

        leader_received = client.get("/requests", headers=auth(active_token))
        assert leader_received.status_code == 200
        assert leader_received.json()["data"]["items"] == []

        leader_detail = client.get(
            f"/requests/{data['id']}", headers=auth(active_token)
        )
        assert leader_detail.status_code == 403

        operations_received = client.get("/requests", headers=auth(admin_token))
        assert operations_received.status_code == 200
        assert [item["id"] for item in operations_received.json()["data"]["items"]] == [
            data["id"]
        ]
        assert (
            operations_received.json()["data"]["items"][0]["review_target"]
            == "operations"
        )

    def test_operations_can_override_project_leader_review_target(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        regular_token: str,
        active_user: User,
        admin_token: str,
    ):
        project = create_project_with_leader(db, active_user)
        create_response = client.post(
            "/requests",
            json=request_payload(project.id, regular_user.id),
            headers=auth(regular_token),
        )
        request_id = create_response.json()["data"]["id"]

        received = client.get("/requests", headers=auth(admin_token))
        assert received.status_code == 200
        assert received.json()["data"]["items"] == []

        all_requests = client.get(
            "/requests?scope=all",
            headers=auth(admin_token),
        )
        assert [item["id"] for item in all_requests.json()["data"]["items"]] == [
            request_id
        ]

        approved = client.post(
            f"/requests/{request_id}/approve",
            json={"comment": "운영진 우회 승인"},
            headers=auth(admin_token),
        )
        assert approved.status_code == 200
        assert approved.json()["data"]["status"] == "approved"

    def test_requester_cannot_review_own_request_even_as_project_leader(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        regular_token: str,
        active_user: User,
        active_token: str,
    ):
        project = create_project_with_leader(db, regular_user)
        MemberService.add(
            db=db,
            project_id=project.id,
            user_id=active_user.id,
            role=MemberRole.LEADER,
            position=MemberRole.LEADER.value,
            actor_id=regular_user.id,
        )
        db.commit()

        create_response = client.post(
            "/requests",
            json=request_payload(project.id, regular_user.id),
            headers=auth(regular_token),
        )
        assert create_response.status_code == 200
        request_id = create_response.json()["data"]["id"]

        self_review = client.post(
            f"/requests/{request_id}/approve",
            json={"comment": "self"},
            headers=auth(regular_token),
        )
        assert self_review.status_code == 403

        other_leader_review = client.post(
            f"/requests/{request_id}/approve",
            json={"comment": "approved"},
            headers=auth(active_token),
        )
        assert other_leader_review.status_code == 200

    def test_target_user_cannot_review_request_created_on_their_behalf(
        self,
        client: TestClient,
        db: Session,
        admin_user: User,
        admin_token: str,
        regular_user: User,
        regular_token: str,
        active_user: User,
        active_token: str,
    ):
        project = create_project_with_leader(db, active_user)
        MemberService.add(
            db=db,
            project_id=project.id,
            user_id=regular_user.id,
            role=MemberRole.LEADER,
            position=MemberRole.LEADER.value,
            actor_id=active_user.id,
        )
        db.commit()

        create_response = client.post(
            "/requests",
            json=request_payload(project.id, active_user.id),
            headers=auth(admin_token),
        )
        assert create_response.status_code == 200
        request_id = create_response.json()["data"]["id"]

        requester_review = client.post(
            f"/requests/{request_id}/approve",
            json={"comment": "requester"},
            headers=auth(admin_token),
        )
        assert requester_review.status_code == 403

        target_review = client.post(
            f"/requests/{request_id}/approve",
            json={"comment": "target"},
            headers=auth(active_token),
        )
        assert target_review.status_code == 403

        eligible_leader_review = client.post(
            f"/requests/{request_id}/approve",
            json={"comment": "other leader"},
            headers=auth(regular_token),
        )
        assert eligible_leader_review.status_code == 200

    def test_create_rejects_request_without_eligible_reviewer(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        regular_token: str,
    ):
        project = create_project_with_leader(db, regular_user)

        response = client.post(
            "/requests",
            json=request_payload(project.id, regular_user.id),
            headers=auth(regular_token),
        )

        assert response.status_code == 400
        assert response.json()["error"] == "NO_ELIGIBLE_REVIEWER"
        assert response.json()["message"] == (
            "승인 가능한 사용자가 없습니다. " "승인 대상을 변경하거나 운영팀에 문의해주세요."
        )

    def test_operations_request_requires_another_eligible_operator(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        regular_user: User,
        active_user: User,
    ):
        project = create_project_with_leader(db, active_user)
        payload = request_payload(project.id, regular_user.id)
        payload["review_target"] = "operations"

        response = client.post(
            "/requests",
            json=payload,
            headers=auth(admin_token),
        )

        assert response.status_code == 400
        assert response.json()["error"] == "NO_ELIGIBLE_REVIEWER"

    def test_review_target_and_reviewer_ids_cannot_be_sent_together(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        regular_token: str,
        active_user: User,
    ):
        project = create_project_with_leader(db, active_user)
        payload = request_payload(project.id, regular_user.id)
        payload["review_target"] = "project_leader"
        payload["reviewer_ids"] = [active_user.id]

        response = client.post(
            "/requests",
            json=payload,
            headers=auth(regular_token),
        )

        assert response.status_code == 422

    def test_empty_reviewer_ids_uses_default_review_target(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        regular_token: str,
        active_user: User,
    ):
        project = create_project_with_leader(db, active_user)
        payload = request_payload(project.id, regular_user.id)
        payload["reviewer_ids"] = []

        response = client.post(
            "/requests",
            json=payload,
            headers=auth(regular_token),
        )

        assert response.status_code == 200
        request_id = response.json()["data"]["id"]
        saved_request = db.get(ApprovalRequest, request_id)
        assert saved_request is not None
        assert saved_request.body["review_target"] == "project_leader"

        patch_response = client.patch(
            f"/requests/{request_id}",
            json={"reviewer_ids": [active_user.id]},
            headers=auth(regular_token),
        )
        assert patch_response.status_code == 400
        assert patch_response.json()["error"] == "INVALID_APPROVAL_REQUEST"

    def test_review_target_patch_replaces_legacy_explicit_reviewers(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        regular_token: str,
        active_user: User,
        active_token: str,
        admin_token: str,
    ):
        project = create_project_with_leader(db, active_user)
        payload = request_payload(project.id, regular_user.id)
        payload["reviewer_ids"] = [active_user.id]
        create_response = client.post(
            "/requests",
            json=payload,
            headers=auth(regular_token),
        )
        request_id = create_response.json()["data"]["id"]

        response = client.patch(
            f"/requests/{request_id}",
            json={"review_target": "operations"},
            headers=auth(regular_token),
        )

        assert response.status_code == 200
        assert response.json()["data"]["review_target"] == "operations"
        assert response.json()["data"]["reviewers"] == []
        assert (
            client.get("/requests", headers=auth(active_token)).json()["data"]["items"]
            == []
        )
        assert [
            item["id"]
            for item in client.get("/requests", headers=auth(admin_token)).json()[
                "data"
            ]["items"]
        ] == [request_id]

    def test_create_request_project_patch_reroutes_to_new_project_leader(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        regular_token: str,
        active_user: User,
        active_token: str,
        admin_user: User,
        admin_token: str,
    ):
        old_project = create_project_with_leader(db, active_user)
        new_project = create_project_with_leader(db, admin_user)
        create_response = client.post(
            "/requests",
            json=request_payload(old_project.id, regular_user.id),
            headers=auth(regular_token),
        )
        request_id = create_response.json()["data"]["id"]

        response = client.patch(
            f"/requests/{request_id}",
            json={
                "after": {
                    "project_id": new_project.id,
                    "position": "leader",
                    "start_date": 10,
                    "end_date": 20,
                    "status": "active",
                    "description": "활동 설명",
                }
            },
            headers=auth(regular_token),
        )

        assert response.status_code == 200
        assert response.json()["data"]["project"]["id"] == new_project.id
        assert (
            client.get("/requests", headers=auth(active_token)).json()["data"]["items"]
            == []
        )
        assert [
            item["id"]
            for item in client.get("/requests", headers=auth(admin_token)).json()[
                "data"
            ]["items"]
        ] == [request_id]

    def test_project_deletion_is_blocked_by_pending_request(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        regular_token: str,
        active_user: User,
        admin_token: str,
    ):
        project = create_project_with_leader(db, active_user)
        create_response = client.post(
            "/requests",
            json=request_payload(project.id, regular_user.id),
            headers=auth(regular_token),
        )
        request_id = create_response.json()["data"]["id"]

        blocked = client.delete(
            f"/projects/{project.id}",
            headers=auth(admin_token),
        )
        assert blocked.status_code == 409
        assert blocked.json()["error"] == "PROJECT_HAS_PENDING_REQUESTS"
        assert blocked.json()["message"] == "대기 중인 승인 요청을 처리한 후 프로젝트를 삭제해주세요."

        deleted_request = client.delete(
            f"/requests/{request_id}",
            headers=auth(regular_token),
        )
        assert deleted_request.status_code == 200

        deleted_project = client.delete(
            f"/projects/{project.id}",
            headers=auth(admin_token),
        )
        assert deleted_project.status_code == 200

    def test_request_cursor_keeps_rows_with_same_created_at(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        regular_token: str,
        active_user: User,
    ):
        project = create_project_with_leader(db, active_user)
        request_ids = []
        for index in range(3):
            payload = request_payload(project.id, regular_user.id)
            payload["reason"] = f"요청 {index}"
            response = client.post(
                "/requests",
                json=payload,
                headers=auth(regular_token),
            )
            assert response.status_code == 200
            request_ids.append(response.json()["data"]["id"])

        db.query(ApprovalRequest).filter(ApprovalRequest.id.in_(request_ids)).update(
            {ApprovalRequest.created_at: 1_700_000_000},
            synchronize_session=False,
        )
        db.commit()

        first = client.get(
            "/requests?scope=sent&limit=2",
            headers=auth(regular_token),
        ).json()["data"]
        assert isinstance(first["next_cursor"], str)

        second = client.get(
            f"/requests?scope=sent&limit=2&cursor={first['next_cursor']}",
            headers=auth(regular_token),
        ).json()["data"]

        returned_ids = [item["id"] for item in first["items"] + second["items"]]
        assert returned_ids == sorted(request_ids, reverse=True)
        assert len(set(returned_ids)) == 3
