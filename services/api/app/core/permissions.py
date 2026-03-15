from __future__ import annotations

from typing import Any


PERMISSION_REGISTRY: list[dict[str, Any]] = [
    {"permission_code": "IAM.READ", "workspace_type": "BOTH", "module_code": "IAM", "description": "Read IAM state", "risk_level": "LOW", "sensitive": False, "active": True},
    {"permission_code": "IAM.WRITE", "workspace_type": "BOTH", "module_code": "IAM", "description": "Modify IAM roles/users", "risk_level": "HIGH", "sensitive": True, "active": True},
    {"permission_code": "PROFILE.READ", "workspace_type": "BOTH", "module_code": "PROFILE", "description": "Read profile data", "risk_level": "LOW", "sensitive": False, "active": True},
    {"permission_code": "PROFILE.WRITE", "workspace_type": "BOTH", "module_code": "PROFILE", "description": "Write profile data", "risk_level": "MEDIUM", "sensitive": False, "active": True},
    {"permission_code": "SUPPORT.READ", "workspace_type": "BOTH", "module_code": "SUPPORT", "description": "Read support records", "risk_level": "LOW", "sensitive": False, "active": True},
    {"permission_code": "SUPPORT.WRITE", "workspace_type": "BOTH", "module_code": "SUPPORT", "description": "Write support records", "risk_level": "HIGH", "sensitive": True, "active": True},
    {"permission_code": "INCIDENTS.READ", "workspace_type": "BOTH", "module_code": "INCIDENTS", "description": "Read incidents", "risk_level": "LOW", "sensitive": False, "active": True},
    {"permission_code": "INCIDENTS.WRITE", "workspace_type": "BOTH", "module_code": "INCIDENTS", "description": "Write incidents", "risk_level": "HIGH", "sensitive": True, "active": True},
    {"permission_code": "SECURITY.READ", "workspace_type": "BOTH", "module_code": "SECURITY", "description": "Read security posture", "risk_level": "HIGH", "sensitive": True, "active": True},
    {"permission_code": "SECURITY.WRITE", "workspace_type": "BOTH", "module_code": "SECURITY", "description": "Execute security actions", "risk_level": "CRITICAL", "sensitive": True, "active": True},
    {"permission_code": "MARKETPLACE.READ", "workspace_type": "TENANT", "module_code": "MARKETPLACE", "description": "Read marketplace", "risk_level": "LOW", "sensitive": False, "active": True},
    {"permission_code": "MARKETPLACE.WRITE", "workspace_type": "TENANT", "module_code": "MARKETPLACE", "description": "Create purchase requests", "risk_level": "MEDIUM", "sensitive": False, "active": True},
    {"permission_code": "ORDERS.READ", "workspace_type": "TENANT", "module_code": "ORDERS", "description": "Read tenant orders", "risk_level": "LOW", "sensitive": False, "active": True},
    {"permission_code": "ORDERS.WRITE", "workspace_type": "TENANT", "module_code": "ORDERS", "description": "Create/update tenant orders", "risk_level": "MEDIUM", "sensitive": True, "active": True},
    {"permission_code": "LICENSES.READ", "workspace_type": "BOTH", "module_code": "LICENSING", "description": "Read licenses and entitlements", "risk_level": "LOW", "sensitive": False, "active": True},
    {"permission_code": "LICENSES.WRITE", "workspace_type": "BOTH", "module_code": "LICENSING", "description": "Issue/modify licenses", "risk_level": "CRITICAL", "sensitive": True, "active": True},
    {"permission_code": "TENANTS.READ", "workspace_type": "PLATFORM", "module_code": "TENANTS", "description": "Read tenants metadata", "risk_level": "MEDIUM", "sensitive": True, "active": True},
    {"permission_code": "TENANTS.WRITE", "workspace_type": "PLATFORM", "module_code": "TENANTS", "description": "Modify tenants", "risk_level": "CRITICAL", "sensitive": True, "active": True},
    {"permission_code": "OBSERVABILITY.READ", "workspace_type": "PLATFORM", "module_code": "OBS", "description": "Read platform observability", "risk_level": "HIGH", "sensitive": True, "active": True},
    {"permission_code": "OBSERVABILITY.WRITE", "workspace_type": "PLATFORM", "module_code": "OBS", "description": "Operate observability controls", "risk_level": "CRITICAL", "sensitive": True, "active": True},
    {"permission_code": "I18N.READ", "workspace_type": "BOTH", "module_code": "I18N", "description": "Read i18n policy", "risk_level": "LOW", "sensitive": False, "active": True},
    {"permission_code": "I18N.WRITE", "workspace_type": "BOTH", "module_code": "I18N", "description": "Modify i18n policy", "risk_level": "MEDIUM", "sensitive": True, "active": True},
    {"permission_code": "PUBLIC.READ", "workspace_type": "BOTH", "module_code": "PUBLIC_PORTAL", "description": "Read public profile/editor state", "risk_level": "LOW", "sensitive": False, "active": True},
    {"permission_code": "PUBLIC.WRITE", "workspace_type": "BOTH", "module_code": "PUBLIC_PORTAL", "description": "Modify public profile/editor state", "risk_level": "MEDIUM", "sensitive": True, "active": True},
    {"permission_code": "STORAGE.READ", "workspace_type": "BOTH", "module_code": "STORAGE", "description": "Read storage metadata/queues", "risk_level": "MEDIUM", "sensitive": True, "active": True},
    {"permission_code": "STORAGE.WRITE", "workspace_type": "BOTH", "module_code": "STORAGE", "description": "Modify storage objects/queues/grants", "risk_level": "HIGH", "sensitive": True, "active": True},
    {"permission_code": "PAYMENTS.READ", "workspace_type": "BOTH", "module_code": "PAYMENTS", "description": "Read billing accounts/invoices", "risk_level": "MEDIUM", "sensitive": True, "active": True},
    {"permission_code": "PAYMENTS.WRITE", "workspace_type": "BOTH", "module_code": "PAYMENTS", "description": "Manage deferred billing and settlement", "risk_level": "CRITICAL", "sensitive": True, "active": True},
    {"permission_code": "AI.COPILOT", "workspace_type": "BOTH", "module_code": "AI", "description": "Use AI copilot endpoints", "risk_level": "MEDIUM", "sensitive": True, "active": True},
]


