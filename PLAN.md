# Waffice FastAPI 리팩토링 계획

SPEC.md 기준으로 전체 도메인 로직을 재구현하는 계획입니다.

---

## Phase 0: 기존 코드 정리

### Task 0.1: 기존 파일 삭제
- [ ] `app/models/` 내 모든 파일 삭제
- [ ] `app/schemas/` 내 모든 파일 삭제
- [ ] `app/controllers/` 내 모든 파일 삭제
- [ ] `app/services/` 내 모든 파일 삭제
- [ ] `app/routes/` 내 `user_route.py`, `project_route.py`, `userhist_route.py` 삭제
- [ ] `tests/` 내 기존 테스트 파일 삭제
- [ ] `alembic/versions/` 정리

---

## Phase 1: DB 스키마 설계

### 설계 원칙
- snake_case 일관성
- 간결하고 명확한 이름
- **모든 시간은 Unix Timestamp (BIGINT)** - timezone 독립적
- `*_at` suffix는 timestamp에만 사용
- `*_id` suffix는 FK에만 사용
- boolean은 `is_*` prefix

---

### Table: `users`

```sql
CREATE TABLE users (
    id              BIGINT PRIMARY KEY AUTO_INCREMENT,

    -- Auth
    google_id       VARCHAR(255) UNIQUE,
    email           VARCHAR(255) NOT NULL UNIQUE,

    -- Profile (required)
    name            VARCHAR(100) NOT NULL,
    generation      VARCHAR(20) NOT NULL DEFAULT '26',

    -- Status
    qualification   ENUM('pending', 'associate', 'regular', 'active') NOT NULL DEFAULT 'pending',
    is_admin        BOOLEAN NOT NULL DEFAULT FALSE,

    -- Profile (optional)
    phone           VARCHAR(20),
    affiliation     VARCHAR(200),
    bio             TEXT,
    avatar_url      VARCHAR(500),

    -- External links
    github_username VARCHAR(100),
    slack_id        VARCHAR(100),
    websites        JSON,  -- [{url, type, description?}]

    -- Timestamps (Unix)
    created_at      BIGINT NOT NULL,
    updated_at      BIGINT NOT NULL,
    deleted_at      BIGINT,

    INDEX idx_users_qualification (qualification),
    INDEX idx_users_is_admin (is_admin),
    INDEX idx_users_created_at (created_at)
);
```

---

### Table: `user_histories`

```sql
CREATE TABLE user_histories (
    id              BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id         BIGINT NOT NULL,
    actor_id        BIGINT,  -- 변경 수행자 (NULL이면 시스템)

    action          ENUM(
                        'qualification_changed',
                        'admin_granted',
                        'admin_revoked',
                        'project_joined',
                        'project_left',
                        'project_role_changed'
                    ) NOT NULL,

    payload         JSON NOT NULL,

    -- Timestamps (Unix) - 불변 데이터이므로 updated_at 없음
    created_at      BIGINT NOT NULL,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (actor_id) REFERENCES users(id) ON DELETE SET NULL,

    INDEX idx_histories_user_id (user_id),
    INDEX idx_histories_action (action),
    INDEX idx_histories_created_at (created_at)
);
```

---

### Table: `projects`

```sql
CREATE TABLE projects (
    id              BIGINT PRIMARY KEY AUTO_INCREMENT,

    name            VARCHAR(200) NOT NULL,
    description     TEXT,
    status          ENUM('active', 'maintenance', 'ended') NOT NULL DEFAULT 'active',

    started_at      DATE NOT NULL,
    ended_at        DATE,

    websites        JSON,  -- [{url, type, description?}]

    -- Timestamps (Unix)
    created_at      BIGINT NOT NULL,
    updated_at      BIGINT NOT NULL,
    deleted_at      BIGINT,

    INDEX idx_projects_status (status),
    INDEX idx_projects_created_at (created_at)
);
```

---

### Table: `project_members`

