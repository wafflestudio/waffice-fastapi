"""활동증명서(certificate of activities) 렌더링 서비스.

`build_context`는 순수하게 DB를 읽어 Jinja2 템플릿에 넘길 컨텍스트 딕셔너리를
만든다 (이 딕셔너리는 JSON 직렬화 가능해야 하며, 그대로 `certificates.snapshot`
에 저장된다). `render_pdf`는 그 컨텍스트를 받아 PDF bytes를 만드는 순수 함수다.

WeasyPrint는 시스템 라이브러리(pango/cairo 등)에 의존하는 선택적 의존성이므로,
app/services/object_storage.py의 lazy `import oci` 패턴을 그대로 따라 함수
내부에서 지연 임포트한다 — WeasyPrint 시스템 라이브러리가 없는 macOS 개발 머신
에서도 이 모듈을 임포트하는 다른 코드(라우트 등)가 깨지지 않아야 한다.
"""

import os
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

KST = ZoneInfo("Asia/Seoul")

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)

_TEMPLATE_NAME = "certificate.html"

_MASKED_ISSUE_NUMBER = "XXXX"

_QUALIFICATION_LABELS = {
    "pending": "준회원 후보",
    "associate": "준회원",
    "regular": "정회원",
    "active": "활동회원",
}

_DISCIPLINE_SECTION_TITLE = "징계 의결의 주문, 이유, 의결일 및 징계 개시일"
_QUALIFICATION_SECTION_TITLE = "회원 자격 취득, 변동 및 상실의 각 기준일 및 사유"
_PROJECT_SECTION_TITLE = "구성원으로서 활동한 소속 프로젝트의 명칭, 기간 및 역할"
_EXECUTIVE_SECTION_TITLE = "임원 또는 집행부원으로서 활동한 기간 및 역할"

CERT_VERIFY_BASE_URL_ENV = "CERT_VERIFY_BASE_URL"
_DEFAULT_VERIFY_BASE_URL = "https://waffice.wafflestudio.com"

# 서명 잉크색(빨강). to_ink_signature_png의 기본 색.
SIGNATURE_INK_RGB = (196, 40, 34)


def _enum_value(value: Any) -> Any:
    """Enum 멤버든 순수 문자열이든 동일하게 다루기 위한 헬퍼."""
    return value.value if hasattr(value, "value") else value


def _format_epoch(ts: int | None) -> str | None:
    """Unix epoch(초) 정수를 KST 기준 'YYYY.MM.DD.' 문자열로 변환한다."""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=KST).strftime("%Y.%m.%d.")


def _format_date(value: date | None) -> str | None:
    """`Date` 컬럼 값을 'YYYY.MM.DD.' 문자열로 변환한다."""
    if value is None:
        return None
    return value.strftime("%Y.%m.%d.")


def _verify_base_url() -> str:
    return os.getenv(CERT_VERIFY_BASE_URL_ENV, _DEFAULT_VERIFY_BASE_URL).rstrip("/")


def _qualification_label(raw: Any) -> str:
    value = _enum_value(raw)
    return _QUALIFICATION_LABELS.get(value, value or "-")


def _build_qualification_rows(db, user) -> list[dict[str, str]]:
    """섹션 2: 회원 자격 취득, 변동 및 상실.

    합성 첫 행(회원 자격 취득, users.created_at) 다음에 `audit_logs`에서
    action=QUALIFICATION_CHANGED인 행들을 기준일(created_at) 오름차순으로
    이어붙인다. payload의 reason을 사유로 사용하되, 사유 저장 기능 도입 전
    생성된 이력처럼 reason이 없거나 빈 값이면 "-"로 채운다.
    """
    from app.models import AuditLog
    from app.models.enums import AuditAction

    rows: list[dict[str, str]] = [
        {
            "date": _format_epoch(user.created_at),
            "content": "회원 자격 취득",
            "reason": "-",
        }
    ]

    logs = (
        db.query(AuditLog)
        .filter(
            AuditLog.user_id == user.id,
            AuditLog.action == AuditAction.QUALIFICATION_CHANGED,
        )
        .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        .all()
    )
    for log in logs:
        payload = log.payload or {}
        from_label = _qualification_label(payload.get("from"))
        to_label = _qualification_label(payload.get("to"))
        raw_reason = payload.get("reason")
        reason = raw_reason.strip() if isinstance(raw_reason, str) else ""
        rows.append(
            {
                "date": _format_epoch(log.created_at),
                "content": f"{from_label} → {to_label}",
                "reason": reason or "-",
            }
        )
    return rows


def _build_project_rows(db, user) -> list[dict[str, str]]:
    """섹션 4: 구성원으로서 활동한 소속 프로젝트의 명칭, 기간 및 역할."""
    from sqlalchemy.orm import joinedload

    from app.models import UserActivity

    activities = (
        db.query(UserActivity)
        .options(joinedload(UserActivity.project))
        .filter(UserActivity.user_id == user.id)
        .order_by(UserActivity.start_date.asc(), UserActivity.id.asc())
        .all()
    )

    rows: list[dict[str, str]] = []
    for activity in activities:
        project = activity.project
        period = (
            f"{_format_epoch(activity.start_date) or '-'} ~ "
            f"{_format_epoch(activity.end_date) if activity.end_date is not None else '현재'}"
        )
        rows.append(
            {
                "name": project.name if project else "-",
                "period": period,
                "role": activity.position,
            }
        )
    return rows