ROLE_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "TENANT": [
        {"template_code": "TENANT_ADMIN", "role_name": "Tenant Administrator", "description": "Full tenant control", "permissions": ["*"]},
        {"template_code": "ACCOUNTANT", "role_name": "Accountant", "description": "Finance and invoicing", "permissions": ["LICENSES.READ", "PAYMENTS.READ", "PROFILE.READ", "PROFILE.WRITE"]},
        {"template_code": "DISPATCHER", "role_name": "Dispatcher", "description": "Orders and operations", "permissions": ["MARKETPLACE.READ", "MARKETPLACE.WRITE", "ORDERS.READ", "ORDERS.WRITE", "INCIDENTS.READ"]},
        {"template_code": "IT_ADMIN", "role_name": "IT Administrator", "description": "Tenant security and IAM", "permissions": ["IAM.READ", "IAM.WRITE", "SECURITY.READ", "SECURITY.WRITE"]},
    ],
    "PLATFORM": [
        {"template_code": "SUPERADMIN_STAFF", "role_name": "Superadmin Staff", "description": "Full platform control", "permissions": ["*"]},
        {"template_code": "SUPPORT_AGENT", "role_name": "Support Agent", "description": "Tenant support operations", "permissions": ["SUPPORT.READ", "SUPPORT.WRITE", "INCIDENTS.READ", "INCIDENTS.WRITE"]},
        {"template_code": "SECURITY_AUDITOR", "role_name": "Security Auditor", "description": "Security and audit", "permissions": ["SECURITY.READ", "OBSERVABILITY.READ", "TENANTS.READ"]},
        {"template_code": "BILLING_ADMIN", "role_name": "Billing Admin", "description": "Licensing and billing", "permissions": ["LICENSES.READ", "LICENSES.WRITE", "PAYMENTS.READ", "PAYMENTS.WRITE", "TENANTS.READ"]},
    ],
}


