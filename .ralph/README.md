# Ralph Wiggum Loop - Waffice FastAPI Refactoring

## 개요

Ralph Wiggum 방식으로 PLAN.md의 작업들을 자동화된 루프로 실행합니다.

## 파일 구조

```
.ralph/
├── README.md           # 이 파일
├── refactor-prompt.md  # 메인 프롬프트 (완료 기준 포함)
├── start-prompt.txt    # Claude Code 시작용 짧은 프롬프트
├── run.sh              # Bash 루프 스크립트 (CLI용)
└── ralph.log           # 실행 로그 (자동 생성)
```

## 사용법

### 방법 1: Claude Code 내에서 직접 실행

새 대화 시작 후 다음을 입력:

```
Read .ralph/refactor-prompt.md and execute the refactoring plan.
Check current progress, identify next incomplete task, implement it, run tests.
Repeat until all criteria are met.
When ALL tests pass, output: <promise>COMPLETE</promise>
```

또는 파일 참조:

```
@.ralph/start-prompt.txt 실행해줘
```

### 방법 2: CLI에서 Bash 루프 실행

```bash
# 기본 (최대 50회 반복)
./.ralph/run.sh

# 최대 반복 횟수 지정
./.ralph/run.sh 100
```

## 완료 기준

`refactor-prompt.md`에 정의된 모든 체크리스트가 완료되면:

1. 모든 Phase (0-11) 구현 완료
2. `uv run pre-commit run --all-files` 통과
3. `uv run pytest` 모든 E2E 테스트 통과
4. 서버 정상 시작

완료 시 `<promise>COMPLETE</promise>` 출력.

## 주의사항

- S3는 Mock 구현 (실제 연동 X)
- E2E 테스트 필수 통과
- 각 Phase 완료 후 테스트 실행 권장
