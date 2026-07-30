from __future__ import annotations

import time

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, joinedload

from app.exceptions import (
    ForbiddenError,
    InvalidApprovalRequestError,
    InvalidCursorError,
    NoEligibleReviewerError,
    NotFoundError,
    RequestAlreadyProcessedError,
)
from app.models import (
    ApprovalRequest,
    ApprovalStatus,
    MemberRole,
    Project,
    ProjectMember,
    Qualification,
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
    ReviewTarget,
)
from app.services.activity import ActivityService
from app.services.member import MemberService
from app.services.project import ProjectService
from app.services.user import UserService

_REQUEST_CURSOR_ID_OFFSET = 10**10


def _encode_cursor(created_at: int, request_id: int) -> str:
    return str(created_at * _REQUEST_CURSOR_ID_OFFSET + request_id)


def _decode_cursor(cursor: str) -> tuple[int, int]:
    try:
        value = int(cursor)
    except (TypeError, ValueError):
        raise InvalidCursorError() from None
    if value < 0:
        raise InvalidCursorError()

    # Backward compatibility for the previous timestamp-only cursor.
    if value < _REQUEST_CURSOR_ID_OFFSET:
        return value, 0
    return divmod(value, _REQUEST_CURSOR_ID_OFFSET)


def _detail_query(db: Session):
    return db.query(ApprovalRequest).options(
        joinedload(ApprovalRequest.requester),
        joinedload(ApprovalRequest.project),
        joinedload(ApprovalRequest.reviewed_by),
        joinedload(ApprovalRequest.reviewers).joinedload(RequestReviewer.user),
    )


