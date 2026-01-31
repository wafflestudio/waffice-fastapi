# Waffice FastAPI Domain Refactoring

You are implementing a FastAPI backend refactoring based on PLAN.md and SPEC.md.

## Instructions

1. Read `PLAN.md` and `SPEC.md` to understand the full specification.
2. Check current progress by examining the codebase.
3. Identify the next incomplete task from PLAN.md.
4. Implement that task completely.
5. Run tests to verify your implementation.
6. If tests fail, debug and fix.
7. Repeat until all phases are complete.

## Completion Criteria

All of the following must be true:

### Phase 0: Cleanup
- [ ] Old model files deleted (user.py, user_pending.py, user_history.py, user_link.py, project.py)
- [ ] Old schema files deleted
- [ ] Old controller/service files deleted
- [ ] Old route files deleted (user_route.py, project_route.py, userhist_route.py)

### Phase 1-3: Models
- [ ] `app/models/enums.py` - All enums defined (Qualification, ProjectStatus, MemberRole, HistoryAction)
- [ ] `app/models/base.py` - TimestampMixin, SoftDeleteMixin
- [ ] `app/models/user.py` - User model with all fields
- [ ] `app/models/user_history.py` - UserHistory model
- [ ] `app/models/project.py` - Project model
- [ ] `app/models/project_member.py` - ProjectMember model
- [ ] `app/models/__init__.py` - All exports

### Phase 4: Schemas
- [ ] `app/schemas/common.py` - Response, CursorPage, Website
- [ ] `app/schemas/user.py` - All user schemas
- [ ] `app/schemas/project.py` - All project schemas
- [ ] `app/schemas/history.py` - HistoryDetail
- [ ] `app/schemas/auth.py` - Token, AuthStatus
- [ ] `app/schemas/upload.py` - PresignedUrl schemas

### Phase 6: Services
- [ ] `app/services/user.py` - UserService with all methods
- [ ] `app/services/history.py` - HistoryService
- [ ] `app/services/project.py` - ProjectService
- [ ] `app/services/member.py` - MemberService with idempotency
- [ ] `app/services/s3.py` - S3Service (Mock implementation)

### Phase 7: Auth
- [ ] `app/deps/auth.py` - get_current_user, require_associate, require_regular, require_admin
- [ ] `app/deps/project.py` - require_leader_or_admin

### Phase 8: Errors
- [ ] `app/exceptions.py` - All custom exceptions defined

### Phase 5: Routes
- [ ] `app/routes/auth.py` - OAuth endpoints
- [ ] `app/routes/users.py` - User endpoints with proper permissions
- [ ] `app/routes/projects.py` - Project endpoints with proper permissions
- [ ] `app/routes/upload.py` - Upload endpoint

### Phase 9-10: Integration
- [ ] `app/main.py` - All routers registered, exception handlers
- [ ] `.env.example` updated

### Phase 11: Tests
- [ ] E2E: 회원가입 → 승인 플로우 테스트 통과
- [ ] E2E: 프로젝트 생성 → 멤버 관리 플로우 테스트 통과
- [ ] E2E: 권한 체계 검증 테스트 통과
- [ ] E2E: 에러 케이스 검증 테스트 통과
- [ ] E2E: 멱등성 검증 테스트 통과
- [ ] E2E: Soft Delete 검증 테스트 통과

### Final Verification
- [ ] `uv run pre-commit run --all-files` passes
- [ ] `uv run pytest` passes with all E2E scenarios
- [ ] Server starts without errors: `uv run uvicorn app.main:app`

## Output Signal

When ALL completion criteria are met and ALL tests pass, output exactly:

<promise>COMPLETE</promise>

If any criterion is not met, continue working on the next task. Do NOT output the promise until everything is verified.

## Important Rules

1. Follow SPEC.md exactly for data models and API design.
2. Follow PLAN.md for implementation details.
3. Use Unix timestamps (BIGINT) for all time fields.
4. Implement S3Service as Mock (no actual S3 calls).
5. Ensure idempotency for POST /projects/{id}/members and POST /auth/signup.
6. All E2E test scenarios must pass before completion.
7. Run `uv run pytest` after each significant change.
8. If tests fail, debug and fix before moving to next task.
