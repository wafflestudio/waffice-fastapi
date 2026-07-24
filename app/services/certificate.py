"""활동증명서(certificate of activities) 도메인 서비스.

`CertificateService` / `SignatureService` / `PresidentService` 세 클래스로 나뉘며,
모두 `app/services/user.py`와 같은 스타일로 db 세션을 첫 인자로 받는
`@staticmethod`로 구성된다.

오브젝트 스토리지 업로드/다운로드는 라우트에서 만든 `OCIObjectStorageService`
인스턴스를 `storage` 인자로 주입받아 사용한다 (`app/routes/profile_image.py`가
라우트에서 직접 `OCIObjectStorageService()`를 만드는 것과 같은 관례를 따르며,
테스트가 `app.routes.certificates.OCIObjectStorageService`를 monkeypatch할 수
있도록 하기 위함이다).
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.exceptions import (
    AssociateCannotIssueCertificateError,
    CertificateRenderFailedError,
    InvalidCertificateOptionsError,
    InvalidCursorError,
    InvalidPresidentTermError,
    NotFoundError,
    PresidentAppointmentConflictError,
    PresidentNotFoundError,
    PresidentSignatureNotFoundError,
    SignatureUploadConflictError,
)
from app.models import (
    Certificate,
    CertificateEvent,
    CertificateSignature,
    PresidentTerm,
    User,
)
from app.models.enums import (
    CertificateActorType,
    CertificateEventAction,
    CertificateKind,
    CertificateSigner,
    CertificateStatus,
    Qualification,
)
from app.schemas.certificate import CertificateOptions
from app.services.certificate_render import (
    KST,
    build_context,
    render_pdf,
    to_ink_signature_png,
)
from app.services.user import UserService

# 발급 후 원본 대조 유효기한 (90일).
CERTIFICATE_VALIDITY_SECONDS = 90 * 24 * 3600

# --- 커서 인코딩 -------------------------------------------------------------
# 복합 정렬 키 (created_at, id)를 단일 정수로 인코딩한다. `OFFSET`이 id의
# 최댓값보다 크기만 하면 `value` 기준 내림차순 정렬이 `(created_at, id)`
# 사전식 내림차순 정렬과 동치이고, `value < cursor_value` 술어도 복합 술어
# `(created_at < cp) OR (created_at = cp AND id < ip)`와 그대로 동치가 된다.
#
# 이 정수는 JS `Number`의 안전 정수 범위(2**53 - 1)를 쉽게 넘어선다.
# `CursorPage.next_cursor`가 `int | str | None`으로 str도 허용하므로
# (app/schemas/common.py), 이 값을 JSON 정수로 내려보내지 않고 **10진수
# 문자열**로 인코딩한다 — 자리수 그대로 문자열로 왕복하면 JS 클라이언트가
# `JSON.parse`로 파싱해도 정밀도 손실 없이 그대로 보존된다.
#
# `Certificate.id`는 `Integer`(MySQL `INT`, signed 32-bit) 컬럼이라 이론상
# 2**31 - 1(2,147,483,647)까지 들어갈 수 있다. `OFFSET`이 그 값보다 작으면
# `id >= OFFSET`인 순간부터 `divmod`가 (created_at, id)가 아닌 엉뚱한 쌍으로
# 디코드되어 `value < cursor_value` 술어가 더 이상 원래의 복합 술어와
# 동치가 아니게 된다 -- 반드시 컬럼이 가질 수 있는 최댓값보다 커야 한다.
_ME_CURSOR_ID_OFFSET = 10**10  # > INT 컬럼 최댓값(2,147,483,647).


def _parse_cursor_int(cursor: str) -> int:
    """커서 문자열을 음이 아닌 정수로 파싱한다. 형식이 잘못되면 400."""
    try:
        value = int(cursor)
    except (TypeError, ValueError):
        raise InvalidCursorError() from None
    if value < 0:
        raise InvalidCursorError()
    return value


def _encode_cursor(major: int, minor: int, offset: int) -> str:
    return str(major * offset + minor)


def _decode_cursor(cursor: str, offset: int) -> tuple[int, int]:
    return divmod(_parse_cursor_int(cursor), offset)


def _new_verification_token_hash() -> str:
    """검증용 토큰의 sha256 해시. 원본 토큰 자체는 저장하지 않는다.

    공개 /verify 엔드포인트 자체는 이번 PR의 범위 밖이며, 이후 PR에서 이
    해시를 사용해 토큰을 검증할 수 있도록 값만 저장해 둔다.
    """
    token = secrets.token_urlsafe(32)
    return hashlib.sha256(token.encode()).hexdigest()


def _signature_data_uri(storage, signature: CertificateSignature) -> str:
    """서명 PNG를 base64 data URI로 만든다.

    `to_ink_signature_png`는 업로드 당시 매직바이트 검사를 통과했더라도
    본문이 잘렸거나 손상된 이미지에 대해서는 Pillow가 디코드 예외
    (`UnidentifiedImageError` 등)를 던질 수 있다. 여기서 잡지 않으면
    `render_pdf`의 예외 처리(weasyprint import/`write_pdf()`만 감쌈)보다
    앞서 실행되는 이 디코드 단계가 처리되지 않은 500을 그대로 노출하므로,
    다른 렌더링 실패와 동일하게 `CertificateRenderFailedError`(502)로
    변환한다.
    """
    body = storage.get_bytes(signature.object_key)
    try:
        png = to_ink_signature_png(body)
    except Exception as exc:
        raise CertificateRenderFailedError() from exc
    return "data:image/png;base64," + base64.b64encode(png).decode()


class SignatureService:
    @staticmethod
    def get_by_user(db: Session, user_id: int) -> CertificateSignature | None:
        """회장 1인당 서명은 최대 1개이므로 단순 조회."""
        return (
            db.query(CertificateSignature)
            .filter(CertificateSignature.user_id == user_id)
            .first()
        )

    @staticmethod
    def upsert(
        db: Session, *, user_id: int, object_key: str, storage
    ) -> CertificateSignature:
        """서명을 등록하거나 교체한다.

        호출자가 `object_key`에 이미 새 이미지를 업로드해 둔 상태여야 한다. DB
        commit이 실패하면 방금 업로드한 새 오브젝트를 best-effort로 삭제하고
        예외를 다시 던진다. commit이 성공하면 그제서야 옛 오브젝트를
        best-effort로 삭제한다("교체"이므로 이전 서명 파일이 남지 않도록).
        """
        existing = SignatureService.get_by_user(db, user_id)
        old_object_key = existing.object_key if existing else None

        if existing is not None:
            existing.object_key = object_key
            signature = existing
        else:
            signature = CertificateSignature(user_id=user_id, object_key=object_key)
            db.add(signature)

        try:
            db.commit()
        except IntegrityError:
            # 두 요청이 동시에 이 유저의 첫 서명을 등록하면 (existing이
            # 둘 다 None으로 보여) 둘 다 INSERT를 시도한다.
            # `uq_certificate_signatures_user_id` 유니크 제약이 실제
            # 무결성은 지켜주지만, 진 쪽은 `IntegrityError`를 던진다 --
            # `PresidentService.appoint`와 동일하게 깔끔한 409 도메인
            # 에러로 변환한다 (그대로 두면 구조화되지 않은 500이 된다).
            db.rollback()
            storage.delete_object(object_key)
            raise SignatureUploadConflictError() from None
        except Exception:
            db.rollback()
            storage.delete_object(object_key)
            raise

        db.refresh(signature)
        if old_object_key and old_object_key != object_key:
            storage.delete_object(old_object_key)
        return signature


class PresidentService:
    @staticmethod
    def get_current(db: Session) -> PresidentTerm | None:
        """현직 회장 임기 = ended_at IS NULL인 행 (DB 유니크 제약상 최대 1개)."""
        return (
            db.query(PresidentTerm)
            .options(joinedload(PresidentTerm.user))
            .filter(PresidentTerm.ended_at.is_(None))
            .first()
        )

    @staticmethod
    def appoint(db: Session, *, user_id: int, started_at: date) -> PresidentTerm:
        """새 회장을 임명한다.

        기존에 열려 있는 임기가 있으면 같은 트랜잭션에서 먼저 닫는다
        (ended_at = started_at). DB의 `uq_president_current` 유니크 제약이
        "열린 임기는 최대 1개"라는 불변식의 최종 방어선이다.

        두 관리자가 거의 동시에 임명을 요청하면, 둘 다 이 시점의 "같은 열린
        임기"(또는 둘 다 없음)를 보고 각자 새 임기를 추가하려 시도할 수 있다.
        `uq_president_current` 유니크 제약이 실제 데이터 무결성(열린 임기
        최대 1개)은 항상 지켜주지만, 진 쪽 트랜잭션은 `db.commit()`에서
        `IntegrityError`를 던진다 — `app/main.py`에는 `AppError` 핸들러만
        있으므로 이를 그대로 두면 구조화되지 않은 500으로 노출된다. 여기서
        잡아 깔끔한 409 도메인 에러로 변환한다.

        `get_current()`(및 이를 쓰는 `require_president`)는 `started_at`을
        보지 않고 `ended_at IS NULL`만으로 "현직"을 판단한다. 따라서
        `started_at`이 미래인 임명을 그대로 허용하면, 신임 회장은 의도한
        시작일보다 훨씬 전에 서명 업로드/조회 권한을 즉시 얻고 전임 회장은
        즉시 잃는다 — 접근 제어 경계가 임기 시작일과 어긋난다. 이 엔드포인트는
        "지금 임명"을 의미하므로 미래 날짜는 거부한다.

        `User.is_president`(main의 `feat: add user roles`가 추가한 별도
        boolean 컬럼, `has_admin_access = is_admin or is_president`가 참조함)를
        여기서 함께 갱신한다: 신임 회장은 True, 전임 회장(있다면)은 False로
        되돌린다. 이 동기화가 없으면 `president_terms`(우리 쪽 "현직 회장" 진실
        공급원)와 `User.is_president`가 서로 다른 사람을 가리킬 수 있어 —
        회장은 되었는데 `has_admin_access`가 안 켜지거나, 회장에서 물러난
        사람이 계속 관리자 권한을 갖는 상황이 생긴다.
        """
        target = UserService.get(db, user_id)
        if target is None:
            raise NotFoundError("대상 회원을 찾을 수 없습니다.")

        if started_at > date.today():
            raise InvalidPresidentTermError("임기 시작일은 오늘보다 미래일 수 없습니다 (임명은 즉시 발효됩니다).")

        current = PresidentService.get_current(db)
        if current is not None:
            if started_at < current.started_at:
                raise InvalidPresidentTermError()
            current.ended_at = started_at
            if current.user_id != user_id:
                current.user.is_president = False

        target.is_president = True

        term = PresidentTerm(user_id=user_id, started_at=started_at)
        db.add(term)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise PresidentAppointmentConflictError() from None
        db.refresh(term)
        return term


class CertificateService:
    @staticmethod
    def _validate_options(options: CertificateOptions, *, allow_advisor: bool) -> None:
        if options.signer != CertificateSigner.ADVISOR:
            return
        if not allow_advisor:
            raise InvalidCertificateOptionsError("지도교수님의 서명이 필요한 경우, 운영팀에 별도 문의해주세요.")
        if not (options.advisor_name and options.advisor_name.strip()):
            raise InvalidCertificateOptionsError("지도교수 서명을 선택한 경우 지도교수 성함을 입력해야 합니다.")

    @staticmethod
    def _ensure_target_eligible(target_user: User) -> None:
        """운영진이 지정한 대상 회원이 활동증명서 발급 자격(정회원/활동회원)인지 확인한다.

        본인 발급 경로(`/preview`)는 `require_certificate_eligible` 라우트
        의존성이 같은 규칙을 이미 강제하지만, 운영진 초안 경로
        (`/drafts`, `/drafts/preview`)는 대상 회원 존재 여부만 확인하고 자격
        등급은 보지 않았다 — 그대로 두면 준회원(이하) 대상으로도
        ORIGINAL_PENDING `Certificate`가 영구 저장돼 자격 규칙을 우회한다.
        """
        if target_user.qualification not in (
            Qualification.REGULAR,
            Qualification.ACTIVE,
        ):
            raise AssociateCannotIssueCertificateError()

    @staticmethod
    def _resolve_signer(
        db: Session, *, options: CertificateOptions, storage
    ) -> tuple[str | None, str | None]:
        """렌더링용 서명자 정보를 구한다.

        signer=advisor는 이미지가 없으므로 (None, None)을 돌려주고, 템플릿은
        `options.advisor_name`을 직접 사용한다. signer=president는 현직 회장과
        등록된 서명 PNG를 조회해 base64 data URI로 임베드할 값을 만든다.
        """
        if options.signer == CertificateSigner.ADVISOR:
            return None, None

        term = PresidentService.get_current(db)
        if term is None:
            raise PresidentNotFoundError()

        signature = SignatureService.get_by_user(db, term.user_id)
        if signature is None:
            raise PresidentSignatureNotFoundError()

        return term.user.name, _signature_data_uri(storage, signature)

    @staticmethod
    def _render(
        db: Session,
        *,
        target_user: User,
        options: CertificateOptions,
        storage,
        issue_number: str | None,
        issued_on: date,
    ) -> tuple[bytes, dict]:
        president_name, signature_data_uri = CertificateService._resolve_signer(
            db, options=options, storage=storage
        )
        context = build_context(
            db,
            target_user,
            options,
            issue_number=issue_number,
            issued_on=issued_on,
            president_name=president_name,
            signature_data_uri=signature_data_uri,
            advisor_name=options.advisor_name,
        )
        pdf_bytes = render_pdf(context)
        return pdf_bytes, context

    # === Read ===
    @staticmethod
    def get(db: Session, certificate_id: int) -> Certificate | None:
        return (
            db.query(Certificate)
            .options(
                joinedload(Certificate.user),
                joinedload(Certificate.requested_by),
                joinedload(Certificate.events).joinedload(CertificateEvent.actor),
            )
            .filter(Certificate.id == certificate_id, Certificate.deleted_at.is_(None))
            .first()
        )

    @staticmethod
    def list_own(
        db: Session, *, user: User, cursor: str | None, limit: int
    ) -> tuple[list[Certificate], str | None]:
        """내 활동증명서 목록. created_at DESC, id DESC 순."""
        query = db.query(Certificate).filter(
            Certificate.user_id == user.id, Certificate.deleted_at.is_(None)
        )

        if cursor is not None:
            created_at, cert_id = _decode_cursor(cursor, _ME_CURSOR_ID_OFFSET)
            query = query.filter(
                or_(
                    Certificate.created_at < created_at,
                    and_(
                        Certificate.created_at == created_at,
                        Certificate.id < cert_id,
                    ),
                )
            )

        items = (
            query.order_by(Certificate.created_at.desc(), Certificate.id.desc())
            .limit(limit + 1)
            .all()
        )
        has_more = len(items) > limit
        page_items = items[:limit]
        next_cursor = None
        if has_more and page_items:
            last = page_items[-1]
            next_cursor = _encode_cursor(last.created_at, last.id, _ME_CURSOR_ID_OFFSET)
        return page_items, next_cursor

    # === Render-only (not persisted) ===
    @staticmethod
    def preview(
        db: Session, *, target_user: User, options: CertificateOptions, storage
    ) -> bytes:
        CertificateService._validate_options(options, allow_advisor=False)
        pdf_bytes, _context = CertificateService._render(
            db,
            target_user=target_user,
            options=options,
            storage=storage,
            issue_number=None,
            issued_on=datetime.now(KST).date(),
        )
        return pdf_bytes

    @staticmethod
    def preview_draft(
        db: Session, *, target_user: User, options: CertificateOptions, storage
    ) -> bytes:
        CertificateService._validate_options(options, allow_advisor=True)
        CertificateService._ensure_target_eligible(target_user)
        pdf_bytes, _context = CertificateService._render(
            db,
            target_user=target_user,
            options=options,
            storage=storage,
            issue_number=None,
            issued_on=datetime.now(KST).date(),
        )
        return pdf_bytes

    # === Issuance ===
    @staticmethod
    def issue_self(
        db: Session, *, user: User, options: CertificateOptions, storage
    ) -> Certificate:
        """kind=SELF: 신청 즉시 발급 완료. issue_number를 이 시점에 부여한다."""
        CertificateService._validate_options(options, allow_advisor=False)

        certificate = Certificate(
            user_id=user.id,
            requested_by_id=user.id,
            kind=CertificateKind.SELF,
            status=CertificateStatus.ISSUED,
            options=options.model_dump(mode="json"),
        )
        db.add(certificate)
        db.flush()  # id를 커밋 전에 확보 (아직 다른 트랜잭션에 보이지 않음)

        issue_number = str(uuid4())
        issued_on = datetime.now(KST).date()
        pdf_bytes, context = CertificateService._render(
            db,
            target_user=user,
            options=options,
            storage=storage,
            issue_number=issue_number,
            issued_on=issued_on,
        )

        # 업로드를 먼저 수행한 뒤 DB를 확정 커밋한다: 스토리지 업로드
        # 실패는 아무것도 커밋되지 않은 채 끝나야 하고, 업로드 후 커밋
        # 실패는 방금 올린 오브젝트를 best-effort로 삭제해야 "ISSUED인데
        # pdf_object_key가 NULL"인 상태가 생기지 않는다.
        object_key = f"certificates/{certificate.id}/{uuid4()}.pdf"
        storage.upload_bytes(object_key, pdf_bytes, "application/pdf")

        try:
            certificate.issue_number = issue_number
            certificate.snapshot = context
            certificate.pdf_object_key = object_key
            certificate.verification_token_hash = _new_verification_token_hash()
            certificate.issued_at = int(time.time())
            certificate.expires_at = (
                certificate.issued_at + CERTIFICATE_VALIDITY_SECONDS
            )

            db.add(
                CertificateEvent(
                    certificate_id=certificate.id,
                    action=CertificateEventAction.APPLIED,
                    actor_type=CertificateActorType.APPLICANT,
                    actor_id=user.id,
                )
            )
            db.add(
                CertificateEvent(
                    certificate_id=certificate.id,
                    action=CertificateEventAction.ISSUED,
                    actor_type=CertificateActorType.SYSTEM,
                    actor_id=None,
                )
            )
            db.commit()
        except Exception:
            db.rollback()
            storage.delete_object(object_key)
            raise

        return CertificateService.get(db, certificate.id)

    # === Draft creation (issuance itself is PR②③④) ===
    @staticmethod
    def create_draft(
        db: Session,
        *,
        actor: User,
        target_user: User,
        options: CertificateOptions,
        storage,
    ) -> Certificate:
        """kind=DRAFT: 운영진이 초안만 생성. issue_number는 아직 부여하지 않는다."""
        CertificateService._validate_options(options, allow_advisor=True)
        CertificateService._ensure_target_eligible(target_user)

        certificate = Certificate(
            user_id=target_user.id,
            requested_by_id=actor.id,
            kind=CertificateKind.DRAFT,
            status=CertificateStatus.ORIGINAL_PENDING,
            options=options.model_dump(mode="json"),
        )
        db.add(certificate)
        db.flush()

        pdf_bytes, _context = CertificateService._render(
            db,
            target_user=target_user,
            options=options,
            storage=storage,
            issue_number=None,
            issued_on=datetime.now(KST).date(),
        )

        object_key = f"certificates/{certificate.id}/{uuid4()}.pdf"
        storage.upload_bytes(object_key, pdf_bytes, "application/pdf")

        try:
            certificate.pdf_object_key = object_key
            db.add(
                CertificateEvent(
                    certificate_id=certificate.id,
                    action=CertificateEventAction.DRAFT_CREATED,
                    actor_type=CertificateActorType.ADMIN,
                    actor_id=actor.id,
                )
            )
            db.commit()
        except Exception:
            db.rollback()
            storage.delete_object(object_key)
            raise

        return (
            db.query(Certificate)
            .options(
                joinedload(Certificate.user),
                joinedload(Certificate.requested_by),
                joinedload(Certificate.events).joinedload(CertificateEvent.actor),
            )
            .filter(Certificate.id == certificate.id, Certificate.deleted_at.is_(None))
            .first()
        )