```sql
CREATE TABLE project_members (
    id              BIGINT PRIMARY KEY AUTO_INCREMENT,
    project_id      BIGINT NOT NULL,
    user_id         BIGINT NOT NULL,

    role            ENUM('leader', 'member') NOT NULL,
    position        VARCHAR(50),

    joined_at       DATE,
    left_at         DATE,  -- NULL = 현재 활성 멤버

    -- Timestamps (Unix)
    created_at      BIGINT NOT NULL,
    updated_at      BIGINT NOT NULL,

    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,

    INDEX idx_members_project (project_id),
    INDEX idx_members_user (user_id),
    INDEX idx_members_active (project_id, user_id, left_at)
);
```

---

### ERD 요약

```
users
├── id (PK)
├── google_id (UNIQUE), email (UNIQUE)
├── name, generation, qualification, is_admin
├── phone, affiliation, bio, avatar_url
├── github_username, slack_id, websites (JSON)
└── created_at, updated_at, deleted_at (Unix)

user_histories
├── id (PK)
├── user_id (FK), actor_id (FK, nullable)
├── action, payload (JSON)
└── created_at (Unix)

projects
├── id (PK)
├── name, description, status
├── started_at (DATE), ended_at (DATE)
├── websites (JSON)
└── created_at, updated_at, deleted_at (Unix)

project_members
├── id (PK)
├── project_id (FK), user_id (FK)
├── role, position
├── joined_at (DATE), left_at (DATE)
└── created_at, updated_at (Unix)
```

---

## Phase 2: Enum 정의

파일: `app/models/enums.py`

```python
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
```

---

## Phase 3: SQLAlchemy 모델

### Task 3.1: Base 모델
파일: `app/models/base.py`

```python
import time
from sqlalchemy import Column, BigInteger

class TimestampMixin:
    created_at = Column(BigInteger, nullable=False, default=lambda: int(time.time()))
    updated_at = Column(BigInteger, nullable=False, default=lambda: int(time.time()), onupdate=lambda: int(time.time()))

class SoftDeleteMixin:
    deleted_at = Column(BigInteger, nullable=True)
```

### Task 3.2: User 모델
파일: `app/models/user.py`

### Task 3.3: UserHistory 모델
파일: `app/models/user_history.py`

### Task 3.4: Project 모델
파일: `app/models/project.py`

### Task 3.5: ProjectMember 모델
파일: `app/models/project_member.py`

### Task 3.6: `__init__.py`
파일: `app/models/__init__.py`

---

## Phase 4: Pydantic 스키마

### Task 4.1: 공통
파일: `app/schemas/common.py`

```python
from pydantic import BaseModel
from typing import Generic, TypeVar

T = TypeVar("T")

class Response(BaseModel, Generic[T]):
    ok: bool = True
    data: T | None = None
    error: str | None = None
    message: str | None = None

class CursorPage(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: int | None = None  # created_at of last item

class Website(BaseModel):
    url: str
    type: str
    description: str | None = None
```

### Task 4.2: User 스키마
파일: `app/schemas/user.py`

```python
# === Request ===
class SignupRequest(BaseModel):
    name: str
    phone: str | None = None
    affiliation: str | None = None
    bio: str | None = None
    github_username: str | None = None

class ProfileUpdateRequest(BaseModel):
    phone: str | None = None
    affiliation: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    github_username: str | None = None
    slack_id: str | None = None
    websites: list[Website] | None = None

class UserUpdateRequest(ProfileUpdateRequest):
    """Admin용"""
    name: str | None = None
    qualification: Qualification | None = None
    is_admin: bool | None = None

class ApproveRequest(BaseModel):
    qualification: Qualification  # associate, regular, active만 허용 (pending 입력 시 INVALID_QUALIFICATION 에러)

# === Response ===
class UserBrief(BaseModel):
    id: int
    name: str
    email: str
    avatar_url: str | None

class UserDetail(BaseModel):
    id: int
    email: str
    name: str
    generation: str
    qualification: Qualification
    is_admin: bool
    phone: str | None
    affiliation: str | None
    bio: str | None
    avatar_url: str | None
    github_username: str | None
    slack_id: str | None
    websites: list[Website] | None
    created_at: int  # Unix timestamp

    model_config = {"from_attributes": True}
```

