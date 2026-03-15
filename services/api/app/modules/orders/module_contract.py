from __future__ import annotations


MODULE_CONTRACT_V1 = {
    "module_name": "Orders",
    "module_code": "MODULE_ORDERS",
    "plane_ownership": "OPERATIONAL",
    "authz_mode": "DB_TRUTH",
    "marketplace_facing": True,
    "typed_schemas": True,
    "readme": True,
    "router_service_boundaries": True,
    "sensitivity": "MEDIUM",
    "route_prefixes": ["/orders"],
    "minimum_tests": [
        "tests/test_orders_routes.py",
        "tests/test_orders_contract.py",
    ],
    "minimum_gate_expectations": [
        "authz_contract",
        "route_ownership_contract",
        "module_factory_contract",
        "module_factory_coverage_contract",
        "support_plane_decomposition_contract",
        "ai_plane_decomposition_contract",
    ],
    "notes": "Orders is reference module for contract shape; workflow maturity is intentionally incremental.",
}
