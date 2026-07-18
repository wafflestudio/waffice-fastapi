from datetime import date

from pydantic import BaseModel, Field

from app.schemas.user import UserBrief


# === Request ===
class PresidentTermCreate(BaseModel):
    """회장 임명 요청 바디. 기존에 열려 있는 임기가 있으면 자동으로 종료된다."""

    user_id: int = Field(description="새로 회장으로 임명할 회원 ID")
    started_at: date = Field(description="임기 시작일", examples=["2026-01-01"])


# === Response ===
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