def _build_executive_rows(db, user) -> list[dict[str, str]]:
    """섹션 5: 임원 또는 집행부원으로서 활동한 기간 및 역할.

    회장(is_president) 이력은 이제 운영팀 프로젝트 리더십에서 파생되므로
    (`ProjectService.sync_admin_team_roles`), 별도 이력 테이블 없이 운영팀
    프로젝트의 audit log(PROJECT_JOINED/PROJECT_ROLE_CHANGED/PROJECT_LEFT)를
    시간순으로 재생해 이 유저가 팀장(=회장)이었던 기간(들)을 복원한다.
    `ProjectMember.joined_at`/`left_at`만으로는 부족하다 -- 팀장에서 팀원으로
    강등되어도(=회장 임기 종료) 그 행의 left_at은 그대로 null이기 때문이다.
    """
    from app.models import AuditLog, Project
    from app.models.enums import AuditAction

    admin_team = db.query(Project).filter(Project.is_admin_team.is_(True)).first()
    if admin_team is None:
        return []

    events = (
        db.query(AuditLog)
        .filter(
            AuditLog.user_id == user.id,
            AuditLog.action.in_(
                [
                    AuditAction.PROJECT_JOINED,
                    AuditAction.PROJECT_ROLE_CHANGED,
                    AuditAction.PROJECT_LEFT,
                ]
            ),
        )
        .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        .all()
    )

    rows: list[dict[str, str]] = []
    period_start: int | None = None
    for event in events:
        payload = event.payload or {}
        if payload.get("project_id") != admin_team.id:
            continue

        if event.action == AuditAction.PROJECT_JOINED:
            if payload.get("role") == "leader":
                period_start = event.created_at
        elif event.action == AuditAction.PROJECT_ROLE_CHANGED:
            was_leader = payload.get("from_role") == "leader"
            now_leader = payload.get("to_role") == "leader"
            if now_leader and not was_leader:
                period_start = event.created_at
            elif was_leader and not now_leader and period_start is not None:
                rows.append(
                    {
                        "period": f"{_format_epoch(period_start)} ~ {_format_epoch(event.created_at)}",
                        "role": "회장",
                    }
                )
                period_start = None
        elif event.action == AuditAction.PROJECT_LEFT:
            if period_start is not None:
                rows.append(
                    {
                        "period": f"{_format_epoch(period_start)} ~ {_format_epoch(event.created_at)}",
                        "role": "회장",
                    }
                )
                period_start = None

    if period_start is not None:
        rows.append({"period": f"{_format_epoch(period_start)} ~ 현재", "role": "회장"})
    return rows


def build_context(
    db,
    user,
    options,
    *,
    issue_number: str | None,
    issued_on: date,
    president_name: str | None,
    signature_data_uri: str | None,
    advisor_name: str | None = None,
) -> dict[str, Any]:
    """활동증명서 렌더링 컨텍스트를 만든다 (순수 DB 읽기, 그 외 부수효과 없음).

    반환값은 JSON 직렬화 가능한 dict이며 그대로 `certificates.snapshot`에
    저장된다 (발급 시점에 보여준 내용을 그대로 얼려서 90일 원본 대조에 쓴다).

    `options`는 `CertificateOptions` 스키마(다른 레인에서 작성)의 인스턴스일
    수도, 같은 필드를 가진 임의의 객체/딕셔너리일 수도 있다 — 이 모듈은 그
    타입을 직접 임포트하지 않고 duck-typing으로 다룬다.
    """

    def _opt(name: str, default: Any = None) -> Any:
        if isinstance(options, dict):
            return options.get(name, default)
        return getattr(options, name, default)

    sections: list[dict[str, Any]] = []

    # 1. 기본 인적 사항 — 항상 포함.
    sections.append(
        {
            "number": len(sections) + 1,
            "title": "기본 인적 사항",
            "type": "personal",
            "data": {
                "name": user.name,
                "student_id": user.student_id or "-",
            },
        }
    )

    # 2. 회원 자격 취득, 변동 및 상실 — 선택.
    if _opt("include_qualification_history", False):
        sections.append(
            {
                "number": len(sections) + 1,
                "title": _QUALIFICATION_SECTION_TITLE,
                "type": "qualification",
                "rows": _build_qualification_rows(db, user),
            }
        )

    # 3. 징계 의결 — 항상 포함(선택 불가), 데이터 소스가 없으므로 항상 공란.
    sections.append(
        {
            "number": len(sections) + 1,
            "title": _DISCIPLINE_SECTION_TITLE,
            "type": "discipline",
            "rows": [],
        }
    )

    # 4. 소속 프로젝트 — 선택.
    if _opt("include_projects", False):
        sections.append(
            {
                "number": len(sections) + 1,
                "title": _PROJECT_SECTION_TITLE,
                "type": "projects",
                "rows": _build_project_rows(db, user),
            }
        )

    # 5. 임원/집행부 — 선택.
    if _opt("include_executive", False):
        sections.append(
            {
                "number": len(sections) + 1,
                "title": _EXECUTIVE_SECTION_TITLE,
                "type": "executive",
                "rows": _build_executive_rows(db, user),
            }
        )

    signer_type = _enum_value(_opt("signer", "president")) or "president"
    if signer_type == "advisor":
        signer = {
            "type": "advisor",
            "name": advisor_name or _opt("advisor_name") or "-",
            "signature_data_uri": None,
        }
    else:
        signer = {
            "type": "president",
            "name": president_name or "-",
            "signature_data_uri": signature_data_uri,
        }

    display_issue_number = issue_number or _MASKED_ISSUE_NUMBER

    return {
        "purpose": _opt("purpose", ""),
        "sections": sections,
        "signer": signer,
        "issue_number_display": display_issue_number,
        "issued_on_display": _format_date(issued_on),
        "verify_url": f"{_verify_base_url()}/verify/{display_issue_number}",
    }


