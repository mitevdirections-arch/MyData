from __future__ import annotations


AI_SURFACE_CONTRACT_V1 = {
    "tenant_runtime": {
        "surface_code": "AI_TENANT_RUNTIME",
        "plane_ownership": "OPERATIONAL",
        "business_runtime": True,
        "marketplace_facing": False,
        "protected_route_prefixes": ["/ai/tenant-copilot"],
        "contract_ref": "AI_CONTRACT_V1:tenant_runtime",
        "retrieval_contract_ref": "AI_RETRIEVAL_CONTRACT_V1:tenant_runtime",
        "drafting_contract_ref": "EIDON_DRAFTING_CONTRACT_V1:tenant_runtime",
        "template_learning_contract_ref": "EIDON_TEMPLATE_LEARNING_CONTRACT_V1:tenant_runtime",
        "notes": "Operational tenant AI runtime surface.",
    },
    "superadmin_control": {
        "surface_code": "AI_SUPERADMIN_CONTROL",
        "plane_ownership": "FOUNDATION",
        "business_runtime": False,
        "marketplace_facing": False,
        "protected_route_prefixes": ["/ai/superadmin-copilot"],
        "contract_ref": "AI_CONTRACT_V1:superadmin_control",
        "notes": "Foundation-controlled superadmin AI control surface.",
    },
}
