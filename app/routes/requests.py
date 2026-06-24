from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.deps.auth import require_regular
from app.exceptions import NotFoundError
from app.models import User
from app.schemas import (
    ApprovalRejectRequest,
    ApprovalRequestBody,
    ApprovalRequestCreateRequest,
    ApprovalRequestDetail,
    ApprovalRequestListItem,
    ApprovalRequestUpdateRequest,
    ApprovalReviewRequest,
    ApprovalReviewWithEditsRequest,
    ApproverDetail,
    CursorPage,
    ProjectBrief,
    RequestKind,
    RequestKindFilter,
    RequestScope,
    RequestStatusFilter,
    Response,
    UserBrief,
)
from app.services import RequestService

router = APIRouter()


def to_list_item(approval_request) -> ApprovalRequestListItem:
    body = ApprovalRequestBody.model_validate(approval_request.body)
    return ApprovalRequestListItem(
        id=approval_request.id,
        requester=UserBrief.model_validate(approval_request.requester),
        requester_generation=approval_request.requester.generation,
        request_kind=RequestKind(body.request_kind),
        status=approval_request.status,
        created_at=approval_request.created_at,
        reviewed_at=approval_request.reviewed_at,
    )


def to_detail(approval_request) -> ApprovalRequestDetail:
    return ApprovalRequestDetail(
        id=approval_request.id,
        requester=UserBrief.model_validate(approval_request.requester),
        requester_generation=approval_request.requester.generation,
        project=(
            ProjectBrief.model_validate(approval_request.project)
            if approval_request.project
            else None
        ),
        reviewer=(
            UserBrief.model_validate(approval_request.reviewer)
            if approval_request.reviewer
            else None
        ),
        approvers=[
            ApproverDetail.model_validate(approver)
            for approver in approval_request.approvers
            if approver.deleted_at is None
        ],
        status=approval_request.status,
        body=ApprovalRequestBody.model_validate(approval_request.body),
        review_comment=approval_request.review_comment,
        created_at=approval_request.created_at,
        updated_at=approval_request.updated_at,
        reviewed_at=approval_request.reviewed_at,
    )


def get_existing_request(db: Session, request_id: int):
    approval_request = RequestService.get(db, request_id)
    if not approval_request:
        raise NotFoundError("Request not found")
    return approval_request


@router.post(
    "",
    response_model=Response[ApprovalRequestDetail],
    summary="Create activity approval request",
)
async def create_request(
    request: ApprovalRequestCreateRequest,
    current_user: User = Depends(require_regular),
    db: Session = Depends(get_db),
):
    approval_request = RequestService.create(
        db,
        actor=current_user,
        request=request,
    )
    return Response(ok=True, data=to_detail(approval_request))


@router.get(
    "",
    response_model=Response[CursorPage[ApprovalRequestListItem]],
    summary="List activity approval requests",
)
async def list_requests(
    scope: RequestScope = Query(default=RequestScope.RECEIVED),
    status: RequestStatusFilter = Query(default=RequestStatusFilter.PENDING),
    request_kind: RequestKindFilter = Query(default=RequestKindFilter.ALL),
    q: str | None = Query(default=None, description="Requester name/generation search"),
    cursor: int | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(require_regular),
    db: Session = Depends(get_db),
):
    items, next_cursor = RequestService.list(
        db,
        actor=current_user,
        scope=scope,
        status=status,
        request_kind=request_kind,
        q=q,
        cursor=cursor,
        limit=limit,
    )
    return Response(
        ok=True,
        data=CursorPage(
            items=[to_list_item(item) for item in items],
            next_cursor=next_cursor,
        ),
    )


@router.get(
    "/{request_id}",
    response_model=Response[ApprovalRequestDetail],
    summary="Get activity approval request detail",
)
async def get_request(
    request_id: int,
    current_user: User = Depends(require_regular),
    db: Session = Depends(get_db),
):
    approval_request = get_existing_request(db, request_id)
    RequestService.ensure_can_view(
        db,
        approval_request=approval_request,
        actor=current_user,
    )
    return Response(ok=True, data=to_detail(approval_request))


@router.patch(
    "/{request_id}",
    response_model=Response[ApprovalRequestDetail],
    summary="Update pending activity approval request",
)
async def update_request(
    request_id: int,
    request: ApprovalRequestUpdateRequest,
    current_user: User = Depends(require_regular),
    db: Session = Depends(get_db),
):
    approval_request = get_existing_request(db, request_id)
    updated = RequestService.update(
        db,
        actor=current_user,
        approval_request=approval_request,
        request=request,
    )
    return Response(ok=True, data=to_detail(updated))


@router.delete(
    "/{request_id}",
    response_model=Response[None],
    summary="Delete activity approval request",
)
async def delete_request(
    request_id: int,
    current_user: User = Depends(require_regular),
    db: Session = Depends(get_db),
):
    approval_request = get_existing_request(db, request_id)
    RequestService.delete(db, actor=current_user, approval_request=approval_request)
    return Response(ok=True, message="Request deleted successfully")


@router.post(
    "/{request_id}/approve",
    response_model=Response[ApprovalRequestDetail],
    summary="Approve activity approval request",
)
async def approve_request(
    request_id: int,
    request: ApprovalReviewRequest,
    current_user: User = Depends(require_regular),
    db: Session = Depends(get_db),
):
    approval_request = get_existing_request(db, request_id)
    updated = RequestService.approve(
        db,
        actor=current_user,
        approval_request=approval_request,
        comment=request.comment,
    )
    return Response(ok=True, data=to_detail(updated), message="Request approved")


@router.post(
    "/{request_id}/approve-with-edits",
    response_model=Response[ApprovalRequestDetail],
    summary="Approve activity approval request with edits",
)
async def approve_request_with_edits(
    request_id: int,
    request: ApprovalReviewWithEditsRequest,
    current_user: User = Depends(require_regular),
    db: Session = Depends(get_db),
):
    approval_request = get_existing_request(db, request_id)
    updated = RequestService.approve_with_edits(
        db,
        actor=current_user,
        approval_request=approval_request,
        request=request,
    )
    return Response(ok=True, data=to_detail(updated), message="Request approved")


@router.post(
    "/{request_id}/reject",
    response_model=Response[ApprovalRequestDetail],
    summary="Reject activity approval request",
)
async def reject_request(
    request_id: int,
    request: ApprovalRejectRequest,
    current_user: User = Depends(require_regular),
    db: Session = Depends(get_db),
):
    approval_request = get_existing_request(db, request_id)
    updated = RequestService.reject(
        db,
        actor=current_user,
        approval_request=approval_request,
        comment=request.comment,
    )
    return Response(ok=True, data=to_detail(updated), message="Request rejected")
