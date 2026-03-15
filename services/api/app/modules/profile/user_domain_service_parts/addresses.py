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

class UserDomainAddressesMixin:
    def list_user_addresses(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, actor: str, limit: int = 500) -> list[dict[str, Any]]:

        self.get_or_create_user_profile(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=user_id, actor=actor)

        wtype, wid = self._normalize_workspace(workspace_type, workspace_id)

        uid = str(user_id or "").strip()

        return [self._address_to_dict(x) for x in self._list_addresses_rows(db, workspace_type=wtype, workspace_id=wid, user_id=uid, limit=limit)]

    def upsert_user_address(

        self,

        db: Session,

        *,

        workspace_type: str,

        workspace_id: str,

        user_id: str,

        actor: str,

        payload: dict[str, Any],

        address_id: str | None = None,

    ) -> dict[str, Any]:

        self.get_or_create_user_profile(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=user_id, actor=actor)

        wtype, wid = self._normalize_workspace(workspace_type, workspace_id)

        uid = str(user_id or "").strip()



        existing_count = int(

            db.query(WorkspaceUserAddress)

            .filter(

                WorkspaceUserAddress.workspace_type == wtype,

                WorkspaceUserAddress.workspace_id == wid,

                WorkspaceUserAddress.user_id == uid,

            )

            .count()

        )



        row: WorkspaceUserAddress | None = None

        if address_id is not None:

            try:

                aid = uuid.UUID(str(address_id).strip())

            except Exception as exc:  # noqa: BLE001

                raise ValueError("address_id_invalid") from exc

            row = (

                db.query(WorkspaceUserAddress)

                .filter(

                    WorkspaceUserAddress.id == aid,

                    WorkspaceUserAddress.workspace_type == wtype,

                    WorkspaceUserAddress.workspace_id == wid,

                    WorkspaceUserAddress.user_id == uid,

                )

                .first()

            )

            if row is None:

                raise ValueError("user_address_not_found")



        now = self._now()

        if row is None:

            row = WorkspaceUserAddress(

                workspace_type=wtype,

                workspace_id=wid,

                user_id=uid,

                address_kind=(self._clean_text(payload.get("address_kind"), 32) or "HOME").upper(),

                label=self._clean_text(payload.get("label"), 128),

                country_code=self._clean_text(payload.get("country_code"), 8),

                line1=self._clean_text(payload.get("line1"), 255),

                line2=self._clean_text(payload.get("line2"), 255),

                city=self._clean_text(payload.get("city"), 128),

                postal_code=self._clean_text(payload.get("postal_code"), 32),

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

            if "address_kind" in payload:

                row.address_kind = (self._clean_text(payload.get("address_kind"), 32) or row.address_kind).upper()

            if "label" in payload:

                row.label = self._clean_text(payload.get("label"), 128)

            if "country_code" in payload:

                row.country_code = self._clean_text(payload.get("country_code"), 8)

            if "line1" in payload:

                row.line1 = self._clean_text(payload.get("line1"), 255)

            if "line2" in payload:

                row.line2 = self._clean_text(payload.get("line2"), 255)

            if "city" in payload:

                row.city = self._clean_text(payload.get("city"), 128)

            if "postal_code" in payload:

                row.postal_code = self._clean_text(payload.get("postal_code"), 32)

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

        if bool(row.is_primary):

            (

                db.query(WorkspaceUserAddress)

                .filter(

                    WorkspaceUserAddress.workspace_type == wtype,

                    WorkspaceUserAddress.workspace_id == wid,

                    WorkspaceUserAddress.user_id == uid,

                    WorkspaceUserAddress.id != row.id,

                )

                .update({WorkspaceUserAddress.is_primary: False}, synchronize_session=False)

            )

            db.flush()

        return self._address_to_dict(row)

    def delete_user_address(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, actor: str, address_id: str) -> dict[str, Any]:

        self.get_or_create_user_profile(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=user_id, actor=actor)

        wtype, wid = self._normalize_workspace(workspace_type, workspace_id)

        uid = str(user_id or "").strip()

        try:

            aid = uuid.UUID(str(address_id).strip())

        except Exception as exc:  # noqa: BLE001

            raise ValueError("address_id_invalid") from exc



        row = (

            db.query(WorkspaceUserAddress)

            .filter(

                WorkspaceUserAddress.id == aid,

                WorkspaceUserAddress.workspace_type == wtype,

                WorkspaceUserAddress.workspace_id == wid,

                WorkspaceUserAddress.user_id == uid,

            )

            .first()

        )

        if row is None:

            raise ValueError("user_address_not_found")

        out = self._address_to_dict(row)

        db.delete(row)

        db.flush()

        return out
