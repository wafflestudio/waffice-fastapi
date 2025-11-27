# app/controllers/project_controller.py

from __future__ import annotations

from datetime import date
from typing import List, Sequence

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.user import WafficeUser
from app.schemas import (
    Project,
    ProjectCreate,
    ProjectMemberRole,
    ProjectUpdate,
    ProjectWebsiteCreate,
)
from app.services.project_service import ProjectService


class ProjectController:
    # ----------------------------------------------------------
    # INTERNAL HELPERS
    # ----------------------------------------------------------
    @staticmethod
    def _ensure_member_or_404(
        db: Session,
        project_id: int,
        user_id: int,
    ):
        member = ProjectService.get_member(db, project_id, user_id)
        if not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project member not found",
            )
        return member

    @staticmethod
    def _ensure_leader_or_403(
        db: Session,
        project_id: int,
        user_id: int,
    ):
        if not ProjectService.is_leader(db, project_id, user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Leader role required for this operation",
            )

    @staticmethod
    def _ensure_exec_or_403(actor: WafficeUser):
        """운영진 권한(admin >= 1) 확인"""
        if getattr(actor, "admin", 0) < 1:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Executive privilege required",
            )

    # ----------------------------------------------------------
    # PUBLIC (일반 유저용 /api/project/*)
    # ----------------------------------------------------------
    @staticmethod
    def list_my_projects(db: Session, user_id: int) -> List[Project]:
        """
        /api/project/me
        - 내가 속해 있는 프로젝트 목록 조회
        """
        return ProjectService.list_by_user(db, user_id)

    @staticmethod
    def get_project_info(db: Session, project_id: int) -> Project:
        """
        /api/project/info
        - project_id 로 프로젝트 상세 조회 (링크, 팀원 포함)
        """
        project = ProjectService.get_detail(db, project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        return project

    @staticmethod
    def update_project_as_leader(
        db: Session,
        project_id: int,
        actor_user_id: int,
        updates: ProjectUpdate,
        websites: Sequence[ProjectWebsiteCreate] | None = None,
    ) -> Project:
        """
        /api/project/update
        - 프로젝트 정보 + 웹사이트를 업데이트
        - actor 가 해당 프로젝트의 leader 여야 함
        """
        ProjectController._ensure_leader_or_403(db, project_id, actor_user_id)

        project = ProjectService.update_with_websites(db, project_id, updates, websites)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        return project

    @staticmethod
    def invite_member(
        db: Session,
        project_id: int,
        actor_user_id: int,
        target_user_id: int,
        role: ProjectMemberRole,
        position: str,
        start_date: date,
        end_date: date | None = None,
    ):
        """
        /api/project/invite
        - 프로젝트에 유저를 초대
        - 초대하는 자가 프로젝트의 leader 여야 함
        """
        ProjectController._ensure_leader_or_403(db, project_id, actor_user_id)

        # 이미 active 멤버인지 여부는 정책에 따라 처리
        existing = ProjectService.get_member(db, project_id, target_user_id)
        if existing and existing.end_date is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User is already an active member of this project",
            )

        member = ProjectService.invite_member(
            db,
            project_id=project_id,
            target_user_id=target_user_id,
            role=role,
            position=position,
            start_date=start_date,
            end_date=end_date,
        )
        return member

    @staticmethod
    def kick_member(
        db: Session,
        project_id: int,
        actor_user_id: int,
        target_user_id: int,
        end_date: date | None = None,
    ):
        """
        /api/project/kick
        - 프로젝트에서 유저를 제외
        - actor 가 leader 여야 함
        - (간단 정책) leader 를 강제 탈퇴시키는 것은 허용하지 않음
        """
        ProjectController._ensure_leader_or_403(db, project_id, actor_user_id)

        target_member = ProjectService.get_member(db, project_id, target_user_id)
        if not target_member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Target member not found in project",
            )

        if target_member.role == ProjectMemberRole.leader.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot kick a leader via this endpoint",
            )

        ok = ProjectService.kick_member(
            db,
            project_id=project_id,
            target_user_id=target_user_id,
            end_date=end_date,
        )
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Target member not found",
            )
        return {"status": "kicked", "project_id": project_id, "user_id": target_user_id}

    @staticmethod
    def leave_project(
        db: Session,
        project_id: int,
        user_id: int,
        end_date: date | None = None,
    ):
        """
        /api/project/leave
        - 프로젝트에서 본인이 탈퇴
        - (현재 정책) leader 도 탈퇴 가능하게 두고, 후속 처리는 exec 쪽에서 조정
        """
        member = ProjectService.get_member(db, project_id, user_id)
        if not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not a member of this project",
            )

        ok = ProjectService.leave(
            db,
            project_id=project_id,
            user_id=user_id,
            end_date=end_date,
        )
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Leave failed: membership not found",
            )

        return {"status": "left", "project_id": project_id, "user_id": user_id}

    # ----------------------------------------------------------
    # EXECUTIVE (/api/exct/project/*)
    # ----------------------------------------------------------
    @staticmethod
    def create_project_as_exec(
        db: Session,
        actor: WafficeUser,
        data: ProjectCreate,
        leader_position: str = "etc",
    ) -> Project:
        """
        /api/exct/project/create
        - 운영진만 호출 가능
        - actor 자신이 leader 로 등록됨
        """
        ProjectController._ensure_exec_or_403(actor)
        project = ProjectService.create(
            db,
            creator_user_id=actor.id,
            data=data,
            leader_position=leader_position,
        )
        return project

    @staticmethod
    def delete_project_as_exec(
        db: Session,
        actor: WafficeUser,
        project_id: int,
    ):
        """
        /api/exct/project/delete
        - 운영진만 호출 가능
        - 프로젝트 전체 삭제
        """
        ProjectController._ensure_exec_or_403(actor)

        ok = ProjectService.delete(db, project_id)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        return {"status": "deleted", "project_id": project_id}

    @staticmethod
    def update_project_as_exec(
        db: Session,
        actor: WafficeUser,
        project_id: int,
        updates: ProjectUpdate,
        websites: Sequence[ProjectWebsiteCreate] | None = None,
    ) -> Project:
        """
        /api/exct/project/update
        - 운영진만 호출 가능
        - 프로젝트 정보 + 웹사이트를 업데이트
        """
        ProjectController._ensure_exec_or_403(actor)

        project = ProjectService.update_with_websites(db, project_id, updates, websites)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        return project