ROLE_PERMISSION_FALLBACK: dict[str, list[str]] = {
    "SUPERADMIN": ["*"],
    "TENANT_ADMIN": ["*"],
    "SUPPORT_AGENT": ["SUPPORT.READ", "SUPPORT.WRITE", "INCIDENTS.READ", "INCIDENTS.WRITE"],
    "SECURITY_AUDITOR": ["SECURITY.READ", "OBSERVABILITY.READ", "TENANTS.READ"],
    "BILLING_ADMIN": ["LICENSES.READ", "LICENSES.WRITE", "PAYMENTS.READ", "PAYMENTS.WRITE", "TENANTS.READ"],
}


def normalize_permission(value: Any) -> str:
    raw = str(value or "").strip().upper()
    return raw


def dedupe_permissions(values: list[Any] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in list(values or []):
        code = normalize_permission(raw)
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def permission_matches(granted: str, required: str) -> bool:
    g = normalize_permission(granted)
    r = normalize_permission(required)
    if not g or not r:
        return False
    if g == "*" or g == r:
        return True
    if g.endswith(".*"):
        prefix = g[:-2]
        if not prefix:
            return True
        return r == prefix or r.startswith(prefix + ".")
    return False


def is_permission_allowed(required: str, effective_permissions: list[str]) -> bool:
    req = normalize_permission(required)
    if not req:
        return False
    for granted in dedupe_permissions(effective_permissions):
        if permission_matches(granted, req):
            return True
    return False


def effective_permissions_from_claims(claims: dict[str, Any] | None) -> list[str]:
    src = claims or {}
    out = dedupe_permissions(list(src.get("perms") or []))

    roles = [normalize_permission(x) for x in list(src.get("roles") or []) if normalize_permission(x)]
    for role in roles:
        out = dedupe_permissions([*out, *list(ROLE_PERMISSION_FALLBACK.get(role, []))])

    return out


def list_permission_registry(*, workspace_type: str | None = None, module_code: str | None = None, include_inactive: bool = False) -> list[dict[str, Any]]:
    w = normalize_permission(workspace_type) if workspace_type else ""
    m = normalize_permission(module_code) if module_code else ""

    out: list[dict[str, Any]] = []
    for row in PERMISSION_REGISTRY:
        if not include_inactive and not bool(row.get("active", True)):
            continue
        scope = normalize_permission(row.get("workspace_type") or "")
        if w and scope not in {"BOTH", w}:
            continue
        if m and normalize_permission(row.get("module_code") or "") != m:
            continue
        out.append(
            {
                "permission_code": normalize_permission(row.get("permission_code")),
                "workspace_type": scope,
                "module_code": normalize_permission(row.get("module_code")),
                "description": str(row.get("description") or ""),
                "risk_level": normalize_permission(row.get("risk_level") or "LOW"),
                "sensitive": bool(row.get("sensitive", False)),
                "active": bool(row.get("active", True)),
            }
        )
    out.sort(key=lambda x: (x.get("module_code"), x.get("permission_code")))
    return out


def list_role_templates(*, workspace_type: str) -> list[dict[str, Any]]:
    w = normalize_permission(workspace_type)
    rows = ROLE_TEMPLATES.get(w, [])
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "workspace_type": w,
                "template_code": normalize_permission(row.get("template_code")),
                "role_name": str(row.get("role_name") or ""),
                "description": str(row.get("description") or ""),
                "permissions": dedupe_permissions(list(row.get("permissions") or [])),
            }
        )
    out.sort(key=lambda x: x.get("template_code"))
    return out