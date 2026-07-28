"""활동증명서(certificate of activities) 도메인 서비스.

`CertificateService` / `SignatureService` 두 클래스로 나뉘며, 모두
`app/services/user.py`와 같은 스타일로 db 세션을 첫 인자로 받는
`@staticmethod`로 구성된다. 현직 회장 조회(`_get_current_president`)는
`User.is_president`를 직접 보는 모듈 레벨 헬퍼로, `is_president` 자체는
운영팀 프로젝트 리더십에서 파생된다 (`ProjectService.sync_operations_roles`).

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
    CertificateAlreadyIssuedError,
    CertificateExpiredError,
    CertificateRenderFailedError,
    InvalidCertificateOptionsError,
    InvalidCursorError,
    PresidentNotFoundError,
    PresidentSignatureNotFoundError,
    SignatureUploadConflictError,
)
from app.models import Certificate, CertificateEvent, CertificateSignature, User
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

# `list_history`는 (priority, created_at, id) 3중 키를 커서로 쓴다.
# `created_at`은 `int(time.time())`로 초 단위까지만 기록되므로, 같은 초에
# 여러 증명서가 생성되면 (priority, created_at)만으로는 동순위(tie)가 생긴다.
# id를 세 번째 키로 추가하지 않으면 그 tie가 페이지 경계에 걸릴 때 커서 술어
# `created_at < cursor_created_at`가 동순위 행 전체를 건너뛰어 목록에서
# 통째로 누락된다.
_HISTORY_CURSOR_CREATED_OFFSET = 10**13  # (priority, created_at) — epoch(초)보다 크다.
_HISTORY_CURSOR_ID_OFFSET = (
    10**10
)  # > INT 컬럼 최댓값(2,147,483,647), 위 _ME_CURSOR_ID_OFFSET과 동일한 근거.


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


def _encode_history_cursor(priority: int, created_at: int, certificate_id: int) -> str:
    # 이 packing이 정확히 왕복하려면 각 필드가 자신의 packing radix보다
    # 작아야 한다(위 `_HISTORY_CURSOR_ID_OFFSET`/`_HISTORY_CURSOR_CREATED_OFFSET`
    # 선언부의 경계 가정 참고). 가정이 깨지면 초과분이 상위 필드로 넘어가
    # (priority, created_at, id) 정렬 순서를 조용히 오염시키므로(스킵/중복),
    # 침묵 오염 대신 여기서 바로 크게 실패시킨다.
    if certificate_id >= _HISTORY_CURSOR_ID_OFFSET:
        raise ValueError(
            "history cursor packing bound violated: "
            f"certificate_id={certificate_id} >= _HISTORY_CURSOR_ID_OFFSET="
            f"{_HISTORY_CURSOR_ID_OFFSET}"
        )
    if created_at >= _HISTORY_CURSOR_CREATED_OFFSET:
        raise ValueError(
            "history cursor packing bound violated: "
            f"created_at={created_at} >= _HISTORY_CURSOR_CREATED_OFFSET="
            f"{_HISTORY_CURSOR_CREATED_OFFSET}"
        )
    major = priority * _HISTORY_CURSOR_CREATED_OFFSET + created_at
    return str(major * _HISTORY_CURSOR_ID_OFFSET + certificate_id)


def _decode_history_cursor(cursor: str) -> tuple[int, int, int]:
    major, certificate_id = divmod(_parse_cursor_int(cursor), _HISTORY_CURSOR_ID_OFFSET)
    priority, created_at = divmod(major, _HISTORY_CURSOR_CREATED_OFFSET)
    return priority, created_at, certificate_id


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
            # 깔끔한 409 도메인 에러로 변환한다 (그대로 두면 구조화되지
            # 않은 500이 된다).
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


def _get_current_president(db: Session) -> User | None:
    """현직 회장 = `is_president=True`인 유저.

    `is_president`는 운영팀 프로젝트 리더십에서 파생되며
    (`ProjectService.sync_operations_roles`), 인수인계 중 일시적으로 여러
    명이 동시에 `is_president=True`일 수 있다 -- `.first()`는 그중 임의의
    한 명을 반환할 뿐, "그 한 명"이 유일한 현직이라는 보장은 없다."""
    return db.query(User).filter(User.is_president.is_(True)).first()


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

        president = _get_current_president(db)
        if president is None:
            raise PresidentNotFoundError()

        signature = SignatureService.get_by_user(db, president.id)
        if signature is None:
            raise PresidentSignatureNotFoundError()

        return president.name, _signature_data_uri(storage, signature)

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
    def _purge_content(db: Session, certificate: Certificate, storage) -> None:
        """원본 PDF/스냅샷을 폐기한다 (`pdf_object_key`/`snapshot`을 NULL로,
        오브젝트 스토리지에서 실제 파일 삭제). `Certificate` row 자체(발급
        이력 메타데이터)는 감사 기록으로 남기고 지우지 않는다."""
        old_object_key = certificate.pdf_object_key
        certificate.pdf_object_key = None
        certificate.snapshot = None
        db.commit()
        if old_object_key:
            storage.delete_object(old_object_key)

    @staticmethod
    def ensure_not_expired(db: Session, certificate: Certificate, storage) -> None:
        """`expires_at`이 지난 증명서는 접근 시점에 원본을 폐기하고
        `CertificateExpiredError`를 던진다.

        이 프로젝트에는 별도 스케줄러/배치가 없어서, "90일 지나면 폐기"를
        만료 이후 첫 접근 시점에 지연 실행(lazy purge)하는 방식으로
        구현한다 — 그때까지 아무도 접근하지 않으면 원본이 그 순간까지는
        스토리지에 남아있을 수 있다. 정말로 접근 여부와 무관하게 정시에
        지우고 싶으면 `purge_all_expired`를 주기적으로 호출하는 배치가
        별도로 필요하다.
        """
        if certificate.expires_at is None or int(time.time()) < certificate.expires_at:
            return
        if certificate.pdf_object_key or certificate.snapshot is not None:
            CertificateService._purge_content(db, certificate, storage)
        raise CertificateExpiredError()

    @staticmethod
    def purge_all_expired(db: Session, storage) -> int:
        """만료됐지만 아직 원본이 안 지워진 증명서를 일괄 폐기한다.

        접근이 없으면 `ensure_not_expired`의 지연 폐기가 절대 실행되지
        않으므로, 정시 폐기가 필요하면 이 메서드를 외부 스케줄러(cron 등)가
        주기적으로 호출해야 한다. 반환값은 이번 호출에서 실제로 폐기한
        건수.
        """
        now = int(time.time())
        candidates = (
            db.query(Certificate)
            .filter(
                Certificate.deleted_at.is_(None),
                Certificate.expires_at.isnot(None),
                Certificate.expires_at < now,
                Certificate.pdf_object_key.isnot(None),
            )
            .all()
        )
        for certificate in candidates:
            CertificateService._purge_content(db, certificate, storage)
        return len(candidates)

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

    @staticmethod
    def list_history(
        db: Session, *, cursor: str | None, limit: int
    ) -> tuple[list[Certificate], str | None]:
        """운영진용 발급 이력. ORIGINAL_PENDING 우선, 그다음 created_at DESC.

        `created_at`이 초 단위(`int(time.time())`)이므로 같은 초에 여러 건이
        생성되면 (priority, created_at)만으로는 동순위가 생긴다. id를 세 번째
        정렬/커서 키로 추가해 동순위 행이 페이지 경계에서 누락되지 않게 한다.

        정렬 우선순위는 파이썬 쪽 `case()` 식이 아니라 실제 컬럼인
        `Certificate.pending_priority`(생성 컬럼, ORIGINAL_PENDING이면 1)를
        사용한다 — `idx_certificates_history_priority`
        (pending_priority, created_at, id) 복합 인덱스가 이 정렬/커서 술어를
        그대로 커버하기 위함이다(`case()` 식으로는 인덱스가 이 쿼리 플랜에
        매칭될 수 없다).
        """
        priority = Certificate.pending_priority
        query = (
            db.query(Certificate)
            .options(joinedload(Certificate.user))
            .filter(Certificate.deleted_at.is_(None))
        )

        if cursor is not None:
            cursor_priority, cursor_created_at, cursor_id = _decode_history_cursor(
                cursor
            )
            query = query.filter(
                or_(
                    priority < cursor_priority,
                    and_(
                        priority == cursor_priority,
                        Certificate.created_at < cursor_created_at,
                    ),
                    and_(
                        priority == cursor_priority,
                        Certificate.created_at == cursor_created_at,
                        Certificate.id < cursor_id,
                    ),
                )
            )

        items = (
            query.order_by(
                priority.desc(), Certificate.created_at.desc(), Certificate.id.desc()
            )
            .limit(limit + 1)
            .all()
        )
        has_more = len(items) > limit
        page_items = items[:limit]
        next_cursor = None
        if has_more and page_items:
            last = page_items[-1]
            next_cursor = _encode_history_cursor(
                last.pending_priority, last.created_at, last.id
            )
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
        """kind=DRAFT: 운영진이 초안만 생성. issue_number는 아직 부여하지 않는다.

        여기서 렌더링되는 PDF에는 발행번호와 원본 확인 안내를 표시하지 않는다.
        PDF는 인쇄되어 회장이 오프라인으로 서명하는 실물 문서가 된다. 이 렌더
        결과(`_context`, 현재 폐기됨)는 어디에도 저장되지 않는다 — 알려진
        한계는 `register_original`의 docstring 참고
        (DIVERGENCE — needs sign-off).
        """
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

    @staticmethod
    def register_original(
        db: Session,
        *,
        president: User,
        certificate: Certificate,
        file_bytes: bytes,
        storage,
    ) -> Certificate:
        """회장이 오프라인 서명한 원본 PDF를 등록한다.

        이 시점에 issue_number가 부여되고 status가 ISSUED로 바뀐다. 업로드되는
        파일 자체가 이미 서명된 원본 스캔본이므로 시스템이 서명 이미지를 다시
        렌더링/임베드하지는 않는다 (signer=president면 이름만 스냅샷에 남긴다).

        호출자(`app.routes.certificates.get_existing_certificate`)가 이미
        조회해 둔 `certificate`는 락 없이 읽은 스냅샷이라 TOCTOU에 노출된다:
        같은 ORIGINAL_PENDING 건에 대한 두 개의 "/original" 요청이 거의
        동시에 들어오면 둘 다 이 스냅샷으로 DRAFT/ORIGINAL_PENDING 가드를
        통과하고, 각자 다른 issue_number/PDF를 업로드한 뒤 커밋해 나중 커밋이
        먼저 커밋을 덮어써 버릴 수 있다("이미 발급됨 -> 409" 보장이 동시성
        하에서 깨진다). 이를 막기 위해 여기서 `SELECT ... FOR UPDATE`로 행을
        다시 잠금 조회하고 그 최신 상태로 가드를 재검증한다: 두 트랜잭션이
        경합하면 하나는 이 조회에서 블록되고, 먼저 커밋한 트랜잭션이 풀리고
        나면 (락 조회는 스냅샷이 아닌 최신 커밋 데이터를 보므로) 이미
        ISSUED로 바뀐 상태를 보고 정상적으로 409를 받는다.

        `.populate_existing()`이 반드시 필요하다: 호출자가 넘긴 `certificate`
        인자가 이미 이 `db` 세션의 identity map에 올라가 있으므로(라우트의
        `get_existing_certificate`가 락 없이 한 번 조회해 둔 상태),
        `populate_existing()` 없이는 SQLAlchemy가 새로 온 (락으로 얻은) 행
        데이터로 그 identity-map 객체의 속성을 다시 채우지 않고 예전에 로드된
        (오래된) 파이썬 객체를 그대로 반환해 버린다 — 그러면 DB 레벨 락은
        정상적으로 블록되더라도 파이썬 쪽 `certificate.status` 체크는 여전히
        stale 값을 보게 되어 이 가드 재검증 자체가 무력화된다.

        알려진 한계 (DIVERGENCE — needs product/eng sign-off, 이 함수만으로는
        고칠 수 없음):

        아래 `build_context` 호출은 `target_user`의 *현재* DB 상태(자격
        이력/프로젝트/현직 회장 등)를 다시 읽어 `certificate.snapshot`에
        저장한다 — `create_draft`가 인쇄 시점에 실제로 렌더링한 컨텍스트
        (저장되지 않고 폐기됨)가 아니다. 오프라인 서명 대기 기간 중
        원본 데이터가 바뀌면, "발급 시점에 보여준 내용을 그대로 얼려서
        90일 원본 대조에 쓴다"는 `build_context`/`Certificate.snapshot`의
        문서화된 목적과 달리 스냅샷이 실제 서명된 실물과 다른 내용을
        담게 된다. 근본 수정은 초안 렌더 컨텍스트를 어딘가에 영속화해야
        하는데, `Certificate.snapshot`은 "발급 전에는 NULL"이 이미
        문서화된 불변식이라 `create_draft`에서 그대로 채우는 것도 그
        불변식을 깨는 별도의 제품 결정이다 — 별도 컬럼(예:
        `draft_snapshot`) 등 저장 형태를 정하는 sign-off가 필요하다.
        """
        certificate = (
            db.query(Certificate)
            .filter(Certificate.id == certificate.id, Certificate.deleted_at.is_(None))
            .with_for_update()
            .populate_existing()
            .first()
        )
        if certificate is None or (
            certificate.kind != CertificateKind.DRAFT
            or certificate.status != CertificateStatus.ORIGINAL_PENDING
        ):
            raise CertificateAlreadyIssuedError()

        options = CertificateOptions.model_validate(certificate.options)
        target_user = certificate.user

        issue_number = str(uuid4())
        issued_on = datetime.now(KST).date()
        president_name = (
            president.name if options.signer == CertificateSigner.PRESIDENT else None
        )
        context = build_context(
            db,
            target_user,
            options,
            issue_number=issue_number,
            issued_on=issued_on,
            president_name=president_name,
            signature_data_uri=None,
            advisor_name=options.advisor_name,
        )

        old_object_key = certificate.pdf_object_key
        object_key = f"certificates/{certificate.id}/{uuid4()}.pdf"
        storage.upload_bytes(object_key, file_bytes, "application/pdf")

        try:
            certificate.pdf_object_key = object_key
            certificate.issue_number = issue_number
            certificate.snapshot = context
            certificate.status = CertificateStatus.ISSUED
            certificate.verification_token_hash = _new_verification_token_hash()
            certificate.issued_at = int(time.time())
            certificate.expires_at = (
                certificate.issued_at + CERTIFICATE_VALIDITY_SECONDS
            )

            db.add(
                CertificateEvent(
                    certificate_id=certificate.id,
                    action=CertificateEventAction.ORIGINAL_REGISTERED,
                    actor_type=CertificateActorType.PRESIDENT,
                    actor_id=president.id,
                )
            )
            db.commit()
        except Exception:
            db.rollback()
            storage.delete_object(object_key)
            raise

        if old_object_key and old_object_key != object_key:
            storage.delete_object(old_object_key)

        return CertificateService.get(db, certificate.id)
