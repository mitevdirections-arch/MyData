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
from app.modules.profile.service_constants import PLATFORM_WORKSPACE_ID, WORKSPACE_PLATFORM, WORKSPACE_TENANT

class UsersSharedMixin:
    USERNAME_SAFE_RE = re.compile(r"[^a-z0-9._-]+")
    CONTACT_CHANNEL_TYPES = {
        "WORK_EMAIL",
        "PERSONAL_EMAIL",
        "WORK_PHONE",
        "PERSONAL_PHONE",
        "WORK_MESSENGER",
        "PERSONAL_MESSENGER",
        "EMERGENCY_PHONE",
        "OTHER",
    }

    def _now(self) -> datetime:

        return datetime.now(timezone.utc)

    def _clean_text(self, value: Any, max_len: int) -> str | None:

        if value is None:

            return None

        txt = str(value).strip()

        if not txt:

            return None

        return txt[:max_len]

    def _clean_sort_order(self, value: Any, default: int = 0) -> int:

        try:

            out = int(value)

        except Exception:  # noqa: BLE001

            return default

        if out < 0:

            return 0

        if out > 100000:

            return 100000

        return out

    def _normalize_contact_channel_type(self, value: Any, *, default: str = "WORK_EMAIL") -> str:

        txt = self._clean_text(value, 32)

        if not txt:

            txt = default

        normalized = str(txt).strip().upper().replace(" ", "_").replace("-", "_")

        if normalized in {"WORK", "WORK_CONTACT"}:

            normalized = "WORK_EMAIL"

        elif normalized in {"PERSONAL", "PRIVATE"}:

            normalized = "PERSONAL_EMAIL"

        if normalized not in self.CONTACT_CHANNEL_TYPES:

            return "OTHER"

        return normalized

    def _as_dict(self, value: Any) -> dict[str, Any]:

        return value if isinstance(value, dict) else {}

    def _normalize_workspace(self, workspace_type: str, workspace_id: str) -> tuple[str, str]:

        wtype = str(workspace_type or "").strip().upper()

        wid = str(workspace_id or "").strip()

        if wtype not in {WORKSPACE_TENANT, WORKSPACE_PLATFORM}:

            raise ValueError("workspace_type_invalid")

        if not wid:

            raise ValueError("workspace_id_required")

        if wtype == WORKSPACE_PLATFORM and wid != PLATFORM_WORKSPACE_ID:

            raise ValueError("platform_workspace_id_invalid")

        return wtype, wid[:64]

    def _ensure_workspace_exists(self, db: Session, *, workspace_type: str, workspace_id: str) -> None:

        wtype, wid = self._normalize_workspace(workspace_type, workspace_id)

        if wtype == WORKSPACE_PLATFORM:

            return

        if db.query(Tenant).filter(Tenant.id == wid).first() is None:

            raise ValueError("tenant_not_found")

    def _ensure_workspace_user(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, actor: str) -> WorkspaceUser:

        wtype, wid = self._normalize_workspace(workspace_type, workspace_id)

        uid = self._clean_text(user_id, 255)

        if not uid:

            raise ValueError("user_id_required")



        row = (

            db.query(WorkspaceUser)

            .filter(

                WorkspaceUser.workspace_type == wtype,

                WorkspaceUser.workspace_id == wid,

                WorkspaceUser.user_id == uid,

            )

            .first()

        )

        if row is not None:

            return row



        if wtype == WORKSPACE_TENANT:
            from app.modules.licensing.service import LicensingPolicyError, service as licensing_service

            try:
                licensing_service.assert_workspace_user_seat_available(
                    db,
                    tenant_id=wid,
                    user_id=uid,
                    exclude_user_id=uid,
                )
            except LicensingPolicyError as exc:
                code = str(exc.code or "").strip().upper()
                if code == "CORE_REQUIRED":
                    raise ValueError("core_required") from exc
                if code == "CORE_SEAT_LIMIT_EXCEEDED":
                    raise ValueError("core_seat_limit_exceeded") from exc
                raise ValueError("licensing_policy_denied") from exc

        now = self._now()

        row = WorkspaceUser(

            workspace_type=wtype,

            workspace_id=wid,

            user_id=uid,

            email=(uid if "@" in uid else None),

            display_name=(uid.split("@", 1)[0] if "@" in uid else uid)[:255],

            job_title=None,

            department=None,

            employment_status="ACTIVE",

            direct_permissions_json=[],

            meta_json={},

            created_by=str(actor or "unknown"),

            updated_by=str(actor or "unknown"),

            created_at=now,

            updated_at=now,

        )

        db.add(row)

        db.flush()

        return row

    def _require_workspace_user(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str) -> WorkspaceUser:

        wtype, wid = self._normalize_workspace(workspace_type, workspace_id)

        uid = self._clean_text(user_id, 255)

        if not uid:

            raise ValueError("user_id_required")

        row = (

            db.query(WorkspaceUser)

            .filter(

                WorkspaceUser.workspace_type == wtype,

                WorkspaceUser.workspace_id == wid,

                WorkspaceUser.user_id == uid,

            )

            .first()

        )

        if row is None:

            raise ValueError("user_membership_required")

        return row

    def _parse_datetime(self, value: Any) -> datetime | None:

        if value is None:

            return None

        if isinstance(value, datetime):

            dt = value

        else:

            txt = str(value).strip()

            if not txt:

                return None

            dt = datetime.fromisoformat(txt.replace("Z", "+00:00"))

        if dt.tzinfo is None:

            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    def _contact_to_dict(self, row: WorkspaceUserContactChannel) -> dict[str, Any]:

        return {

            "id": str(row.id),

            "channel_type": row.channel_type,

            "label": row.label,

            "value": row.value,

            "is_primary": bool(row.is_primary),

            "is_public": bool(row.is_public),

            "sort_order": int(row.sort_order or 0),

            "metadata": row.metadata_json or {},

            "updated_by": row.updated_by,

            "updated_at": row.updated_at.isoformat() if row.updated_at else None,

        }

    def _address_to_dict(self, row: WorkspaceUserAddress) -> dict[str, Any]:

        return {

            "id": str(row.id),

            "address_kind": row.address_kind,

            "label": row.label,

            "country_code": row.country_code,

            "line1": row.line1,

            "line2": row.line2,

            "city": row.city,

            "postal_code": row.postal_code,

            "is_primary": bool(row.is_primary),

            "is_public": bool(row.is_public),

            "sort_order": int(row.sort_order or 0),

            "metadata": row.metadata_json or {},

            "updated_by": row.updated_by,

            "updated_at": row.updated_at.isoformat() if row.updated_at else None,

        }

    def _doc_to_dict(self, row: WorkspaceUserDocument) -> dict[str, Any]:

        return {

            "id": str(row.id),

            "doc_kind": row.doc_kind,

            "title": row.title,

            "doc_number": row.doc_number,

            "issuer": row.issuer,

            "country_code": row.country_code,

            "issued_on": row.issued_on.isoformat() if row.issued_on else None,

            "valid_from": row.valid_from.isoformat() if row.valid_from else None,

            "valid_until": row.valid_until.isoformat() if row.valid_until else None,

            "status": row.status,

            "storage": {

                "provider": row.storage_provider,

                "bucket": row.bucket,

                "object_key": row.object_key,

                "file_name": row.file_name,

                "mime_type": row.mime_type,

                "size_bytes": row.size_bytes,

                "sha256": row.sha256,

            },

            "metadata": row.metadata_json or {},

            "updated_by": row.updated_by,

            "updated_at": row.updated_at.isoformat() if row.updated_at else None,

        }

    def _credential_public_dict(self, row: WorkspaceUserCredential) -> dict[str, Any]:

        return {

            "id": str(row.id),

            "workspace_type": row.workspace_type,

            "workspace_id": row.workspace_id,

            "user_id": row.user_id,

            "username": row.username,

            "hash_alg": row.hash_alg,

            "hash_iterations": int(row.hash_iterations or 0),

            "must_change_password": bool(row.must_change_password),

            "status": row.status,

            "failed_attempts": int(row.failed_attempts or 0),

            "locked_until": row.locked_until.isoformat() if row.locked_until else None,

            "password_set_at": row.password_set_at.isoformat() if row.password_set_at else None,

            "password_expires_at": row.password_expires_at.isoformat() if row.password_expires_at else None,

            "last_login_at": row.last_login_at.isoformat() if row.last_login_at else None,

            "updated_by": row.updated_by,

            "updated_at": row.updated_at.isoformat() if row.updated_at else None,

        }

    def _next_of_kin_to_dict(self, row: WorkspaceUserNextOfKin) -> dict[str, Any]:

        return {

            "id": str(row.id),

            "full_name": row.full_name,

            "relation": row.relation,

            "contact": {

                "email": row.contact_email,

                "phone": row.contact_phone,

            },

            "address": {

                "country_code": row.address_country_code,

                "line1": row.address_line1,

                "line2": row.address_line2,

                "city": row.address_city,

                "postal_code": row.address_postal_code,

            },

            "is_primary": bool(row.is_primary),

            "sort_order": int(row.sort_order or 0),

            "metadata": row.metadata_json or {},

            "updated_by": row.updated_by,

            "updated_at": row.updated_at.isoformat() if row.updated_at else None,

        }

    def _profile_to_dict(self, row: WorkspaceUserProfile, *, contacts: list[dict[str, Any]], addresses: list[dict[str, Any]], documents: list[dict[str, Any]], next_of_kin: list[dict[str, Any]]) -> dict[str, Any]:

        payroll = {

            "account_holder": row.bank_account_holder,

            "iban": row.bank_iban,

            "swift": row.bank_swift,

            "bank_name": row.bank_name,

            "currency": row.bank_currency,

        }

        return {

            "id": str(row.id),

            "workspace_type": row.workspace_type,

            "workspace_id": row.workspace_id,

            "user_id": row.user_id,

            "identity": {

                "first_name": row.first_name,

                "last_name": row.last_name,

                "display_name": row.display_name,

                "date_of_birth": row.date_of_birth.isoformat() if row.date_of_birth else None,

                "employee_code": row.employee_code,

            },

            "contacts": {

                "email": row.contact_email,

                "phone": row.contact_phone,

            },

            "contact_channels": contacts,

            "address": {

                "country_code": row.address_country_code,

                "line1": row.address_line1,

                "line2": row.address_line2,

                "city": row.address_city,

                "postal_code": row.address_postal_code,

            },

            "addresses": addresses,

            "payroll": payroll,

            "banking": payroll,

            "employment": {

                "job_title": row.job_title,

                "department": row.department,

                "employment_status": row.employment_status,

            },

            "preferences": {

                "locale": row.preferred_locale,

                "time_zone": row.preferred_time_zone,

                "date_style": row.date_style,

                "time_style": row.time_style,

                "unit_system": row.unit_system,

            },

            "next_of_kin": next_of_kin,

            "documents": documents,

            "metadata": row.metadata_json or {},

            "updated_by": row.updated_by,

            "updated_at": row.updated_at.isoformat() if row.updated_at else None,

        }

    def _list_next_of_kin_rows(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, limit: int = 500) -> list[WorkspaceUserNextOfKin]:

        return (

            db.query(WorkspaceUserNextOfKin)

            .filter(

                WorkspaceUserNextOfKin.workspace_type == workspace_type,

                WorkspaceUserNextOfKin.workspace_id == workspace_id,

                WorkspaceUserNextOfKin.user_id == user_id,

            )

            .order_by(

                WorkspaceUserNextOfKin.is_primary.desc(),

                WorkspaceUserNextOfKin.sort_order.asc(),

                WorkspaceUserNextOfKin.created_at.asc(),

            )

            .limit(max(1, min(int(limit), 5000)))

            .all()

        )

    def _list_contacts_rows(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, limit: int = 500) -> list[WorkspaceUserContactChannel]:

        return (

            db.query(WorkspaceUserContactChannel)

            .filter(

                WorkspaceUserContactChannel.workspace_type == workspace_type,

                WorkspaceUserContactChannel.workspace_id == workspace_id,

                WorkspaceUserContactChannel.user_id == user_id,

            )

            .order_by(

                WorkspaceUserContactChannel.is_primary.desc(),

                WorkspaceUserContactChannel.sort_order.asc(),

                WorkspaceUserContactChannel.created_at.asc(),

            )

            .limit(max(1, min(int(limit), 5000)))

            .all()

        )

    def _list_addresses_rows(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, limit: int = 500) -> list[WorkspaceUserAddress]:

        return (

            db.query(WorkspaceUserAddress)

            .filter(

                WorkspaceUserAddress.workspace_type == workspace_type,

                WorkspaceUserAddress.workspace_id == workspace_id,

                WorkspaceUserAddress.user_id == user_id,

            )

            .order_by(

                WorkspaceUserAddress.is_primary.desc(),

                WorkspaceUserAddress.sort_order.asc(),

                WorkspaceUserAddress.created_at.asc(),

            )

            .limit(max(1, min(int(limit), 5000)))

            .all()

        )

    def _list_documents_rows(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, limit: int = 500) -> list[WorkspaceUserDocument]:

        return (

            db.query(WorkspaceUserDocument)

            .filter(

                WorkspaceUserDocument.workspace_type == workspace_type,

                WorkspaceUserDocument.workspace_id == workspace_id,

                WorkspaceUserDocument.user_id == user_id,

            )

            .order_by(WorkspaceUserDocument.updated_at.desc(), WorkspaceUserDocument.created_at.desc())

            .limit(max(1, min(int(limit), 5000)))

            .all()

        )


