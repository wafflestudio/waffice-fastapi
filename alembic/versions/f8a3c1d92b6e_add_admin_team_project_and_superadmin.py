"""add admin team project and superadmin flag

Bootstraps the single "운영팀" (admin team) project that now drives
User.is_admin/is_president (see ProjectService.sync_admin_team_roles):
active members of that project get is_admin=True, its leader(s) get
is_president=True. Also adds User.is_superadmin, a break-glass flag excluded
from that resync so it always keeps is_admin=True regardless of admin-team
membership.

Also drops users.is_president_marker -- the computed column + (already
disabled) unique-constraint machinery that used to enforce "at most one
current president" is superseded entirely by this project-membership model,
so the temporarily-relaxed state it supported is now permanent.

Data steps (safe to run against an empty database, e.g. fresh test DBs):
1. Create the "운영팀" project (is_admin_team=True).
2. Add every existing is_president=1 user as its LEADER.
3. Add every other existing is_admin=1 user as a regular MEMBER (so nobody
   loses admin access at rollout).
4. Set is_superadmin=1 (and is_admin=1) for the designated break-glass
   account.
5. Re-run the same is_admin/is_president resync sync_admin_team_roles does,
   so the end state is guaranteed consistent with the new invariant even if
   steps 2-4 missed an edge case.

Revision ID: f8a3c1d92b6e
Revises: 9d21f3a84b67
Create Date: 2026-07-29 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "f8a3c1d92b6e"
down_revision: Union[str, None] = "9d21f3a84b67"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The account granted is_superadmin -- always kept is_admin=True regardless
# of 운영팀 (admin team) project membership.
SUPERADMIN_EMAIL = "admin@gmail.com"


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("is_admin_team", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("is_superadmin", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.drop_column("users", "is_president_marker")

    conn = op.get_bind()

    result = conn.execute(
        sa.text(
            """
            INSERT INTO projects
                (name, description, status, started_at, ended_at, websites,
                 is_admin_team, created_at, updated_at, deleted_at)
            VALUES
                ('운영팀', NULL, 'active', CURDATE(), NULL, NULL,
                 1, UNIX_TIMESTAMP(), UNIX_TIMESTAMP(), NULL)
            """
        )
    )
    admin_team_id = result.lastrowid

    conn.execute(
        sa.text(
            """
            INSERT INTO project_members
                (project_id, user_id, role, position, joined_at, left_at,
                 created_at, updated_at)
            SELECT :project_id, id, 'leader', NULL, CURDATE(), NULL,
                   UNIX_TIMESTAMP(), UNIX_TIMESTAMP()
            FROM users
            WHERE is_president = 1
            """
        ),
        {"project_id": admin_team_id},
    )
    conn.execute(
        sa.text(
            """
            INSERT INTO project_members
                (project_id, user_id, role, position, joined_at, left_at,
                 created_at, updated_at)
            SELECT :project_id, id, 'member', NULL, CURDATE(), NULL,
                   UNIX_TIMESTAMP(), UNIX_TIMESTAMP()
            FROM users
            WHERE is_admin = 1 AND is_president = 0
            """
        ),
        {"project_id": admin_team_id},
    )

    conn.execute(
        sa.text(
            "UPDATE users SET is_superadmin = 1, is_admin = 1 WHERE email = :email"
        ),
        {"email": SUPERADMIN_EMAIL},
    )

    # Final resync, mirroring ProjectService.sync_admin_team_roles, so the
    # end state is consistent even if a prior step missed an edge case.
    conn.execute(
        sa.text(
            """
            UPDATE users SET is_admin = 1
            WHERE is_superadmin = 0 AND id IN (
                SELECT user_id FROM project_members
                WHERE project_id = :project_id AND left_at IS NULL
            )
            """
        ),
        {"project_id": admin_team_id},
    )
    conn.execute(
        sa.text(
            """
            UPDATE users SET is_admin = 0
            WHERE is_superadmin = 0 AND id NOT IN (
                SELECT user_id FROM project_members
                WHERE project_id = :project_id AND left_at IS NULL
            )
            """
        ),
        {"project_id": admin_team_id},
    )
    conn.execute(
        sa.text(
            """
            UPDATE users SET is_president = 1
            WHERE id IN (
                SELECT user_id FROM project_members
                WHERE project_id = :project_id AND left_at IS NULL AND role = 'leader'
            )
            """
        ),
        {"project_id": admin_team_id},
    )
    conn.execute(
        sa.text(
            """
            UPDATE users SET is_president = 0
            WHERE id NOT IN (
                SELECT user_id FROM project_members
                WHERE project_id = :project_id AND left_at IS NULL AND role = 'leader'
            )
            """
        ),
        {"project_id": admin_team_id},
    )


def downgrade() -> None:
    conn = op.get_bind()
    # Best-effort only: this deletes the bootstrapped 운영팀 project (and its
    # members via ON DELETE CASCADE) but does not attempt to restore each
    # user's prior is_admin/is_president value -- that history isn't
    # recoverable once sync_admin_team_roles has overwritten it.
    conn.execute(
        sa.text("DELETE FROM projects WHERE is_admin_team = 1"),
    )

    op.add_column(
        "users",
        sa.Column(
            "is_president_marker",
            mysql.TINYINT(),
            sa.Computed("IF(is_president, 1, NULL)", persisted=False),
            nullable=True,
        ),
    )
    op.drop_column("users", "is_superadmin")
    op.drop_column("projects", "is_admin_team")
