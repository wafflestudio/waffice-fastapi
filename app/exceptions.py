class AppError(Exception):
    """Base application error"""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        data: dict | None = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.data = data
        super().__init__(message)


class UnauthorizedError(AppError):
    """401 - Authentication required"""

    def __init__(self, message: str = "Authentication required"):
        super().__init__("UNAUTHORIZED", message, 401)


class ForbiddenError(AppError):
    """403 - Insufficient permissions"""

    def __init__(self, message: str = "Insufficient permissions"):
        super().__init__("FORBIDDEN", message, 403)


class NotFoundError(AppError):
    """404 - Resource not found"""

    def __init__(self, message: str = "Resource not found"):
        super().__init__("NOT_FOUND", message, 404)


class LastLeaderError(AppError):
    """Cannot remove the last leader from a project"""

    def __init__(self, message: str = "Cannot remove the last leader from project"):
        super().__init__("LAST_LEADER_CANNOT_BE_REMOVED", message, 400)


class CannotRemoveSelfError(AppError):
    """Cannot remove oneself from a project"""

    def __init__(self, message: str = "Cannot remove yourself from the project"):
        super().__init__("CANNOT_REMOVE_SELF", message, 400)


class InvalidQualificationError(AppError):
    """Invalid qualification value"""

    def __init__(
        self, message: str = "Invalid qualification value (cannot approve to pending)"
    ):
        super().__init__("INVALID_QUALIFICATION", message, 400)


class TemporaryMemberApprovalError(AppError):
    """Cannot approve a temporary (roster-imported) member"""

    def __init__(
        self,
        message: str = (
            "Cannot approve a temporary member. They must sign up "
            "(OAuth) and be linked to this record first."
        ),
    ):
        super().__init__("TEMPORARY_MEMBER_CANNOT_BE_APPROVED", message, 400)


class InvalidRosterFileError(AppError):
    """Uploaded roster file is not a valid .xlsx/.csv, or is missing a header column"""

    def __init__(self, message: str = "파일 양식이 올바르지 않습니다."):
        super().__init__("INVALID_ROSTER_FILE", message, 400)


class EmptyRosterError(AppError):
    """Roster file has a header but no data rows"""

    def __init__(self, message: str = "명부에 회원 데이터가 없습니다."):
        super().__init__("EMPTY_ROSTER", message, 422)


class RosterTooLargeError(AppError):
    """Roster exceeds the maximum allowed number of rows"""

    def __init__(self, message: str = "명부가 최대 2000행을 초과했습니다."):
        super().__init__("ROSTER_TOO_LARGE", message, 400)


class RosterFileTooLargeError(AppError):
    """Uploaded roster file exceeds the maximum byte size"""

    def __init__(self, message: str = "파일 용량이 너무 큽니다. (최대 5MB)"):
        super().__init__("ROSTER_FILE_TOO_LARGE", message, 413)


class InvalidProjectMemberFileError(AppError):
    """Project member file contains invalid headers or rows."""

    def __init__(self, errors: list[dict], message: str = "팀원 명단을 적용할 수 없습니다."):
        super().__init__(
            "INVALID_PROJECT_MEMBER_FILE",
            message,
            400,
            data={"errors": errors},
        )


class NoLeaderError(AppError):
    """No leader specified in project"""

    def __init__(
        self, message: str = "At least one leader is required when creating a project"
    ):
        super().__init__("NO_LEADER_IN_PROJECT", message, 400)


class InvalidAuthTokenError(AppError):
    """Invalid or expired auth token"""

    def __init__(self, message: str = "Invalid or expired auth token"):
        super().__init__("INVALID_AUTH_TOKEN", message, 400)


class UserNotRegisteredError(AppError):
    """User not found during signin (needs signup)"""

    def __init__(self, message: str = "User not found, please signup first"):
        super().__init__("USER_NOT_REGISTERED", message, 400)


class GoogleAccountAlreadyLinkedError(AppError):
    """Google account is already linked to another user"""

    def __init__(self, message: str = "Google account is already linked"):
        super().__init__("GOOGLE_ACCOUNT_ALREADY_LINKED", message, 409)


class EmailAlreadyInUseError(AppError):
    """Email is already used by another user"""

    def __init__(self, message: str = "Email is already in use"):
        super().__init__("EMAIL_ALREADY_IN_USE", message, 409)


class StudentIdAlreadyInUseError(AppError):
    """Student ID is already used by a registered user"""

    def __init__(self, message: str = "Student ID is already in use"):
        super().__init__("STUDENT_ID_ALREADY_IN_USE", message, 409)


class InvalidApprovalRequestError(AppError):
    """Invalid activity approval request"""

    def __init__(self, message: str = "Invalid approval request"):
        super().__init__("INVALID_APPROVAL_REQUEST", message, 400)


class NoEligibleReviewerError(AppError):
    """400 - No eligible reviewer exists"""

    def __init__(
        self,
        message: str = ("승인 가능한 사용자가 없습니다. " "승인 대상을 변경하거나 운영팀에 문의해주세요."),
    ):
        super().__init__("NO_ELIGIBLE_REVIEWER", message, 400)


class RequestAlreadyProcessedError(AppError):
    """Approval request has already been processed"""

    def __init__(self, message: str = "Request has already been processed"):
        super().__init__("REQUEST_ALREADY_PROCESSED", message, 400)


class ProjectHasPendingRequestsError(AppError):
    """409 - Project deletion is blocked by pending approval requests"""

    def __init__(
        self,
        message: str = "대기 중인 승인 요청을 처리한 후 프로젝트를 삭제해주세요.",
    ):
        super().__init__("PROJECT_HAS_PENDING_REQUESTS", message, 409)


