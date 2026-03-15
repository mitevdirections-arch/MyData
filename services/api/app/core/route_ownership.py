from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from app.core.policy_matrix import ROUTE_POLICY


class RoutePlane(str, Enum):
    FOUNDATION = "FOUNDATION"
    OPERATIONAL = "OPERATIONAL"


ROUTE_PLANE_FOUNDATION = RoutePlane.FOUNDATION.value
ROUTE_PLANE_OPERATIONAL = RoutePlane.OPERATIONAL.value
ALLOWED_ROUTE_PLANES = {ROUTE_PLANE_FOUNDATION, ROUTE_PLANE_OPERATIONAL}


ROUTE_PLANE_OWNERSHIP: dict[tuple[str, str], str] = {
    ("DELETE", "/admin/storage/verification-docs/{object_id}"): ROUTE_PLANE_FOUNDATION,
    ("DELETE", "/profile/admin/users/{user_id}/addresses/{address_id}"): ROUTE_PLANE_FOUNDATION,
    ("DELETE", "/profile/admin/users/{user_id}/contacts/{contact_id}"): ROUTE_PLANE_FOUNDATION,
    ("DELETE", "/profile/admin/users/{user_id}/documents/{document_id}"): ROUTE_PLANE_FOUNDATION,
    ("DELETE", "/profile/admin/users/{user_id}/next-of-kin/{kin_id}"): ROUTE_PLANE_FOUNDATION,
    ("DELETE", "/profile/workspace/addresses/{address_id}"): ROUTE_PLANE_FOUNDATION,
    ("DELETE", "/profile/workspace/contacts/{contact_id}"): ROUTE_PLANE_FOUNDATION,
    ("DELETE", "/users/admin/users/{user_id}/addresses/{address_id}"): ROUTE_PLANE_FOUNDATION,
    ("DELETE", "/users/admin/users/{user_id}/contacts/{contact_id}"): ROUTE_PLANE_FOUNDATION,
    ("DELETE", "/users/admin/users/{user_id}/documents/{document_id}"): ROUTE_PLANE_FOUNDATION,
    ("DELETE", "/users/admin/users/{user_id}/next-of-kin/{kin_id}"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/admin/i18n/tenant-default"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/admin/incidents"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/admin/incidents/{incident_id}"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/admin/onboarding/applications"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/admin/payments/credit-account"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/admin/payments/invoice-template"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/admin/payments/invoices"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/admin/payments/invoices/{invoice_id}/document"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/admin/public-profile/assets"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/admin/public-profile/editor"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/admin/public-profile/editor/preview"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/admin/public-profile/settings"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/admin/storage/policy"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/admin/storage/verification-docs"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/admin/tenants"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/guard/admin/audit"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/guard/admin/audit/verify"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/guard/admin/bot/checks"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/guard/admin/bot/credentials"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/guard/admin/bot/lockouts"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/guard/admin/tenant-verify"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/guard/device/lease/me"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/guard/heartbeat/policy"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/guard/tenant-status"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/i18n/effective"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/iam/admin/rls-context"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/iam/me/access"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/iam/permission-registry"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/iam/role-templates"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/licenses/active"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/licenses/admin/issuance-policy"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/licenses/admin/issue-requests"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/licenses/core-entitlement"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/licenses/entitlement-v2"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/licenses/module-entitlement/{module_code}"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/marketplace/admin/catalog"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/marketplace/admin/offers"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/marketplace/admin/purchase-requests"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/marketplace/catalog"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/marketplace/offers/active"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/marketplace/purchase-requests"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/orders"): ROUTE_PLANE_OPERATIONAL,
    ("GET", "/orders/{order_id}"): ROUTE_PLANE_OPERATIONAL,
    ("GET", "/profile/admin/roles"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/profile/admin/users"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/profile/admin/users/{user_id}"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/profile/admin/users/{user_id}/addresses"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/profile/admin/users/{user_id}/contacts"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/profile/admin/users/{user_id}/credentials"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/profile/admin/users/{user_id}/documents"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/profile/admin/users/{user_id}/next-of-kin"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/profile/admin/users/{user_id}/profile"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/profile/me"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/profile/workspace"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/profile/workspace/addresses"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/profile/workspace/contacts"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/superadmin/i18n/platform-default"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/superadmin/incidents"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/superadmin/meta/tenants-overview"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/superadmin/payments/credit-accounts"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/superadmin/payments/invoice-template/{tenant_id}"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/superadmin/payments/invoices"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/superadmin/payments/invoices/{invoice_id}/document"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/superadmin/security/alerts/queue"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/superadmin/security/events"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/superadmin/security/keys/lifecycle"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/superadmin/security/posture"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/superadmin/storage/delete-queue"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/support/superadmin/faq"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/support/superadmin/requests"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/support/superadmin/requests/{request_id}/messages"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/support/superadmin/sessions"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/support/tenant/requests"): ROUTE_PLANE_OPERATIONAL,
    ("GET", "/support/tenant/requests/{request_id}/messages"): ROUTE_PLANE_OPERATIONAL,
    ("GET", "/users/admin/roles"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/users/admin/users"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/users/admin/users/{user_id}"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/users/admin/users/{user_id}/addresses"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/users/admin/users/{user_id}/contacts"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/users/admin/users/{user_id}/credentials"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/users/admin/users/{user_id}/documents"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/users/admin/users/{user_id}/next-of-kin"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/users/admin/users/{user_id}/profile"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/users/me"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/admin/incidents"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/admin/payments/invoice-template/preview"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/admin/public-profile/assets/logo/presign-upload"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/admin/public-profile/assets/{asset_id}/mark-uploaded"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/admin/public-profile/editor/publish"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/admin/storage/grants/exchange"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/admin/storage/grants/issue-download"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/admin/storage/grants/issue-upload"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/admin/storage/verification-docs/presign-upload"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/admin/storage/verification-docs/{object_id}/mark-uploaded"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/admin/storage/verification-docs/{object_id}/presign-download"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/admin/tenants/bootstrap-demo"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/admin/tenants/{tenant_id}/bootstrap-first-admin"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/ai/superadmin-copilot"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/ai/superadmin-copilot/quality-events/summary"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/ai/superadmin-copilot/runtime-decision-surface"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/ai/superadmin-copilot/template-submissions/queue"): ROUTE_PLANE_FOUNDATION,
    ("GET", "/ai/superadmin-copilot/template-submissions/{submission_id}"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/ai/superadmin-copilot/template-submissions/{submission_id}/approve"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/ai/superadmin-copilot/template-submissions/{submission_id}/reject"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/ai/superadmin-copilot/template-submissions/{submission_id}/publish"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/ai/superadmin-copilot/published-patterns/{artifact_id}/distribution-record"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/ai/superadmin-copilot/distribution-records/{record_id}/rollout-governance"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/ai/superadmin-copilot/rollout-governance-records/{record_id}/activation-record"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/ai/superadmin-copilot/activation-records/{record_id}/runtime-enablement-record"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/ai/tenant-copilot"): ROUTE_PLANE_OPERATIONAL,
    ("POST", "/ai/tenant-copilot/retrieve-order-reference"): ROUTE_PLANE_OPERATIONAL,
    ("POST", "/ai/tenant-copilot/order-draft-assist"): ROUTE_PLANE_OPERATIONAL,
    ("POST", "/ai/tenant-copilot/order-drafting"): ROUTE_PLANE_OPERATIONAL,
    ("POST", "/ai/tenant-copilot/document-understanding"): ROUTE_PLANE_OPERATIONAL,
    ("POST", "/ai/tenant-copilot/order-document-intake"): ROUTE_PLANE_OPERATIONAL,
    ("POST", "/ai/tenant-copilot/order-intake-feedback"): ROUTE_PLANE_OPERATIONAL,
    ("POST", "/ai/tenant-copilot/template-submissions/stage"): ROUTE_PLANE_OPERATIONAL,
    ("POST", "/guard/admin/bot/check-once"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/guard/admin/bot/credentials/issue"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/guard/admin/bot/credentials/{bot_id}/revoke"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/guard/admin/bot/credentials/{bot_id}/rotate"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/guard/admin/bot/credentials/{bot_id}/unlock"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/guard/device/lease"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/guard/heartbeat"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/guard/license-snapshot"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/iam/me/access/check"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/licenses/admin/issue-core"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/licenses/admin/issue-module-trial"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/licenses/admin/issue-requests/{request_id}/approve"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/licenses/admin/issue-requests/{request_id}/reject"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/licenses/admin/issue-startup"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/licenses/admin/visual-code-preview"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/marketplace/admin/offers"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/marketplace/admin/purchase-requests/{request_id}/approve"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/marketplace/admin/purchase-requests/{request_id}/reject"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/marketplace/purchase-requests"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/orders"): ROUTE_PLANE_OPERATIONAL,
    ("POST", "/profile/admin/users/{user_id}/addresses"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/profile/admin/users/{user_id}/contacts"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/profile/admin/users/{user_id}/credentials/issue"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/profile/admin/users/{user_id}/credentials/reset-password"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/profile/admin/users/{user_id}/documents"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/profile/admin/users/{user_id}/next-of-kin"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/profile/workspace/addresses"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/profile/workspace/contacts"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/superadmin/incidents/{incident_id}/ack"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/superadmin/incidents/{incident_id}/resolve"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/superadmin/payments/invoices/{invoice_id}/mark-paid"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/superadmin/payments/overdue/run-once"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/superadmin/provisioning/tenant/run"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/superadmin/security/alerts/dispatch-once"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/superadmin/security/alerts/test-incident"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/superadmin/security/alerts/{alert_id}/fail-now"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/superadmin/security/alerts/{alert_id}/requeue"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/superadmin/security/kill-switch/tenant/{tenant_id}"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/superadmin/storage/delete-queue/run-once"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/superadmin/storage/delete-queue/{job_id}/fail-now"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/superadmin/storage/delete-queue/{job_id}/requeue"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/support/superadmin/faq"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/support/superadmin/requests/{request_id}/messages"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/support/superadmin/requests/{request_id}/start-session"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/support/superadmin/sessions/{session_id}/end"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/support/superadmin/sessions/{session_id}/issue-token"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/support/tenant/requests"): ROUTE_PLANE_OPERATIONAL,
    ("POST", "/support/tenant/requests/{request_id}/chat-bot"): ROUTE_PLANE_OPERATIONAL,
    ("POST", "/support/tenant/requests/{request_id}/close"): ROUTE_PLANE_OPERATIONAL,
    ("POST", "/support/tenant/requests/{request_id}/messages"): ROUTE_PLANE_OPERATIONAL,
    ("POST", "/support/tenant/requests/{request_id}/open-door"): ROUTE_PLANE_OPERATIONAL,
    ("POST", "/users/admin/users/{user_id}/addresses"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/users/admin/users/{user_id}/contacts"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/users/admin/users/{user_id}/credentials/issue"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/users/admin/users/{user_id}/credentials/reset-password"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/users/admin/users/{user_id}/documents"): ROUTE_PLANE_FOUNDATION,
    ("POST", "/users/admin/users/{user_id}/next-of-kin"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/admin/i18n/tenant-default"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/admin/payments/invoice-template"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/admin/public-profile/editor/draft"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/admin/public-profile/settings"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/licenses/admin/issuance-policy"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/marketplace/admin/catalog/{module_code}"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/marketplace/admin/offers/{offer_id}"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/profile/admin/roles/{role_code}"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/profile/admin/users/{user_id}"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/profile/admin/users/{user_id}/addresses/{address_id}"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/profile/admin/users/{user_id}/contacts/{contact_id}"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/profile/admin/users/{user_id}/documents/{document_id}"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/profile/admin/users/{user_id}/next-of-kin/{kin_id}"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/profile/admin/users/{user_id}/profile"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/profile/admin/users/{user_id}/roles"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/profile/me"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/profile/workspace"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/profile/workspace/addresses/{address_id}"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/profile/workspace/contacts/{contact_id}"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/superadmin/i18n/platform-default"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/superadmin/payments/credit-accounts/{tenant_id}"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/superadmin/payments/invoice-template/{tenant_id}"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/support/superadmin/faq/{entry_id}"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/users/admin/roles/{role_code}"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/users/admin/users/{user_id}"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/users/admin/users/{user_id}/addresses/{address_id}"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/users/admin/users/{user_id}/contacts/{contact_id}"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/users/admin/users/{user_id}/documents/{document_id}"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/users/admin/users/{user_id}/next-of-kin/{kin_id}"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/users/admin/users/{user_id}/profile"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/users/admin/users/{user_id}/roles"): ROUTE_PLANE_FOUNDATION,
    ("PUT", "/users/me"): ROUTE_PLANE_FOUNDATION,
}


def _normalize_plane(value: str | RoutePlane | None) -> str | None:
    raw = str(value or "").strip().upper()
    if raw in ALLOWED_ROUTE_PLANES:
        return raw
    return None


def route_keys_without_explicit_plane_ownership() -> list[str]:
    missing: list[str] = []
    for method, path in sorted(ROUTE_POLICY.keys()):
        plane = _normalize_plane(ROUTE_PLANE_OWNERSHIP.get((method, path)))
        if plane is None:
            missing.append(f"{method} {path}")
    return missing


def route_plane_ownership_drift() -> dict[str, list[str]]:
    policy_keys = set(ROUTE_POLICY.keys())
    ownership_keys = set(ROUTE_PLANE_OWNERSHIP.keys())

    missing = sorted(f"{m} {p}" for (m, p) in (policy_keys - ownership_keys))
    extra = sorted(f"{m} {p}" for (m, p) in (ownership_keys - policy_keys))

    return {
        "missing": missing,
        "extra": extra,
    }


def resolve_route_plane(method: str, path: str) -> str | None:
    key = (str(method or "").upper(), str(path or ""))
    return _normalize_plane(ROUTE_PLANE_OWNERSHIP.get(key))


def route_plane_coverage_snapshot() -> dict[str, Any]:
    missing = route_keys_without_explicit_plane_ownership()
    drift = route_plane_ownership_drift()

    foundation = 0
    operational = 0
    for v in ROUTE_PLANE_OWNERSHIP.values():
        norm = _normalize_plane(v)
        if norm == ROUTE_PLANE_FOUNDATION:
            foundation += 1
        elif norm == ROUTE_PLANE_OPERATIONAL:
            operational += 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "routes_total": len(ROUTE_POLICY),
        "foundation_routes": foundation,
        "operational_routes": operational,
        "missing_ownership": len(missing),
        "drift_missing": len(drift.get("missing") or []),
        "drift_extra": len(drift.get("extra") or []),
    }
