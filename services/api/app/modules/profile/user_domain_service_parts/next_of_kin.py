from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import re
import secrets
from typing import Any
import uuid

from sqlalchemy.orm import Session

from app.db.models import (
    Tenant,
    WorkspaceUser,
    WorkspaceUserAddress,
    WorkspaceUserContactChannel,
    WorkspaceUserCredential,
    WorkspaceUserDocument,
    WorkspaceUserNextOfKin,
    WorkspaceUserProfile,
)
from app.modules.profile.service import PLATFORM_WORKSPACE_ID, WORKSPACE_PLATFORM, WORKSPACE_TENANT, service as workspace_service
from app.modules.profile import user_domain_ops

class UserDomainNextOfKinMixin:
    def list_user_next_of_kin(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, actor: str, limit: int = 500) -> list[dict[str, Any]]:
        return user_domain_ops.list_user_next_of_kin(
            self,
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            user_id=user_id,
            actor=actor,
            limit=limit,
        )

    def upsert_user_next_of_kin(
        self,
        db: Session,
        *,
        workspace_type: str,
        workspace_id: str,
        user_id: str,
        actor: str,
        payload: dict[str, Any],
        kin_id: str | None = None,
    ) -> dict[str, Any]:
        return user_domain_ops.upsert_user_next_of_kin(
            self,
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            user_id=user_id,
            actor=actor,
            payload=payload,
            kin_id=kin_id,
        )

    def delete_user_next_of_kin(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, actor: str, kin_id: str) -> dict[str, Any]:
        return user_domain_ops.delete_user_next_of_kin(
            self,
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            user_id=user_id,
            actor=actor,
            kin_id=kin_id,
        )