### Task 4.3: Project 스키마
파일: `app/schemas/project.py`

```python
# === Request ===
class MemberInput(BaseModel):
    user_id: int
    role: MemberRole
    position: str | None = None

class ProjectCreateRequest(BaseModel):
    name: str
    description: str | None = None
    status: ProjectStatus = ProjectStatus.ACTIVE
    started_at: date
    ended_at: date | None = None
    websites: list[Website] | None = None
    members: list[MemberInput]  # 최소 1명 leader 필수 (없으면 NO_LEADER_IN_PROJECT 에러)

class ProjectUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    status: ProjectStatus | None = None
    started_at: date | None = None
    ended_at: date | None = None
    websites: list[Website] | None = None

class MemberUpdateRequest(BaseModel):
    role: MemberRole | None = None
    position: str | None = None

# === Response ===
class MemberDetail(BaseModel):
    id: int
    user: UserBrief
    role: MemberRole
    position: str | None
    joined_at: date | None
    left_at: date | None

class ProjectBrief(BaseModel):
    id: int
    name: str
    status: ProjectStatus
    started_at: date
    created_at: int

class ProjectDetail(ProjectBrief):
    description: str | None
    ended_at: date | None
    websites: list[Website] | None
    members: list[MemberDetail]
```

### Task 4.4: History 스키마
파일: `app/schemas/history.py`

```python
class HistoryDetail(BaseModel):
    id: int
    action: HistoryAction
    payload: dict
    actor: UserBrief | None
    created_at: int  # Unix timestamp
```

### Task 4.5: Auth 스키마
파일: `app/schemas/auth.py`

```python
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class AuthStatus(BaseModel):
    status: Literal["new", "pending", "active"]
    user: UserDetail | None = None
```

### Task 4.6: Upload 스키마
파일: `app/schemas/upload.py`

```python
class PresignedUrlRequest(BaseModel):
    filename: str
    content_type: str

class PresignedUrlResponse(BaseModel):
    upload_url: str
    file_url: str
```

---

## Phase 5: API 엔드포인트

### 페이지네이션 규칙
- Cursor-based pagination
- `created_at` 기준 내림차순 정렬
- Query params: `cursor` (optional, Unix timestamp), `limit` (default: 20)
- Response: `CursorPage[T]` with `next_cursor`

```
Auth
────────────────────────────────────────────────────────
POST   /auth/google              OAuth 시작
GET    /auth/google/callback     OAuth 콜백
POST   /auth/signup              회원가입

Users - 본인
────────────────────────────────────────────────────────
GET    /users/me                 내 정보            [ALL]
PATCH  /users/me                 내 정보 수정        [ASSOCIATE+]
GET    /users/me/history         내 이력            [ALL]
GET    /users/me/projects        내 프로젝트         [REGULAR+]

Users - 관리
────────────────────────────────────────────────────────
GET    /users                    유저 목록 (cursor)  [ADMIN]
GET    /users/pending            가입대기 목록       [ADMIN]
GET    /users/{id}               유저 상세          [ADMIN]
PATCH  /users/{id}               유저 수정          [ADMIN]
DELETE /users/{id}               유저 삭제          [ADMIN]
POST   /users/{id}/approve       가입 승인          [ADMIN]
GET    /users/{id}/history       유저 이력          [ADMIN]

Projects
────────────────────────────────────────────────────────
GET    /projects                 목록 (cursor)      [REGULAR+]
POST   /projects                 생성              [ADMIN]
GET    /projects/{id}            상세              [REGULAR+]
PATCH  /projects/{id}            수정              [LEADER|ADMIN]
DELETE /projects/{id}            삭제              [ADMIN]

Project Members
────────────────────────────────────────────────────────
POST   /projects/{id}/members              추가    [LEADER|ADMIN]
PATCH  /projects/{id}/members/{user_id}    수정    [LEADER|ADMIN]
DELETE /projects/{id}/members/{user_id}    제거    [LEADER|ADMIN]

Upload
────────────────────────────────────────────────────────
POST   /upload/presigned-url     S3 URL 발급       [ASSOCIATE+]
```

