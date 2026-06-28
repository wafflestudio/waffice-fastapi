from enum import Enum


class Qualification(str, Enum):
    PENDING = "pending"
    ASSOCIATE = "associate"
    REGULAR = "regular"
    ACTIVE = "active"


class ProjectStatus(str, Enum):
    ACTIVE = "active"
    MAINTENANCE = "maintenance"
    ENDED = "ended"


class MemberRole(str, Enum):
    LEADER = "leader"
    MEMBER = "member"


class UserRole(str, Enum):
    MEMBER = "member"
    LEADER = "leader"
    ADMIN = "admin"
    ADMIN_AND_LEADER = "admin_and_leader"


class AuditAction(str, Enum):
    QUALIFICATION_CHANGED = "qualification_changed"
    ROLE_CHANGED = "role_changed"
    PROJECT_JOINED = "project_joined"
    PROJECT_LEFT = "project_left"
    PROJECT_ROLE_CHANGED = "project_role_changed"


class GraduationStatus(str, Enum):
    UNDERGRADUATE = "학부생"
    GRADUATED = "졸업생"
    LEAVE_OF_ABSENCE = "휴학생"
    GRADUATE_STUDENT = "대학원생"


class ActivityStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class NotificationChannel(str, Enum):
    EMAIL = "email"
    SMS = "sms"
    BOTH = "both"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
