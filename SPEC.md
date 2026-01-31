# 모델 (볼드는 필수)

기본적으로 모든 모델은 `created_at`, `updated_at`을 가지고, `created_at`에 대한 index를 가진다.
- 시간은 **Unix Timestamp (BIGINT)** 로 저장하여 timezone 독립적으로 관리
- 삭제는 소프트 삭제 방식으로 `deleted_at` 필드를 사용
- 예외: `user_histories`는 불변 데이터이므로 `updated_at` 없음

## 유저 (`users`)

- **id** (PK, BIGINT AUTO_INCREMENT)
- **google_id** (VARCHAR, UNIQUE) - OAuth 연동용
- **email** (VARCHAR, UNIQUE)
- **name** (VARCHAR)
- **generation** (VARCHAR) - 가입 시 "26"으로 autofill
- **qualification** (ENUM: pending/associate/regular/active)
    - pending: 가입대기
    - associate: 준회원
    - regular: 정회원
    - active: 활동회원
- **is_admin** (BOOLEAN) - 운영진 여부
- phone (VARCHAR)
- affiliation (VARCHAR) - 소속 (학부/직장)
- bio (TEXT) - 자기소개
- avatar_url (VARCHAR) - 프로필 이미지 S3 URL
- github_username (VARCHAR)
- slack_id (VARCHAR)
- websites (JSON Array) - 개인 웹사이트 목록
    - 각 항목: `{url, type, description?}`
    - 예: `[{"url": "https://github.com/user", "type": "github", "description": "개인 깃헙"}]`
- created_at (BIGINT) - Unix timestamp
- updated_at (BIGINT) - Unix timestamp
- deleted_at (BIGINT, nullable) - 소프트 삭제

## 유저 상태 변경 기록 (`user_histories`)

유저의 주요 상태 변경을 기록한다. (불변 데이터, `updated_at` 없음)
- 자격 변경 (가입대기 → 준회원 등)
- 어드민 권한 부여/해제
- 프로젝트 소속 변경 (참여/탈퇴/역할 변경)

필드:
- **id** (PK, BIGINT AUTO_INCREMENT)
- **user_id** (FK → users)
- **action** (ENUM)
    - qualification_changed
    - admin_granted
    - admin_revoked
    - project_joined
    - project_left
    - project_role_changed
- **payload** (JSON) - 변경 상세 정보
- **created_at** (BIGINT) - Unix timestamp
- actor_id (FK → users, nullable) - 변경 수행자

payload 예시:
```json
// qualification_changed
{"from": "pending", "to": "associate"}

// admin_granted / admin_revoked
{}

// project_joined
{"project_id": 1, "project_name": "와플스튜디오", "role": "member", "position": "BE"}

// project_left
{"project_id": 1, "project_name": "와플스튜디오"}

// project_role_changed
{"project_id": 1, "from_role": "member", "to_role": "leader", "from_position": "BE", "to_position": "PM"}
```

## 프로젝트 (`projects`)

- **id** (PK, BIGINT AUTO_INCREMENT)
- **name** (VARCHAR)
- **status** (ENUM: active/maintenance/ended)
    - active: 활성화
    - maintenance: 유지보수
    - ended: 종결
- **started_at** (DATE)
- ended_at (DATE, nullable)
- description (TEXT) - 팀 소개
- websites (JSON Array) - 팀 웹사이트 목록
    - 각 항목: `{url, type, description?}`
- created_at (BIGINT) - Unix timestamp
- updated_at (BIGINT) - Unix timestamp
- deleted_at (BIGINT, nullable) - 소프트 삭제

## 프로젝트 멤버 (`project_members`)

- **id** (PK, BIGINT AUTO_INCREMENT)
- **project_id** (FK → projects)
- **user_id** (FK → users)
- **role** (ENUM: leader/member)
    - leader: 팀장 (복수 가능)
    - member: 팀원
- position (VARCHAR) - 팀내 포지션 (자유 입력: FE, BE, Designer, PM 등)
- joined_at (DATE)
- left_at (DATE, nullable) - NULL이면 현재 활성 멤버
- created_at (BIGINT) - Unix timestamp
- updated_at (BIGINT) - Unix timestamp

제약사항:
- 한 유저는 한 프로젝트에서 특정 시점에 0개 또는 1개의 활성 소속만 가질 수 있음
- 포지션/역할 변경 시: 기존 소속의 `left_at` 설정 → 새 소속 레코드 생성
- 탈퇴 시: `left_at`만 설정 (소프트 삭제)
- **마지막 팀장은 제거 불가** - 최소 1명의 팀장 유지 필요
- **자기 자신은 프로젝트에서 탈퇴 불가** - 어드민 또는 다른 팀장이 제거해야 함