class InvalidProfileImageError(AppError):
    """Invalid profile image content type"""

    def __init__(self, message: str = "Only jpeg, png, or webp images are allowed"):
        super().__init__("INVALID_PROFILE_IMAGE", message, 400)


class ProfileImageTooLargeError(AppError):
    """Profile image is too large"""

    def __init__(self, message: str = "Profile image must be 5MB or smaller"):
        super().__init__("PROFILE_IMAGE_TOO_LARGE", message, 413)


class ObjectStorageError(AppError):
    """Object storage operation failed"""

    def __init__(self, message: str = "Object storage operation failed"):
        super().__init__("OBJECT_STORAGE_ERROR", message, 502)


# === Certificate of activities (활동증명서) — president / signature ===
class NotPresidentError(AppError):
    """403 - Action requires the current president"""

    def __init__(self, message: str = "회장만 수행할 수 있는 기능입니다."):
        super().__init__("NOT_PRESIDENT", message, 403)


class InvalidSignatureFileError(AppError):
    """400 - Uploaded signature is not a valid PNG/JPEG/WebP image"""

    def __init__(self, message: str = "이미지 파일(PNG, JPG, WEBP)이 맞는지 확인해주세요."):
        super().__init__("INVALID_SIGNATURE_FILE", message, 400)


class SignatureFileTooLargeError(AppError):
    """413 - Uploaded signature exceeds the maximum byte size"""

    def __init__(self, message: str = "파일 용량이 너무 큽니다. (최대 5MB)"):
        super().__init__("SIGNATURE_FILE_TOO_LARGE", message, 413)


class PresidentAppointmentConflictError(AppError):
    """409 - Lost a race with another concurrent president appointment"""

    def __init__(self, message: str = "다른 회장 임명 요청과 충돌했습니다. 다시 시도해주세요."):
        super().__init__("PRESIDENT_APPOINTMENT_CONFLICT", message, 409)


class InvalidPresidentTermError(AppError):
    """400 - New president term's started_at is invalid (before the current
    term's start date, or in the future -- appointment takes effect
    immediately, so a future-dated started_at would grant/revoke
    `require_president` access ahead of the intended date)"""

    def __init__(
        self,
        message: str = "새 임기 시작일은 현직 회장의 임기 시작일보다 빠를 수 없습니다.",
    ):
        super().__init__("INVALID_PRESIDENT_TERM", message, 400)


class SignatureUploadConflictError(AppError):
    """409 - Lost a race with another concurrent signature upload/replace"""

    def __init__(self, message: str = "다른 서명 등록 요청과 충돌했습니다. 다시 시도해주세요."):
        super().__init__("SIGNATURE_UPLOAD_CONFLICT", message, 409)


class AssociateCannotIssueCertificateError(AppError):
    """403 - Associate-level members cannot issue certificates of activities"""

    def __init__(self, message: str = "준회원은 활동증명서를 발급받을 수 없습니다."):
        super().__init__("ASSOCIATE_CANNOT_ISSUE_CERTIFICATE", message, 403)


class PresidentNotFoundError(AppError):
    """409 - No current president is registered"""

    def __init__(self, message: str = "현재 등록된 회장이 없습니다. 운영팀에 문의해주세요."):
        super().__init__("PRESIDENT_NOT_FOUND", message, 409)


class PresidentSignatureNotFoundError(AppError):
    """409 - The current president has no registered signature"""

    def __init__(
        self,
        message: str = "회장의 서명을 찾을 수 없습니다. 운영팀에 에러를 신고해주세요!",
    ):
        super().__init__("PRESIDENT_SIGNATURE_NOT_FOUND", message, 409)


class InvalidCertificateOptionsError(AppError):
    """400 - Certificate options failed validation (message varies by cause)"""

    def __init__(self, message: str = "발급 옵션이 올바르지 않습니다."):
        super().__init__("INVALID_CERTIFICATE_OPTIONS", message, 400)


class CertificateRenderFailedError(AppError):
    """502 - PDF rendering failed"""

    def __init__(self, message: str = "활동증명서 생성에 실패했습니다."):
        super().__init__("CERTIFICATE_RENDER_FAILED", message, 502)


class CertificateNotFoundError(AppError):
    """404 - Certificate of activities not found"""

    def __init__(self, message: str = "활동증명서를 찾을 수 없습니다."):
        super().__init__("CERTIFICATE_NOT_FOUND", message, 404)


class CertificateExpiredError(AppError):
    """410 - Certificate's 90-day original-comparison window has passed; the
    original PDF/snapshot has been (or is being) purged"""

    def __init__(self, message: str = "만료된 활동증명서입니다. 원본이 폐기되었습니다."):
        super().__init__("CERTIFICATE_EXPIRED", message, 410)


class InvalidCursorError(AppError):
    """400 - Pagination cursor is malformed"""

    def __init__(self, message: str = "잘못된 페이지네이션 커서입니다."):
        super().__init__("INVALID_CURSOR", message, 400)


class InvalidCertificateFileError(AppError):
    """400 - Uploaded certificate original is not a valid PDF"""

    def __init__(self, message: str = ".pdf 파일이 맞는지 확인해주세요."):
        super().__init__("INVALID_CERTIFICATE_FILE", message, 400)


class CertificateFileTooLargeError(AppError):
    """413 - Uploaded certificate original exceeds the maximum byte size"""

    def __init__(self, message: str = "파일 용량이 너무 큽니다. (최대 10MB)"):
        super().__init__("CERTIFICATE_FILE_TOO_LARGE", message, 413)


class CertificateAlreadyIssuedError(AppError):
    """409 - Certificate has already been issued (or is not a pending draft)"""

    def __init__(self, message: str = "이미 발급이 완료된 활동증명서입니다."):
        super().__init__("CERTIFICATE_ALREADY_ISSUED", message, 409)
