from __future__ import annotations

import re
from typing import Any

WORKSPACE_TENANT = "TENANT"
WORKSPACE_PLATFORM = "PLATFORM"
PLATFORM_WORKSPACE_ID = "platform"

ROLE_CODE_RE = re.compile(r"[^A-Z0-9_]")
PERM_RE = re.compile(r"[^A-Z0-9_.*:]")

CORE_PLAN_SEATS: dict[str, int] = {"CORE3": 3, "CORE5": 5, "CORE8": 8, "CORE13": 13, "CORE21": 21, "CORE24": 24, "CORE34": 34, "CORE45": 45}
UNLIMITED_CORE_PLANS: set[str] = {"COREENTERPRISE", "CORE_ENT"}

DEFAULT_TENANT_ROLES: list[dict[str, Any]] = [
    {"role_code": "TENANT_ADMIN", "role_name": "Tenant Administrator", "permissions": ["*"]},
    {"role_code": "ACCOUNTANT", "role_name": "Accountant", "permissions": ["FINANCE.READ", "FINANCE.WRITE", "INVOICES.READ", "INVOICES.WRITE", "PAYMENTS.READ"]},
    {"role_code": "DISPATCHER", "role_name": "Dispatcher", "permissions": ["ORDERS.READ", "ORDERS.WRITE", "FLEET.READ", "CMR.WRITE"]},
    {"role_code": "DRIVER", "role_name": "Driver", "permissions": ["ORDERS.READ", "TRIPS.READ", "TRIPS.UPDATE_STATUS"]},
    {"role_code": "WAREHOUSE_OPERATOR", "role_name": "Warehouse Operator", "permissions": ["WAREHOUSE.READ", "WAREHOUSE.WRITE", "STOCK.READ", "STOCK.WRITE"]},
    {"role_code": "IT_ADMIN", "role_name": "IT Administrator", "permissions": ["SECURITY.READ", "SECURITY.WRITE", "USERS.READ", "USERS.WRITE"]},
]

DEFAULT_PLATFORM_ROLES: list[dict[str, Any]] = [
    {"role_code": "SUPERADMIN_STAFF", "role_name": "Superadmin Staff", "permissions": ["*"]},
    {"role_code": "SUPPORT_AGENT", "role_name": "Support Agent", "permissions": ["SUPPORT.READ", "SUPPORT.WRITE", "INCIDENTS.READ", "INCIDENTS.WRITE"]},
    {"role_code": "SECURITY_AUDITOR", "role_name": "Security Auditor", "permissions": ["AUDIT.READ", "SECURITY.READ", "SECURITY.WRITE"]},
    {"role_code": "BILLING_ADMIN", "role_name": "Billing Admin", "permissions": ["BILLING.READ", "BILLING.WRITE", "LICENSES.READ", "LICENSES.WRITE", "PAYMENTS.READ", "PAYMENTS.WRITE"]},
    {"role_code": "OPS_ADMIN", "role_name": "Operations Admin", "permissions": ["OPS.READ", "OPS.WRITE", "TENANTS.READ"]},
]
