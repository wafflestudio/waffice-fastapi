"""회장(president) / 서명(signature) API.

- President: 서명 등록/조회 (require_president).
- Staff/admin: 회장 임기 관리 (require_admin).

라우트 등록 순서 주의: 같은 HTTP 메서드에서 리터럴 세그먼트 경로(`/signature/me`,
`/president-terms/current`, ...)는 반드시 가변 경로(`/{certificate_id}`)보다
먼저 등록해야 Starlette가 잘못 매칭하지 않는다. (이 축소판에는 가변 경로가
없지만, 향후 활동증명서 라우트가 합류할 때를 대비해 순서를 그대로 유지한다.)
"""

from collections.abc import Callable
from uuid import uuid4

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.deps.auth import require_admin, require_president
from app.exceptions import InvalidSignatureFileError, SignatureFileTooLargeError
from app.models import User
from app.schemas import (
    PresidentTermCreate,
    PresidentTermDetail,
    Response,
    SignatureDetail,
)
from app.services import OCIObjectStorageService, PresidentService, SignatureService

router = APIRouter()

MAX_SIGNATURE_FILE_SIZE = 5 * 1024 * 1024


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
    response_model=Response[PresidentTermDetail | None],
    summary="현직 회장 조회 (운영진)",
    description="현재 열려 있는(ended_at IS NULL) 회장 임기를 조회한다.",
)
async def get_current_president(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    term = PresidentService.get_current(db)
    return Response(
        ok=True,
        data=PresidentTermDetail.model_validate(term) if term else None,
    )
