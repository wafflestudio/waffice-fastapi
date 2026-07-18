from datetime import date

from pydantic import BaseModel, Field

from app.models.enums import (
    CertificateActorType,
    CertificateEventAction,
    CertificateKind,
    CertificateSigner,
    CertificateStatus,
)
from app.schemas.user import UserBrief


# === Options (shared by preview/self-issue/draft) ===
class CertificateOptions(BaseModel):
    """활동증명서 발급 옵션.

    섹션 3(징계 의결)은 규정상 항상 포함되며 선택 불가하므로 별도 필드가 없다.
    signer=advisor(지도교수 서명)는 초안(DRAFT) 발급에서만 허용되며, 이 제약은
    옵션의 사용 맥락(본인 발급 vs 초안)에 따라 달라지므로 스키마가 아닌
    서비스 계층(`CertificateService`)에서 검증한다.
    """

    signer: CertificateSigner = Field(
        default=CertificateSigner.PRESIDENT,
        description=(
            "서명자. 'president'(회장) 또는 'advisor'(지도교수). "
            "지도교수 서명은 운영진이 생성하는 초안(DRAFT) 발급에서만 허용된다."
        ),
    )
    advisor_name: str | None = Field(
        default=None,
        max_length=100,
        description="지도교수 성함. signer=advisor일 때만 사용되며 그 경우 필수.",
        examples=["서진욱"],
    )
    purpose: str = Field(
        min_length=1,
        max_length=200,
        description="발급 용도",
        examples=["대학원 진학 제출용"],
    )
    include_qualification_history: bool = Field(
        default=False,
        description="섹션 2(회원 자격 취득, 변동 및 상실의 각 기준일 및 사유) 포함 여부",
    )
    include_projects: bool = Field(
        default=False,
        description="섹션 4(구성원으로서 활동한 소속 프로젝트의 명칭, 기간 및 역할) 포함 여부",
    )
    include_executive: bool = Field(
        default=False,
        description="섹션 5(임원 또는 집행부원으로서 활동한 기간 및 역할) 포함 여부",
    )


# === Request ===
class DraftCertificateCreate(BaseModel):
    """운영진이 활동증명서 초안을 생성/미리보기할 때의 요청 바디."""

    user_id: int = Field(description="발급 대상 회원 ID")
    options: CertificateOptions


class PresidentTermCreate(BaseModel):
    """회장 임명 요청 바디. 기존에 열려 있는 임기가 있으면 자동으로 종료된다."""

    user_id: int = Field(description="새로 회장으로 임명할 회원 ID")
    started_at: date = Field(description="임기 시작일", examples=["2026-01-01"])


# === Response ===
class CertificateEventItem(BaseModel):
    """활동증명서 처리 이력(append-only) 한 건."""

    id: int = Field(description="이력 항목 ID")
    action: CertificateEventAction = Field(
        description=(
            "처리 종류: 'applied'(신청), 'issued'(발급 완료), "
            "'draft_created'(초안 생성), 'original_registered'(원본 등록)"
        )
    )
    actor_type: CertificateActorType = Field(
        description="처리 주체 구분: 'applicant' | 'system' | 'president' | 'admin'"
    )
    actor: UserBrief | None = Field(description="처리한 사용자. 시스템이 자동 처리한 경우 null")
    created_at: int = Field(description="처리 일시 (Unix epoch)")

    model_config = {"from_attributes": True}


class CertificateDetail(BaseModel):
    """활동증명서 상세."""

    id: int = Field(description="증명서 ID")
    kind: CertificateKind = Field(description="'self'(본인 발급) | 'draft'(초안 생성)")
    status: CertificateStatus = Field(description="발급 상태")
    user: UserBrief = Field(description="발급 대상 회원")
    requested_by: UserBrief | None = Field(description="신청자/초안 생성자. SELF 발급은 본인과 동일")
    options: CertificateOptions = Field(description="발급 시 선택한 옵션")
    issue_number: str | None = Field(description="발행번호. 발급 확정 전에는 null")
    issued_at: int | None = Field(description="발급 일시 (Unix epoch). 미발급 시 null")
    expires_at: int | None = Field(
        description="원본 대조 유효기한 (발급일 + 90일, Unix epoch). 미발급 시 null"
    )
    created_at: int = Field(description="신청/생성 일시 (Unix epoch)")
    updated_at: int = Field(description="마지막 수정 일시 (Unix epoch)")
    events: list[CertificateEventItem] = Field(
        default_factory=list, description="처리 이력 (오래된 순)"
    )

    model_config = {"from_attributes": True}


class CertificateSummary(BaseModel):
    """내가 신청/발급받은 활동증명서 목록 항목 (GET /certificates/me)."""

    id: int = Field(description="신청 번호 (증명서 ID)")
    kind: CertificateKind = Field(description="'self'(본인 발급) | 'draft'(초안 생성)")
    status: CertificateStatus = Field(
        description="처리 상태: 'issued'(발급 완료) | 'original_pending'(원본 미등록)"
    )
    issue_number: str | None = Field(description="발행번호. 발급 완료 전에는 null")
    created_at: int = Field(description="신청 일시 (Unix epoch)")
    issued_at: int | None = Field(description="발급 일시 (Unix epoch). 미발급 시 null")

    model_config = {"from_attributes": True}


class SignatureDetail(BaseModel):
    """회장 서명 등록 정보."""

    id: int = Field(description="서명 등록 ID")
    user_id: int = Field(description="회장(사용자) ID")
    created_at: int = Field(description="최초 등록 일시 (Unix epoch)")
    updated_at: int = Field(description="마지막 교체 일시 (Unix epoch)")

    model_config = {"from_attributes": True}


class PresidentTermDetail(BaseModel):
    """회장 임기."""

    id: int = Field(description="임기 ID")
    user: UserBrief = Field(description="회장")
    started_at: date = Field(description="임기 시작일")
    ended_at: date | None = Field(description="임기 종료일. 현직이면 null")
    created_at: int = Field(description="레코드 생성 일시 (Unix epoch)")
    updated_at: int = Field(description="마지막 수정 일시 (Unix epoch)")

    model_config = {"from_attributes": True}