### Task 5.1: Auth 라우트
파일: `app/routes/auth.py`

### Task 5.2: Users 라우트
파일: `app/routes/users.py`

### Task 5.3: Projects 라우트
파일: `app/routes/projects.py`

### Task 5.4: Upload 라우트
파일: `app/routes/upload.py`

---

## Phase 6: 서비스 레이어

### Task 6.1: UserService
파일: `app/services/user.py`

```python
class UserService:
    @staticmethod
    def get(db: Session, user_id: int) -> User | None
        """deleted_at IS NULL 조건 포함"""

    @staticmethod
    def get_by_google_id(db: Session, google_id: str) -> User | None

    @staticmethod
    def get_by_email(db: Session, email: str) -> User | None

    @staticmethod
    def list(db: Session, *, cursor: int | None = None, limit: int = 20) -> tuple[list[User], int | None]
        """cursor-based pagination, returns (items, next_cursor)"""

    @staticmethod
    def list_pending(db: Session) -> list[User]

    @staticmethod
    def create(db: Session, **data) -> User

    @staticmethod
    def update(db: Session, user: User, **data) -> User

    @staticmethod
    def delete(db: Session, user: User) -> None
```

### Task 6.2: HistoryService
파일: `app/services/history.py`

```python
class HistoryService:
    @staticmethod
    def log(db: Session, user_id: int, action: HistoryAction, payload: dict, actor_id: int | None = None) -> UserHistory

    @staticmethod
    def list_by_user(db: Session, user_id: int) -> list[UserHistory]
```

### Task 6.3: ProjectService
파일: `app/services/project.py`

```python
class ProjectService:
    @staticmethod
    def get(db: Session, project_id: int) -> Project | None

    @staticmethod
    def get_with_members(db: Session, project_id: int) -> Project | None

    @staticmethod
    def list(db: Session, *, cursor: int | None = None, limit: int = 20, status: ProjectStatus | None = None) -> tuple[list[Project], int | None]

    @staticmethod
    def list_by_user(db: Session, user_id: int) -> list[Project]

    @staticmethod
    def create(db: Session, **data) -> Project

    @staticmethod
    def update(db: Session, project: Project, **data) -> Project

    @staticmethod
    def delete(db: Session, project: Project) -> None
```

### Task 6.4: MemberService
파일: `app/services/member.py`

```python
class MemberService:
    @staticmethod
    def get_active(db: Session, project_id: int, user_id: int) -> ProjectMember | None

    @staticmethod
    def list_active(db: Session, project_id: int) -> list[ProjectMember]

    @staticmethod
    def count_leaders(db: Session, project_id: int) -> int

    @staticmethod
    def is_leader(db: Session, project_id: int, user_id: int) -> bool

    @staticmethod
    def add(db: Session, project_id: int, user_id: int, role: MemberRole, position: str | None, actor_id: int) -> ProjectMember
        """
        멤버 추가 (멱등성 보장)
        - 이미 활성 멤버면 기존 멤버 반환 (에러 없이)
        - 신규면 생성 + UserHistory에 project_joined 기록
        """

    @staticmethod
    def remove(db: Session, member: ProjectMember, actor_id: int) -> None
        """
        left_at 설정, UserHistory에 project_left 기록
        Raises:
            LastLeaderError: 마지막 팀장인 경우
            CannotRemoveSelfError: 자기 자신 제거 시도
        """

    @staticmethod
    def change(db: Session, member: ProjectMember, role: MemberRole | None, position: str | None, actor_id: int) -> ProjectMember
        """기존 멤버십 종료 → 새 멤버십 생성, UserHistory에 project_role_changed 기록"""
```

