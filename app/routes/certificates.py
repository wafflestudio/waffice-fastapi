"""활동증명서(certificate of activities) API.

- Member: 본인 발급/미리보기/내 이력 조회/다운로드 (require_certificate_eligible).
- Staff/admin: 초안 생성/미리보기, 발급 이력 전체 조회, 회장 임기 관리 (require_admin).
- President: 서명 등록/조회, 초안의 오프라인 서명 원본 등록 (require_president).

라우트 등록 순서 주의: 같은 HTTP 메서드에서 리터럴 세그먼트 경로(`/preview`,
`/me`, `/signature/me`, `/president-terms/current`, ...)는 반드시 가변 경로
(`/{certificate_id}/download`, `/{certificate_id}`)보다 먼저 등록해야
Starlette가 "me"를 `certificate_id="me"`로 잘못 매칭하지 않는다. `GET
/{certificate_id}`는 그중에서도 가장 넓게 매칭되는(1-세그먼트) 가변 경로라서
라우터 맨 끝에 등록한다.
"""

from collections.abc import Callable
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Query,
    Response as FastAPIResponse,
    UploadFile,
)
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.deps.auth import (
    get_current_user,
    require_admin,
    require_certificate_eligible,
    require_president,
)
from app.exceptions import (
    CertificateFileTooLargeError,
    CertificateNotFoundError,
    ForbiddenError,
    InvalidCertificateFileError,
    InvalidSignatureFileError,
    NotFoundError,
    SignatureFileTooLargeError,
)
from app.models import Certificate, User
from app.schemas import (
    CertificateDetail,
    CertificateEventItem,
    CertificateHistoryItem,
    CertificateOptions,
    CertificateSummary,
    CursorPage,
    DraftCertificateCreate,
    PresidentTermCreate,
    PresidentTermDetail,
    Response,
    SignatureDetail,
    UserBrief,
)
from app.services import (
    CertificateService,
    OCIObjectStorageService,
    PresidentService,
    SignatureService,
    UserService,
)

router = APIRouter()

PDF_MAGIC = b"%PDF-"

MAX_SIGNATURE_FILE_SIZE = 5 * 1024 * 1024
MAX_CERTIFICATE_FILE_SIZE = 10 * 1024 * 1024


def _is_png(body: bytes) -> bool:
    return body.startswith(b"\x89PNG\r\n\x1a\n")


def _is_jpeg(body: bytes) -> bool:
    return body.startswith(b"\xff\xd8\xff")


def _is_webp(body: bytes) -> bool:
    return len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WEBP"


# 회장 서명으로 허용하는 이미지 포맷: content-type -> (매직바이트 검사 함수, 확장자).
# SVG는 스크립트/외부 참조를 품을 수 있어 향후 렌더러 보안상 제외한다. GIF는
# 애니메이션(다중 프레임) 여부를 검증하지 않고, 프로필 이미지 업로드
# (app/routes/profile_image.py)도 GIF를 받지 않아 일관성을 위해 제외한다.
SIGNATURE_IMAGE_TYPES: dict[str, tuple[Callable[[bytes], bool], str]] = {
    "image/png": (_is_png, ".png"),
    "image/jpeg": (_is_jpeg, ".jpg"),
    "image/jpg": (_is_jpeg, ".jpg"),
    "image/webp": (_is_webp, ".webp"),
}


def _to_signature_detail(
    signature, storage: OCIObjectStorageService
) -> SignatureDetail:
    return SignatureDetail(
        id=signature.id,
        user_id=signature.user_id,
        url=storage.public_url(signature.object_key),
        created_at=signature.created_at,
        updated_at=signature.updated_at,
    )


def to_detail(certificate: Certificate) -> CertificateDetail:
    """`Certificate.events`는 relationship에 order_by가 없으므로 여기서 정렬한다."""
    events = sorted(certificate.events, key=lambda event: (event.created_at, event.id))
    return CertificateDetail(
        id=certificate.id,
        kind=certificate.kind,
        status=certificate.status,
        user=UserBrief.model_validate(certificate.user),
        requested_by=(
            UserBrief.model_validate(certificate.requested_by)
            if certificate.requested_by
            else None
        ),
        options=CertificateOptions.model_validate(certificate.options),
        issue_number=certificate.issue_number,
        issued_at=certificate.issued_at,
        expires_at=certificate.expires_at,
        created_at=certificate.created_at,
        updated_at=certificate.updated_at,
        events=[CertificateEventItem.model_validate(event) for event in events],
    )


def get_existing_target_user(db: Session, user_id: int) -> User:
    user = UserService.get(db, user_id)
    if user is None:
        raise NotFoundError("대상 회원을 찾을 수 없습니다.")
    return user


def get_existing_certificate(db: Session, certificate_id: int) -> Certificate:
    certificate = CertificateService.get(db, certificate_id)
    if certificate is None:
        raise CertificateNotFoundError()
    return certificate


