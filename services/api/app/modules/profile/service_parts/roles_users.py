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
    DEFAULT_PLATFORM_ROLES,
    DEFAULT_TENANT_ROLES,
    PERM_RE,
    PLATFORM_WORKSPACE_ID,
    ROLE_CODE_RE,
    WORKSPACE_PLATFORM,
    WORKSPACE_TENANT,
)

class ProfileRoleUserMixin:
    def _role_to_dict(self, row: WorkspaceRole) -> dict[str, Any]:
        return {
            "id": str(row.id), "workspace_type": row.workspace_type, "workspace_id": row.workspace_id,
            "role_code": row.role_code, "role_name": row.role_name, "description": row.description,
            "permissions": row.permissions_json or [], "is_system": bool(row.is_system),
            "updated_by": row.updated_by, "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def list_roles(self, db: Session, *, workspace_type: str, workspace_id: str, actor: str, limit: int = 500) -> list[dict[str, Any]]:
        self._ensure_default_roles(db, workspace_type=workspace_type, workspace_id=workspace_id, actor=actor)
        rows = db.query(WorkspaceRole).filter(WorkspaceRole.workspace_type == workspace_type, WorkspaceRole.workspace_id == workspace_id).order_by(WorkspaceRole.is_system.desc(), WorkspaceRole.role_code.asc()).limit(max(1, min(int(limit), 2000))).all()
        return [self._role_to_dict(x) for x in rows]

    def upsert_role(self, db: Session, *, workspace_type: str, workspace_id: str, role_code: str, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        self._ensure_default_roles(db, workspace_type=workspace_type, workspace_id=workspace_id, actor=actor)
        code = self._normalize_role_code(role_code)
        row = db.query(WorkspaceRole).filter(WorkspaceRole.workspace_type == workspace_type, WorkspaceRole.workspace_id == workspace_id, WorkspaceRole.role_code == code).first()
        now = self._now()
        if row is None:
            row = WorkspaceRole(
                workspace_type=workspace_type, workspace_id=workspace_id, role_code=code,
                role_name=self._clean_text(payload.get("role_name"), 128) or code,
                description=self._clean_text(payload.get("description"), 1024),
                permissions_json=self._normalize_permissions(list(payload.get("permissions") or [])),
                is_system=bool(payload.get("is_system", False)),
                created_by=str(actor or "unknown"), updated_by=str(actor or "unknown"), created_at=now, updated_at=now,
            )
            db.add(row)
            db.flush()
            self._recompute_effective_permissions_for_role(
                db,
                workspace_type=workspace_type,
                workspace_id=workspace_id,
                role_code=code,
                actor=actor,
            )
            return self._role_to_dict(row)
        if bool(row.is_system):
            raise ValueError("system_role_read_only")
        row.role_name = self._clean_text(payload.get("role_name"), 128) or row.role_name
        row.description = self._clean_text(payload.get("description"), 1024)
        if "permissions" in payload:
            row.permissions_json = self._normalize_permissions(list(payload.get("permissions") or []))
        row.updated_by = str(actor or "unknown")
        row.updated_at = now
        db.flush()
        self._recompute_effective_permissions_for_role(
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            role_code=code,
            actor=actor,
        )
        return self._role_to_dict(row)

    def delete_role(self, db: Session, *, workspace_type: str, workspace_id: str, role_code: str, actor: str) -> dict[str, Any]:
        self._ensure_default_roles(db, workspace_type=workspace_type, workspace_id=workspace_id, actor=actor)
        code = self._normalize_role_code(role_code)
        row = db.query(WorkspaceRole).filter(
            WorkspaceRole.workspace_type == workspace_type,
            WorkspaceRole.workspace_id == workspace_id,
            WorkspaceRole.role_code == code,
        ).first()
        if row is None:
            raise ValueError("role_not_found")
        if bool(row.is_system):
            raise ValueError("system_role_read_only")

        assignment_count = int(
            db.query(func.count(WorkspaceUserRole.id)).filter(
                WorkspaceUserRole.workspace_type == workspace_type,
                WorkspaceUserRole.workspace_id == workspace_id,
                WorkspaceUserRole.role_code == code,
            ).scalar()
            or 0
        )
        if assignment_count > 0:
            raise ValueError("role_in_use")

        out = self._role_to_dict(row)
        db.delete(row)
        db.flush()
        return out

    def _resolve_user_roles(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str) -> list[str]:
        rows = db.query(WorkspaceUserRole).filter(WorkspaceUserRole.workspace_type == workspace_type, WorkspaceUserRole.workspace_id == workspace_id, WorkspaceUserRole.user_id == user_id).order_by(WorkspaceUserRole.role_code.asc()).all()
        return [x.role_code for x in rows]

    def _resolve_effective_permissions(self, db: Session, *, workspace_type: str, workspace_id: str, user: WorkspaceUser, roles: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for p in list(user.direct_permissions_json or []):
            val = str(p or "").strip().upper()
            if val and val not in seen:
                seen.add(val)
                out.append(val)
        if roles:
            role_rows = db.query(WorkspaceRole).filter(WorkspaceRole.workspace_type == workspace_type, WorkspaceRole.workspace_id == workspace_id, WorkspaceRole.role_code.in_(roles)).all()
            for rr in role_rows:
                for p in list(rr.permissions_json or []):
                    val = str(p or "").strip().upper()
                    if val and val not in seen:
                        seen.add(val)
                        out.append(val)
        return out

    def _user_to_dict(self, row: WorkspaceUser, *, roles: list[str], effective_permissions: list[str]) -> dict[str, Any]:
        return {
            "id": str(row.id), "workspace_type": row.workspace_type, "workspace_id": row.workspace_id, "user_id": row.user_id,
            "email": row.email, "display_name": row.display_name, "job_title": row.job_title, "department": row.department,
            "employment_status": row.employment_status, "direct_permissions": row.direct_permissions_json or [],
            "roles": roles, "effective_permissions": effective_permissions, "meta": row.meta_json or {},
            "updated_by": row.updated_by, "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def list_workspace_users(self, db: Session, *, workspace_type: str, workspace_id: str, actor: str, limit: int = 200) -> list[dict[str, Any]]:
        self._ensure_default_roles(db, workspace_type=workspace_type, workspace_id=workspace_id, actor=actor)
        rows = db.query(WorkspaceUser).filter(WorkspaceUser.workspace_type == workspace_type, WorkspaceUser.workspace_id == workspace_id).order_by(WorkspaceUser.updated_at.desc(), WorkspaceUser.created_at.desc()).limit(max(1, min(int(limit), 1000))).all()
        out: list[dict[str, Any]] = []
        for row in rows:
            roles = self._resolve_user_roles(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=row.user_id)
            perms = self._resolve_effective_permissions(db, workspace_type=workspace_type, workspace_id=workspace_id, user=row, roles=roles)
            out.append(self._user_to_dict(row, roles=roles, effective_permissions=perms))
        return out

    def upsert_workspace_user(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        self._ensure_default_roles(db, workspace_type=workspace_type, workspace_id=workspace_id, actor=actor)
        uid = self._clean_text(user_id, 255)
        if not uid:
            raise ValueError("user_id_required")
        row = db.query(WorkspaceUser).filter(WorkspaceUser.workspace_type == workspace_type, WorkspaceUser.workspace_id == workspace_id, WorkspaceUser.user_id == uid).first()
        now = self._now()
        requested_employment_status = (
            self._clean_text(payload.get("employment_status"), 32)
            or (row.employment_status if row is not None else "ACTIVE")
        ).upper()

        should_consume_seat = (
            workspace_type == WORKSPACE_TENANT
            and requested_employment_status == "ACTIVE"
            and (row is None or str(row.employment_status or "").upper() != "ACTIVE")
        )
        if should_consume_seat:
            from app.modules.licensing.service import LicensingPolicyError, service as licensing_service

            try:
                licensing_service.assert_workspace_user_seat_available(
                    db,
                    tenant_id=workspace_id,
                    user_id=uid,
                    exclude_user_id=uid,
                )
            except LicensingPolicyError:
                raise

        if row is None:
            row = WorkspaceUser(
                workspace_type=workspace_type, workspace_id=workspace_id, user_id=uid,
                email=self._clean_text(payload.get("email"), 255),
                display_name=self._clean_text(payload.get("display_name"), 255) or (uid.split("@", 1)[0] if "@" in uid else uid)[:255],
                job_title=self._clean_text(payload.get("job_title"), 128), department=self._clean_text(payload.get("department"), 128),
                employment_status=requested_employment_status,
                direct_permissions_json=self._normalize_permissions(list(payload.get("direct_permissions") or [])),
                meta_json=(dict(payload.get("meta") or {}) if isinstance(payload.get("meta"), dict) else {}),
                created_by=str(actor or "unknown"), updated_by=str(actor or "unknown"), created_at=now, updated_at=now,
            )
            db.add(row)
        else:
            row.email = self._clean_text(payload.get("email"), 255)
            row.display_name = self._clean_text(payload.get("display_name"), 255) or row.display_name
            row.job_title = self._clean_text(payload.get("job_title"), 128)
            row.department = self._clean_text(payload.get("department"), 128)
            row.employment_status = requested_employment_status
            if "direct_permissions" in payload:
                row.direct_permissions_json = self._normalize_permissions(list(payload.get("direct_permissions") or []))
            if isinstance(payload.get("meta"), dict):
                row.meta_json = dict(payload.get("meta") or {})
            row.updated_by = str(actor or "unknown")
            row.updated_at = now
        db.flush()
        self._recompute_effective_permissions_for_user(
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            user_id=uid,
            actor=actor,
        )
        roles = self._resolve_user_roles(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=uid)
        perms = self._resolve_effective_permissions(db, workspace_type=workspace_type, workspace_id=workspace_id, user=row, roles=roles)
        return self._user_to_dict(row, roles=roles, effective_permissions=perms)

    def get_workspace_user(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, actor: str) -> dict[str, Any]:
        self._ensure_default_roles(db, workspace_type=workspace_type, workspace_id=workspace_id, actor=actor)
        row = db.query(WorkspaceUser).filter(WorkspaceUser.workspace_type == workspace_type, WorkspaceUser.workspace_id == workspace_id, WorkspaceUser.user_id == str(user_id or "").strip()).first()
        if row is None:
            raise ValueError("workspace_user_not_found")
        roles = self._resolve_user_roles(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=row.user_id)
        perms = self._resolve_effective_permissions(db, workspace_type=workspace_type, workspace_id=workspace_id, user=row, roles=roles)
        return self._user_to_dict(row, roles=roles, effective_permissions=perms)

    def set_workspace_user_roles(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, role_codes: list[Any], actor: str) -> dict[str, Any]:
        uid = self._clean_text(user_id, 255)
        if not uid:
            raise ValueError("user_id_required")
        self._ensure_default_roles(db, workspace_type=workspace_type, workspace_id=workspace_id, actor=actor)
        user = db.query(WorkspaceUser).filter(WorkspaceUser.workspace_type == workspace_type, WorkspaceUser.workspace_id == workspace_id, WorkspaceUser.user_id == uid).first()
        if user is None:
            raise ValueError("user_membership_required")

        requested_codes: list[str] = []
        seen: set[str] = set()
        for raw in list(role_codes or []):
            code = self._normalize_role_code(raw)
            if code in seen:
                continue
            seen.add(code)
            requested_codes.append(code)
        if requested_codes:
            found_codes = {x.role_code for x in db.query(WorkspaceRole).filter(WorkspaceRole.workspace_type == workspace_type, WorkspaceRole.workspace_id == workspace_id, WorkspaceRole.role_code.in_(requested_codes)).all()}
            missing = [c for c in requested_codes if c not in found_codes]
            if missing:
                raise ValueError(f"role_not_found:{','.join(missing)}")

        db.query(WorkspaceUserRole).filter(WorkspaceUserRole.workspace_type == workspace_type, WorkspaceUserRole.workspace_id == workspace_id, WorkspaceUserRole.user_id == uid).delete(synchronize_session=False)
        now = self._now()
        for code in requested_codes:
            db.add(WorkspaceUserRole(workspace_type=workspace_type, workspace_id=workspace_id, user_id=uid, role_code=code, assigned_by=str(actor or "unknown"), assigned_at=now))
        user.updated_by = str(actor or "unknown")
        user.updated_at = now
        db.flush()
        self._recompute_effective_permissions_for_user(
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            user_id=uid,
            actor=actor,
        )
        roles = self._resolve_user_roles(db, workspace_type=workspace_type, workspace_id=workspace_id, user_id=uid)
        perms = self._resolve_effective_permissions(db, workspace_type=workspace_type, workspace_id=workspace_id, user=user, roles=roles)
        return self._user_to_dict(user, roles=roles, effective_permissions=perms)