### Task 6.5: S3Service (Mock)
파일: `app/services/s3.py`

> **Note**: S3가 아직 준비되어 있지 않으므로 **Mock 구현**으로 진행.
> 실제 S3 연동은 인프라 준비 후 별도 작업.

```python
class S3Service:
    def generate_presigned_url(self, filename: str, content_type: str) -> dict[str, str]:
        """
        Mock 구현:
        - upload_url: 실제 업로드 불가, placeholder URL 반환
        - file_url: 예상되는 S3 URL 형식 반환

        TODO: S3 준비 후 boto3 실제 연동
        """
        mock_key = f"profiles/{uuid4()}/{filename}"
        return {
            "upload_url": f"https://mock-s3-upload.example.com/{mock_key}",
            "file_url": f"https://{settings.AWS_S3_BUCKET}.s3.amazonaws.com/{mock_key}"
        }
```

---

## Phase 7: 인증/인가

### Task 7.1: Dependencies
파일: `app/deps/auth.py`

```python
async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User

async def require_associate(user: User = Depends(get_current_user)) -> User
    """qualification != pending"""

async def require_regular(user: User = Depends(get_current_user)) -> User
    """qualification in (regular, active)"""

async def require_admin(user: User = Depends(get_current_user)) -> User
    """is_admin = True"""
```

### Task 7.2: Project Permission
파일: `app/deps/project.py`

```python
def require_leader_or_admin(project_id: int, user: User, db: Session) -> Project
```

---

## Phase 8: 에러 처리

### Task 8.1: Custom Exceptions
파일: `app/exceptions.py`

```python
class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code

# 정의된 에러
class UnauthorizedError(AppError): ...          # 401
class ForbiddenError(AppError): ...             # 403
class NotFoundError(AppError): ...              # 404
class LastLeaderError(AppError): ...            # LAST_LEADER_CANNOT_BE_REMOVED
class CannotRemoveSelfError(AppError): ...      # CANNOT_REMOVE_SELF
class InvalidQualificationError(AppError): ...  # INVALID_QUALIFICATION (approve 시 pending 입력 등)
class NoLeaderError(AppError): ...              # NO_LEADER_IN_PROJECT (프로젝트 생성 시 팀장 없음)
```

### Task 8.2: Exception Handler
파일: `app/main.py`

```python
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"ok": False, "error": exc.code, "message": exc.message}
    )
```

---

## Phase 9: main.py

### Task 9.1: 라우터 등록
파일: `app/main.py`

```python
from app.routes import auth, users, projects, upload

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(users.router, prefix="/users", tags=["Users"])
app.include_router(projects.router, prefix="/projects", tags=["Projects"])
app.include_router(upload.router, prefix="/upload", tags=["Upload"])
```

---

## Phase 10: 설정

### Task 10.1: 환경변수
`.env.example`:
```
# Database
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=
DB_NAME=waffice

# JWT
JWT_SECRET=your-secret-key
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440

# Google OAuth
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=

# S3 (현재 Mock - 인프라 준비 후 실제 값으로 교체)
AWS_S3_BUCKET=waffice-uploads
AWS_S3_REGION=ap-northeast-2
```

---

## Phase 11: 테스트

### Task 11.1: 서비스 테스트 (Unit)
`tests/services/`
- 각 서비스 메서드의 정상/에러 케이스 테스트
- Mock DB 사용

### Task 11.2: API 테스트 (Integration)
`tests/api/`
- 개별 엔드포인트 테스트
- 권한별 접근 제어 테스트

### Task 11.3: E2E 테스트 (Critical)
`tests/e2e/`

> **중요**: E2E 테스트를 통해 전체 플로우가 정상 동작하는지 반드시 검증해야 함.

