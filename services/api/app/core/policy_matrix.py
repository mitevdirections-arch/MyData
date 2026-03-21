from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import os
import time
from typing import Any

from fastapi import HTTPException, Request

from app.core.auth import ensure_tenant_scope_claims, is_superadmin_step_up_code_valid
from app.core.perf_sql_trace import sql_trace_zone
from app.core.permissions import effective_permissions_from_claims, is_permission_allowed, normalize_permission
from app.core.security_telemetry import emit_security_event
from app.core.settings import get_settings
from app.core.perf_profile import record_segment
from app.core.authz_fast_path import (
    resolve_effective_permissions_from_canonical,
    resolve_effective_permissions_from_fast_path,
)
from app.db.session import get_session_factory

AUTHENTICATED_ONLY = "__AUTHENTICATED__"
AUTHZ_SOURCE_CLAIMS = "CLAIMS"
AUTHZ_SOURCE_TENANT_DB = "TENANT_DB"


class AuthzMode(str, Enum):
    DB_TRUTH = "DB_TRUTH"
    TOKEN_CLAIMS = "TOKEN_CLAIMS"
    FAST_PATH = "FAST_PATH"


AUTHZ_MODE_DB_TRUTH = AuthzMode.DB_TRUTH.value
AUTHZ_MODE_TOKEN_CLAIMS = AuthzMode.TOKEN_CLAIMS.value
AUTHZ_MODE_FAST_PATH = AuthzMode.FAST_PATH.value

PUBLIC_PREFIXES = (
    "/healthz",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/public/",
    "/auth/dev-token",
    "/i18n/locales",
    "/i18n/catalog/",
    "/support/public/",
)

PROTECTED_PREFIXES = (
    "/admin/",
    "/superadmin/",
    "/guard/",
    "/licenses/",
    "/marketplace/",
    "/orders/",
    "/partners/",
    "/profile/",
    "/users/",
    "/support/",
    "/iam/",
    "/i18n/effective",
    "/ai/",
)

DEVICE_POLICY_ENFORCED_PREFIXES = (
    "/orders",
    "/partners",
    "/support/tenant",
    "/ai/tenant-copilot",
)
DEVICE_POLICY_NON_ACTIVE_ALLOWLIST: set[tuple[str, str]] = {
    ("POST", "/guard/heartbeat"),
    ("GET", "/guard/heartbeat/policy"),
    ("POST", "/guard/device/lease"),
    ("GET", "/guard/device/lease/me"),
    ("GET", "/guard/device/status"),
    ("POST", "/guard/device/activate"),
    ("POST", "/guard/device/logout"),
    ("GET", "/guard/tenant-status"),
}
DEVICE_POLICY_OPERATIONAL_EXEMPT_ROUTES: set[tuple[str, str]] = {
    ("GET", "/admin/partners/{partner_id}/verification-summary"),
    ("POST", "/admin/partners/{partner_id}/verification/recheck"),
}


@dataclass(frozen=True)
class RoutePolicy:
    permission_code: str
    step_up: bool = False
    authz_source: str = AUTHZ_SOURCE_CLAIMS
    authz_mode: str | None = None


