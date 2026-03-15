from __future__ import annotations


SUPPORT_SURFACE_CONTRACT_V1 = {
    "tenant_runtime": {
        "surface_code": "SUPPORT_TENANT_RUNTIME",
        "plane_ownership": "OPERATIONAL",
        "business_runtime": True,
        "marketplace_facing": False,
        "protected_route_prefixes": ["/support/tenant"],
        "public_route_prefixes": ["/support/public"],
        "notes": "Tenant runtime support surface, including public FAQ runtime exposure.",
    },
    "superadmin_control": {
        "surface_code": "SUPPORT_SUPERADMIN_CONTROL",
        "plane_ownership": "FOUNDATION",
        "business_runtime": False,
        "marketplace_facing": False,
        "protected_route_prefixes": ["/support/superadmin"],
        "public_route_prefixes": [],
        "notes": "Foundation-controlled superadmin support control surface.",
    },
}