**필수 E2E 시나리오:**

1. **회원가입 → 승인 플로우**
   ```
   OAuth 콜백 → signup (pending) → admin approve → 정회원 전환
   ```

2. **프로젝트 생성 → 멤버 관리 플로우**
   ```
   admin 프로젝트 생성 (with leader) → 멤버 추가 → 역할 변경 → 멤버 제거
   ```

3. **권한 체계 검증**
   ```
   pending 유저: 프로젝트 접근 시 403
   associate 유저: 프로젝트 접근 시 403
   regular 유저: 프로젝트 조회 성공
   leader: 프로젝트 수정 성공
   non-leader: 프로젝트 수정 시 403
   ```

4. **에러 케이스 검증**
   ```
   마지막 팀장 제거 시도 → LAST_LEADER_CANNOT_BE_REMOVED
   자기 자신 제거 시도 → CANNOT_REMOVE_SELF
   pending으로 approve 시도 → INVALID_QUALIFICATION
   leader 없이 프로젝트 생성 → NO_LEADER_IN_PROJECT
   ```

5. **멱등성 검증**
   ```
   같은 멤버 2번 추가 → 에러 없이 기존 멤버 반환
   같은 유저 2번 signup → 에러 없이 기존 유저 반환
   ```

6. **Soft Delete 검증**
   ```
   유저 삭제 후 조회 → NOT_FOUND
   프로젝트 삭제 후 조회 → NOT_FOUND
   삭제된 유저로 로그인 시도 → 적절한 에러
   ```

**테스트 환경:**
- TestClient (FastAPI)
- 테스트용 DB (SQLite in-memory 또는 별도 MySQL)
- JWT 토큰 fixture

---

## 권한 요약

| Level | Condition | Access |
|-------|-----------|--------|
| ALL | 로그인만 | `/users/me`, `/users/me/history` |
| ASSOCIATE+ | qualification ≠ pending | + 프로필 수정, 업로드 |
| REGULAR+ | regular or active | + 프로젝트 조회 |
| LEADER | 해당 프로젝트 팀장 | 프로젝트/멤버 수정 |
| ADMIN | is_admin = true | 전체 관리 |

---

## 에러 코드 요약

| Code | HTTP | Description |
|------|------|-------------|
| UNAUTHORIZED | 401 | 인증 필요 |
| FORBIDDEN | 403 | 권한 없음 |
| NOT_FOUND | 404 | 리소스 없음 |
| LAST_LEADER_CANNOT_BE_REMOVED | 400 | 마지막 팀장 제거 불가 |
| CANNOT_REMOVE_SELF | 400 | 자기 자신 제거 불가 |
| INVALID_QUALIFICATION | 400 | 잘못된 자격 값 (approve 시 pending 입력 등) |
| NO_LEADER_IN_PROJECT | 400 | 프로젝트 생성 시 팀장 없음 |

## 멱등성 (Idempotency)

| API | 동작 |
|-----|------|
| `POST /projects/{id}/members` | 이미 활성 멤버면 기존 멤버 반환 |
| `POST /auth/signup` | 이미 가입된 유저면 기존 유저 + 토큰 반환 |

---

## 구현 순서

1. **Phase 0**: 기존 코드 삭제
2. **Phase 1-3**: DB 스키마 → Enum → SQLAlchemy 모델
3. **Phase 4**: Pydantic 스키마
4. **Phase 6**: 서비스 레이어 (S3는 Mock 구현)
5. **Phase 7**: 인증/인가
6. **Phase 8**: 에러 처리
7. **Phase 5**: API 라우트
8. **Phase 9-10**: main.py, 설정
9. **Phase 11**: 테스트 (**E2E 테스트 필수 - 전체 플로우 검증**)

## 참고사항

- **S3**: 인프라 미준비로 Mock 구현. 실제 연동은 추후 진행.
- **E2E 테스트**: 구현 완료 후 반드시 E2E 시나리오 전체 통과 확인 필요.
