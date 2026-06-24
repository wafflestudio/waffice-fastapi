from __future__ import annotations

import time

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, joinedload

from app.exceptions import (
    ForbiddenError,
    InvalidApprovalRequestError,
    NotFoundError,
    RequestAlreadyProcessedError,
)
from app.models import (
    ApprovalRequest,
    ApprovalStatus,
    MemberRole,
    Project,
    ProjectMember,
    RequestReviewer,
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

REQUEST_KIND_FILTERS = {
    RequestKindFilter.CREATE: RequestKind.CREATE,
    RequestKindFilter.UPDATE: RequestKind.UPDATE,
    RequestKindFilter.DELETE: RequestKind.DELETE,
}


class RequestQuery:
    """Read approval requests with the eager loads and filters used by routes."""

    @staticmethod
    def base_detail_query(db: Session):
        """Return the shared detail query with related users, project, and reviewers."""
        return db.query(ApprovalRequest).options(
            joinedload(ApprovalRequest.requester),
            joinedload(ApprovalRequest.project),
            joinedload(ApprovalRequest.reviewed_by),
            joinedload(ApprovalRequest.reviewers).joinedload(RequestReviewer.user),
        )

    @staticmethod
    def get(db: Session, request_id: int) -> ApprovalRequest | None:
        """Find one non-deleted request by id, ready for detail serialization."""
        return (
            RequestQuery.base_detail_query(db)
            .filter(
                and_(
                    ApprovalRequest.id == request_id,
                    ApprovalRequest.deleted_at.is_(None),
                )
            )
            .first()
        )

    @staticmethod
    def _received_condition(db: Session, actor: User):
        """Build the condition for requests the actor can review or receive."""
        leader_projects = db.query(ProjectMember.project_id).filter(
            and_(
                ProjectMember.user_id == actor.id,
                ProjectMember.role == MemberRole.LEADER,
                ProjectMember.left_at.is_(None),
            )
        )
        explicit_reviewer = (
            db.query(RequestReviewer.id)
            .filter(
                and_(
                    RequestReviewer.approval_request_id == ApprovalRequest.id,
                    RequestReviewer.user_id == actor.id,
                    RequestReviewer.deleted_at.is_(None),
                )
            )
            .exists()
        )
        return or_(ApprovalRequest.project_id.in_(leader_projects), explicit_reviewer)

    @staticmethod
    def list(
        db: Session,
        *,
        actor: User,
        scope: RequestScope,
        status: RequestStatusFilter,
        request_kind: RequestKindFilter,
        cursor: int | None,
        limit: int,
    ) -> tuple[list[ApprovalRequest], int | None]:
        """List requests by scope, status, kind, and cursor pagination."""
        query = (
            RequestQuery.base_detail_query(db)
            .filter(ApprovalRequest.deleted_at.is_(None))
            .join(User, User.id == ApprovalRequest.requester_id)
        )

        if scope == RequestScope.ALL:
            if not actor.is_admin:
                raise ForbiddenError("Admin access required")
        elif scope == RequestScope.SENT:
            query = query.filter(ApprovalRequest.requester_id == actor.id)
        elif not actor.is_admin:
            query = query.filter(RequestQuery._received_condition(db, actor))

        if status != RequestStatusFilter.ALL:
            query = query.filter(ApprovalRequest.status == ApprovalStatus(status.value))

        if request_kind != RequestKindFilter.ALL:
            query = query.filter(
                ApprovalRequest.body["request_kind"].as_string()
                == REQUEST_KIND_FILTERS[request_kind].value
            )

        if cursor is not None:
            query = query.filter(ApprovalRequest.created_at < cursor)

        items = query.order_by(ApprovalRequest.created_at.desc()).limit(limit + 1).all()
        has_more = len(items) > limit
        page_items = items[:limit]
        next_cursor = page_items[-1].created_at if has_more and page_items else None
        return page_items, next_cursor


class RequestWorkflow:
    """Mutate approval requests and apply the domain rules behind review actions."""

    @staticmethod
    def can_view_or_review(
        db: Session,
        *,
        approval_request: ApprovalRequest,
        actor: User,
        include_requester: bool = True,
    ) -> bool:
        """Return whether the actor can view or review the request."""
        if actor.is_admin:
            return True
        if include_requester and approval_request.requester_id == actor.id:
            return True
        if approval_request.project_id is not None:
            leader = (
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
            )
            if leader is not None:
                return True
        return (
            db.query(RequestReviewer)
            .filter(
                and_(
                    RequestReviewer.approval_request_id == approval_request.id,
                    RequestReviewer.user_id == actor.id,
                    RequestReviewer.deleted_at.is_(None),
                )
            )
            .first()
            is not None
        )

    @staticmethod
    def _ensure_user_exists(db: Session, user_id: int) -> None:
        """Raise when a referenced active user does not exist."""
        user = (
            db.query(User)
            .filter(and_(User.id == user_id, User.deleted_at.is_(None)))
            .first()
        )
        if not user:
            raise NotFoundError("User not found")

    @staticmethod
    def _ensure_project_exists(db: Session, project_id: int) -> None:
        """Raise when a referenced active project does not exist."""
        project = (
            db.query(Project)
            .filter(and_(Project.id == project_id, Project.deleted_at.is_(None)))
            .first()
        )
        if not project:
            raise NotFoundError("Project not found")

    @staticmethod
    def _get_user_activity(
        db: Session, *, activity_id: int | None, target_user_id: int
    ) -> UserActivity:
        """Fetch an activity only when it belongs to the request target user."""
        activity = db.query(UserActivity).filter(UserActivity.id == activity_id).first()
        if not activity or activity.user_id != target_user_id:
            raise NotFoundError("Activity not found")
        return activity

    @staticmethod
    def build_create_body(
        db: Session,
        *,
        actor: User,
        request: ApprovalRequestCreateRequest,
    ) -> tuple[int | None, dict]:
        """Build the persisted body and project reference for a new request."""
        target_user_id = request.target_user_id or actor.id
        if target_user_id != actor.id and not actor.is_admin:
            raise ForbiddenError("Cannot create a request for another user")
        RequestWorkflow._ensure_user_exists(db, target_user_id)

        after = request.after.model_dump(mode="json") if request.after else None
        if after is not None:
            RequestWorkflow._ensure_project_exists(db, after["project_id"])

        project_id = after["project_id"] if after is not None else None
        before = None
        if request.request_kind in (RequestKind.UPDATE, RequestKind.DELETE):
            activity = RequestWorkflow._get_user_activity(
                db,
                activity_id=request.activity_id,
                target_user_id=target_user_id,
            )
            if activity.project_id is None:
                raise InvalidApprovalRequestError(
                    "Project activity request requires a project activity"
                )
            before = {
                "project_id": activity.project_id,
                "position": activity.position,
                "start_date": activity.start_date,
                "end_date": activity.end_date,
                "status": activity.status.value,
                "description": activity.description,
            }
            project_id = activity.project_id
            if (
                request.request_kind == RequestKind.UPDATE
                and after["project_id"] != activity.project_id
            ):
                raise InvalidApprovalRequestError(
                    "Activity project cannot be changed by an update request"
                )

        return project_id, {
            "request_kind": request.request_kind.value,
            "target_user_id": target_user_id,
            "activity_id": request.activity_id,
            "before": before,
            "after": after,
            "reason": request.reason,
            "review": {"reviewer_patch": None, "final": None, "diff": None},
        }

    @staticmethod
    def replace_reviewers(
        db: Session,
        approval_request: ApprovalRequest,
        reviewer_ids: list[int],
    ) -> None:
        """Replace reviewers after validating users and removing duplicate ids."""
        approval_request.reviewers.clear()
        seen: set[int] = set()
        for user_id in reviewer_ids:
            if user_id in seen:
                continue
            RequestWorkflow._ensure_user_exists(db, user_id)
            approval_request.reviewers.append(
                RequestReviewer(
                    user_id=user_id,
                    project_id=approval_request.project_id,
                )
            )
            seen.add(user_id)

    @staticmethod
    def _update_after(
        db: Session,
        approval_request: ApprovalRequest,
        body: dict,
        request: ApprovalRequestUpdateRequest,
    ) -> None:
        """Apply an updated after payload while preserving request-kind constraints."""
        if RequestKind(body["request_kind"]) == RequestKind.DELETE:
            raise InvalidApprovalRequestError("Delete requests cannot update after")

        after = request.after.model_dump(mode="json")
        RequestWorkflow._ensure_project_exists(db, after["project_id"])
        if (
            RequestKind(body["request_kind"]) == RequestKind.UPDATE
            and body["before"]["project_id"] != after["project_id"]
        ):
            raise InvalidApprovalRequestError(
                "Activity project cannot be changed by an update request"
            )
        body["after"] = after
        approval_request.project_id = after["project_id"]

    @staticmethod
    def apply_activity(
        db: Session, *, approval_request: ApprovalRequest, final: dict | None
    ) -> UserActivity | None:
        """Apply an approved create, update, or delete request to user activities."""
        if final is not None:
            RequestWorkflow._ensure_project_exists(db, final["project_id"])

        body = approval_request.body
        target_user_id = body["target_user_id"]
        request_kind = RequestKind(body["request_kind"])

        if request_kind == RequestKind.CREATE:
            activity = UserActivity(user_id=target_user_id, **final)
            db.add(activity)
            db.flush()
            return activity

        if request_kind == RequestKind.UPDATE:
            activity = RequestWorkflow._get_user_activity(
                db,
                activity_id=body["activity_id"],
                target_user_id=target_user_id,
            )
            for key, value in final.items():
                setattr(activity, key, value)
            db.flush()
            return activity

        if request_kind == RequestKind.DELETE:
            activity = RequestWorkflow._get_user_activity(
                db,
                activity_id=body["activity_id"],
                target_user_id=target_user_id,
            )
            db.delete(activity)
            db.flush()
            return None

        raise InvalidApprovalRequestError("Unsupported request kind")

    @staticmethod
    def mark_reviewed(
        approval_request: ApprovalRequest,
        *,
        actor: User,
        status: ApprovalStatus,
        comment: str | None,
        body: dict,
    ) -> None:
        """Store the terminal review status, reviewer metadata, and final body."""
        approval_request.status = status
        approval_request.reviewed_by_id = actor.id
        approval_request.reviewed_at = int(time.time())
        approval_request.review_comment = comment
        approval_request.body = body


class RequestService:
    """Public use cases consumed by request routes."""

    @staticmethod
    def get(db: Session, request_id: int) -> ApprovalRequest | None:
        """Return one request detail or None when it is missing/deleted."""
        return RequestQuery.get(db, request_id)

    @staticmethod
    def list(
        db: Session,
        *,
        actor: User,
        scope: RequestScope,
        status: RequestStatusFilter,
        request_kind: RequestKindFilter,
        cursor: int | None,
        limit: int,
    ) -> tuple[list[ApprovalRequest], int | None]:
        """Return one cursor-paginated page of requests visible for the scope."""
        return RequestQuery.list(
            db,
            actor=actor,
            scope=scope,
            status=status,
            request_kind=request_kind,
            cursor=cursor,
            limit=limit,
        )

    @staticmethod
    def create(
        db: Session,
        *,
        actor: User,
        request: ApprovalRequestCreateRequest,
    ) -> ApprovalRequest:
        """Create a pending approval request with its reviewer set."""
        project_id, body = RequestWorkflow.build_create_body(
            db,
            actor=actor,
            request=request,
        )
        approval_request = ApprovalRequest(
            project_id=project_id,
            requester_id=actor.id,
            status=ApprovalStatus.PENDING,
            body=body,
        )
        db.add(approval_request)
        db.flush()

        RequestWorkflow.replace_reviewers(db, approval_request, request.reviewer_ids)
        db.commit()
        return RequestService.get(db, approval_request.id)

    @staticmethod
    def ensure_can_view(
        db: Session, *, approval_request: ApprovalRequest, actor: User
    ) -> None:
        """Raise when the actor cannot access request detail."""
        if not RequestWorkflow.can_view_or_review(
            db,
            approval_request=approval_request,
            actor=actor,
        ):
            raise ForbiddenError("Cannot access this request")

    @staticmethod
    def update(
        db: Session,
        *,
        actor: User,
        approval_request: ApprovalRequest,
        request: ApprovalRequestUpdateRequest,
    ) -> ApprovalRequest:
        """Update a pending request owned by the actor."""
        if approval_request.requester_id != actor.id:
            raise ForbiddenError("Only the requester can update this request")
        if approval_request.status != ApprovalStatus.PENDING:
            raise RequestAlreadyProcessedError()

        body = dict(approval_request.body)
        if request.after is not None:
            RequestWorkflow._update_after(db, approval_request, body, request)
        if request.reason is not None:
            body["reason"] = request.reason
        if request.reviewer_ids is not None:
            RequestWorkflow.replace_reviewers(
                db, approval_request, request.reviewer_ids
            )

        approval_request.body = body
        db.commit()
        return RequestService.get(db, approval_request.id)

    @staticmethod
    def delete(db: Session, *, actor: User, approval_request: ApprovalRequest) -> None:
        """Soft-delete a request, enforcing pending state for non-admin requesters."""
        if not actor.is_admin:
            if approval_request.requester_id != actor.id:
                raise ForbiddenError("Only the requester can delete this request")
            if approval_request.status != ApprovalStatus.PENDING:
                raise RequestAlreadyProcessedError()

        approval_request.deleted_at = int(time.time())
        db.commit()

    @staticmethod
    def approve(
        db: Session,
        *,
        actor: User,
        approval_request: ApprovalRequest,
        comment: str | None,
    ) -> ApprovalRequest:
        """Approve a pending request exactly as submitted."""
        if not RequestWorkflow.can_view_or_review(
            db,
            approval_request=approval_request,
            actor=actor,
            include_requester=False,
        ):
            raise ForbiddenError("Cannot review this request")
        if approval_request.status != ApprovalStatus.PENDING:
            raise RequestAlreadyProcessedError()

        body = dict(approval_request.body)
        final = dict(body["after"]) if body.get("after") is not None else None
        RequestWorkflow.apply_activity(
            db,
            approval_request=approval_request,
            final=final,
        )
        body["review"] = {"reviewer_patch": None, "final": final, "diff": {}}
        RequestWorkflow.mark_reviewed(
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
        """Approve a pending non-delete request after applying reviewer edits."""
        if not RequestWorkflow.can_view_or_review(
            db,
            approval_request=approval_request,
            actor=actor,
            include_requester=False,
        ):
            raise ForbiddenError("Cannot review this request")
        if approval_request.status != ApprovalStatus.PENDING:
            raise RequestAlreadyProcessedError()

        body = dict(approval_request.body)
        if RequestKind(body["request_kind"]) == RequestKind.DELETE:
            raise InvalidApprovalRequestError("Delete requests cannot be edited")

        requested = dict(body["after"])
        patch = request.reviewer_patch.model_dump(exclude_unset=True, mode="json")
        final = {**requested, **patch}
        RequestWorkflow.apply_activity(
            db,
            approval_request=approval_request,
            final=final,
        )
        body["review"] = {
            "reviewer_patch": patch,
            "final": final,
            "diff": {
                key: {"requested": requested_value, "final": final_value}
                for key, requested_value in requested.items()
                if requested_value != (final_value := final.get(key))
            },
        }
        RequestWorkflow.mark_reviewed(
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
        """Reject a pending request without changing user activities."""
        if not RequestWorkflow.can_view_or_review(
            db,
            approval_request=approval_request,
            actor=actor,
            include_requester=False,
        ):
            raise ForbiddenError("Cannot review this request")
        if approval_request.status != ApprovalStatus.PENDING:
            raise RequestAlreadyProcessedError()

        RequestWorkflow.mark_reviewed(
            approval_request,
            actor=actor,
            status=ApprovalStatus.REJECTED,
            comment=comment,
            body=approval_request.body,
        )
        db.commit()
        return RequestService.get(db, approval_request.id)
