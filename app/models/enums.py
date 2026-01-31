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


class HistoryAction(str, Enum):
    QUALIFICATION_CHANGED = "qualification_changed"
    ADMIN_GRANTED = "admin_granted"
    ADMIN_REVOKED = "admin_revoked"
    PROJECT_JOINED = "project_joined"
    PROJECT_LEFT = "project_left"
    PROJECT_ROLE_CHANGED = "project_role_changed"
