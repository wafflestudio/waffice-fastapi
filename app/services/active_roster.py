from __future__ import annotations

from typing import NamedTuple

from sqlalchemy.orm import Session

from app.models import AuditAction, GraduationStatus, Qualification, User
from app.services.audit_log import AuditLogService
from app.services.roster import ActiveMemberRosterRow


class ActiveRosterResolvedRow(NamedTuple):
    row_number: int
    name: str
    student_id: str
    generation: str | None
    graduation_status: GraduationStatus | None
    user: User | None  # None -> no DB match, becomes a new temporary member


class ActiveRosterDiff(NamedTuple):
    promote: list[ActiveRosterResolvedRow]  # matched, currently non-ACTIVE -> ACTIVE
    demote: list[User]  # currently ACTIVE, not in the upload -> REGULAR
    maintain: list[ActiveRosterResolvedRow]  # matched, currently ACTIVE -> unchanged
    to_create: list[ActiveRosterResolvedRow]  # user is None, no DB match


def _apply_roster_fields(user: User, row: ActiveRosterResolvedRow) -> None:
    """Overwrite generation/graduation_status from the file, but only for
    fields the row actually provided -- a blank cell leaves the existing
    value on an already-matched user untouched rather than wiping it."""
    if row.generation is not None:
        user.generation = row.generation
    if row.graduation_status is not None:
        user.graduation_status = row.graduation_status


