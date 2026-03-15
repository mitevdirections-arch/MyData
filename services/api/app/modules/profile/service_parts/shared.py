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

class ProfileSharedMixin:
    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _clean_text(self, value: Any, max_len: int) -> str | None:
        if value is None:
            return None
        txt = str(value).strip()
        return txt[:max_len] if txt else None

    def _clean_date_style(self, value: Any, default: str = "YMD") -> str:
        val = str(value or default).strip().upper()
        return val if val in {"YMD", "DMY", "MDY"} else default

    def _clean_time_style(self, value: Any, default: str = "H24") -> str:
        val = str(value or default).strip().upper()
        return val if val in {"H12", "H24"} else default

    def _clean_unit_system(self, value: Any, default: str = "metric") -> str:
        val = str(value or default).strip().lower()
        return val if val in {"metric", "imperial"} else default

    def _normalize_role_code(self, value: Any) -> str:
        raw = str(value or "").strip().upper()
        cleaned = ROLE_CODE_RE.sub("_", raw)
        cleaned = re.sub(r"_+", "_", cleaned).strip("_")
        if not cleaned:
            raise ValueError("role_code_required")
        return cleaned[:64]

    def _normalize_permissions(self, perms: list[Any] | None) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in list(perms or []):
            val = PERM_RE.sub("", str(raw or "").strip().upper())
            if not val or val in seen:
                continue
            seen.add(val)
            out.append(val[:96])
        return out

    def _authz_fast_path_source_version(self) -> int:
        return max(1, int(get_settings().authz_tenant_db_fast_path_source_version))

    def _recompute_effective_permissions_for_user(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, actor: str) -> None:
        upsert_effective_permissions_snapshot(
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            user_id=user_id,
            actor=actor,
            source_version=self._authz_fast_path_source_version(),
        )

    def _recompute_effective_permissions_for_role(self, db: Session, *, workspace_type: str, workspace_id: str, role_code: str, actor: str) -> None:
        recompute_effective_permissions_for_role(
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            role_code=role_code,
            actor=actor,
            source_version=self._authz_fast_path_source_version(),
        )

    def resolve_workspace(self, claims: dict[str, Any], workspace: str | None = None) -> tuple[str, str]:
        roles = set(claims.get("roles") or [])
        tenant_id = str(claims.get("tenant_id") or "").strip()
        requested = str(workspace or "").strip().upper()
        if requested and requested not in {"TENANT", "PLATFORM", "AUTO"}:
            raise ValueError("workspace_invalid")

        if requested in {"", "AUTO"}:
            if "SUPERADMIN" in roles:
                return WORKSPACE_PLATFORM, PLATFORM_WORKSPACE_ID
            if tenant_id:
                return WORKSPACE_TENANT, tenant_id
            raise ValueError("missing_tenant_context")

        if requested == "PLATFORM":
            if "SUPERADMIN" not in roles:
                raise ValueError("platform_workspace_requires_superadmin")
            return WORKSPACE_PLATFORM, PLATFORM_WORKSPACE_ID

        if not tenant_id:
            raise ValueError("missing_tenant_context")
        if "SUPERADMIN" in roles:
            support_tenant_id = str(claims.get("support_tenant_id") or "").strip()
            support_session_id = str(claims.get("support_session_id") or "").strip()
            if support_tenant_id != tenant_id or not support_session_id:
                raise ValueError("support_session_required_for_tenant_scope")
        if not ({"TENANT_ADMIN", "SUPERADMIN"} & roles):
            raise ValueError("tenant_admin_required")
        return WORKSPACE_TENANT, tenant_id

    def _ensure_workspace_exists(self, db: Session, *, workspace_type: str, workspace_id: str) -> None:
        if workspace_type not in {WORKSPACE_TENANT, WORKSPACE_PLATFORM}:
            raise ValueError("workspace_type_invalid")
        if not workspace_id:
            raise ValueError("workspace_id_required")
        if workspace_type == WORKSPACE_PLATFORM:
            if workspace_id != PLATFORM_WORKSPACE_ID:
                raise ValueError("platform_workspace_id_invalid")
            return
        if db.query(Tenant).filter(Tenant.id == workspace_id).first() is None:
            raise ValueError("tenant_not_found")

    def _ensure_default_roles(self, db: Session, *, workspace_type: str, workspace_id: str, actor: str) -> None:
        self._ensure_workspace_exists(db, workspace_type=workspace_type, workspace_id=workspace_id)
        exists = db.query(WorkspaceRole).filter(WorkspaceRole.workspace_type == workspace_type, WorkspaceRole.workspace_id == workspace_id, WorkspaceRole.is_system == True).count()  # noqa: E712
        if int(exists) > 0:
            return
        templates = DEFAULT_PLATFORM_ROLES if workspace_type == WORKSPACE_PLATFORM else DEFAULT_TENANT_ROLES
        now = self._now()
        for t in templates:
            db.add(WorkspaceRole(
                workspace_type=workspace_type,
                workspace_id=workspace_id,
                role_code=self._normalize_role_code(t.get("role_code")),
                role_name=self._clean_text(t.get("role_name"), 128) or "Role",
                description=None,
                permissions_json=self._normalize_permissions(list(t.get("permissions") or [])),
                is_system=True,
                created_by=str(actor or "system"),
                updated_by=str(actor or "system"),
                created_at=now,
                updated_at=now,
            ))
        db.flush()
