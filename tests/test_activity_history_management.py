from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import ActivityStatus, MemberRole, User, UserActivity
from app.services import ActivityService, MemberService, ProjectService


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_project_with_leader(db: Session, leader: User):
    project = ProjectService.create(
        db,
        name="Activity History Project",
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


def create_activity(
    db: Session,
    *,
    user: User,
    project_id: int,
    position: str,
    start_date: int,
) -> UserActivity:
    activity = UserActivity(
        user_id=user.id,
        project_id=project_id,
        position=position,
        start_date=start_date,
        status=ActivityStatus.ACTIVE,
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity


def request_payload(
    project_id: int,
    user_id: int,
    *,
    kind: str = "create",
    activity_id: int | None = None,
    position: str = "백엔드 엔지니어",
) -> dict:
    payload = {
        "request_kind": kind,
        "target_user_id": user_id,
        "reason": "활동 이력 반영 요청",
        "after": {
            "project_id": project_id,
            "position": position,
            "start_date": 100,
            "end_date": None,
            "status": "active",
            "description": "API 구현",
        },
    }
    if activity_id is not None:
        payload["activity_id"] = activity_id
    return payload


class TestMyActivityHistory:
    def test_returns_only_create_pending_update_pending_and_active(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        regular_token: str,
        active_user: User,
    ):
        project = create_project_with_leader(db, active_user)
        updating = create_activity(
            db,
            user=regular_user,
            project_id=project.id,
            position="기존 활동",
            start_date=300,
        )
        active = create_activity(
            db,
            user=regular_user,
            project_id=project.id,
            position="승인 완료 활동",
            start_date=200,
        )

        update_response = client.post(
            "/requests",
            json=request_payload(
                project.id,
                regular_user.id,
                kind="update",
                activity_id=updating.id,
                position="수정 요청 내용",
            ),
            headers=auth(regular_token),
        )
        create_response = client.post(
            "/requests",
            json=request_payload(
                project.id,
                regular_user.id,
                position="새 활동 요청",
            ),
            headers=auth(regular_token),
        )

        assert update_response.status_code == 200
        assert create_response.status_code == 200

        response = client.get(
            "/users/me/activities",
            headers=auth(regular_token),
        )

        assert response.status_code == 200
        items = response.json()["data"]
        assert {item["status"] for item in items} == {
            "create_pending",
            "update_pending",
            "active",
        }

        create_pending = next(
            item for item in items if item["status"] == "create_pending"
        )
        assert create_pending["id"] is None
        assert (
            create_pending["pending_request_id"] == create_response.json()["data"]["id"]
        )
        assert create_pending["position"] == "새 활동 요청"

        update_pending = next(
            item for item in items if item["status"] == "update_pending"
        )
        assert update_pending["id"] == updating.id
        assert (
            update_pending["pending_request_id"] == update_response.json()["data"]["id"]
        )

        active_item = next(item for item in items if item["status"] == "active")
        assert active_item["id"] == active.id

    def test_rejected_update_marks_activity_as_rejected(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        regular_token: str,
        active_user: User,
        active_token: str,
    ):
        project = create_project_with_leader(db, active_user)
        updating = create_activity(
            db,
            user=regular_user,
            project_id=project.id,
            position="기존 활동",
            start_date=300,
        )

        update_response = client.post(
            "/requests",
            json=request_payload(
                project.id,
                regular_user.id,
                kind="update",
                activity_id=updating.id,
                position="수정 요청 내용",
            ),
            headers=auth(regular_token),
        )
        request_id = update_response.json()["data"]["id"]

        reject_response = client.post(
            f"/requests/{request_id}/reject",
            json={"comment": "반려합니다"},
            headers=auth(active_token),
        )
        assert reject_response.status_code == 200

        response = client.get(
            "/users/me/activities",
            headers=auth(regular_token),
        )
        assert response.status_code == 200
        items = response.json()["data"]

        rejected_item = next(item for item in items if item["id"] == updating.id)
        assert rejected_item["status"] == "rejected"
        assert rejected_item["pending_request_id"] == request_id
        # Rejection doesn't change the underlying activity's own fields.
        assert rejected_item["position"] == "기존 활동"

    def test_rejected_create_appears_as_virtual_rejected_item(
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
            json=request_payload(
                project.id,
                regular_user.id,
                position="거절될 활동",
            ),
            headers=auth(regular_token),
        )
        request_id = create_response.json()["data"]["id"]

        reject_response = client.post(
            f"/requests/{request_id}/reject",
            json={"comment": "반려합니다"},
            headers=auth(active_token),
        )
        assert reject_response.status_code == 200

        response = client.get(
            "/users/me/activities",
            headers=auth(regular_token),
        )
        assert response.status_code == 200
        items = response.json()["data"]

        rejected_item = next(item for item in items if item["status"] == "rejected")
        assert rejected_item["id"] is None
        assert rejected_item["pending_request_id"] == request_id
        assert rejected_item["position"] == "거절될 활동"

    def test_recent_rejected_limit_caps_number_of_rejected_creates(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        regular_token: str,
        active_user: User,
        active_token: str,
    ):
        project = create_project_with_leader(db, active_user)
        limit = ActivityService.RECENT_REJECTED_LIMIT

        for index in range(limit + 5):
            create_response = client.post(
                "/requests",
                json=request_payload(
                    project.id,
                    regular_user.id,
                    position=f"거절될 활동 {index}",
                ),
                headers=auth(regular_token),
            )
            request_id = create_response.json()["data"]["id"]
            reject_response = client.post(
                f"/requests/{request_id}/reject",
                json={"comment": "반려합니다"},
                headers=auth(active_token),
            )
            assert reject_response.status_code == 200

        response = client.get(
            "/users/me/activities",
            headers=auth(regular_token),
        )
        assert response.status_code == 200
        items = response.json()["data"]
        rejected_items = [item for item in items if item["status"] == "rejected"]
        assert len(rejected_items) == limit

    def test_create_approval_links_request_to_created_activity(
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

        approve_response = client.post(
            f"/requests/{request_id}/approve",
            json={"comment": "승인"},
            headers=auth(active_token),
        )

        assert approve_response.status_code == 200
        activity_id = approve_response.json()["data"]["body"]["activity_id"]
        assert isinstance(activity_id, int)

        list_response = client.get(
            f"/requests?scope=sent&status=all&activity_id={activity_id}",
            headers=auth(regular_token),
        )
        assert list_response.status_code == 200
        items = list_response.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["id"] == request_id
        assert items[0]["activity_id"] == activity_id
        assert items[0]["target_user_id"] == regular_user.id
        assert items[0]["after"]["position"] == "백엔드 엔지니어"

        history_response = client.get(
            "/users/me/activities",
            headers=auth(regular_token),
        )
        assert history_response.status_code == 200
        assert history_response.json()["data"][0]["status"] == "active"


class TestAllActivities:
    def test_admin_can_paginate_all_users_activities_by_id(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        regular_token: str,
        regular_user: User,
        active_user: User,
    ):
        project = create_project_with_leader(db, active_user)
        created_ids = [
            create_activity(
                db,
                user=regular_user,
                project_id=project.id,
                position=f"활동 {index}",
                start_date=index,
            ).id
            for index in range(3)
        ]

        forbidden = client.get(
            "/activities",
            headers=auth(regular_token),
        )
        assert forbidden.status_code == 403

        first_response = client.get(
            "/activities?limit=2",
            headers=auth(admin_token),
        )
        assert first_response.status_code == 200
        first_page = first_response.json()["data"]
        assert [item["id"] for item in first_page["items"]] == list(
            reversed(created_ids[1:])
        )
        assert first_page["next_cursor"] == created_ids[1]
        assert all(item["status"] == "active" for item in first_page["items"])

        second_response = client.get(
            f"/activities?limit=2&cursor={first_page['next_cursor']}",
            headers=auth(admin_token),
        )
        assert second_response.status_code == 200
        second_page = second_response.json()["data"]
        assert [item["id"] for item in second_page["items"]] == [created_ids[0]]
        assert second_page["next_cursor"] is None