class ActiveRosterService:
    @staticmethod
    def resolve(
        db: Session, rows: list[ActiveMemberRosterRow]
    ) -> tuple[list[ActiveRosterResolvedRow], list[dict]]:
        """
        Match each roster row against the DB by student_id and validate.
        Returns (resolved, errors) -- a non-empty `errors` means the caller
        must reject the whole upload before any write; there is no partial
        application.

        A row is rejected when: the same student_id appears twice in the file
        (duplicate_student_id), the student_id matches more than one non-deleted
        user (ambiguous_student_id), or it matches exactly one user who is
        ASSOCIATE (associate_conflict) or PENDING (pending_conflict) -- both
        must be resolved outside the active-roster flow first. A student_id
        with no match at all resolves with user=None (a new temporary member).
        """
        student_ids = [row.student_id for row in rows]
        users_by_student_id: dict[str, list[User]] = {}
        if student_ids:
            for user in (
                db.query(User)
                .filter(User.deleted_at.is_(None), User.student_id.in_(student_ids))
                .all()
            ):
                users_by_student_id.setdefault(user.student_id, []).append(user)

        errors: list[dict] = []
        resolved: list[ActiveRosterResolvedRow] = []
        seen_student_ids: set[str] = set()

        for row in rows:
            if row.student_id in seen_student_ids:
                errors.append(
                    _active_roster_error(
                        row.row_number,
                        "학번",
                        "duplicate_student_id",
                        f'"{row.student_id}"이(가) 파일에 중복되어 있습니다.',
                    )
                )
                continue
            seen_student_ids.add(row.student_id)

            matches = users_by_student_id.get(row.student_id, [])
            if len(matches) > 1:
                errors.append(
                    _active_roster_error(
                        row.row_number,
                        "학번",
                        "ambiguous_student_id",
                        "같은 학번을 가진 회원이 여러 명입니다. 운영팀에 문의해주세요.",
                    )
                )
                continue

            user = matches[0] if matches else None
            if user is not None and user.qualification == Qualification.ASSOCIATE:
                errors.append(
                    _active_roster_error(
                        row.row_number,
                        "학번",
                        "associate_conflict",
                        f"갱신될 회원 명단에 준회원 {user.name}이 존재합니다. "
                        "활동회원 명부는 준회원과 구분하여 갱신해주세요.",
                    )
                )
                continue
            if user is not None and user.qualification == Qualification.PENDING:
                errors.append(
                    _active_roster_error(
                        row.row_number,
                        "학번",
                        "pending_conflict",
                        f"갱신될 회원 명단에 대기 회원 {user.name}이 존재합니다. "
                        "활동회원 명부는 대기 회원과 구분하여 갱신해주세요.",
                    )
                )
                continue

            resolved.append(
                ActiveRosterResolvedRow(
                    row.row_number,
                    row.name,
                    row.student_id,
                    row.generation,
                    row.graduation_status,
                    user,
                )
            )

        return resolved, errors

    @staticmethod
    def diff(db: Session, resolved: list[ActiveRosterResolvedRow]) -> ActiveRosterDiff:
        """Diff the resolved upload against who is currently ACTIVE in the DB."""
        matched_ids = {row.user.id for row in resolved if row.user is not None}
        existing_active = (
            db.query(User)
            .filter(
                User.deleted_at.is_(None),
                User.qualification == Qualification.ACTIVE,
            )
            .all()
        )

        promote = [
            row
            for row in resolved
            if row.user is not None and row.user.qualification != Qualification.ACTIVE
        ]
        maintain = [
            row
            for row in resolved
            if row.user is not None and row.user.qualification == Qualification.ACTIVE
        ]
        demote = [user for user in existing_active if user.id not in matched_ids]
        to_create = [row for row in resolved if row.user is None]

        return ActiveRosterDiff(promote, demote, maintain, to_create)

    @staticmethod
    def apply(
        db: Session,
        diff: ActiveRosterDiff,
        *,
        reference_date: int,
        actor_id: int,
    ) -> dict[str, list[User]]:
        """
        Apply the diff in one transaction: create temporary members for
        `to_create`, promote them together with `diff.promote` to ACTIVE, and
        demote `diff.demote` to REGULAR. Every matched row's generation/
        graduation_status (if provided in the file) is written to its user,
        new or existing. Every qualification change is logged to AuditLog,
        backdated to `reference_date`. Commits once at the end; rolls back on
        any error.
        """
        created_temporary: list[User] = []
        promoted: list[User] = []
        demoted: list[User] = []

        try:
            for row in diff.to_create:
                user = User(name=row.name, student_id=row.student_id, is_temporary=True)
                db.add(user)
                created_temporary.append(user)
            if created_temporary:
                # Flush first so the INSERT happens (and the User.generation /
                # graduation_status column *Python-side* defaults apply -- that
                # default fires on a None value even when explicitly passed to
                # the constructor above, so setting it there wouldn't work).
                # Re-assigning after the flush makes it an UPDATE instead, which
                # isn't subject to the INSERT-only default and so persists a
                # real None when the file didn't provide a value.
                db.flush()
                for create_row, user in zip(diff.to_create, created_temporary):
                    user.generation = create_row.generation
                    user.graduation_status = create_row.graduation_status

            for row in diff.promote:
                _apply_roster_fields(row.user, row)

            for user in [row.user for row in diff.promote] + created_temporary:
                old_qualification = user.qualification
                user.qualification = Qualification.ACTIVE
                AuditLogService.log(
                    db,
                    user_id=user.id,
                    action=AuditAction.QUALIFICATION_CHANGED,
                    payload={
                        "from": old_qualification.value,
                        "to": Qualification.ACTIVE.value,
                        "reason": "활동회원 등록",
                    },
                    actor_id=actor_id,
                    created_at=reference_date,
                )
                promoted.append(user)

            for row in diff.maintain:
                _apply_roster_fields(row.user, row)

            for user in diff.demote:
                AuditLogService.log(
                    db,
                    user_id=user.id,
                    action=AuditAction.QUALIFICATION_CHANGED,
                    payload={
                        "from": Qualification.ACTIVE.value,
                        "to": Qualification.REGULAR.value,
                        "reason": "활동 기간 종료",
                    },
                    actor_id=actor_id,
                    created_at=reference_date,
                )
                user.qualification = Qualification.REGULAR
                demoted.append(user)

            db.commit()
        except Exception:
            db.rollback()
            raise

        for user in created_temporary + promoted + demoted:
            db.refresh(user)

        return {
            "created_temporary": created_temporary,
            "promoted": promoted,
            "demoted": demoted,
            "maintained": [row.user for row in diff.maintain],
        }


def _active_roster_error(row: int, field: str, code: str, message: str) -> dict:
    return {"row": row, "field": field, "code": code, "message": message}