def _block_remote_urls(url: str, timeout=10, ssl_context=None, http_headers=None):
    """WeasyPrint용 url_fetcher: `data:` URI만 허용한다.

    서명 이미지는 base64 data URI로 임베드되므로 원격 fetch가 전혀 필요 없다.
    템플릿/에셋이 오염되어 외부 URL을 참조하더라도 WeasyPrint가 그것을 가져오지
    못하도록(SSRF 방지) 막는다.
    """
    if not url.startswith("data:"):
        raise ValueError(f"Blocked non-data: URL fetch in certificate rendering: {url}")

    from weasyprint.urls import default_url_fetcher

    return default_url_fetcher(url, timeout=timeout, ssl_context=ssl_context)


def to_ink_signature_png(
    body: bytes, rgb: tuple[int, int, int] = SIGNATURE_INK_RGB
) -> bytes:
    """업로드된 서명 이미지를 '지정 색(기본 빨강) 잉크 + 투명 배경' PNG로 변환한다.

    회장이 올리는 서명은 보통 흰 배경 위 검은 획이라(JPEG 등 투명도가 없는
    포맷 포함) 그대로 겹쳐 찍으면 불투명한 흰 배경 박스가 증명서 글자를
    가린다. 여기서 휘도(밝기) 기반으로 밝은 배경 픽셀은 투명하게, 어두운 획
    픽셀은 rgb 색으로 칠한 PNG를 만들어 그 문제를 없애고 잉크색도 지정한다.
    입력이 이미 투명한 경우 투명 영역이 검게 해석돼 전부 칠해지는 것을 막기
    위해 먼저 흰색 배경에 합성한다. Pillow는 WeasyPrint의 의존성이라 이미
    설치돼 있으며, 이 모듈의 weasyprint lazy-import 관례를 그대로 따른다.
    """
    from io import BytesIO

    from PIL import Image

    src = Image.open(BytesIO(body))
    if src.mode in ("RGBA", "LA") or (src.mode == "P" and "transparency" in src.info):
        src = src.convert("RGBA")
        white_bg = Image.new("RGBA", src.size, (255, 255, 255, 255))
        src = Image.alpha_composite(white_bg, src)
    gray = src.convert("L")

    cutoff = 205
    span = cutoff * 0.72

    def _alpha(p: int) -> int:
        if p >= cutoff:
            return 0
        a = int((cutoff - p) * 255 / span)
        return 255 if a > 255 else a

    alpha = gray.point(_alpha)
    out = Image.new("RGBA", gray.size, rgb + (0,))
    out.putalpha(alpha)
    buf = BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def render_pdf(context: dict[str, Any]) -> bytes:
    """컨텍스트 딕셔너리로부터 활동증명서 PDF bytes를 렌더링한다 (순수 함수).

    "문서 Flat화"(위변조 방지): WeasyPrint는 AcroForm 같은 인터랙티브 폼
    필드나 첨부파일을 생성하지 않으므로, 별도 처리 없이도 비인터랙티브 PDF가
    나온다. 다만 이것은 "편집 불가능한 레이어가 없다"는 수준이지 픽셀
    래스터화까지 하는 진짜 flatten은 아니다 — 그 수준의 위변조 방지는 이번
    PR의 범위 밖이다.
    """
    try:
        from weasyprint import HTML
    except ImportError as exc:
        from app.exceptions import CertificateRenderFailedError

        raise CertificateRenderFailedError() from exc

    template = _jinja_env.get_template(_TEMPLATE_NAME)
    html_str = template.render(**context)

    try:
        return HTML(string=html_str, url_fetcher=_block_remote_urls).write_pdf()
    except Exception as exc:
        from app.exceptions import CertificateRenderFailedError

        raise CertificateRenderFailedError() from exc
