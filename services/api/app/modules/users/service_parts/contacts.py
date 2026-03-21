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

class UsersContactsMixin:
    def list_user_contacts(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, actor: str, limit: int = 500) -> list[dict[str, Any]]:

        self.get_or_create_user_profile(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=user_id, actor=actor)

        wtype, wid = self._normalize_workspace(workspace_type, workspace_id)

        uid = str(user_id or "").strip()

        return [self._contact_to_dict(x) for x in self._list_contacts_rows(db, workspace_type=wtype, workspace_id=wid, user_id=uid, limit=limit)]

    def upsert_user_contact(

        self,

        db: Session,

        *,

        workspace_type: str,

        workspace_id: str,

        user_id: str,

        actor: str,

        payload: dict[str, Any],

        contact_id: str | None = None,

    ) -> dict[str, Any]:

        self.get_or_create_user_profile(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=user_id, actor=actor)

        wtype, wid = self._normalize_workspace(workspace_type, workspace_id)

        uid = str(user_id or "").strip()



        existing_count = int(

            db.query(WorkspaceUserContactChannel)

            .filter(

                WorkspaceUserContactChannel.workspace_type == wtype,

                WorkspaceUserContactChannel.workspace_id == wid,

                WorkspaceUserContactChannel.user_id == uid,

            )

            .count()

        )



        row: WorkspaceUserContactChannel | None = None

        if contact_id is not None:

            try:

                cid = uuid.UUID(str(contact_id).strip())

            except Exception as exc:  # noqa: BLE001

                raise ValueError("contact_id_invalid") from exc

            row = (

                db.query(WorkspaceUserContactChannel)

                .filter(

                    WorkspaceUserContactChannel.id == cid,

                    WorkspaceUserContactChannel.workspace_type == wtype,

                    WorkspaceUserContactChannel.workspace_id == wid,

                    WorkspaceUserContactChannel.user_id == uid,

                )

                .first()

            )

            if row is None:

                raise ValueError("user_contact_not_found")



        now = self._now()

        if row is None:

            value = self._clean_text(payload.get("value"), 255)

            if not value:

                raise ValueError("value_required")

            row = WorkspaceUserContactChannel(

                workspace_type=wtype,

                workspace_id=wid,

                user_id=uid,

                channel_type=self._normalize_contact_channel_type(payload.get("channel_type"), default=("WORK_EMAIL" if existing_count == 0 else "PERSONAL_EMAIL")),

                label=self._clean_text(payload.get("label"), 128),

                value=value,

                is_primary=bool(payload.get("is_primary", existing_count == 0)),

                is_public=bool(payload.get("is_public", False)),

                sort_order=self._clean_sort_order(payload.get("sort_order"), default=0),

                metadata_json=(dict(payload.get("metadata") or {}) if isinstance(payload.get("metadata"), dict) else {}),

                created_by=str(actor or "unknown"),

                updated_by=str(actor or "unknown"),

                created_at=now,

                updated_at=now,

            )

            db.add(row)

        else:

            if "channel_type" in payload:

                row.channel_type = self._normalize_contact_channel_type(payload.get("channel_type"), default=row.channel_type)

            if "label" in payload:

                row.label = self._clean_text(payload.get("label"), 128)

            if "value" in payload:

                val = self._clean_text(payload.get("value"), 255)

                if not val:

                    raise ValueError("value_required")

                row.value = val

            if "is_primary" in payload:

                row.is_primary = bool(payload.get("is_primary"))

            if "is_public" in payload:

                row.is_public = bool(payload.get("is_public"))

            if "sort_order" in payload:

                row.sort_order = self._clean_sort_order(payload.get("sort_order"), default=int(row.sort_order or 0))

            if "metadata" in payload and isinstance(payload.get("metadata"), dict):

                row.metadata_json = dict(payload.get("metadata") or {})

            row.updated_by = str(actor or "unknown")

            row.updated_at = now



        db.flush()
        self._enforce_exactly_one_primary(
            db,
            model=WorkspaceUserContactChannel,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=uid,
            actor=actor,
            preferred_id=(row.id if bool(row.is_primary) else None),
        )

        return self._contact_to_dict(row)

    def delete_user_contact(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, actor: str, contact_id: str) -> dict[str, Any]:

        self.get_or_create_user_profile(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=user_id, actor=actor)

        wtype, wid = self._normalize_workspace(workspace_type, workspace_id)

        uid = str(user_id or "").strip()

        try:

            cid = uuid.UUID(str(contact_id).strip())

        except Exception as exc:  # noqa: BLE001

            raise ValueError("contact_id_invalid") from exc



        row = (

            db.query(WorkspaceUserContactChannel)

            .filter(

                WorkspaceUserContactChannel.id == cid,

                WorkspaceUserContactChannel.workspace_type == wtype,

                WorkspaceUserContactChannel.workspace_id == wid,

                WorkspaceUserContactChannel.user_id == uid,

            )

            .first()

        )

        if row is None:

            raise ValueError("user_contact_not_found")

        out = self._contact_to_dict(row)
        db.delete(row)
        db.flush()
        self._enforce_exactly_one_primary(
            db,
            model=WorkspaceUserContactChannel,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=uid,
            actor=actor,
        )
        return out


