"""회장(president) / 서명(signature) 도메인 서비스.

`SignatureService` / `PresidentService` 두 클래스로 나뉘며, 모두
`app/services/user.py`와 같은 스타일로 db 세션을 첫 인자로 받는
`@staticmethod`로 구성된다.

오브젝트 스토리지 업로드/다운로드는 라우트에서 만든 `OCIObjectStorageService`
인스턴스를 `storage` 인자로 주입받아 사용한다 (`app/routes/profile_image.py`가
라우트에서 직접 `OCIObjectStorageService()`를 만드는 것과 같은 관례를 따르며,
테스트가 `app.routes.certificates.OCIObjectStorageService`를 monkeypatch할 수
있도록 하기 위함이다).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.exceptions import (
    InvalidPresidentTermError,
    NotFoundError,
    PresidentAppointmentConflictError,
    SignatureUploadConflictError,
)
from app.models import CertificateSignature, PresidentTerm
from app.services.user import UserService


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
            raise InvalidPresidentTermError(
                "임기 시작일은 오늘보다 미래일 수 없습니다 (임명은 즉시 발효됩니다)."
            )

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
