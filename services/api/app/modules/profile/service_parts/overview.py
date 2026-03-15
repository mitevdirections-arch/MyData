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

class ProfileOverviewMixin:
    def superadmin_platform_overview(self, db: Session, *, actor: str) -> dict[str, Any]:
        now = self._now()
        total_tenants = int(db.query(Tenant).count())
        active_tenants = int(db.query(Tenant).filter(Tenant.is_active == True).count())  # noqa: E712
        with_core = int(db.query(func.count(func.distinct(License.tenant_id))).filter(License.license_type == "CORE", License.status == "ACTIVE", License.valid_from <= now, License.valid_to >= now).scalar() or 0)
        with_startup = int(db.query(func.count(func.distinct(License.tenant_id))).filter(License.license_type == "STARTUP", License.status == "ACTIVE", License.valid_from <= now, License.valid_to >= now).scalar() or 0)
        active_modules = int(db.query(License).filter(License.status == "ACTIVE", License.valid_from <= now, License.valid_to >= now, License.license_type.in_(["MODULE", "MODULE_TRIAL"])).count())
        active_leased_users = int(db.query(DeviceLease).filter(DeviceLease.is_active == True).count())  # noqa: E712

        bucket = {"small_1_8": 0, "medium_9_24": 0, "large_25_45": 0, "enterprise_unlimited": 0, "unknown": 0}
        for _, plan in db.query(License.tenant_id, License.module_code).filter(License.license_type == "CORE", License.status == "ACTIVE", License.valid_from <= now, License.valid_to >= now).all():
            code = str(plan or "").strip().upper().replace("CORE_ENTERPRISE", "COREENTERPRISE")
            if code in UNLIMITED_CORE_PLANS:
                bucket["enterprise_unlimited"] += 1
                continue
            seats = CORE_PLAN_SEATS.get(code)
            if seats is None:
                bucket["unknown"] += 1
            elif seats <= 8:
                bucket["small_1_8"] += 1
            elif seats <= 24:
                bucket["medium_9_24"] += 1
            else:
                bucket["large_25_45"] += 1

        top_usage = db.query(DeviceLease.tenant_id, func.count(DeviceLease.user_id).label("active_users")).filter(DeviceLease.is_active == True).group_by(DeviceLease.tenant_id).order_by(func.count(DeviceLease.user_id).desc()).limit(10).all()  # noqa: E712
        top_tenants = [{"tenant_id": str(x.tenant_id), "active_users": int(x.active_users)} for x in top_usage]

        return {
            "ok": True,
            "requested_by": str(actor or "unknown"),
            "generated_at": now.isoformat(),
            "tenants": {"total": total_tenants, "active": active_tenants, "with_active_core": with_core, "with_active_startup": with_startup, "size_buckets": bucket},
            "usage": {"active_module_licenses": active_modules, "active_leased_users": active_leased_users, "top_tenants_by_active_users": top_tenants},
        }

