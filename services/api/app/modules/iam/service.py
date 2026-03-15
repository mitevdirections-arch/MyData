from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.permissions import dedupe_permissions, is_permission_allowed, list_permission_registry, list_role_templates
from app.db.models import WorkspaceRole, WorkspaceUser, WorkspaceUserRole
from app.modules.licensing.service import service as licensing_service
from app.modules.profile.service import WORKSPACE_TENANT, service as profile_service


class IAMService:
    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _clean(self, value: Any, max_len: int = 255) -> str:
        return str(value or "").strip()[:max_len]

    def _resolve_scope(self, claims: dict[str, Any], workspace: str | None) -> tuple[str, str]:
        return profile_service.resolve_workspace(claims, workspace=workspace)

    def _user_effective_permissions(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, token_perms: list[Any] | None) -> dict[str, Any]:
        uid = self._clean(user_id)
        if not uid:
            raise ValueError("user_id_required")

        user = (
            db.query(WorkspaceUser)
            .filter(
                WorkspaceUser.workspace_type == workspace_type,
                WorkspaceUser.workspace_id == workspace_id,
                WorkspaceUser.user_id == uid,
            )
            .first()
        )

        direct = dedupe_permissions((user.direct_permissions_json if user is not None else []) or [])

        role_codes = [
            x.role_code
            for x in (
                db.query(WorkspaceUserRole)
                .filter(
                    WorkspaceUserRole.workspace_type == workspace_type,
                    WorkspaceUserRole.workspace_id == workspace_id,
                    WorkspaceUserRole.user_id == uid,
                )
                .order_by(WorkspaceUserRole.role_code.asc())
                .all()
            )
        ]

        role_perms: list[str] = []
        if role_codes:
            role_rows = (
                db.query(WorkspaceRole)
                .filter(
                    WorkspaceRole.workspace_type == workspace_type,
                    WorkspaceRole.workspace_id == workspace_id,
                    WorkspaceRole.role_code.in_(role_codes),
                )
                .all()
            )
            for rr in role_rows:
                role_perms.extend(list(rr.permissions_json or []))

        token_permissions = dedupe_permissions(list(token_perms or []))

        effective = dedupe_permissions([*direct, *role_perms, *token_permissions])

        return {
            "user_id": uid,
            "roles": role_codes,
            "direct_permissions": direct,
            "role_permissions": dedupe_permissions(role_perms),
            "token_permissions": token_permissions,
            "effective_permissions": effective,
        }

    def _entitlements_v2(self, db: Session, *, workspace_type: str, workspace_id: str) -> dict[str, Any] | None:
        if workspace_type != WORKSPACE_TENANT:
            return None
        return licensing_service.entitlement_snapshot_v2(db=db, tenant_id=workspace_id)

    def me_access(self, db: Session, *, claims: dict[str, Any], workspace: str | None) -> dict[str, Any]:
        wtype, wid = self._resolve_scope(claims, workspace)
        user_id = self._clean(claims.get("sub"))

        perms = self._user_effective_permissions(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=user_id,
            token_perms=list(claims.get("perms") or []),
        )

        registry = list_permission_registry(workspace_type=wtype)
        templates = list_role_templates(workspace_type=wtype)
        ent_v2 = self._entitlements_v2(db, workspace_type=wtype, workspace_id=wid)

        return {
            "workspace_type": wtype,
            "workspace_id": wid,
            "identity": {
                "sub": user_id,
                "roles_claim": [str(x) for x in list(claims.get("roles") or [])],
            },
            "permissions": perms,
            "permission_registry_count": len(registry),
            "role_templates_count": len(templates),
            "entitlements_v2": ent_v2,
            "generated_at": self._now().isoformat(),
        }

    def check_permission(self, db: Session, *, claims: dict[str, Any], workspace: str | None, permission_code: str) -> dict[str, Any]:
        req = self._clean(permission_code, 96).upper()
        if not req:
            raise ValueError("permission_code_required")

        access = self.me_access(db, claims=claims, workspace=workspace)
        effective = list((access.get("permissions") or {}).get("effective_permissions") or [])
        allowed = is_permission_allowed(req, effective)

        return {
            "workspace_type": access.get("workspace_type"),
            "workspace_id": access.get("workspace_id"),
            "permission_code": req,
            "allowed": bool(allowed),
            "effective_permissions": effective,
        }


service = IAMService()