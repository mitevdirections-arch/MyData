from __future__ import annotations

from datetime import datetime, timezone
import uuid
import re
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.authz_fast_path import (
    recompute_effective_permissions_for_role,
    upsert_effective_permissions_snapshot,
)
from app.core.settings import get_settings

from app.db.models import (
    AdminProfile,
    DeviceLease,
    License,
    Tenant,
    WorkspaceAddress,
    WorkspaceContactPoint,
    WorkspaceOrganizationProfile,
    WorkspaceRole,
    WorkspaceUser,
    WorkspaceUserRole,
)
from app.modules.profile.service_constants import (
    CORE_PLAN_SEATS,
    DEFAULT_PLATFORM_ROLES,
    DEFAULT_TENANT_ROLES,
    PERM_RE,
    PLATFORM_WORKSPACE_ID,
    ROLE_CODE_RE,
    UNLIMITED_CORE_PLANS,
    WORKSPACE_PLATFORM,
    WORKSPACE_TENANT,
)

class ProfileAdminProfileMixin:
    def _profile_to_dict(self, row: AdminProfile) -> dict[str, Any]:
        return {
            "id": str(row.id), "workspace_type": row.workspace_type, "workspace_id": row.workspace_id, "user_id": row.user_id,
            "display_name": row.display_name, "email": row.email, "phone": row.phone, "job_title": row.job_title, "avatar_url": row.avatar_url,
            "preferences": {"locale": row.preferred_locale, "time_zone": row.preferred_time_zone, "date_style": row.date_style, "time_style": row.time_style, "unit_system": row.unit_system},
            "notification_prefs": row.notification_prefs_json or {},
            "is_active": bool(row.is_active),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def get_or_create_admin_profile(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, actor: str) -> dict[str, Any]:
        self._ensure_workspace_exists(db, workspace_type=workspace_type, workspace_id=workspace_id)
        uid = self._clean_text(user_id, 255)
        if not uid:
            raise ValueError("user_id_required")
        row = db.query(AdminProfile).filter(AdminProfile.workspace_type == workspace_type, AdminProfile.workspace_id == workspace_id, AdminProfile.user_id == uid).first()
        if row is None:
            now = self._now()
            row = AdminProfile(
                workspace_type=workspace_type,
                workspace_id=workspace_id,
                user_id=uid,
                display_name=(uid.split("@", 1)[0] if "@" in uid else uid)[:255],
                email=(uid if "@" in uid else None),
                phone=None,
                job_title=None,
                avatar_url=None,
                preferred_locale="en",
                preferred_time_zone="UTC",
                date_style="YMD",
                time_style="H24",
                unit_system="metric",
                notification_prefs_json={},
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.flush()
        return self._profile_to_dict(row)

    def update_admin_profile(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.get_or_create_admin_profile(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=user_id, actor=actor)
        row = db.query(AdminProfile).filter(AdminProfile.workspace_type == workspace_type, AdminProfile.workspace_id == workspace_id, AdminProfile.user_id == user_id).first()
        if row is None:
            raise ValueError("profile_not_found")
        row.display_name = self._clean_text(payload.get("display_name"), 255)
        row.email = self._clean_text(payload.get("email"), 255)
        row.phone = self._clean_text(payload.get("phone"), 64)
        row.job_title = self._clean_text(payload.get("job_title"), 128)
        row.avatar_url = self._clean_text(payload.get("avatar_url"), 1024)
        prefs = payload.get("preferences") if isinstance(payload.get("preferences"), dict) else {}
        row.preferred_locale = self._clean_text(prefs.get("locale"), 32) or row.preferred_locale
        row.preferred_time_zone = self._clean_text(prefs.get("time_zone"), 64) or row.preferred_time_zone
        row.date_style = self._clean_date_style(prefs.get("date_style"), default=row.date_style)
        row.time_style = self._clean_time_style(prefs.get("time_style"), default=row.time_style)
        row.unit_system = self._clean_unit_system(prefs.get("unit_system"), default=row.unit_system)
        if isinstance(payload.get("notification_prefs"), dict):
            row.notification_prefs_json = dict(payload.get("notification_prefs") or {})
        row.updated_at = self._now()
        db.flush()
        return self._profile_to_dict(row)