def _received_condition(db: Session, actor: User):
    review_target = ApprovalRequest.body["review_target"].as_string()
    target_user_id = ApprovalRequest.body["target_user_id"].as_integer()
    leader_projects = (
        db.query(ProjectMember.project_id)
        .join(Project, Project.id == ProjectMember.project_id)
        .filter(
            and_(
                ProjectMember.user_id == actor.id,
                ProjectMember.role == MemberRole.LEADER,
                ProjectMember.left_at.is_(None),
                Project.deleted_at.is_(None),
            )
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
    leader_target = and_(
        or_(
            review_target == ReviewTarget.PROJECT_LEADER.value,
            review_target.is_(None),
        ),
        ApprovalRequest.project_id.in_(leader_projects),
    )
    target_conditions = [leader_target, explicit_reviewer]
    if actor.has_admin_access:
        target_conditions.append(review_target == ReviewTarget.OPERATIONS.value)

    return and_(
        ApprovalRequest.requester_id != actor.id,
        target_user_id != actor.id,
        or_(*target_conditions),
    )


def _ensure_user_exists(db: Session, user_id: int) -> None:
    if UserService.get(db, user_id) is None:
        raise NotFoundError("User not found")


def _ensure_project_exists(db: Session, project_id: int) -> None:
    if ProjectService.get(db, project_id) is None:
        raise NotFoundError("Project not found")


def _get_user_activity(
    db: Session, *, activity_id: int | None, target_user_id: int
) -> UserActivity:
    activity = ActivityService.get_for_user(
        db,
        activity_id=activity_id,
        user_id=target_user_id,
    )
    if activity is None:
        raise NotFoundError("Activity not found")
    return activity


def _get_review_target(approval_request: ApprovalRequest) -> ReviewTarget:
    value = approval_request.body.get(
        "review_target", ReviewTarget.PROJECT_LEADER.value
    )
    try:
        return ReviewTarget(value)
    except ValueError:
        raise InvalidApprovalRequestError("Invalid review target") from None


def _is_explicit_reviewer(
    db: Session,
    *,
    approval_request: ApprovalRequest,
    actor: User,
) -> bool:
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


def _can_review(
    db: Session,
    *,
    approval_request: ApprovalRequest,
    actor: User,
) -> bool:
    target_user_id = approval_request.body["target_user_id"]
    if actor.id in (approval_request.requester_id, target_user_id):
        return False
    if actor.has_admin_access:
        return True
    if _is_explicit_reviewer(
        db,
        approval_request=approval_request,
        actor=actor,
    ):
        return True
    return (
        _get_review_target(approval_request) == ReviewTarget.PROJECT_LEADER
        and approval_request.project_id is not None
        and MemberService.is_leader(db, approval_request.project_id, actor.id)
    )


def _can_view(
    db: Session,
    *,
    approval_request: ApprovalRequest,
    actor: User,
) -> bool:
    if actor.has_admin_access or approval_request.requester_id == actor.id:
        return True
    if _is_explicit_reviewer(
        db,
        approval_request=approval_request,
        actor=actor,
    ):
        return True
    return (
        _get_review_target(approval_request) == ReviewTarget.PROJECT_LEADER
        and approval_request.project_id is not None
        and MemberService.is_leader(db, approval_request.project_id, actor.id)
    )


def _lock_request(db: Session, approval_request: ApprovalRequest) -> ApprovalRequest:
    locked = (
        db.query(ApprovalRequest)
        .filter(
            and_(
                ApprovalRequest.id == approval_request.id,
                ApprovalRequest.deleted_at.is_(None),
            )
        )
        .populate_existing()
        .with_for_update()
        .first()
    )
    if locked is None:
        raise NotFoundError("Request not found")
    return locked


def _lock_project(db: Session, project_id: int) -> Project:
    project = (
        db.query(Project)
        .filter(and_(Project.id == project_id, Project.deleted_at.is_(None)))
        .populate_existing()
        .with_for_update()
        .first()
    )
    if project is None:
        raise NotFoundError("Project not found")
    return project


def _eligible_users_query(db: Session, excluded_user_ids: set[int]):
    query = db.query(User.id).filter(
        and_(
            User.deleted_at.is_(None),
            User.qualification.in_((Qualification.REGULAR, Qualification.ACTIVE)),
        )
    )
    if excluded_user_ids:
        query = query.filter(User.id.notin_(excluded_user_ids))
    return query


def _ensure_has_eligible_reviewer(
    db: Session, approval_request: ApprovalRequest
) -> None:
    excluded_user_ids = {
        approval_request.requester_id,
        approval_request.body["target_user_id"],
    }
    eligible_users = _eligible_users_query(db, excluded_user_ids).subquery()

    explicit_reviewer_exists = (
        db.query(RequestReviewer.id)
        .join(eligible_users, eligible_users.c.id == RequestReviewer.user_id)
        .filter(
            and_(
                RequestReviewer.approval_request_id == approval_request.id,
                RequestReviewer.deleted_at.is_(None),
            )
        )
        .first()
        is not None
    )
    if explicit_reviewer_exists:
        return

    review_target = _get_review_target(approval_request)
    if review_target == ReviewTarget.OPERATIONS:
        group_reviewer_exists = (
            db.query(User.id)
            .join(eligible_users, eligible_users.c.id == User.id)
            .filter(or_(User.is_admin.is_(True), User.is_president.is_(True)))
            .first()
            is not None
        )
    else:
        group_reviewer_exists = (
            db.query(ProjectMember.id)
            .join(eligible_users, eligible_users.c.id == ProjectMember.user_id)
            .filter(
                and_(
                    ProjectMember.project_id == approval_request.project_id,
                    ProjectMember.role == MemberRole.LEADER,
                    ProjectMember.left_at.is_(None),
                )
            )
            .first()
            is not None
        )

    if not group_reviewer_exists:
        raise NoEligibleReviewerError()


def _build_create_body(
    db: Session,
    *,
    actor: User,
    request: ApprovalRequestCreateRequest,
) -> tuple[int | None, dict]:
    target_user_id = request.target_user_id or actor.id
    if target_user_id != actor.id and not actor.has_admin_access:
        raise ForbiddenError("Cannot create a request for another user")
    _ensure_user_exists(db, target_user_id)

    after = request.after.model_dump(mode="json") if request.after else None
    if after is not None:
        _ensure_project_exists(db, after["project_id"])

    project_id = after["project_id"] if after is not None else None
    before = None
    if request.request_kind in (RequestKind.UPDATE, RequestKind.DELETE):
        activity = _get_user_activity(
            db,
            activity_id=request.activity_id,
            target_user_id=target_user_id,
        )
        if activity.project_id is None:
            raise InvalidApprovalRequestError(
                "Project activity request requires a project activity"
            )
        before = ActivityService.to_request_snapshot(activity)
        project_id = activity.project_id
        if (
            request.request_kind == RequestKind.UPDATE
            and after["project_id"] != activity.project_id
        ):
            raise InvalidApprovalRequestError(
                "Activity project cannot be changed by an update request"
            )

    if project_id is None:
        raise InvalidApprovalRequestError("Project is required")
    _lock_project(db, project_id)

    body = {
        "request_kind": request.request_kind.value,
        "target_user_id": target_user_id,
        "activity_id": request.activity_id,
        "before": before,
        "after": after,
        "reason": request.reason,
        "review": {"reviewer_patch": None, "final": None, "diff": None},
    }
    if not request.reviewer_ids:
        body["review_target"] = request.review_target.value
    return project_id, body


def _replace_reviewers(
    db: Session,
    approval_request: ApprovalRequest,
    reviewer_ids: list[int],
) -> None:
    approval_request.reviewers.clear()
    seen: set[int] = set()
    for user_id in reviewer_ids:
        if user_id in seen:
            continue
        _ensure_user_exists(db, user_id)
        approval_request.reviewers.append(RequestReviewer(user_id=user_id))
        seen.add(user_id)


def _update_after(
    db: Session,
    approval_request: ApprovalRequest,
    body: dict,
    request: ApprovalRequestUpdateRequest,
) -> None:
    request_kind = RequestKind(body["request_kind"])
    if request_kind == RequestKind.DELETE:
        raise InvalidApprovalRequestError("Delete requests cannot update after")

    after = request.after.model_dump(mode="json")
    if request_kind == RequestKind.CREATE:
        _lock_project(db, after["project_id"])
    else:
        _ensure_project_exists(db, after["project_id"])
    if (
        request_kind == RequestKind.UPDATE
        and body["before"]["project_id"] != after["project_id"]
    ):
        raise InvalidApprovalRequestError(
            "Activity project cannot be changed by an update request"
        )
    body["after"] = after
    approval_request.project_id = after["project_id"]


def _apply_activity(
    db: Session, *, approval_request: ApprovalRequest, final: dict | None
) -> UserActivity | None:
    if final is not None:
        _ensure_project_exists(db, final["project_id"])

    body = approval_request.body
    target_user_id = body["target_user_id"]
    request_kind = RequestKind(body["request_kind"])

    if request_kind == RequestKind.CREATE:
        activity = UserActivity(user_id=target_user_id, **final)
        db.add(activity)
        db.flush()
        return activity

    if request_kind == RequestKind.UPDATE:
        activity = _get_user_activity(
            db,
            activity_id=body["activity_id"],
            target_user_id=target_user_id,
        )
        for key, value in final.items():
            setattr(activity, key, value)
        db.flush()
        return activity

    if request_kind == RequestKind.DELETE:
        activity = _get_user_activity(
            db,
            activity_id=body["activity_id"],
            target_user_id=target_user_id,
        )
        db.delete(activity)
        db.flush()
        return None

    raise InvalidApprovalRequestError("Unsupported request kind")


def _mark_reviewed(
    approval_request: ApprovalRequest,
    *,
    actor: User,
    status: ApprovalStatus,
    comment: str | None,
    body: dict,
) -> None:
    approval_request.status = status
    approval_request.reviewed_by_id = actor.id
    approval_request.reviewed_at = int(time.time())
    approval_request.review_comment = comment
    approval_request.body = body


class RequestService:
    @staticmethod
    def _commit_and_get(
        db: Session, approval_request: ApprovalRequest
    ) -> ApprovalRequest:
        db.commit()
        return RequestService.get(db, approval_request.id)

    @staticmethod
    def _ensure_can_review_pending(
        db: Session, *, actor: User, approval_request: ApprovalRequest
    ) -> None:
        if not _can_review(
            db,
            approval_request=approval_request,
            actor=actor,
        ):
            raise ForbiddenError("Cannot review this request")
        if approval_request.status != ApprovalStatus.PENDING:
            raise RequestAlreadyProcessedError()

    @staticmethod
    def get(db: Session, request_id: int) -> ApprovalRequest | None:
        return (
            _detail_query(db)
            .filter(
                and_(
                    ApprovalRequest.id == request_id,
                    ApprovalRequest.deleted_at.is_(None),
                )
            )
            .first()
        )

    @staticmethod
    def list(
        db: Session,
        *,
        actor: User,
        scope: RequestScope,
        status: RequestStatusFilter,
        request_kind: RequestKindFilter,
        activity_id: int | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[ApprovalRequest], str | None]:
        query = (
            _detail_query(db)
            .filter(ApprovalRequest.deleted_at.is_(None))
            .join(User, User.id == ApprovalRequest.requester_id)
        )

        if scope == RequestScope.ALL:
            if not actor.has_admin_access:
                raise ForbiddenError("Admin access required")
        elif scope == RequestScope.SENT:
            query = query.filter(ApprovalRequest.requester_id == actor.id)
        else:
            query = query.filter(_received_condition(db, actor))

        if status != RequestStatusFilter.ALL:
            query = query.filter(ApprovalRequest.status == ApprovalStatus(status.value))

        if request_kind != RequestKindFilter.ALL:
            query = query.filter(
                ApprovalRequest.body["request_kind"].as_string() == request_kind.value
            )

        if activity_id is not None:
            query = query.filter(
                ApprovalRequest.body["activity_id"].as_integer() == activity_id
            )

        if cursor is not None:
            cursor_created_at, cursor_id = _decode_cursor(cursor)
            query = query.filter(
                or_(
                    ApprovalRequest.created_at < cursor_created_at,
                    and_(
                        ApprovalRequest.created_at == cursor_created_at,
                        ApprovalRequest.id < cursor_id,
                    ),
                )
            )

        items = (
            query.order_by(
                ApprovalRequest.created_at.desc(),
                ApprovalRequest.id.desc(),
            )
            .limit(limit + 1)
            .all()
        )
        has_more = len(items) > limit
        page_items = items[:limit]
        next_cursor = (
            _encode_cursor(page_items[-1].created_at, page_items[-1].id)
            if has_more and page_items
            else None
        )
        return page_items, next_cursor

    @staticmethod
    def create(
        db: Session,
        *,
        actor: User,
        request: ApprovalRequestCreateRequest,
    ) -> ApprovalRequest:
        project_id, body = _build_create_body(db, actor=actor, request=request)
        approval_request = ApprovalRequest(
            project_id=project_id,
            requester_id=actor.id,
            status=ApprovalStatus.PENDING,
            body=body,
        )
        db.add(approval_request)
        db.flush()

        _replace_reviewers(db, approval_request, request.reviewer_ids or [])
        db.flush()
        _ensure_has_eligible_reviewer(db, approval_request)
        return RequestService._commit_and_get(db, approval_request)

    @staticmethod
    def ensure_can_view(
        db: Session, *, approval_request: ApprovalRequest, actor: User
    ) -> None:
        if not _can_view(
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
        approval_request = _lock_request(db, approval_request)
        if approval_request.requester_id != actor.id:
            raise ForbiddenError("Only the requester can update this request")
        if approval_request.status != ApprovalStatus.PENDING:
            raise RequestAlreadyProcessedError()

        body = dict(approval_request.body)
        if request.after is not None:
            _update_after(db, approval_request, body, request)
        if request.reason is not None:
            body["reason"] = request.reason
        if request.review_target is not None:
            body["review_target"] = request.review_target.value
            _replace_reviewers(db, approval_request, [])
        if request.reviewer_ids is not None:
            if "review_target" in body:
                raise InvalidApprovalRequestError(
                    "reviewer_ids cannot update a group-targeted request"
                )
            _replace_reviewers(db, approval_request, request.reviewer_ids)

        approval_request.body = body
        db.flush()
        _ensure_has_eligible_reviewer(db, approval_request)
        return RequestService._commit_and_get(db, approval_request)

    @staticmethod
    def delete(db: Session, *, actor: User, approval_request: ApprovalRequest) -> None:
        approval_request = _lock_request(db, approval_request)
        if not actor.has_admin_access:
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
        approval_request = _lock_request(db, approval_request)
        RequestService._ensure_can_review_pending(
            db,
            actor=actor,
            approval_request=approval_request,
        )

        body = dict(approval_request.body)
        final = dict(body["after"]) if body.get("after") is not None else None
        activity = _apply_activity(db, approval_request=approval_request, final=final)
        if RequestKind(body["request_kind"]) == RequestKind.CREATE:
            if activity is None:
                raise InvalidApprovalRequestError(
                    "Create approval did not produce an activity"
                )
            body["activity_id"] = activity.id
        body["review"] = {"reviewer_patch": None, "final": final, "diff": {}}
        _mark_reviewed(
            approval_request,
            actor=actor,
            status=ApprovalStatus.APPROVED,
            comment=comment,
            body=body,
        )
        return RequestService._commit_and_get(db, approval_request)

    @staticmethod
    def approve_with_edits(
        db: Session,
        *,
        actor: User,
        approval_request: ApprovalRequest,
        request: ApprovalReviewWithEditsRequest,
    ) -> ApprovalRequest:
        approval_request = _lock_request(db, approval_request)
        RequestService._ensure_can_review_pending(
            db,
            actor=actor,
            approval_request=approval_request,
        )

        body = dict(approval_request.body)
        if RequestKind(body["request_kind"]) == RequestKind.DELETE:
            raise InvalidApprovalRequestError("Delete requests cannot be edited")

        requested = dict(body["after"])
        patch = request.reviewer_patch.model_dump(exclude_unset=True, mode="json")
        final = {**requested, **patch}
        activity = _apply_activity(db, approval_request=approval_request, final=final)
        if RequestKind(body["request_kind"]) == RequestKind.CREATE:
            if activity is None:
                raise InvalidApprovalRequestError(
                    "Create approval did not produce an activity"
                )
            body["activity_id"] = activity.id
        body["review"] = {
            "reviewer_patch": patch,
            "final": final,
            "diff": {
                key: {"requested": requested_value, "final": final_value}
                for key, requested_value in requested.items()
                if requested_value != (final_value := final.get(key))
            },
        }
        _mark_reviewed(
            approval_request,
            actor=actor,
            status=ApprovalStatus.APPROVED,
            comment=request.comment,
            body=body,
        )
        return RequestService._commit_and_get(db, approval_request)

    @staticmethod
    def reject(
        db: Session,
        *,
        actor: User,
        approval_request: ApprovalRequest,
        comment: str,
    ) -> ApprovalRequest:
        approval_request = _lock_request(db, approval_request)
        RequestService._ensure_can_review_pending(
            db,
            actor=actor,
            approval_request=approval_request,
        )

        _mark_reviewed(
            approval_request,
            actor=actor,
            status=ApprovalStatus.REJECTED,
            comment=comment,
            body=approval_request.body,
        )
        return RequestService._commit_and_get(db, approval_request)