# =====================================================================
# Member
# =====================================================================
@router.post(
    "/preview",
    summary="활동증명서 미리보기",
    description=(
        "현재 로그인한 회원 기준으로 활동증명서를 렌더링해 PDF로 돌려준다. "
        "저장되지 않으며, 발행번호는 'XXXX'로 마스킹된다."
    ),
)
async def preview_certificate(
    options: CertificateOptions,
    current_user: User = Depends(require_certificate_eligible),
    db: Session = Depends(get_db),
):
    storage = OCIObjectStorageService()
    pdf_bytes = CertificateService.preview(
        db, target_user=current_user, options=options, storage=storage
    )
    return FastAPIResponse(content=pdf_bytes, media_type="application/pdf")


@router.post(
    "",
    response_model=Response[CertificateDetail],
    summary="활동증명서 발급",
    description="본인 명의로 활동증명서를 즉시 발급한다 (발행번호를 이 시점에 부여).",
)
async def issue_certificate(
    options: CertificateOptions,
    current_user: User = Depends(require_certificate_eligible),
    db: Session = Depends(get_db),
):
    storage = OCIObjectStorageService()
    certificate = CertificateService.issue_self(
        db, user=current_user, options=options, storage=storage
    )
    return Response(ok=True, data=to_detail(certificate))


@router.get(
    "/me",
    response_model=Response[CursorPage[CertificateSummary]],
    summary="내 활동증명서 신청/발급 내역",
    description="본인이 신청했거나 발급받은 활동증명서 목록을 커서 기반으로 조회한다.",
)
async def list_my_certificates(
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(require_certificate_eligible),
    db: Session = Depends(get_db),
):
    items, next_cursor = CertificateService.list_own(
        db, user=current_user, cursor=cursor, limit=limit
    )
    return Response(
        ok=True,
        data=CursorPage(
            items=[CertificateSummary.model_validate(item) for item in items],
            next_cursor=next_cursor,
        ),
    )


@router.get(
    "/{certificate_id}/download",
    summary="활동증명서 PDF 다운로드",
    description="발급된 활동증명서 PDF를 스트리밍으로 내려받는다. 본인 또는 관리자만 가능하다.",
)
async def download_certificate(
    certificate_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    certificate = get_existing_certificate(db, certificate_id)
    if certificate.user_id != current_user.id and not current_user.is_admin:
        raise ForbiddenError("본인 또는 관리자만 다운로드할 수 있습니다.")

    storage = OCIObjectStorageService()
    CertificateService.ensure_not_expired(db, certificate, storage)
    if not certificate.pdf_object_key:
        raise CertificateNotFoundError()

    pdf_bytes = storage.get_bytes(certificate.pdf_object_key)
    return FastAPIResponse(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="certificate_{certificate.id}.pdf"'
            )
        },
    )


# =====================================================================
# President
# =====================================================================
@router.get(
    "/signature/me",
    response_model=Response[SignatureDetail | None],
    summary="내 서명 조회",
    description="현직 회장이 등록해 둔 자신의 서명 이미지 정보를 조회한다.",
)
async def get_my_signature(
    president: User = Depends(require_president),
    db: Session = Depends(get_db),
):
    signature = SignatureService.get_by_user(db, president.id)
    if signature is None:
        return Response(ok=True, data=None, message="등록된 서명이 없습니다.")
    storage = OCIObjectStorageService()
    return Response(ok=True, data=_to_signature_detail(signature, storage))


@router.put(
    "/signature/me",
    response_model=Response[SignatureDetail],
    summary="내 서명 등록/교체",
    description="현직 회장이 서명 이미지(PNG, JPG, WEBP)를 등록하거나 기존 서명을 교체한다. 투명 배경 PNG를 권장한다 — JPEG는 배경이 불투명한 흰색 사각형으로 채워져 증명서의 성명 글자를 가릴 수 있다.",
)
async def upsert_my_signature(
    file: UploadFile = File(...),
    president: User = Depends(require_president),
    db: Session = Depends(get_db),
):
    if file.content_type not in SIGNATURE_IMAGE_TYPES:
        raise InvalidSignatureFileError()

    body = await file.read()
    if len(body) > MAX_SIGNATURE_FILE_SIZE:
        raise SignatureFileTooLargeError()

    is_valid_magic, ext = SIGNATURE_IMAGE_TYPES[file.content_type]
    if not is_valid_magic(body):
        raise InvalidSignatureFileError()

    storage = OCIObjectStorageService()
    object_key = f"signatures/{president.id}/{uuid4()}{ext}"
    storage.upload_bytes(object_key, body, file.content_type)

    signature = SignatureService.upsert(
        db, user_id=president.id, object_key=object_key, storage=storage
    )
    return Response(ok=True, data=_to_signature_detail(signature, storage))


