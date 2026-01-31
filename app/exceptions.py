class AppError(Exception):
    """Base application error"""

    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
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


class NoLeaderError(AppError):
    """No leader specified in project"""

    def __init__(
        self, message: str = "At least one leader is required when creating a project"
    ):
        super().__init__("NO_LEADER_IN_PROJECT", message, 400)
