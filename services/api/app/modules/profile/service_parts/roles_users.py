from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session


class ProfileRoleUserMixin:
    """Compatibility consumer over canonical users-domain role/user logic."""

    @staticmethod
    def _users_service():
        from app.modules.users.service import service as users_service

        return users_service

    def list_roles(self, db: Session, *, workspace_type: str, workspace_id: str, actor: str, limit: int = 500) -> list[dict[str, Any]]:
        return self._users_service().list_roles(
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            actor=actor,
            limit=limit,
        )

    def upsert_role(self, db: Session, *, workspace_type: str, workspace_id: str, role_code: str, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        return self._users_service().upsert_role(
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            role_code=role_code,
            payload=payload,
            actor=actor,
        )

    def delete_role(self, db: Session, *, workspace_type: str, workspace_id: str, role_code: str, actor: str) -> dict[str, Any]:
        return self._users_service().delete_role(
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            role_code=role_code,
            actor=actor,
        )

    def list_workspace_users(self, db: Session, *, workspace_type: str, workspace_id: str, actor: str, limit: int = 200) -> list[dict[str, Any]]:
        return self._users_service().list_workspace_users(
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            actor=actor,
            limit=limit,
        )

    def upsert_workspace_user(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        return self._users_service().upsert_workspace_user(
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            user_id=user_id,
            payload=payload,
            actor=actor,
        )

    def get_workspace_user(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, actor: str) -> dict[str, Any]:
        return self._users_service().get_workspace_user(
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            user_id=user_id,
            actor=actor,
        )

    def set_workspace_user_roles(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, role_codes: list[Any], actor: str) -> dict[str, Any]:
        return self._users_service().set_workspace_user_roles(
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            user_id=user_id,
            role_codes=role_codes,
            actor=actor,
        )