@router.post(
    "/{certificate_id}/original",
    response_model=Response[CertificateDetail],
    summary="활동증명서 원본 등록",
    description=(
        "회장이 오프라인으로 서명한 원본 PDF를 등록한다. 초안(DRAFT, "
        "ORIGINAL_PENDING) 상태의 증명서에만 가능하며, 이 시점에 발행번호가 "
        "부여되고 발급이 완료(ISSUED)된다."
    ),
)
async def register_certificate_original(
    certificate_id: int,
    file: UploadFile = File(...),
    president: User = Depends(require_president),
    db: Session = Depends(get_db),
):
    certificate = get_existing_certificate(db, certificate_id)

    if file.content_type != "application/pdf":
        raise InvalidCertificateFileError()

    body = await file.read()
    if not body.startswith(PDF_MAGIC):
        raise InvalidCertificateFileError()
    if len(body) > MAX_CERTIFICATE_FILE_SIZE:
        raise CertificateFileTooLargeError()

    storage = OCIObjectStorageService()
    updated = CertificateService.register_original(
        db,
        president=president,
        certificate=certificate,
        file_bytes=body,
        storage=storage,
    )
    return Response(ok=True, data=to_detail(updated))


# =====================================================================
# Staff / admin
# =====================================================================
@router.post(
    "/drafts/preview",
    summary="활동증명서 초안 미리보기 (운영진)",
    description="운영진이 지정 회원 기준으로 초안 활동증명서를 렌더링해 PDF로 돌려준다.",
)
async def preview_draft_certificate(
    request: DraftCertificateCreate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target_user = get_existing_target_user(db, request.user_id)
    storage = OCIObjectStorageService()
    pdf_bytes = CertificateService.preview_draft(
        db, target_user=target_user, options=request.options, storage=storage
    )
    return FastAPIResponse(content=pdf_bytes, media_type="application/pdf")


@router.post(
    "/drafts",
    response_model=Response[CertificateDetail],
    summary="활동증명서 초안 생성 (운영진)",
    description=(
        "운영진이 지정 회원의 활동증명서 초안을 생성한다. 발행번호는 회장이 "
        "오프라인 서명 원본을 등록할 때 부여된다."
    ),
)
async def create_draft_certificate(
    request: DraftCertificateCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target_user = get_existing_target_user(db, request.user_id)
    storage = OCIObjectStorageService()
    certificate = CertificateService.create_draft(
        db,
        actor=admin,
        target_user=target_user,
        options=request.options,
        storage=storage,
    )
    return Response(ok=True, data=to_detail(certificate))


# =====================================================================
# President term administration (admin)
# =====================================================================
@router.post(
    "/president-terms",
    response_model=Response[PresidentTermDetail],
    summary="회장 임명 (운영진)",
    description="새 회장을 임명한다. 기존에 열려 있는 임기가 있으면 같은 트랜잭션에서 자동 종료된다.",
)
async def appoint_president(
    request: PresidentTermCreate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    term = PresidentService.appoint(
        db, user_id=request.user_id, started_at=request.started_at
    )
    return Response(ok=True, data=PresidentTermDetail.model_validate(term))


@router.get(
    "/president-terms/current",
    response_model=Response[list[PresidentTermDetail]],
    summary="현직 회장 목록 조회 (운영진)",
    description=(
        "현재 열려 있는(ended_at IS NULL) 회장 임기를 전부 조회한다. "
        "(임시 비활성화 상태) 동시에 여러 명이 현직일 수 있어 리스트로 반환한다."
    ),
)
async def get_current_president(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    terms = PresidentService.get_current_terms(db)
    return Response(
        ok=True,
        data=[PresidentTermDetail.model_validate(term) for term in terms],
    )


# =====================================================================
# Staff / admin -- history (registered LAST: `/{certificate_id}` is a bare
# 1-segment variable path and must not shadow any literal-segment GET route
# above it, e.g. `/me`, `/signature/me`, `/president-terms/current`).
# =====================================================================
@router.get(
    "",
    response_model=Response[CursorPage[CertificateHistoryItem]],
    summary="활동증명서 발급 이력 (운영진)",
    description="전체 활동증명서 발급 이력을 조회한다. 원본 미등록(ORIGINAL_PENDING) 건이 먼저, 그다음 최신순.",
)
async def list_certificate_history(
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    items, next_cursor = CertificateService.list_history(db, cursor=cursor, limit=limit)
    return Response(
        ok=True,
        data=CursorPage(
            items=[CertificateHistoryItem.model_validate(item) for item in items],
            next_cursor=next_cursor,
        ),
    )


@router.get(
    "/{certificate_id}",
    response_model=Response[CertificateDetail],
    summary="활동증명서 발급 이력 상세 (운영진)",
    description="특정 활동증명서의 상세 정보와 처리 이력을 조회한다.",
)
async def get_certificate_history_detail(
    certificate_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    certificate = get_existing_certificate(db, certificate_id)
    return Response(ok=True, data=to_detail(certificate))