---

# 액션

## 유저 관리

### 회원 가입 / 로그인

- 구글 로그인으로 Social Login 회원 가입 / 로그인 시도
- 기존 유저 정보 있으면 로그인, 아니면 가입 플로우
- 가입 플로우의 경우:
    - **이름, 이메일** (Google에서 가져옴)
    - 선택: github_username, phone, affiliation, bio
    - generation은 "26"으로 autofill
    - qualification은 "pending"으로 생성
    - is_admin은 false로 생성

### 유저 정보 변경

- 기본 정보 변경 (유저 본인, 준회원 이상)
    - phone, affiliation, bio, avatar_url, github_username, slack_id, websites
- 회원 타입 변경 (어드민)
    - qualification, is_admin 변경
    - 변경 시 `user_histories`에 기록
    - 예시 플로우:
        - 가입 승인: pending → associate/regular/active
        - 루키 승급: associate → regular/active
        - 활동 전환: regular → active
        - 활동 중단: active → regular

### 프로필 이미지 업로드

- S3 Presigned URL을 통한 이미지 업로드
- 업로드 완료 후 S3 URL을 유저 프로필에 저장

---

## 프로젝트 관리

### 프로젝트 목록 조회

- 정회원/활동회원만 전체 프로젝트 목록 조회 가능
- 준회원은 프로젝트 관련 기능 접근 불가

### 프로젝트 생성 (어드민)

- 모든 항목 설정 가능
- 생성 시 최소 1명의 팀장 필수
- 각 멤버에 대해 `user_histories`에 project_joined 기록

### 프로젝트 정보 변경 (어드민 & 팀장)

- 모든 항목 수정 가능
- 팀원 추가/제거/수정 포함
- 팀원 역할/포지션 변경 시:
    - 기존 소속 `left_at` 설정 → 새 소속 생성
    - `user_histories`에 project_role_changed 기록

### 프로젝트 삭제 (어드민)

- 소프트 삭제 (`deleted_at` 설정)

---

# 권한 체계

## 자격별 권한

| 기능 | 가입대기 | 준회원 | 정회원 | 활동회원 |
|------|---------|--------|--------|---------|
| 로그인 | O | O | O | O |
| 자기 정보 조회 | O | O | O | O |
| 자기 이력 조회 | O | O | O | O |
| 자기 정보 수정 | X | O | O | O |
| 프로필 이미지 업로드 | X | O | O | O |
| 프로젝트 목록 조회 | X | X | O | O |
| 프로젝트 상세 조회 | X | X | O | O |
| 내 프로젝트 목록 | X | X | O | O |

## 운영진(어드민) 권한

- 모든 유저 목록 조회
- 유저 자격/어드민 권한 변경
- 유저 삭제 (소프트 삭제)
- 프로젝트 생성/수정/삭제
- 프로젝트 멤버 관리

## 팀장 권한 (해당 프로젝트 한정)

- 프로젝트 정보 수정
- 팀원 추가/제거 (단, 마지막 팀장 제거 불가)
- 팀원 역할/포지션 변경

---

# API 설계

## 페이지네이션

- **Cursor-based pagination** 사용
- `created_at` 기준 **내림차순 정렬 (최신순)**
- 파라미터: `cursor` (optional, Unix timestamp), `limit` (default: 20)
- 응답에 `next_cursor` 포함

## 에러 응답

```json
{
  "ok": false,
  "error": "ERROR_CODE",
  "message": "Human readable message"
}
```

주요 에러 코드:
- `UNAUTHORIZED` - 인증 필요
- `FORBIDDEN` - 권한 없음
- `NOT_FOUND` - 리소스 없음
- `LAST_LEADER_CANNOT_BE_REMOVED` - 마지막 팀장 제거 불가
- `CANNOT_REMOVE_SELF` - 자기 자신 제거 불가
- `INVALID_QUALIFICATION` - 잘못된 자격 값 (예: approve 시 pending 입력)
- `NO_LEADER_IN_PROJECT` - 프로젝트 생성 시 팀장 없음

## 멱등성 (Idempotency)

동일한 요청을 여러 번 보내도 같은 결과를 보장:
- `POST /projects/{id}/members`: 이미 활성 멤버면 기존 멤버 정보 반환
- `POST /auth/signup`: 이미 가입된 유저면 기존 유저 정보 + 토큰 반환
