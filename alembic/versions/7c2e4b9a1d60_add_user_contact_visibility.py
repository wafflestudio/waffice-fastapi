"""add user student ID, phone, and contact email visibility flags

Revision ID: 7c2e4b9a1d60
Revises: a4c8f1b3d9e2
Create Date: 2026-11-19

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import context, op

# revision identifiers, used by Alembic.
revision: str = "7c2e4b9a1d60"
down_revision: Union[str, None] = "a4c8f1b3d9e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_VISIBILITY_COLUMNS = {
    "is_student_id_public",
    "is_phone_public",
    "is_contact_email_public",
}


def _has_visibility_columns() -> bool:
    columns = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT "
                "FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' "
                "AND COLUMN_NAME IN "
                "('is_student_id_public', 'is_phone_public', 'is_contact_email_public')"
            )
        )
        .all()
    )
    if 0 < len(columns) < len(_VISIBILITY_COLUMNS):
        existing = {column[0] for column in columns}
        missing = _VISIBILITY_COLUMNS - existing
        raise RuntimeError(
            "Incomplete users visibility schema: "
            f"existing columns: {', '.join(sorted(existing))}; "
            f"missing columns: {', '.join(sorted(missing))}"
        )
    for name, column_type, is_nullable, column_default in columns:
        if (column_type, is_nullable, str(column_default)) != (
            "tinyint(1)",
            "NO",
            "0",
        ):
            raise RuntimeError(
                f"Unexpected definition for users.{name}: expected TINYINT(1) "
                f"NOT NULL DEFAULT 0, found type={column_type!r}, "
                f"nullable={is_nullable!r}, default={column_default!r}"
            )
    return bool(columns)


def upgrade() -> None:
    # MySQL may have committed the DDL before Alembic stamped the revision.
    if not context.is_offline_mode() and _has_visibility_columns():
        return

    op.execute(
        "ALTER TABLE users "
        "ADD COLUMN is_student_id_public TINYINT(1) NOT NULL DEFAULT 0, "
        "ADD COLUMN is_phone_public TINYINT(1) NOT NULL DEFAULT 0, "
        "ADD COLUMN is_contact_email_public TINYINT(1) NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    if context.is_offline_mode() or _has_visibility_columns():
        op.execute(
            "ALTER TABLE users DROP COLUMN is_student_id_public, "
            "DROP COLUMN is_phone_public, "
            "DROP COLUMN is_contact_email_public"
        )
