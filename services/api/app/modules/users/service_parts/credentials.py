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
from app.modules.users import user_domain_ops

class UsersCredentialsMixin:
    def _sanitize_username(self, raw: str) -> str:

        base = self.USERNAME_SAFE_RE.sub("", str(raw or "").strip().lower())

        base = base.strip("._-")

        if len(base) < 3:

            base = f"user{secrets.randbelow(10000):04d}"

        return base[:64]

    def _unique_username(self, db: Session, *, workspace_type: str, workspace_id: str, candidate: str, current_id: uuid.UUID | None = None) -> str:

        base = self._sanitize_username(candidate)

        for i in range(0, 200):

            username = base if i == 0 else f"{base}{i:02d}"

            q = (

                db.query(WorkspaceUserCredential)

                .filter(

                    WorkspaceUserCredential.workspace_type == workspace_type,

                    WorkspaceUserCredential.workspace_id == workspace_id,

                    WorkspaceUserCredential.username == username,

                )

            )

            if current_id is not None:

                q = q.filter(WorkspaceUserCredential.id != current_id)

            if q.first() is None:

                return username

        raise ValueError("username_not_available")

    def _generate_temp_password(self, length: int = 18) -> str:

        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%^&*"

        n = max(12, min(int(length), 64))

        return "".join(secrets.choice(alphabet) for _ in range(n))

    def _hash_password(self, password: str, *, iterations: int) -> tuple[str, str]:

        salt = secrets.token_bytes(16)

        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))

        return (

            base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),

            base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),

        )

    def get_user_credential(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, actor: str) -> dict[str, Any] | None:
        return user_domain_ops.get_user_credential(
            self,
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            user_id=user_id,
            actor=actor,
        )

    def issue_user_credentials(
        self,
        db: Session,
        *,
        workspace_type: str,
        workspace_id: str,
        user_id: str,
        actor: str,
        payload: dict[str, Any],
        reset_existing: bool = False,
    ) -> dict[str, Any]:
        return user_domain_ops.issue_user_credentials(
            self,
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            user_id=user_id,
            actor=actor,
            payload=payload,
            reset_existing=reset_existing,
        )

    def reset_user_password(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:
        return user_domain_ops.reset_user_password(
            self,
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            user_id=user_id,
            actor=actor,
            payload=payload,
        )

    def issue_user_invite(
        self,
        db: Session,
        *,
        workspace_type: str,
        workspace_id: str,
        user_id: str,
        actor: str,
        payload: dict[str, Any],
        reset_existing: bool = False,
    ) -> dict[str, Any]:
        return user_domain_ops.issue_user_invite(
            self,
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            user_id=user_id,
            actor=actor,
            payload=payload,
            reset_existing=reset_existing,
        )

    def lock_user_credential(
        self,
        db: Session,
        *,
        workspace_type: str,
        workspace_id: str,
        user_id: str,
        actor: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return user_domain_ops.lock_user_credential(
            self,
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            user_id=user_id,
            actor=actor,
            payload=payload,
        )

    def unlock_user_credential(
        self,
        db: Session,
        *,
        workspace_type: str,
        workspace_id: str,
        user_id: str,
        actor: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return user_domain_ops.unlock_user_credential(
            self,
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            user_id=user_id,
            actor=actor,
            payload=payload,
        )

    def revoke_user_invite(
        self,
        db: Session,
        *,
        workspace_type: str,
        workspace_id: str,
        user_id: str,
        actor: str,
    ) -> dict[str, Any]:
        return user_domain_ops.revoke_user_invite(
            self,
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            user_id=user_id,
            actor=actor,
        )


