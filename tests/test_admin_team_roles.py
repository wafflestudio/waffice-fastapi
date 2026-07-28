"""Tests for is_admin/is_president being derived from 운영팀 (admin team)
project membership (ProjectService.sync_admin_team_roles), and the
"only the sitting president can appoint the next leader" permission rule.

The 운영팀 project itself is never created via any API (is_admin_team is not
exposed on any request schema -- only the bootstrap migration sets it), so
tests create it directly through the db fixture.
"""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Project, User
from app.services.certificate_render import _build_executive_rows


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_admin_team(db: Session) -> Project:
    project = Project(name="운영팀", is_admin_team=True, started_at=date.today())
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def test_joining_admin_team_grants_is_admin(
    client: TestClient,
    db: Session,
    admin_token: str,
    admin_user: User,
    regular_user: User,
):
    admin_team = _create_admin_team(db)
    response = client.post(
        f"/projects/{admin_team.id}/members",
        json={"user_id": regular_user.id, "role": "member"},
        headers=_auth(admin_token),
    )
    assert response.status_code == 200
    db.refresh(regular_user)
    assert regular_user.is_admin is True
    assert regular_user.is_president is False


def test_leaving_admin_team_revokes_is_admin(
    client: TestClient,
    db: Session,
    admin_token: str,
    admin_user: User,
    regular_user: User,
):
    admin_team = _create_admin_team(db)
    client.post(
        f"/projects/{admin_team.id}/members",
        json={"user_id": regular_user.id, "role": "member"},
        headers=_auth(admin_token),
    )
    db.refresh(regular_user)
    assert regular_user.is_admin is True

    response = client.delete(
        f"/projects/{admin_team.id}/members/{regular_user.id}",
        headers=_auth(admin_token),
    )
    assert response.status_code == 200
    db.refresh(regular_user)
    assert regular_user.is_admin is False


def test_sync_resets_unrelated_is_admin_flag(
    client: TestClient,
    db: Session,
    admin_token: str,
    admin_user: User,
    active_user: User,
    regular_user: User,
):
    """An is_admin flag with no relation to admin-team membership gets wiped
    the next time the admin team's roster changes (full resync, not a patch)."""
    active_user.is_admin = True
    db.commit()

    admin_team = _create_admin_team(db)
    response = client.post(
        f"/projects/{admin_team.id}/members",
        json={"user_id": regular_user.id, "role": "member"},
        headers=_auth(admin_token),
    )
    assert response.status_code == 200

    db.refresh(active_user)
    assert active_user.is_admin is False


def test_leader_of_admin_team_becomes_president(
    client: TestClient,
    db: Session,
    admin_token: str,
    admin_user: User,
    regular_user: User,
):
    admin_team = _create_admin_team(db)
    response = client.post(
        f"/projects/{admin_team.id}/members",
        json={"user_id": regular_user.id, "role": "leader"},
        headers=_auth(admin_token),
    )
    assert response.status_code == 200
    db.refresh(regular_user)
    assert regular_user.is_president is True
    assert regular_user.is_admin is True


def test_demoting_leader_revokes_president_but_keeps_admin(
    client: TestClient,
    db: Session,
    admin_token: str,
    admin_user: User,
    regular_token: str,
    regular_user: User,
    active_user: User,
):
    admin_team = _create_admin_team(db)
    # Bootstrap: admin appoints the first leader (no sitting president yet).
    client.post(
        f"/projects/{admin_team.id}/members",
        json={"user_id": regular_user.id, "role": "leader"},
        headers=_auth(admin_token),
    )
    # Promote a co-leader first (only the sitting president, regular_user,
    # may do this now) so demoting regular_user doesn't hit the "last
    # leader" invariant.
    promote = client.post(
        f"/projects/{admin_team.id}/members",
        json={"user_id": active_user.id, "role": "leader"},
        headers=_auth(regular_token),
    )
    assert promote.status_code == 200

    response = client.patch(
        f"/projects/{admin_team.id}/members/{regular_user.id}",
        json={"role": "member"},
        headers=_auth(admin_token),
    )
    assert response.status_code == 200
    db.refresh(regular_user)
    assert regular_user.is_president is False
    assert regular_user.is_admin is True


def test_multiple_concurrent_leaders_allowed(
    client: TestClient,
    db: Session,
    admin_token: str,
    admin_user: User,
    regular_token: str,
    regular_user: User,
    active_user: User,
):
    admin_team = _create_admin_team(db)
    # Bootstrap: no leader yet, so a plain admin can appoint the first one.
    first = client.post(
        f"/projects/{admin_team.id}/members",
        json={"user_id": regular_user.id, "role": "leader"},
        headers=_auth(admin_token),
    )
    assert first.status_code == 200
    db.refresh(regular_user)
    assert regular_user.is_president is True

    # Now a leader exists: only the sitting president (regular_user) may
    # appoint a second one.
    second = client.post(
        f"/projects/{admin_team.id}/members",
        json={"user_id": active_user.id, "role": "leader"},
        headers=_auth(regular_token),
    )
    assert second.status_code == 200
    db.refresh(active_user)
    db.refresh(regular_user)
    assert active_user.is_president is True
    assert regular_user.is_president is True


def test_non_president_admin_cannot_appoint_second_leader(
    client: TestClient,
    db: Session,
    admin_token: str,
    admin_user: User,
    regular_user: User,
    active_user: User,
):
    admin_team = _create_admin_team(db)
    bootstrap = client.post(
        f"/projects/{admin_team.id}/members",
        json={"user_id": regular_user.id, "role": "leader"},
        headers=_auth(admin_token),
    )
    assert bootstrap.status_code == 200

    # admin_user has is_admin=True (unrelated to the admin team) but is not
    # the sitting president, so appointing a second leader must be forbidden.
    response = client.post(
        f"/projects/{admin_team.id}/members",
        json={"user_id": active_user.id, "role": "leader"},
        headers=_auth(admin_token),
    )
    assert response.status_code == 403
    assert response.json()["error"] == "PRESIDENT_APPOINTMENT_FORBIDDEN"


def test_superadmin_keeps_is_admin_after_sync(
    client: TestClient,
    db: Session,
    admin_token: str,
    admin_user: User,
    active_user: User,
    regular_user: User,
):
    active_user.is_superadmin = True
    active_user.is_admin = True
    db.commit()

    admin_team = _create_admin_team(db)
    response = client.post(
        f"/projects/{admin_team.id}/members",
        json={"user_id": regular_user.id, "role": "member"},
        headers=_auth(admin_token),
    )
    assert response.status_code == 200

    db.refresh(active_user)
    assert active_user.is_admin is True


def test_build_executive_rows_reflects_demotion_not_just_membership(
    db: Session, regular_user: User
):
    """A member who was leader, then demoted to member (still in the admin
    team), should show an executive period that ENDS at the demotion --
    ProjectMember.left_at alone can't tell us that, since it stays null."""
    from app.models import MemberRole
    from app.services.member import MemberService

    admin_team = _create_admin_team(db)
    member = MemberService.add(
        db,
        project_id=admin_team.id,
        user_id=regular_user.id,
        role=MemberRole.LEADER,
        position=None,
        actor_id=regular_user.id,
    )
    db.commit()
    MemberService.change(
        db, member=member, actor_id=regular_user.id, role=MemberRole.MEMBER
    )
    db.commit()

    rows = _build_executive_rows(db, regular_user)
    assert len(rows) == 1
    assert rows[0]["role"] == "회장"
    assert "~" in rows[0]["period"]
    assert not rows[0]["period"].endswith("현재")