ROUTE_POLICY: dict[tuple[str, str], RoutePolicy] = {
    ("GET", "/admin/i18n/tenant-default"): RoutePolicy("I18N.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/admin/i18n/tenant-default"): RoutePolicy("I18N.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/admin/incidents"): RoutePolicy("INCIDENTS.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/admin/incidents"): RoutePolicy("INCIDENTS.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/admin/incidents/{incident_id}"): RoutePolicy("INCIDENTS.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/admin/onboarding/applications"): RoutePolicy("TENANTS.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/admin/onboarding/applications/{application_id}/approve"): RoutePolicy("TENANTS.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/admin/payments/credit-account"): RoutePolicy("PAYMENTS.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/admin/payments/invoice-template"): RoutePolicy("PAYMENTS.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/admin/payments/invoice-template"): RoutePolicy("PAYMENTS.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/admin/payments/invoice-template/preview"): RoutePolicy("PAYMENTS.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/admin/payments/invoices"): RoutePolicy("PAYMENTS.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/admin/payments/invoices/{invoice_id}/document"): RoutePolicy("PAYMENTS.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/admin/public-profile/assets"): RoutePolicy("PUBLIC.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/admin/public-profile/assets/logo/presign-upload"): RoutePolicy("PUBLIC.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/admin/public-profile/assets/{asset_id}/mark-uploaded"): RoutePolicy("PUBLIC.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/admin/public-profile/editor"): RoutePolicy("PUBLIC.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/admin/public-profile/editor/draft"): RoutePolicy("PUBLIC.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/admin/public-profile/editor/preview"): RoutePolicy("PUBLIC.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/admin/public-profile/editor/publish"): RoutePolicy("PUBLIC.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/admin/public-profile/settings"): RoutePolicy("PUBLIC.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/admin/public-profile/settings"): RoutePolicy("PUBLIC.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/admin/storage/grants/exchange"): RoutePolicy("STORAGE.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/admin/storage/grants/issue-download"): RoutePolicy("STORAGE.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/admin/storage/grants/issue-upload"): RoutePolicy("STORAGE.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/admin/storage/policy"): RoutePolicy("STORAGE.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/admin/storage/verification-docs"): RoutePolicy("STORAGE.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/admin/storage/verification-docs/presign-upload"): RoutePolicy("STORAGE.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("DELETE", "/admin/storage/verification-docs/{object_id}"): RoutePolicy("STORAGE.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/admin/storage/verification-docs/{object_id}/mark-uploaded"): RoutePolicy("STORAGE.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/admin/storage/verification-docs/{object_id}/presign-download"): RoutePolicy("STORAGE.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/admin/tenants"): RoutePolicy("TENANTS.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/admin/tenants/bootstrap-demo"): RoutePolicy("TENANTS.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/admin/tenants/{tenant_id}/bootstrap-first-admin"): RoutePolicy("TENANTS.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/ai/superadmin-copilot"): RoutePolicy("AI.COPILOT", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/ai/superadmin-copilot/quality-events/summary"): RoutePolicy("AI.COPILOT", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/ai/superadmin-copilot/runtime-decision-surface"): RoutePolicy("AI.COPILOT", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/ai/superadmin-copilot/template-submissions/queue"): RoutePolicy("AI.COPILOT", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/ai/superadmin-copilot/template-submissions/{submission_id}"): RoutePolicy("AI.COPILOT", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/ai/superadmin-copilot/template-submissions/{submission_id}/approve"): RoutePolicy("AI.COPILOT", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/ai/superadmin-copilot/template-submissions/{submission_id}/reject"): RoutePolicy("AI.COPILOT", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/ai/superadmin-copilot/template-submissions/{submission_id}/publish"): RoutePolicy("AI.COPILOT", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/ai/superadmin-copilot/published-patterns/{artifact_id}/distribution-record"): RoutePolicy("AI.COPILOT", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/ai/superadmin-copilot/distribution-records/{record_id}/rollout-governance"): RoutePolicy("AI.COPILOT", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/ai/superadmin-copilot/rollout-governance-records/{record_id}/activation-record"): RoutePolicy("AI.COPILOT", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/ai/superadmin-copilot/activation-records/{record_id}/runtime-enablement-record"): RoutePolicy("AI.COPILOT", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/ai/tenant-copilot"): RoutePolicy("AI.COPILOT", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/ai/tenant-copilot/orders-copilot"): RoutePolicy("AI.COPILOT", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/ai/tenant-copilot/retrieve-order-reference"): RoutePolicy("AI.COPILOT", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/ai/tenant-copilot/order-draft-assist"): RoutePolicy("AI.COPILOT", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/ai/tenant-copilot/order-drafting"): RoutePolicy("AI.COPILOT", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/ai/tenant-copilot/document-understanding"): RoutePolicy("AI.COPILOT", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/ai/tenant-copilot/order-document-intake"): RoutePolicy("AI.COPILOT", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/ai/tenant-copilot/order-intake-feedback"): RoutePolicy("AI.COPILOT", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/ai/tenant-copilot/order-feedback"): RoutePolicy("AI.COPILOT", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/ai/tenant-copilot/template-submissions/stage"): RoutePolicy("AI.COPILOT", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/guard/admin/audit"): RoutePolicy("SECURITY.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/guard/admin/audit/verify"): RoutePolicy("SECURITY.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/guard/admin/bot/check-once"): RoutePolicy("SECURITY.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/guard/admin/bot/checks"): RoutePolicy("SECURITY.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/guard/admin/bot/credentials"): RoutePolicy("SECURITY.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/guard/admin/bot/credentials/issue"): RoutePolicy("SECURITY.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/guard/admin/bot/credentials/{bot_id}/revoke"): RoutePolicy("SECURITY.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/guard/admin/bot/credentials/{bot_id}/rotate"): RoutePolicy("SECURITY.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/guard/admin/bot/credentials/{bot_id}/unlock"): RoutePolicy("SECURITY.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/guard/admin/bot/lockouts"): RoutePolicy("SECURITY.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/guard/admin/tenant-verify"): RoutePolicy("SECURITY.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/guard/device/lease"): RoutePolicy(AUTHENTICATED_ONLY, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/guard/device/lease/me"): RoutePolicy(AUTHENTICATED_ONLY, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/guard/device/status"): RoutePolicy(AUTHENTICATED_ONLY, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/guard/device/activate"): RoutePolicy(AUTHENTICATED_ONLY, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/guard/device/logout"): RoutePolicy(AUTHENTICATED_ONLY, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/guard/heartbeat"): RoutePolicy(AUTHENTICATED_ONLY, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/guard/heartbeat/policy"): RoutePolicy(AUTHENTICATED_ONLY, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/guard/license-snapshot"): RoutePolicy(AUTHENTICATED_ONLY, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/guard/tenant-status"): RoutePolicy(AUTHENTICATED_ONLY, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/i18n/effective"): RoutePolicy("I18N.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/iam/admin/rls-context"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/iam/me/access"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/iam/me/access/check"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/iam/permission-registry"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/iam/role-templates"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/licenses/active"): RoutePolicy("LICENSES.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/licenses/admin/issuance-policy"): RoutePolicy("LICENSES.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/licenses/admin/issuance-policy"): RoutePolicy("LICENSES.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/licenses/admin/issue-module-trial"): RoutePolicy("LICENSES.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/licenses/admin/issue-requests"): RoutePolicy("LICENSES.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/licenses/admin/issue-requests/{request_id}/approve"): RoutePolicy("LICENSES.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/licenses/admin/issue-requests/{request_id}/reject"): RoutePolicy("LICENSES.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/licenses/admin/issue-startup"): RoutePolicy("LICENSES.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/licenses/admin/issue-core"): RoutePolicy("LICENSES.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/licenses/admin/visual-code-preview"): RoutePolicy("LICENSES.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/licenses/core-entitlement"): RoutePolicy("LICENSES.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/licenses/entitlement-v2"): RoutePolicy("LICENSES.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/licenses/module-entitlement/{module_code}"): RoutePolicy("LICENSES.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/marketplace/admin/catalog"): RoutePolicy("MARKETPLACE.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/marketplace/admin/catalog/{module_code}"): RoutePolicy("MARKETPLACE.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/marketplace/admin/offers"): RoutePolicy("MARKETPLACE.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/marketplace/admin/offers"): RoutePolicy("MARKETPLACE.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/marketplace/admin/offers/{offer_id}"): RoutePolicy("MARKETPLACE.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/marketplace/admin/purchase-requests"): RoutePolicy("MARKETPLACE.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/marketplace/admin/purchase-requests/{request_id}/approve"): RoutePolicy("MARKETPLACE.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/marketplace/admin/purchase-requests/{request_id}/reject"): RoutePolicy("MARKETPLACE.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/marketplace/catalog"): RoutePolicy("MARKETPLACE.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/marketplace/offers/active"): RoutePolicy("MARKETPLACE.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/marketplace/purchase-requests"): RoutePolicy("MARKETPLACE.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/marketplace/purchase-requests"): RoutePolicy("MARKETPLACE.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/orders"): RoutePolicy("ORDERS.READ", authz_source=AUTHZ_SOURCE_TENANT_DB, authz_mode=AUTHZ_MODE_DB_TRUTH),
    ("POST", "/orders"): RoutePolicy("ORDERS.WRITE", authz_source=AUTHZ_SOURCE_TENANT_DB, authz_mode=AUTHZ_MODE_DB_TRUTH),
    ("GET", "/orders/{order_id}"): RoutePolicy("ORDERS.READ", authz_source=AUTHZ_SOURCE_TENANT_DB, authz_mode=AUTHZ_MODE_DB_TRUTH),
    ("GET", "/partners"): RoutePolicy("PARTNERS.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/partners"): RoutePolicy("PARTNERS.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/partners/{partner_id}"): RoutePolicy("PARTNERS.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/partners/{partner_id}"): RoutePolicy("PARTNERS.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/partners/{partner_id}/archive"): RoutePolicy("PARTNERS.ARCHIVE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/partners/{partner_id}/roles"): RoutePolicy("PARTNERS.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/partners/{partner_id}/ratings"): RoutePolicy("PARTNERS.RATE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/partners/{partner_id}/rating-summary"): RoutePolicy("PARTNERS.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/partners/{partner_id}/global-signal"): RoutePolicy("PARTNERS.VIEW_GLOBAL_SIGNAL", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/partners/{partner_id}/blacklist"): RoutePolicy("PARTNERS.MANAGE_BLACKLIST", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/partners/{partner_id}/watchlist"): RoutePolicy("PARTNERS.MANAGE_BLACKLIST", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/admin/partners/{partner_id}/verification-summary"): RoutePolicy("PARTNERS.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/admin/partners/{partner_id}/verification/recheck"): RoutePolicy("PARTNERS.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/admin/company/verification-summary"): RoutePolicy("PROFILE.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/admin/company/verification/recheck"): RoutePolicy("PROFILE.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/admin/entity-verification/targets/upsert"): RoutePolicy("entity_verification.admin", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/admin/entity-verification/targets/{target_id}"): RoutePolicy("entity_verification.read", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/admin/entity-verification/targets/{target_id}/summary"): RoutePolicy("entity_verification.read", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/admin/entity-verification/targets/{target_id}/checks"): RoutePolicy("entity_verification.read", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/admin/entity-verification/targets/{target_id}/recheck"): RoutePolicy("entity_verification.recheck", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/admin/entity-verification/targets/{target_id}/providers/vies/check"): RoutePolicy("entity_verification.check", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/profile/admin/roles"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/profile/admin/roles/{role_code}"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("DELETE", "/profile/admin/roles/{role_code}"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/profile/admin/users"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/profile/admin/users/{user_id}"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/profile/admin/users/{user_id}"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/profile/admin/users/{user_id}/roles"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/profile/admin/users/{user_id}/provision"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/profile/admin/users/{user_id}/profile"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/profile/admin/users/{user_id}/profile"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/profile/admin/users/{user_id}/contacts"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/profile/admin/users/{user_id}/contacts"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/profile/admin/users/{user_id}/contacts/{contact_id}"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("DELETE", "/profile/admin/users/{user_id}/contacts/{contact_id}"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/profile/admin/users/{user_id}/addresses"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/profile/admin/users/{user_id}/addresses"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/profile/admin/users/{user_id}/addresses/{address_id}"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("DELETE", "/profile/admin/users/{user_id}/addresses/{address_id}"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/profile/admin/users/{user_id}/next-of-kin"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/profile/admin/users/{user_id}/next-of-kin"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/profile/admin/users/{user_id}/next-of-kin/{kin_id}"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("DELETE", "/profile/admin/users/{user_id}/next-of-kin/{kin_id}"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/profile/admin/users/{user_id}/documents"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/profile/admin/users/{user_id}/documents"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/profile/admin/users/{user_id}/documents/{document_id}"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("DELETE", "/profile/admin/users/{user_id}/documents/{document_id}"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/profile/admin/users/{user_id}/credentials"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/profile/admin/users/{user_id}/credentials/issue"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/profile/admin/users/{user_id}/credentials/invite"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/profile/admin/users/{user_id}/credentials/reset-password"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/profile/admin/users/{user_id}/credentials/lock"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/profile/admin/users/{user_id}/credentials/unlock"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/profile/admin/users/{user_id}/credentials/revoke-invite"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/profile/me"): RoutePolicy("PROFILE.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/profile/me"): RoutePolicy("PROFILE.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/profile/workspace"): RoutePolicy("PROFILE.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/profile/workspace"): RoutePolicy("PROFILE.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/profile/workspace/contacts"): RoutePolicy("PROFILE.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/profile/workspace/contacts"): RoutePolicy("PROFILE.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/profile/workspace/contacts/{contact_id}"): RoutePolicy("PROFILE.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("DELETE", "/profile/workspace/contacts/{contact_id}"): RoutePolicy("PROFILE.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/profile/workspace/addresses"): RoutePolicy("PROFILE.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/profile/workspace/addresses"): RoutePolicy("PROFILE.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/profile/workspace/addresses/{address_id}"): RoutePolicy("PROFILE.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("DELETE", "/profile/workspace/addresses/{address_id}"): RoutePolicy("PROFILE.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/users/admin/roles"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/users/admin/roles/{role_code}"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("DELETE", "/users/admin/roles/{role_code}"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/users/admin/users"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/users/admin/users/{user_id}"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/users/admin/users/{user_id}"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/users/admin/users/{user_id}/roles"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/users/admin/users/{user_id}/provision"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/users/admin/users/{user_id}/profile"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/users/admin/users/{user_id}/profile"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/users/admin/users/{user_id}/contacts"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/users/admin/users/{user_id}/contacts"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/users/admin/users/{user_id}/contacts/{contact_id}"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("DELETE", "/users/admin/users/{user_id}/contacts/{contact_id}"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/users/admin/users/{user_id}/addresses"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/users/admin/users/{user_id}/addresses"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/users/admin/users/{user_id}/addresses/{address_id}"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("DELETE", "/users/admin/users/{user_id}/addresses/{address_id}"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/users/admin/users/{user_id}/next-of-kin"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/users/admin/users/{user_id}/next-of-kin"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/users/admin/users/{user_id}/next-of-kin/{kin_id}"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("DELETE", "/users/admin/users/{user_id}/next-of-kin/{kin_id}"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/users/admin/users/{user_id}/documents"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/users/admin/users/{user_id}/documents"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/users/admin/users/{user_id}/documents/{document_id}"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("DELETE", "/users/admin/users/{user_id}/documents/{document_id}"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/users/admin/users/{user_id}/credentials"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/users/admin/users/{user_id}/credentials/issue"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/users/admin/users/{user_id}/credentials/invite"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/users/admin/users/{user_id}/credentials/reset-password"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/users/admin/users/{user_id}/credentials/lock"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/users/admin/users/{user_id}/credentials/unlock"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/users/admin/users/{user_id}/credentials/revoke-invite"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/users/me"): RoutePolicy("PROFILE.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/users/me"): RoutePolicy("PROFILE.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/superadmin/i18n/platform-default"): RoutePolicy("I18N.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/superadmin/i18n/platform-default"): RoutePolicy("I18N.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/superadmin/incidents"): RoutePolicy("INCIDENTS.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/superadmin/incidents/{incident_id}/ack"): RoutePolicy("INCIDENTS.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/superadmin/incidents/{incident_id}/resolve"): RoutePolicy("INCIDENTS.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/superadmin/meta/tenants-overview"): RoutePolicy("TENANTS.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/superadmin/payments/credit-accounts"): RoutePolicy("PAYMENTS.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/superadmin/payments/credit-accounts/{tenant_id}"): RoutePolicy("PAYMENTS.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/superadmin/payments/invoice-template/{tenant_id}"): RoutePolicy("PAYMENTS.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/superadmin/payments/invoice-template/{tenant_id}"): RoutePolicy("PAYMENTS.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/superadmin/payments/invoices"): RoutePolicy("PAYMENTS.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/superadmin/payments/invoices/{invoice_id}/document"): RoutePolicy("PAYMENTS.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/superadmin/payments/invoices/{invoice_id}/mark-paid"): RoutePolicy("PAYMENTS.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/superadmin/payments/overdue/run-once"): RoutePolicy("PAYMENTS.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/superadmin/provisioning/tenant/run"): RoutePolicy("TENANTS.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/superadmin/security/events"): RoutePolicy("SECURITY.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/superadmin/security/alerts/dispatch-once"): RoutePolicy("SECURITY.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/superadmin/security/alerts/queue"): RoutePolicy("SECURITY.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/superadmin/security/alerts/test-incident"): RoutePolicy("SECURITY.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/superadmin/security/alerts/{alert_id}/fail-now"): RoutePolicy("SECURITY.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/superadmin/security/alerts/{alert_id}/requeue"): RoutePolicy("SECURITY.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/superadmin/security/keys/lifecycle"): RoutePolicy("SECURITY.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/superadmin/security/kill-switch/tenant/{tenant_id}"): RoutePolicy("SECURITY.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/superadmin/security/posture"): RoutePolicy("SECURITY.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/superadmin/storage/delete-queue"): RoutePolicy("STORAGE.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/superadmin/storage/delete-queue/run-once"): RoutePolicy("STORAGE.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/superadmin/storage/delete-queue/{job_id}/fail-now"): RoutePolicy("STORAGE.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/superadmin/storage/delete-queue/{job_id}/requeue"): RoutePolicy("STORAGE.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/support/superadmin/faq"): RoutePolicy("SUPPORT.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/support/superadmin/faq"): RoutePolicy("SUPPORT.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/support/superadmin/faq/{entry_id}"): RoutePolicy("SUPPORT.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/support/superadmin/requests"): RoutePolicy("SUPPORT.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/support/superadmin/requests/{request_id}/messages"): RoutePolicy("SUPPORT.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/support/superadmin/requests/{request_id}/messages"): RoutePolicy("SUPPORT.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/support/superadmin/requests/{request_id}/start-session"): RoutePolicy("SUPPORT.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/support/superadmin/sessions"): RoutePolicy("SUPPORT.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/support/superadmin/sessions/{session_id}/end"): RoutePolicy("SUPPORT.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/support/superadmin/sessions/{session_id}/issue-token"): RoutePolicy("SUPPORT.WRITE", step_up=True, authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/support/tenant/requests"): RoutePolicy("SUPPORT.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/support/tenant/requests"): RoutePolicy("SUPPORT.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/support/tenant/requests/{request_id}/chat-bot"): RoutePolicy("SUPPORT.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/support/tenant/requests/{request_id}/close"): RoutePolicy("SUPPORT.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/support/tenant/requests/{request_id}/messages"): RoutePolicy("SUPPORT.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/support/tenant/requests/{request_id}/messages"): RoutePolicy("SUPPORT.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/support/tenant/requests/{request_id}/open-door"): RoutePolicy("SUPPORT.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
}


def _path_matches_prefix(path: str, prefix: str) -> bool:
    p = str(path or "")
    px = str(prefix or "")
    if not p or not px:
        return False
    if p.startswith(px):
        return True
    if px.endswith("/") and p == px[:-1]:
        return True
    return False


def is_public_route_path(path: str) -> bool:
    p = str(path or "")
    return any(_path_matches_prefix(p, x) for x in PUBLIC_PREFIXES)


def is_protected_route_path(path: str) -> bool:
    p = str(path or "")
    if is_public_route_path(p):
        return False
    return any(_path_matches_prefix(p, x) for x in PROTECTED_PREFIXES)


def _normalize_authz_mode(value: str | AuthzMode | None) -> str | None:
    raw = normalize_permission(str(value or ""))
    if raw in {AUTHZ_MODE_DB_TRUTH, AUTHZ_MODE_TOKEN_CLAIMS, AUTHZ_MODE_FAST_PATH}:
        return raw
    return None


def resolve_rule_authz_mode(rule: RoutePolicy) -> str:
    mode = _normalize_authz_mode(rule.authz_mode)
    if mode:
        return mode

    source = normalize_permission(rule.authz_source or AUTHZ_SOURCE_CLAIMS)
    if source == AUTHZ_SOURCE_CLAIMS:
        return AUTHZ_MODE_TOKEN_CLAIMS
    if source == AUTHZ_SOURCE_TENANT_DB:
        return AUTHZ_MODE_DB_TRUTH

    raise HTTPException(status_code=403, detail="policy_authz_source_invalid")


def protected_routes_without_explicit_authz_mode() -> list[str]:
    missing: list[str] = []
    for (method, path), rule in sorted(ROUTE_POLICY.items()):
        if not is_protected_route_path(path):
            continue
        if _normalize_authz_mode(rule.authz_mode) is None:
            missing.append(f"{method} {path}")
    return missing


def _route_path_template(request: Request) -> str:
    route = request.scope.get("route")
    if route is not None:
        val = getattr(route, "path", None) or getattr(route, "path_format", None)
        if val:
            return str(val)
    return str(request.url.path)


def _device_policy_enabled() -> bool:
    return bool(getattr(get_settings(), "guard_device_policy_enabled", False))


def _is_device_policy_enforced_path(path: str) -> bool:
    p = str(path or "")
    return any(_path_matches_prefix(p, px) for px in DEVICE_POLICY_ENFORCED_PREFIXES)


def _is_non_active_allowlisted(method: str, path: str) -> bool:
    return (str(method or "").upper(), str(path or "")) in DEVICE_POLICY_NON_ACTIVE_ALLOWLIST


def device_policy_uncovered_operational_routes() -> list[str]:
    # Late import avoids module cycle at import-time.
    from app.core.route_ownership import ROUTE_PLANE_OPERATIONAL, ROUTE_PLANE_OWNERSHIP

    uncovered: list[str] = []
    for (method, path), plane in sorted(ROUTE_PLANE_OWNERSHIP.items()):
        if str(plane or "").strip().upper() != ROUTE_PLANE_OPERATIONAL:
            continue
        m = str(method or "").upper()
        p = str(path or "")
        if (m, p) in DEVICE_POLICY_OPERATIONAL_EXEMPT_ROUTES:
            continue
        if _is_non_active_allowlisted(m, p):
            continue
        if not _is_device_policy_enforced_path(p):
            uncovered.append(f"{m} {p}")
    return uncovered


def device_policy_allowlist_contract_violations() -> list[str]:
    violations: list[str] = []
    for method, path in sorted(DEVICE_POLICY_NON_ACTIVE_ALLOWLIST):
        m = str(method or "").upper()
        p = str(path or "")
        if (m, p) not in ROUTE_POLICY:
            violations.append(f"{m} {p}:missing_route_policy")
            continue
        if not is_protected_route_path(p):
            violations.append(f"{m} {p}:not_protected_path")
    return violations


def _claims_from_request(request: Request) -> dict[str, Any] | None:
    c = getattr(request.state, "claims", None)
    if isinstance(c, dict):
        return c
    return None


def _request_authz_cache_enabled() -> bool:
    raw = str(os.getenv("MYDATA_PERF_REQUEST_AUTHZ_CACHE", "1")).strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _request_authz_cache(request: Request) -> dict[str, Any]:
    cache = getattr(request.state, "_mydata_request_authz_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        setattr(request.state, "_mydata_request_authz_cache", cache)
    return cache


def _tenant_db_authz_wrapper_breakdown_enabled() -> bool:
    access_raw = str(os.getenv("MYDATA_PERF_ACCESS_BREAKDOWN", "0")).strip().lower()
    if access_raw in {"1", "true", "yes", "on"}:
        return True
    raw = str(os.getenv("MYDATA_PERF_AUTHZ_WRAPPER_BREAKDOWN", "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _protected_envelope_breakdown_enabled() -> bool:
    raw = str(os.getenv("MYDATA_PERF_PROTECTED_ENVELOPE_BREAKDOWN", "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _env_bool_override(name: str) -> bool | None:
    raw = os.getenv(str(name))
    if raw is None:
        return None
    val = str(raw).strip().lower()
    if val in {"1", "true", "yes", "on"}:
        return True
    if val in {"0", "false", "no", "off"}:
        return False
    return None


def _tenant_db_fast_path_enabled(*, settings: Any) -> bool:
    override = _env_bool_override("MYDATA_AUTHZ_FAST_PATH_ENABLED")
    if override is not None:
        return bool(override)
    return bool(getattr(settings, "authz_tenant_db_fast_path_enabled", False))


def _tenant_db_fast_path_shadow_compare_enabled(*, settings: Any) -> bool:
    override = _env_bool_override("MYDATA_AUTHZ_FAST_PATH_SHADOW")
    if override is not None:
        return bool(override)
    return bool(getattr(settings, "authz_tenant_db_fast_path_shadow_compare_enabled", False))


def _record_tenant_db_fast_path_counters(
    *,
    shadow_compares: int,
    shadow_mismatches: int,
    fast_hits: int,
    fallbacks: int,
) -> None:
    record_segment("authz_fast_path_shadow_compares", float(max(0, int(shadow_compares))))
    record_segment("authz_fast_path_shadow_mismatches", float(max(0, int(shadow_mismatches))))
    record_segment("authz_fast_path_hits", float(max(0, int(fast_hits))))
    record_segment("authz_fast_path_fallbacks", float(max(0, int(fallbacks))))


def _claims_signature(claims: dict[str, Any]) -> tuple[str, str, str]:
    sub = str((claims or {}).get("sub") or "").strip()
    tenant_id = str((claims or {}).get("tenant_id") or "").strip()
    roles = sorted(str(x).strip().upper() for x in list((claims or {}).get("roles") or []) if str(x).strip())
    return sub, tenant_id, "|".join(roles)


def _request_ip(request: Request) -> str | None:
    if request.client and request.client.host:
        return str(request.client.host)
    return None


def _emit_policy_security_event(
    *,
    request: Request,
    claims: dict[str, Any] | None,
    event_code: str,
    severity: str,
    details: dict[str, Any] | None = None,
) -> None:
    try:
        actor = str((claims or {}).get("sub") or "anonymous")
        tenant_id = str((claims or {}).get("tenant_id") or "").strip() or None
        db = get_session_factory()()
        try:
            emit_security_event(
                db,
                event_code=event_code,
                severity=severity,
                actor=actor,
                tenant_id=tenant_id,
                target=_route_path_template(request),
                source="POLICY_MATRIX",
                category="SECURITY",
                request_id=str(getattr(request.state, "request_id", "") or "") or None,
                request_path=str(request.url.path or "") or None,
                request_method=str(request.method or "").upper() or None,
                ip=_request_ip(request),
                details=dict(details or {}),
                create_incident_for_high=True,
            )
            db.commit()
        finally:
            db.close()
    except Exception:  # noqa: BLE001
        return


def _enforce_step_up_if_required(*, request: Request, claims: dict[str, Any] | None, required: bool) -> None:
    if not required:
        return
    roles = {normalize_permission(x) for x in list((claims or {}).get("roles") or []) if normalize_permission(x)}
    if "SUPERADMIN" not in roles:
        _emit_policy_security_event(
            request=request,
            claims=claims,
            event_code="STEP_UP_SUPERADMIN_REQUIRED",
            severity="HIGH",
            details={"detail": "step_up_superadmin_required"},
        )
        raise HTTPException(status_code=403, detail="step_up_superadmin_required")

    header_name = str(get_settings().superadmin_step_up_header or "X-Step-Up-Code").strip() or "X-Step-Up-Code"
    code = request.headers.get(header_name)
    if not is_superadmin_step_up_code_valid(code):
        _emit_policy_security_event(
            request=request,
            claims=claims,
            event_code="STEP_UP_CODE_INVALID",
            severity="HIGH",
            details={"detail": "step_up_required", "header": header_name},
        )
        raise HTTPException(status_code=403, detail="step_up_required")


def _enforce_device_policy_for_business_routes(*, request: Request, claims: dict[str, Any], method: str, path: str) -> None:
    if not _device_policy_enabled():
        return
    if _is_non_active_allowlisted(method, path):
        return
    if not _is_device_policy_enforced_path(path):
        return

    header_name = str(getattr(get_settings(), "guard_device_header_name", "X-Device-ID") or "X-Device-ID").strip() or "X-Device-ID"
    device_id = str(request.headers.get(header_name) or "").strip()
    if not device_id:
        _emit_policy_security_event(
            request=request,
            claims=claims,
            event_code="DEVICE_CONTEXT_REQUIRED",
            severity="HIGH",
            details={"method": method, "path": path, "header": header_name},
        )
        raise HTTPException(status_code=403, detail="DEVICE_CONTEXT_REQUIRED")

    try:
        tenant_id = ensure_tenant_scope_claims(claims, request=request)
    except TypeError as exc:
        if "unexpected keyword argument 'request'" in str(exc):
            tenant_id = ensure_tenant_scope_claims(claims)
        else:
            raise
    user_id = str((claims or {}).get("sub") or "").strip()
    if not user_id:
        raise HTTPException(status_code=403, detail="DEVICE_CONTEXT_REQUIRED")

    from app.modules.guard.service import service as guard_service

    db = get_session_factory()()
    try:
        guard_service.assert_request_device_active(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            device_id=device_id,
        )
    except ValueError as exc:
        code = str(exc or "DEVICE_NOT_ACTIVE").strip() or "DEVICE_NOT_ACTIVE"
        if code not in {"DEVICE_NOT_ACTIVE", "DEVICE_REVOKED", "DEVICE_LOGGED_OUT"}:
            code = "DEVICE_NOT_ACTIVE"
        _emit_policy_security_event(
            request=request,
            claims=claims,
            event_code=code,
            severity="HIGH",
            details={"method": method, "path": path, "device_id": device_id},
        )
        raise HTTPException(status_code=403, detail=code) from exc
    finally:
        db.close()


def _tenant_db_effective_permissions_from_canonical(*, db, tenant_id: str, user_id: str) -> list[str]:
    truth = resolve_effective_permissions_from_canonical(
        db,
        workspace_type="TENANT",
        workspace_id=tenant_id,
        user_id=user_id,
    )

    if not bool(truth.get("found")):
        return []

    employment_status = str(truth.get("employment_status") or "").strip().upper()
    if employment_status != "ACTIVE":
        return []

    return list(truth.get("effective_permissions") or [])


def _tenant_db_effective_permissions_from_fast_path(
    *,
    db,
    tenant_id: str,
    user_id: str,
    required_source_version: int,
) -> tuple[list[str] | None, bool]:
    truth = resolve_effective_permissions_from_fast_path(
        db,
        workspace_type="TENANT",
        workspace_id=tenant_id,
        user_id=user_id,
        required_source_version=required_source_version,
    )

    if not bool(truth.get("found")):
        return None, False
    if not bool(truth.get("valid")):
        return None, False

    return list(truth.get("effective_permissions") or []), True


def _tenant_db_effective_permissions(*, claims: dict[str, Any], request: Request | None = None) -> list[str]:
    wrapper_started = time.perf_counter()
    breakdown_enabled = _tenant_db_authz_wrapper_breakdown_enabled()
    session_ms = 0.0
    fastpath_call_ms = 0.0

    shadow_compares = 0
    shadow_mismatches = 0
    fast_hits = 0
    fallbacks = 0

    cache_enabled = bool(request is not None and _request_authz_cache_enabled())
    cache: dict[str, Any] | None = _request_authz_cache(request) if cache_enabled and request is not None else None
    try:
        tenant_id = ensure_tenant_scope_claims(claims, request=request)
    except TypeError as exc:
        # Backward-compatible for monkeypatched tests using legacy callable signature.
        if "unexpected keyword argument 'request'" in str(exc):
            tenant_id = ensure_tenant_scope_claims(claims)
        else:
            raise

    roles = {normalize_permission(x) for x in list((claims or {}).get("roles") or []) if normalize_permission(x)}
    if "SUPERADMIN" in roles:
        return ["*"]

    user_id = str((claims or {}).get("sub") or "").strip()
    if not user_id:
        return []

    settings = get_settings()
    fast_path_enabled = _tenant_db_fast_path_enabled(settings=settings)
    shadow_compare_enabled = _tenant_db_fast_path_shadow_compare_enabled(settings=settings)
    required_source_version = max(1, int(settings.authz_tenant_db_fast_path_source_version))
    claims_sig = cache.get("tenant_scope_claims_signature") if isinstance(cache, dict) else None
    if not isinstance(claims_sig, tuple):
        claims_sig = _claims_signature(claims)
    cache_key = (
        claims_sig,
        bool(fast_path_enabled),
        bool(shadow_compare_enabled),
        int(required_source_version),
    )
    if isinstance(cache, dict):
        cached_key = cache.get("tenant_db_authz_key")
        cached_permissions = cache.get("tenant_db_authz_permissions")
        if cached_key == cache_key and isinstance(cached_permissions, list):
            return list(cached_permissions)

    db = None
    db_factory = get_session_factory()

    def _get_or_open_db():
        nonlocal db, session_ms
        if db is None:
            sess_started = time.perf_counter()
            db = db_factory()
            session_ms += (time.perf_counter() - sess_started) * 1000.0
        return db

    try:
        if fast_path_enabled:
            fast_permissions: list[str] | None = None
            fast_ok = False
            try:
                fast_started = time.perf_counter()
                fast_permissions, fast_ok = _tenant_db_effective_permissions_from_fast_path(
                    db=_get_or_open_db(),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    required_source_version=required_source_version,
                )
                fastpath_call_ms += (time.perf_counter() - fast_started) * 1000.0
            except Exception:  # noqa: BLE001
                fast_permissions, fast_ok = None, False
            if not fast_ok:
                fallbacks += 1
                canonical_permissions = _tenant_db_effective_permissions_from_canonical(
                    db=_get_or_open_db(),
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
                out = list(canonical_permissions)
            else:
                fast_hits += 1
                out = list(fast_permissions or [])

            if shadow_compare_enabled:
                shadow_compares += 1
                canonical_permissions = _tenant_db_effective_permissions_from_canonical(
                    db=_get_or_open_db(),
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
                if set(canonical_permissions) != set(list(out)):
                    shadow_mismatches += 1
                    if fast_ok:
                        fallbacks += 1
                        out = list(canonical_permissions)

            if isinstance(cache, dict):
                cache["tenant_db_authz_key"] = cache_key
                cache["tenant_db_authz_permissions"] = list(out)
            return out

        canonical_permissions = _tenant_db_effective_permissions_from_canonical(
            db=_get_or_open_db(),
            tenant_id=tenant_id,
            user_id=user_id,
        )

        if shadow_compare_enabled:
            shadow_compares += 1
            try:
                fast_started = time.perf_counter()
                fast_permissions, fast_ok = _tenant_db_effective_permissions_from_fast_path(
                    db=_get_or_open_db(),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    required_source_version=required_source_version,
                )
                fastpath_call_ms += (time.perf_counter() - fast_started) * 1000.0
            except Exception:  # noqa: BLE001
                fast_permissions, fast_ok = None, False
            if fast_ok and set(canonical_permissions) != set(list(fast_permissions or [])):
                shadow_mismatches += 1

        out = list(canonical_permissions)
        if isinstance(cache, dict):
            cache["tenant_db_authz_key"] = cache_key
            cache["tenant_db_authz_permissions"] = list(out)
        return out
    except Exception:  # noqa: BLE001
        # Fail-closed on any authz data-plane error.
        return []
    finally:
        _record_tenant_db_fast_path_counters(
            shadow_compares=shadow_compares,
            shadow_mismatches=shadow_mismatches,
            fast_hits=fast_hits,
            fallbacks=fallbacks,
        )
        if db is not None:
            close_started = time.perf_counter()
            db.close()
            session_ms += (time.perf_counter() - close_started) * 1000.0
        if breakdown_enabled:
            wrapper_ms = (time.perf_counter() - wrapper_started) * 1000.0
            record_segment("tenant_db_authz_wrapper_ms", max(0.0, float(wrapper_ms)))
            record_segment("tenant_db_authz_session_ms", max(0.0, float(session_ms)))
            record_segment("tenant_db_authz_fastpath_call_ms", max(0.0, float(fastpath_call_ms)))


def _effective_permissions_for_rule(
    *,
    claims: dict[str, Any],
    rule: RoutePolicy,
    request: Request | None = None,
) -> list[str]:
    mode = resolve_rule_authz_mode(rule)
    if mode == AUTHZ_MODE_TOKEN_CLAIMS:
        return effective_permissions_from_claims(claims)
    if mode in {AUTHZ_MODE_DB_TRUTH, AUTHZ_MODE_FAST_PATH}:
        tenant_authz_started = time.perf_counter()
        try:
            with sql_trace_zone("tenant_db_authz"):
                try:
                    return _tenant_db_effective_permissions(claims=claims, request=request)
                except TypeError as exc:
                    # Backward-compatible for monkeypatched tests using legacy callable signature.
                    if "unexpected keyword argument 'request'" in str(exc):
                        return _tenant_db_effective_permissions(claims=claims)
                    raise
        finally:
            record_segment("tenant_db_authz_ms", (time.perf_counter() - tenant_authz_started) * 1000.0)
    raise HTTPException(status_code=403, detail="policy_authz_source_invalid")


def enforce_request_policy(request: Request) -> None:
    path = _route_path_template(request)
    method = str(request.method or "GET").upper()

    if not is_protected_route_path(path):
        return

    policy_started = time.perf_counter()
    try:
        rule = ROUTE_POLICY.get((method, path))
        if rule is None:
            _emit_policy_security_event(
                request=request,
                claims=_claims_from_request(request),
                event_code="POLICY_MISSING_FOR_ROUTE",
                severity="CRITICAL",
                details={"method": method, "path": path},
            )
            raise HTTPException(status_code=403, detail="policy_missing_for_route")

        claims = _claims_from_request(request)
        if claims is None:
            _emit_policy_security_event(
                request=request,
                claims=None,
                event_code="MISSING_AUTHORIZATION",
                severity="HIGH",
                details={"method": method, "path": path},
            )
            raise HTTPException(status_code=401, detail="missing_authorization")

        required = normalize_permission(rule.permission_code)
        if required and required != AUTHENTICATED_ONLY:
            authz_mode = resolve_rule_authz_mode(rule)
            authz_started = time.perf_counter()
            try:
                effective = _effective_permissions_for_rule(claims=claims, rule=rule, request=request)
            except HTTPException as exc:
                _emit_policy_security_event(
                    request=request,
                    claims=claims,
                    event_code="POLICY_AUTHZ_SOURCE_INVALID" if str(exc.detail) == "policy_authz_source_invalid" else "PERMISSION_RESOLUTION_FAILED",
                    severity="CRITICAL" if str(exc.detail) == "policy_authz_source_invalid" else "HIGH",
                    details={
                        "required": required,
                        "method": method,
                        "path": path,
                        "authz_mode": authz_mode,
                        "detail": str(exc.detail),
                    },
                )
                raise
            finally:
                record_segment("authz_ms", (time.perf_counter() - authz_started) * 1000.0)

            if not is_permission_allowed(required, effective):
                _emit_policy_security_event(
                    request=request,
                    claims=claims,
                    event_code="PERMISSION_DENIED",
                    severity="HIGH",
                    details={
                        "required": required,
                        "method": method,
                        "path": path,
                        "authz_mode": authz_mode,
                    },
                )
                raise HTTPException(status_code=403, detail=f"permission_required:{required}")

            _enforce_step_up_if_required(request=request, claims=claims, required=bool(rule.step_up))

        _enforce_device_policy_for_business_routes(
            request=request,
            claims=claims,
            method=method,
            path=path,
        )
    finally:
        policy_ms = (time.perf_counter() - policy_started) * 1000.0
        record_segment("policy_resolve_ms", policy_ms)
        if _protected_envelope_breakdown_enabled():
            record_segment("protected_policy_ms", policy_ms)

def policy_coverage_snapshot() -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rules": len(ROUTE_POLICY),
        "protected_prefixes": list(PROTECTED_PREFIXES),
        "public_prefixes": list(PUBLIC_PREFIXES),
    }







