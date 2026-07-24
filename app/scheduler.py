"""주기적으로 실행되어야 하는 앱 내부 백그라운드 작업.

이 프로젝트에는 별도 배치/크론 인프라가 없다. "만료된 활동증명서 원본
폐기"처럼 아무도 접근하지 않아도 정시에 실행되어야 하는 작업은, 운영진이
수동으로 호출하는 API 엔드포인트가 아니라 앱 프로세스 안에서 APScheduler로
직접 돌린다 (`app/main.py`의 lifespan에서 `start_scheduler`/
`shutdown_scheduler`를 호출).

멀티 파드 배포 시 주의점: 각 파드가 독립적으로 이 스케줄러를 띄우므로, 같은
작업이 여러 파드에서 동시에(또는 거의 동시에) 실행될 수 있다.
`CertificateService.purge_all_expired`는 멱등적이다 -- 이미 폐기된 행은
`pdf_object_key IS NOT NULL` 조건에 안 걸려 다시 선택되지 않으므로 중복
실행 자체는 안전하지만, 그만큼 중복 조회/삭제 시도가 낭비된다. 정확히 한
파드만 실행하도록 분산 락을 거는 건 이번 범위 밖이다 (필요해지면
`app/config/database.py`의 마이그레이션 advisory-lock 패턴을 참고해 추가할
수 있다).
"""

import logging
import sys

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from app.config.database import SessionLocal
from app.services.certificate import CertificateService
from app.services.object_storage import OCIObjectStorageService

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _purge_expired_certificates() -> None:
    db = SessionLocal()
    try:
        storage = OCIObjectStorageService()
        purged_count = CertificateService.purge_all_expired(db, storage)
        if purged_count:
            logger.info("purged %d expired certificate(s)", purged_count)
    except Exception:
        logger.exception("failed to purge expired certificates")
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler | None:
    """앱 시작 시 1회 호출. 이미 떠 있으면 그대로 반환한다 (재시작 시 중복
    등록 방지).

    pytest 하에서는 시작하지 않는다: `TestClient(app)`가 `with` 블록으로
    쓰이면 테스트마다 lifespan이 실제로 실행되는데, 여기서 스케줄러를 띄우면
    백그라운드 스레드가 테스트와 별개의 DB 세션으로 동시에 쿼리를 실행하다가
    각 테스트가 끝날 때마다 도는 전체 테이블 TRUNCATE와 경합할 수 있다
    (`tests/conftest.py`의 `db` fixture).
    """
    global _scheduler
    if "pytest" in sys.modules:
        return None
    if _scheduler is not None:
        return _scheduler

    scheduler = BackgroundScheduler(timezone="Asia/Seoul")
    # 매일 새벽 4시(KST)에 만료된 증명서 원본을 폐기.
    scheduler.add_job(
        _purge_expired_certificates,
        trigger=CronTrigger(hour=4, minute=0),
        id="purge_expired_certificates_daily",
    )
    # 배포 직후에도 (다음 새벽까지 기다리지 않고) 한 번 실행되도록 즉시 1회
    # 추가 예약 -- 운영자가 재배포 직후 동작을 바로 확인할 수 있게 하기 위함.
    scheduler.add_job(
        _purge_expired_certificates,
        trigger=DateTrigger(),
        id="purge_expired_certificates_startup",
    )
    scheduler.start()
    _scheduler = scheduler
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
