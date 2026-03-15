from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import time
from typing import Any

from fastapi import HTTPException, Request

from app.core.auth import ensure_tenant_scope_claims, is_superadmin_step_up_code_valid
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
    "/profile/",
    "/users/",
    "/support/",
    "/iam/",
    "/i18n/effective",
    "/ai/",
)


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
    ("POST", "/ai/tenant-copilot/order-draft-assist"): RoutePolicy("AI.COPILOT", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/ai/tenant-copilot/order-document-intake"): RoutePolicy("AI.COPILOT", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("POST", "/ai/tenant-copilot/order-intake-feedback"): RoutePolicy("AI.COPILOT", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
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
    ("GET", "/profile/admin/roles"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/profile/admin/roles/{role_code}"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/profile/admin/users"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/profile/admin/users/{user_id}"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/profile/admin/users/{user_id}"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/profile/admin/users/{user_id}/roles"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
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
    ("POST", "/profile/admin/users/{user_id}/credentials/reset-password"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
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
    ("GET", "/users/admin/users"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("GET", "/users/admin/users/{user_id}"): RoutePolicy("IAM.READ", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/users/admin/users/{user_id}"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
    ("PUT", "/users/admin/users/{user_id}/roles"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
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
    ("POST", "/users/admin/users/{user_id}/credentials/reset-password"): RoutePolicy("IAM.WRITE", authz_mode=AUTHZ_MODE_TOKEN_CLAIMS),
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


def _claims_from_request(request: Request) -> dict[str, Any] | None:
    c = getattr(request.state, "claims", None)
    if isinstance(c, dict):
        return c
    return None


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


def _tenant_db_effective_permissions(*, claims: dict[str, Any]) -> list[str]:
    tenant_id = ensure_tenant_scope_claims(claims)

    roles = {normalize_permission(x) for x in list((claims or {}).get("roles") or []) if normalize_permission(x)}
    if "SUPERADMIN" in roles:
        return ["*"]

    user_id = str((claims or {}).get("sub") or "").strip()
    if not user_id:
        return []

    settings = get_settings()
    fast_path_enabled = bool(settings.authz_tenant_db_fast_path_enabled)
    shadow_compare_enabled = bool(settings.authz_tenant_db_fast_path_shadow_compare_enabled)
    required_source_version = max(1, int(settings.authz_tenant_db_fast_path_source_version))

    db = get_session_factory()()
    try:
        if fast_path_enabled:
            fast_permissions, fast_ok = _tenant_db_effective_permissions_from_fast_path(
                db=db,
                tenant_id=tenant_id,
                user_id=user_id,
                required_source_version=required_source_version,
            )
            if not fast_ok:
                return []

            if shadow_compare_enabled:
                canonical_permissions = _tenant_db_effective_permissions_from_canonical(
                    db=db,
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
                if set(canonical_permissions) != set(list(fast_permissions or [])):
                    return []

            return list(fast_permissions or [])

        canonical_permissions = _tenant_db_effective_permissions_from_canonical(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        if shadow_compare_enabled:
            fast_permissions, fast_ok = _tenant_db_effective_permissions_from_fast_path(
                db=db,
                tenant_id=tenant_id,
                user_id=user_id,
                required_source_version=required_source_version,
            )
            if fast_ok and set(canonical_permissions) != set(list(fast_permissions or [])):
                return []

        return canonical_permissions
    except Exception:  # noqa: BLE001
        # Fail-closed on any authz data-plane error.
        return []
    finally:
        db.close()


def _effective_permissions_for_rule(*, claims: dict[str, Any], rule: RoutePolicy) -> list[str]:
    mode = resolve_rule_authz_mode(rule)
    if mode == AUTHZ_MODE_TOKEN_CLAIMS:
        return effective_permissions_from_claims(claims)
    if mode in {AUTHZ_MODE_DB_TRUTH, AUTHZ_MODE_FAST_PATH}:
        tenant_authz_started = time.perf_counter()
        try:
            return _tenant_db_effective_permissions(claims=claims)
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
                effective = _effective_permissions_for_rule(claims=claims, rule=rule)
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
    finally:
        record_segment("policy_resolve_ms", (time.perf_counter() - policy_started) * 1000.0)

def policy_coverage_snapshot() -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rules": len(ROUTE_POLICY),
        "protected_prefixes": list(PROTECTED_PREFIXES),
        "public_prefixes": list(PUBLIC_PREFIXES),
    }







