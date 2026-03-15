from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from app.db.models import (
    DeviceLease,
    GuardBehaviorState,
    GuardBotCheck,
    GuardBotCredential,
    GuardBotNonce,
    GuardHeartbeat,
    Incident,
    License,
    LicenseIssueRequest,
    LicenseIssuancePolicy,
    Order,
    SecurityAlertQueue,
    StorageDeleteQueue,
    StorageGrant,
    StorageObjectMeta,
    SupportMessage,
    SupportRequest,
    SupportSession,
)

TENANT_RLS_MODELS = (
    License,
    LicenseIssuancePolicy,
    LicenseIssueRequest,
    Order,
    SecurityAlertQueue,
    GuardHeartbeat,
    GuardBehaviorState,
    GuardBotCheck,
    GuardBotCredential,
    GuardBotNonce,
    DeviceLease,
    StorageObjectMeta,
    Incident,
    SupportRequest,
    SupportSession,
    SupportMessage,
    StorageGrant,
    StorageDeleteQueue,
)


class RLSScopeViolationError(RuntimeError):
    pass


def _claim_roles(claims: dict[str, Any]) -> set[str]:
    return {str(x).strip().upper() for x in list(claims.get("roles") or []) if str(x).strip()}


def resolve_rls_tenant_id(claims: dict[str, Any]) -> str | None:
    roles = _claim_roles(claims)
    token_tenant = str(claims.get("tenant_id") or "").strip()

    if "SUPERADMIN" in roles:
        support_tenant = str(claims.get("support_tenant_id") or "").strip()
        support_session = str(claims.get("support_session_id") or "").strip()
        if support_tenant and support_session:
            return support_tenant
        return None

    return token_tenant or None


def rls_context_from_claims(claims: dict[str, Any]) -> dict[str, Any]:
    tenant_id = resolve_rls_tenant_id(claims)
    roles = sorted(_claim_roles(claims))
    if tenant_id:
        mode = "TENANT_SCOPED"
    elif "SUPERADMIN" in set(roles):
        mode = "SUPERADMIN_GLOBAL"
    else:
        mode = "UNSCOPED"
    return {
        "mode": mode,
        "tenant_id": tenant_id,
        "roles": roles,
    }


def bind_rls_context(db: Session, claims: dict[str, Any], *, enabled: bool = True) -> dict[str, Any]:
    ctx = rls_context_from_claims(claims)
    db.info["rls_enabled"] = bool(enabled)
    db.info["rls_tenant_id"] = ctx.get("tenant_id")
    db.info["rls_mode"] = ctx.get("mode")
    db.info["rls_roles"] = ctx.get("roles")
    db.info["rls_bypass"] = bool(ctx.get("mode") == "SUPERADMIN_GLOBAL")
    return ctx


def _extract_write_scope(obj: Any) -> tuple[str | None, str | None]:
    if hasattr(obj, "tenant_id"):
        return "TENANT", str(getattr(obj, "tenant_id") or "").strip() or None

    if hasattr(obj, "workspace_type") and hasattr(obj, "workspace_id"):
        wtype = str(getattr(obj, "workspace_type") or "").strip().upper()
        wid = str(getattr(obj, "workspace_id") or "").strip() or None
        if wtype in {"TENANT", "PLATFORM"}:
            return wtype, wid

    return None, None


def validate_tenant_write_scope(
    *,
    rls_enabled: bool,
    rls_bypass: bool,
    rls_tenant_id: str | None,
    objects: list[Any],
) -> None:
    if not rls_enabled or rls_bypass:
        return

    tenant_id = str(rls_tenant_id or "").strip()
    if not tenant_id:
        return

    for obj in objects:
        scope_type, scope_id = _extract_write_scope(obj)
        if scope_type is None:
            continue

        if scope_type == "PLATFORM":
            raise RLSScopeViolationError("rls_platform_workspace_write_forbidden")

        if not scope_id:
            raise RLSScopeViolationError("rls_tenant_required_for_write")

        if scope_id != tenant_id:
            raise RLSScopeViolationError("rls_tenant_scope_violation")


@event.listens_for(Session, "do_orm_execute")
def _tenant_rls_criteria(execute_state) -> None:
    if not execute_state.is_select:
        return

    sess = execute_state.session
    if not bool(sess.info.get("rls_enabled")):
        return
    if bool(sess.info.get("rls_bypass")):
        return

    tenant_id = str(sess.info.get("rls_tenant_id") or "").strip()
    if not tenant_id:
        return

    stmt = execute_state.statement
    for model in TENANT_RLS_MODELS:
        stmt = stmt.options(
            with_loader_criteria(
                model,
                lambda cls: cls.tenant_id == tenant_id,
                include_aliases=True,
            )
        )
    execute_state.statement = stmt


@event.listens_for(Session, "before_flush")
def _tenant_rls_before_flush(session: Session, _flush_context, _instances) -> None:
    validate_tenant_write_scope(
        rls_enabled=bool(session.info.get("rls_enabled")),
        rls_bypass=bool(session.info.get("rls_bypass")),
        rls_tenant_id=str(session.info.get("rls_tenant_id") or "") or None,
        objects=[*list(session.new), *list(session.dirty), *list(session.deleted)],
    )