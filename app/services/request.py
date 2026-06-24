from __future__ import annotations

import time

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, joinedload

from app.exceptions import AppError, ForbiddenError, NotFoundError
from app.models import (
    ApprovalRequest,
    ApprovalStatus,
    Approver,
    MemberRole,
    Project,
    ProjectMember,
    User,
    UserActivity,
)
from app.schemas.request import (
    ApprovalRequestCreateRequest,
    ApprovalRequestUpdateRequest,
    ApprovalReviewWithEditsRequest,
    RequestKind,
    RequestKindFilter,
    RequestScope,
    RequestStatusFilter,
)


class InvalidApprovalRequestError(AppError):
    def __init__(self, message: str = "Invalid approval request"):
        super().__init__("INVALID_APPROVAL_REQUEST", message, 400)


class RequestAlreadyProcessedError(AppError):
    def __init__(self, message: str = "Request has already been processed"):
        super().__init__("REQUEST_ALREADY_PROCESSED", message, 400)


class RequestService:
    @staticmethod
    def activity_snapshot(activity: UserActivity) -> dict:
        return {
            "project_id": activity.project_id,
            "position": activity.position,
            "start_date": activity.start_date,
            "end_date": activity.end_date,
            "status": activity.status.value,
            "description": activity.description,
        }

    @staticmethod
    def get(db: Session, request_id: int) -> ApprovalRequest | None:
        return (
            db.query(ApprovalRequest)
            .options(
                joinedload(ApprovalRequest.requester),
                joinedload(ApprovalRequest.project),
                joinedload(ApprovalRequest.reviewer),
                joinedload(ApprovalRequest.approvers).joinedload(Approver.user),
            )
            .filter(
                and_(
                    ApprovalRequest.id == request_id,
                    ApprovalRequest.deleted_at.is_(None),
                )
            )
            .first()
        )

    @staticmethod
    def ensure_user_exists(db: Session, user_id: int) -> User:
        user = (
            db.query(User)
            .filter(and_(User.id == user_id, User.deleted_at.is_(None)))
            .first()
        )
        if not user:
            raise NotFoundError("User not found")
        return user

    @staticmethod
    def ensure_project_exists(db: Session, project_id: int) -> Project:
        project = (
            db.query(Project)
            .filter(and_(Project.id == project_id, Project.deleted_at.is_(None)))
            .first()
        )
        if not project:
            raise NotFoundError("Project not found")
        return project

    @staticmethod
    def validate_activity_payload(db: Session, data: dict) -> None:
        RequestService.ensure_project_exists(db, data["project_id"])

    @staticmethod
    def replace_approvers(
        db: Session,
        approval_request: ApprovalRequest,
        approver_ids: list[int],
    ) -> None:
        approval_request.approvers.clear()
        seen: set[int] = set()
        for user_id in approver_ids:
            if user_id in seen:
                continue
            RequestService.ensure_user_exists(db, user_id)
            approval_request.approvers.append(
                Approver(
                    user_id=user_id,
                    project_id=approval_request.project_id,
                )
            )
            seen.add(user_id)

    @staticmethod
    def create(
        db: Session,
        *,
        actor: User,
        request: ApprovalRequestCreateRequest,
    ) -> ApprovalRequest:
        target_user_id = request.target_user_id or actor.id
        if target_user_id != actor.id and not actor.is_admin:
            raise ForbiddenError("Cannot create a request for another user")
        RequestService.ensure_user_exists(db, target_user_id)

        after = request.after.model_dump(mode="json") if request.after else None
        if after is not None:
            RequestService.validate_activity_payload(db, after)

        project_id = after["project_id"] if after is not None else None
        before = None
        if request.request_kind in (RequestKind.UPDATE, RequestKind.DELETE):
            activity = (
                db.query(UserActivity)
                .filter(UserActivity.id == request.activity_id)
                .first()
            )
            if not activity or activity.user_id != target_user_id:
                raise NotFoundError("Activity not found")
            before = RequestService.activity_snapshot(activity)
            if activity.project_id is None:
                raise InvalidApprovalRequestError(
                    "Project activity request requires a project activity"
                )
            if request.request_kind == RequestKind.UPDATE:
                if after["project_id"] != activity.project_id:
                    raise InvalidApprovalRequestError(
                        "Activity project cannot be changed by an update request"
                    )
                project_id = activity.project_id
            if request.request_kind == RequestKind.DELETE:
                project_id = activity.project_id

        body = {
            "request_kind": request.request_kind.value,
            "target_user_id": target_user_id,
            "activity_id": request.activity_id,
            "before": before,
            "after": after,
            "reason": request.reason,
            "review": {
                "reviewer_patch": None,
                "final": None,
                "diff": None,
            },
        }
        approval_request = ApprovalRequest(
            project_id=project_id,
            requester_id=actor.id,
            status=ApprovalStatus.PENDING,
            body=body,
        )
        db.add(approval_request)
        db.flush()

        RequestService.replace_approvers(db, approval_request, request.approver_ids)
        db.commit()
        return RequestService.get(db, approval_request.id)

    @staticmethod
    def base_query(db: Session):
        return (
            db.query(ApprovalRequest)
            .options(
                joinedload(ApprovalRequest.requester),
                joinedload(ApprovalRequest.project),
                joinedload(ApprovalRequest.reviewer),
                joinedload(ApprovalRequest.approvers).joinedload(Approver.user),
            )
            .filter(ApprovalRequest.deleted_at.is_(None))
        )

    @staticmethod
    def reviewer_condition(db: Session, user: User):
        leader_projects = db.query(ProjectMember.project_id).filter(
            and_(
                ProjectMember.user_id == user.id,
                ProjectMember.role == MemberRole.LEADER,
                ProjectMember.left_at.is_(None),
            )
        )
        explicit_approver = (
            db.query(Approver.id)
            .filter(
                and_(
                    Approver.approval_request_id == ApprovalRequest.id,
                    Approver.user_id == user.id,
                    Approver.deleted_at.is_(None),
                )
            )
            .exists()
        )
        return or_(
            ApprovalRequest.project_id.in_(leader_projects),
            explicit_approver,
        )

    @staticmethod
    def list(
        db: Session,
        *,
        actor: User,
        scope: RequestScope,
        status: RequestStatusFilter,
        request_kind: RequestKindFilter,
        q: str | None,
        cursor: int | None,
        limit: int,
    ) -> tuple[list[ApprovalRequest], int | None]:
        query = RequestService.base_query(db).join(
            User, User.id == ApprovalRequest.requester_id
        )

        if scope == RequestScope.ALL:
            if not actor.is_admin:
                raise ForbiddenError("Admin access required")
        elif scope == RequestScope.SENT:
            query = query.filter(ApprovalRequest.requester_id == actor.id)
        else:
            if not actor.is_admin:
                query = query.filter(RequestService.reviewer_condition(db, actor))

        if status != RequestStatusFilter.ALL:
            query = query.filter(ApprovalRequest.status == ApprovalStatus(status.value))

        if request_kind != RequestKindFilter.ALL:
            mapped_request_kind = {
                RequestKindFilter.CREATE: RequestKind.CREATE,
                RequestKindFilter.UPDATE: RequestKind.UPDATE,
                RequestKindFilter.DELETE: RequestKind.DELETE,
            }[request_kind]
            query = query.filter(
                ApprovalRequest.body["request_kind"].as_string()
                == mapped_request_kind.value
            )

        if q:
            like = f"%{q}%"
            query = query.filter(or_(User.name.like(like), User.generation.like(like)))

        if cursor is not None:
            query = query.filter(ApprovalRequest.created_at < cursor)

        items = query.order_by(ApprovalRequest.created_at.desc()).limit(limit + 1).all()
        has_more = len(items) > limit
        if has_more:
            items = items[:limit]
        next_cursor = items[-1].created_at if has_more and items else None
        return items, next_cursor

    @staticmethod
    def can_view(
        db: Session, *, approval_request: ApprovalRequest, actor: User
    ) -> bool:
        return (
            actor.is_admin
            or approval_request.requester_id == actor.id
            or RequestService.can_review(
                db, approval_request=approval_request, actor=actor
            )
        )

    @staticmethod
    def can_review(
        db: Session, *, approval_request: ApprovalRequest, actor: User
    ) -> bool:
        if actor.is_admin:
            return True

        if approval_request.project_id is not None:
            is_leader = (
                db.query(ProjectMember)
                .filter(
                    and_(
                        ProjectMember.project_id == approval_request.project_id,
                        ProjectMember.user_id == actor.id,
                        ProjectMember.role == MemberRole.LEADER,
                        ProjectMember.left_at.is_(None),
                    )
                )
                .first()
                is not None
            )
            if is_leader:
                return True

        return (
            db.query(Approver)
            .filter(
                and_(
                    Approver.approval_request_id == approval_request.id,
                    Approver.user_id == actor.id,
                    Approver.deleted_at.is_(None),
                )
            )
            .first()
            is not None
        )

    @staticmethod
    def ensure_can_view(
        db: Session, *, approval_request: ApprovalRequest, actor: User
    ) -> None:
        if not RequestService.can_view(
            db, approval_request=approval_request, actor=actor
        ):
            raise ForbiddenError("Cannot access this request")

    @staticmethod
    def ensure_can_review(
        db: Session, *, approval_request: ApprovalRequest, actor: User
    ) -> None:
        if not RequestService.can_review(
            db, approval_request=approval_request, actor=actor
        ):
            raise ForbiddenError("Cannot review this request")

    @staticmethod
    def ensure_pending(approval_request: ApprovalRequest) -> None:
        if approval_request.status != ApprovalStatus.PENDING:
            raise RequestAlreadyProcessedError()

    @staticmethod
    def update(
        db: Session,
        *,
        actor: User,
        approval_request: ApprovalRequest,
        request: ApprovalRequestUpdateRequest,
    ) -> ApprovalRequest:
        if approval_request.requester_id != actor.id:
            raise ForbiddenError("Only the requester can update this request")
        RequestService.ensure_pending(approval_request)

        body = dict(approval_request.body)

        if request.after is not None:
            if RequestKind(body["request_kind"]) == RequestKind.DELETE:
                raise InvalidApprovalRequestError("Delete requests cannot update after")
            after = request.after.model_dump(mode="json")
            RequestService.validate_activity_payload(db, after)
            if (
                RequestKind(body["request_kind"]) == RequestKind.UPDATE
                and body["before"]["project_id"] != after["project_id"]
            ):
                raise InvalidApprovalRequestError(
                    "Activity project cannot be changed by an update request"
                )
            body["after"] = after
            approval_request.project_id = after["project_id"]

        if request.reason is not None:
            body["reason"] = request.reason

        if request.approver_ids is not None:
            RequestService.replace_approvers(db, approval_request, request.approver_ids)

        approval_request.body = body
        db.commit()
        return RequestService.get(db, approval_request.id)

    @staticmethod
    def delete(db: Session, *, actor: User, approval_request: ApprovalRequest) -> None:
        if not actor.is_admin:
            if approval_request.requester_id != actor.id:
                raise ForbiddenError("Only the requester can delete this request")
            RequestService.ensure_pending(approval_request)

        approval_request.deleted_at = int(time.time())
        db.commit()

    @staticmethod
    def diff(requested: dict, final: dict) -> dict:
        diff: dict = {}
        for key, requested_value in requested.items():
            final_value = final.get(key)
            if requested_value != final_value:
                diff[key] = {"requested": requested_value, "final": final_value}
        return diff

    @staticmethod
    def apply_activity(
        db: Session, *, approval_request: ApprovalRequest, final: dict | None
    ) -> UserActivity | None:
        if final is not None:
            RequestService.validate_activity_payload(db, final)
        body = approval_request.body
        target_user_id = body["target_user_id"]
        request_kind = RequestKind(body["request_kind"])

        if request_kind == RequestKind.CREATE:
            activity = UserActivity(user_id=target_user_id, **final)
            db.add(activity)
            db.flush()
            return activity

        if request_kind == RequestKind.UPDATE:
            activity = (
                db.query(UserActivity)
                .filter(UserActivity.id == body["activity_id"])
                .first()
            )
            if not activity or activity.user_id != target_user_id:
                raise NotFoundError("Activity not found")
            for key, value in final.items():
                setattr(activity, key, value)
            db.flush()
            return activity

        if request_kind == RequestKind.DELETE:
            activity = (
                db.query(UserActivity)
                .filter(UserActivity.id == body["activity_id"])
                .first()
            )
            if not activity or activity.user_id != target_user_id:
                raise NotFoundError("Activity not found")
            db.delete(activity)
            db.flush()
            return None

        raise InvalidApprovalRequestError("Unsupported request kind")

    @staticmethod
    def approve(
        db: Session,
        *,
        actor: User,
        approval_request: ApprovalRequest,
        comment: str | None,
    ) -> ApprovalRequest:
        RequestService.ensure_can_review(
            db, approval_request=approval_request, actor=actor
        )
        RequestService.ensure_pending(approval_request)

        body = dict(approval_request.body)
        final = dict(body["after"]) if body.get("after") is not None else None
        RequestService.apply_activity(
            db, approval_request=approval_request, final=final
        )

        body["review"] = {
            "reviewer_patch": None,
            "final": final,
            "diff": {},
        }
        RequestService.mark_processed(
            approval_request,
            actor=actor,
            status=ApprovalStatus.APPROVED,
            comment=comment,
            body=body,
        )
        db.commit()
        return RequestService.get(db, approval_request.id)

    @staticmethod
    def approve_with_edits(
        db: Session,
        *,
        actor: User,
        approval_request: ApprovalRequest,
        request: ApprovalReviewWithEditsRequest,
    ) -> ApprovalRequest:
        RequestService.ensure_can_review(
            db, approval_request=approval_request, actor=actor
        )
        RequestService.ensure_pending(approval_request)

        body = dict(approval_request.body)
        if RequestKind(body["request_kind"]) == RequestKind.DELETE:
            raise InvalidApprovalRequestError("Delete requests cannot be edited")
        requested = dict(body["after"])
        patch = request.reviewer_patch.model_dump(exclude_unset=True, mode="json")
        final = {**requested, **patch}

        RequestService.apply_activity(
            db, approval_request=approval_request, final=final
        )

        body["review"] = {
            "reviewer_patch": patch,
            "final": final,
            "diff": RequestService.diff(requested, final),
        }
        RequestService.mark_processed(
            approval_request,
            actor=actor,
            status=ApprovalStatus.APPROVED,
            comment=request.comment,
            body=body,
        )
        db.commit()
        return RequestService.get(db, approval_request.id)

    @staticmethod
    def reject(
        db: Session,
        *,
        actor: User,
        approval_request: ApprovalRequest,
        comment: str,
    ) -> ApprovalRequest:
        RequestService.ensure_can_review(
            db, approval_request=approval_request, actor=actor
        )
        RequestService.ensure_pending(approval_request)
        RequestService.mark_processed(
            approval_request,
            actor=actor,
            status=ApprovalStatus.REJECTED,
            comment=comment,
            body=approval_request.body,
        )
        db.commit()
        return RequestService.get(db, approval_request.id)

    @staticmethod
    def mark_processed(
        approval_request: ApprovalRequest,
        *,
        actor: User,
        status: ApprovalStatus,
        comment: str | None,
        body: dict,
    ) -> None:
        approval_request.status = status
        approval_request.reviewer_id = actor.id
        approval_request.reviewed_at = int(time.time())
        approval_request.review_comment = comment
        approval_request.body = body
