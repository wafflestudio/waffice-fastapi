# app/services/project_service.py

from __future__ import annotations

from datetime import date
from typing import Iterable, List, Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.models import Project, ProjectMember, ProjectWebsite
from app.schemas import (
    ProjectCreate,
    ProjectMemberRole,
    ProjectUpdate,
    ProjectWebsiteCreate,
)


class ProjectService:
    # ----------------------------------------------------------
    # BASIC GET
    # ----------------------------------------------------------
    @staticmethod
    def get_by_id(db: Session, project_id: int) -> Project | None:
        return db.get(Project, project_id)

    @staticmethod
    def get_detail(db: Session, project_id: int) -> Project | None:
        """
        프로젝트 1개 + websites + members까지 로드
        /api/project/info 용
        """
        stmt = (
            select(Project)
            .options(
                selectinload(Project.websites),
                selectinload(Project.members),
            )
            .where(Project.id == project_id)
        )
        return db.execute(stmt).scalar_one_or_none()

    # ----------------------------------------------------------
    # LIST BY USER
    # ----------------------------------------------------------
    @staticmethod
    def list_by_user(db: Session, user_id: int) -> List[Project]:
        """
        특정 유저가 멤버로 속해 있는 프로젝트 목록
        /api/project/me 용
        """
        stmt = (
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .options(
                selectinload(Project.websites),
                selectinload(Project.members),
            )
            .where(ProjectMember.user_id == user_id)
        )
        return list(db.scalars(stmt).all())

    # ----------------------------------------------------------
    # MEMBER / LEADER 조회 헬퍼
    # (컨트롤러에서 권한 체크할 때 사용)
    # ----------------------------------------------------------
    @staticmethod
    def get_member(
        db: Session,
        project_id: int,
        user_id: int,
    ) -> ProjectMember | None:
        stmt = select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
        return db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def is_leader(
        db: Session,
        project_id: int,
        user_id: int,
    ) -> bool:
        stmt = select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
            ProjectMember.role == "leader",
        )
        return db.execute(stmt).scalar_one_or_none() is not None

    # ----------------------------------------------------------
    # CREATE / DELETE / UPDATE
    # ----------------------------------------------------------
    @staticmethod
    def create(
        db: Session,
        creator_user_id: int,
        data: ProjectCreate,
        leader_position: str = "etc",
    ) -> Project:
        """
        /api/exct/project/create
        - Project 생성
        - 생성자를 leader 멤버로 등록
        """
        payload = data.model_dump()
        project = Project(
            name=payload["name"],
            description=payload.get("description"),
            status=payload.get("status", "active"),
            start_date=payload["start_date"],
            end_date=payload.get("end_date"),
        )
        db.add(project)
        db.flush()

        leader_member = ProjectMember(
            project_id=project.id,
            user_id=creator_user_id,
            role="leader",
            position=leader_position,
            start_date=payload["start_date"],
            end_date=None,
        )
        db.add(leader_member)

        db.commit()
        db.refresh(project)
        return project

    @staticmethod
    def delete(db: Session, project_id: int) -> bool:
        """
        /api/exct/project/delete
        - 프로젝트 및 관련 멤버/웹사이트 삭제 (FK CASCADE 전제)
        """
        project = db.get(Project, project_id)
        if not project:
            return False
        db.delete(project)
        db.commit()
        return True

    @staticmethod
    def update_with_websites(
        db: Session,
        project_id: int,
        updates: ProjectUpdate,
        websites: Sequence[ProjectWebsiteCreate] | None = None,
    ) -> Project | None:
        """
        /api/project/update, /api/exct/project/update 공용
        - Project 필드 업데이트
        - websites 가 주어지면 기존 것을 전부 교체
        """
        project = db.get(Project, project_id)
        if not project:
            return None

        data = updates.model_dump(exclude_unset=True)
        for key, value in data.items():
            setattr(project, key, value)

        if websites is not None:
            project.websites.clear()
            db.flush()

            for w in websites:
                w_data = w.model_dump()
                pw = ProjectWebsite(
                    project_id=project.id,
                    label=w_data.get("label"),
                    url=w_data["url"],
                    kind=w_data.get("kind"),
                    is_primary=w_data.get("is_primary", False),
                    ord=w_data.get("ord", 0),
                )
                project.websites.append(pw)

        db.commit()
        db.refresh(project)
        return project

    # ----------------------------------------------------------
    # MEMBER OPS: INVITE / KICK / LEAVE
    # ----------------------------------------------------------
    @staticmethod
    def invite_member(
        db: Session,
        project_id: int,
        target_user_id: int,
        role: ProjectMemberRole,
        position: str,
        start_date: date,
        end_date: date | None = None,
    ) -> ProjectMember:
        """
        /api/project/invite
        - 해당 유저가 이미 멤버인지 여부는 컨트롤러에서 미리 체크하거나
          여기서 allow-multiple 정책에 따라 허용
        """
        role_value = role.value if hasattr(role, "value") else str(role)

        member = ProjectMember(
            project_id=project_id,
            user_id=target_user_id,
            role=role_value,
            position=position,
            start_date=start_date,
            end_date=end_date,
        )
        db.add(member)
        db.commit()
        db.refresh(member)
        return member

    @staticmethod
    def kick_member(
        db: Session,
        project_id: int,
        target_user_id: int,
        end_date: date | None = None,
    ) -> bool:
        """
        /api/project/kick
        - 현재 진행 중인 멤버십을 종료(end_date 설정)하는 방식
        """
        member = ProjectService.get_member(db, project_id, target_user_id)
        if not member:
            return False

        member.end_date = end_date or date.today()
        db.commit()
        return True

    @staticmethod
    def leave(
        db: Session,
        project_id: int,
        user_id: int,
        end_date: date | None = None,
    ) -> bool:
        """
        /api/project/leave
        - 본인 멤버십 종료
        - 마지막 leader 여부 체크 등은 컨트롤러에서 정책에 따라 처리
        """
        member = ProjectService.get_member(db, project_id, user_id)
        if not member:
            return False

        member.end_date = end_date or date.today()
        db.commit()
        return True
