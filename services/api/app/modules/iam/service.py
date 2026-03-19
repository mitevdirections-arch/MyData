from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import time
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.perf_profile import get_recorded_segment, record_segment
from app.core.permissions import dedupe_permissions, is_permission_allowed, list_permission_registry, list_role_templates
from app.core.perf_sql_trace import sql_trace_zone
from app.db.models import WorkspaceRole, WorkspaceUser, WorkspaceUserRole
from app.modules.licensing.service import service as licensing_service
from app.modules.profile.service import WORKSPACE_TENANT, service as profile_service

IAM_SQL_BREAKDOWN_ENV = "MYDATA_PERF_IAM_SQL_BREAKDOWN"
IAM_ZONE_USER = "iam_user"
IAM_ZONE_ROLES = "iam_roles"
IAM_ZONE_ENTITLEMENT = "iam_entitlement"


class IAMService:
    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _clean(self, value: Any, max_len: int = 255) -> str:
        return str(value or "").strip()[:max_len]

    def _resolve_scope(self, claims: dict[str, Any], workspace: str | None) -> tuple[str, str]:
        return profile_service.resolve_workspace(claims, workspace=workspace)

    def _iam_sql_breakdown_enabled(self) -> bool:
        raw = str(os.getenv(IAM_SQL_BREAKDOWN_ENV, "0")).strip().lower()
        return raw in {"1", "true", "yes", "on"}

    def _zone_metric(self, *, metric: str, zone: str) -> float:
        return max(0.0, float(get_recorded_segment(f"{metric}_{zone}")))

    def _record_zone_delta(
        self,
        *,
        zone: str,
        before_count: float,
        before_ms: float,
        alias_count_key: str,
        alias_ms_key: str,
    ) -> None:
        after_count = self._zone_metric(metric="sql_query_count", zone=zone)
        after_ms = self._zone_metric(metric="sql_query_ms", zone=zone)
        record_segment(alias_count_key, max(0.0, after_count - before_count))
        record_segment(alias_ms_key, max(0.0, after_ms - before_ms))

    def _user_effective_permissions(self, db: Session, *, workspace_type: str, workspace_id: str, user_id: str, token_perms: list[Any] | None) -> dict[str, Any]:
        uid = self._clean(user_id)
        if not uid:
            raise ValueError("user_id_required")

        breakdown = self._iam_sql_breakdown_enabled()

        user_count_before = self._zone_metric(metric="sql_query_count", zone=IAM_ZONE_USER)
        user_ms_before = self._zone_metric(metric="sql_query_ms", zone=IAM_ZONE_USER)
        user_started = time.perf_counter()
        with sql_trace_zone(IAM_ZONE_USER if breakdown else None):
            user = (
                db.query(WorkspaceUser)
                .filter(
                    WorkspaceUser.workspace_type == workspace_type,
                    WorkspaceUser.workspace_id == workspace_id,
                    WorkspaceUser.user_id == uid,
                )
                .first()
            )
        if breakdown:
            record_segment("iam_user_phase_ms", (time.perf_counter() - user_started) * 1000.0)
            self._record_zone_delta(
                zone=IAM_ZONE_USER,
                before_count=user_count_before,
                before_ms=user_ms_before,
                alias_count_key="iam_user_sql_query_count",
                alias_ms_key="iam_user_sql_query_ms",
            )

        direct = dedupe_permissions((user.direct_permissions_json if user is not None else []) or [])

        roles_count_before = self._zone_metric(metric="sql_query_count", zone=IAM_ZONE_ROLES)
        roles_ms_before = self._zone_metric(metric="sql_query_ms", zone=IAM_ZONE_ROLES)
        roles_started = time.perf_counter()
        with sql_trace_zone(IAM_ZONE_ROLES if breakdown else None):
            role_rows = db.execute(
                select(
                    WorkspaceUserRole.role_code,
                    WorkspaceRole.permissions_json,
                )
                .select_from(WorkspaceUserRole)
                .outerjoin(
                    WorkspaceRole,
                    and_(
                        WorkspaceRole.workspace_type == WorkspaceUserRole.workspace_type,
                        WorkspaceRole.workspace_id == WorkspaceUserRole.workspace_id,
                        WorkspaceRole.role_code == WorkspaceUserRole.role_code,
                    ),
                )
                .where(
                    WorkspaceUserRole.workspace_type == workspace_type,
                    WorkspaceUserRole.workspace_id == workspace_id,
                    WorkspaceUserRole.user_id == uid,
                )
                .order_by(WorkspaceUserRole.role_code.asc())
            ).all()

            role_codes = [str(role_code) for role_code, _permissions_json in role_rows]
            role_perms: list[str] = []
            for _role_code, permissions_json in role_rows:
                if permissions_json:
                    role_perms.extend(list(permissions_json))
        if breakdown:
            record_segment("iam_roles_phase_ms", (time.perf_counter() - roles_started) * 1000.0)
            self._record_zone_delta(
                zone=IAM_ZONE_ROLES,
                before_count=roles_count_before,
                before_ms=roles_ms_before,
                alias_count_key="iam_roles_sql_query_count",
                alias_ms_key="iam_roles_sql_query_ms",
            )

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
        breakdown = self._iam_sql_breakdown_enabled()
        entitlement_count_before = self._zone_metric(metric="sql_query_count", zone=IAM_ZONE_ENTITLEMENT)
        entitlement_ms_before = self._zone_metric(metric="sql_query_ms", zone=IAM_ZONE_ENTITLEMENT)
        entitlement_started = time.perf_counter()
        with sql_trace_zone(IAM_ZONE_ENTITLEMENT if breakdown else None):
            snapshot = licensing_service.entitlement_snapshot_v2(db=db, tenant_id=workspace_id)
        if breakdown:
            record_segment("iam_entitlement_phase_ms", (time.perf_counter() - entitlement_started) * 1000.0)
            self._record_zone_delta(
                zone=IAM_ZONE_ENTITLEMENT,
                before_count=entitlement_count_before,
                before_ms=entitlement_ms_before,
                alias_count_key="iam_entitlement_sql_query_count",
                alias_ms_key="iam_entitlement_sql_query_ms",
            )
        return snapshot

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
