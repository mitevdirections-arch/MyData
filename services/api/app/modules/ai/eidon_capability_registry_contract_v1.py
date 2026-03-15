from __future__ import annotations

from typing import Any


EIDON_ORDERS_COPILOT_UNSUPPORTED_INTENT_CODE = "unsupported_orders_copilot_intent"
EIDON_UNKNOWN_CAPABILITY_CODE = "unknown_eidon_capability_code"
EIDON_UNKNOWN_CAPABILITY_ENDPOINT = "unknown_eidon_capability_endpoint"
EIDON_CAPABILITY_REGISTRY_EXPOSURE_MISMATCH = "eidon_capability_registry_exposure_mismatch"

ORDERS_COPILOT_INTENT_RETRIEVE_ORDER_REFERENCE = "retrieve_order_reference"
ORDERS_COPILOT_INTENT_DOCUMENT_UNDERSTANDING = "document_understanding"
ORDERS_COPILOT_INTENT_ORDER_DRAFTING = "order_drafting"
ORDERS_COPILOT_INTENT_ORDER_FEEDBACK = "order_feedback"

EIDON_ORDERS_COPILOT_SUPPORTED_INTENTS: tuple[str, ...] = (
    ORDERS_COPILOT_INTENT_RETRIEVE_ORDER_REFERENCE,
    ORDERS_COPILOT_INTENT_DOCUMENT_UNDERSTANDING,
    ORDERS_COPILOT_INTENT_ORDER_DRAFTING,
    ORDERS_COPILOT_INTENT_ORDER_FEEDBACK,
)

EIDON_CAPABILITY_AI_ORDERS_RETRIEVE_REFERENCE = "AI.ORDERS.RETRIEVE_REFERENCE"
EIDON_CAPABILITY_AI_ORDERS_DOCUMENT_UNDERSTANDING = "AI.ORDERS.DOCUMENT_UNDERSTANDING"
EIDON_CAPABILITY_AI_ORDERS_DRAFTING = "AI.ORDERS.DRAFTING"
EIDON_CAPABILITY_AI_ORDERS_FEEDBACK = "AI.ORDERS.FEEDBACK"
EIDON_CAPABILITY_AI_ORDERS_COPILOT = "AI.ORDERS.COPILOT"

EIDON_ORDERS_RETRIEVE_REFERENCE_CANONICAL_ENDPOINT_PATH = "/ai/tenant-copilot/retrieve-order-reference"
EIDON_ORDERS_DOCUMENT_UNDERSTANDING_CANONICAL_ENDPOINT_PATH = "/ai/tenant-copilot/document-understanding"
EIDON_ORDERS_DRAFTING_CANONICAL_ENDPOINT_PATH = "/ai/tenant-copilot/order-drafting"
EIDON_ORDERS_FEEDBACK_CANONICAL_ENDPOINT_PATH = "/ai/tenant-copilot/order-feedback"
EIDON_ORDERS_COPILOT_CANONICAL_ENDPOINT_PATH = "/ai/tenant-copilot/orders-copilot"

EIDON_ORDERS_INTENT_TO_CAPABILITY_CODE: dict[str, str] = {
    ORDERS_COPILOT_INTENT_RETRIEVE_ORDER_REFERENCE: EIDON_CAPABILITY_AI_ORDERS_RETRIEVE_REFERENCE,
    ORDERS_COPILOT_INTENT_DOCUMENT_UNDERSTANDING: EIDON_CAPABILITY_AI_ORDERS_DOCUMENT_UNDERSTANDING,
    ORDERS_COPILOT_INTENT_ORDER_DRAFTING: EIDON_CAPABILITY_AI_ORDERS_DRAFTING,
    ORDERS_COPILOT_INTENT_ORDER_FEEDBACK: EIDON_CAPABILITY_AI_ORDERS_FEEDBACK,
}

EIDON_ORDERS_CANONICAL_ENDPOINT_PATH_TO_CAPABILITY_CODE: dict[str, str] = {
    EIDON_ORDERS_RETRIEVE_REFERENCE_CANONICAL_ENDPOINT_PATH: EIDON_CAPABILITY_AI_ORDERS_RETRIEVE_REFERENCE,
    EIDON_ORDERS_DOCUMENT_UNDERSTANDING_CANONICAL_ENDPOINT_PATH: EIDON_CAPABILITY_AI_ORDERS_DOCUMENT_UNDERSTANDING,
    EIDON_ORDERS_DRAFTING_CANONICAL_ENDPOINT_PATH: EIDON_CAPABILITY_AI_ORDERS_DRAFTING,
    EIDON_ORDERS_FEEDBACK_CANONICAL_ENDPOINT_PATH: EIDON_CAPABILITY_AI_ORDERS_FEEDBACK,
    EIDON_ORDERS_COPILOT_CANONICAL_ENDPOINT_PATH: EIDON_CAPABILITY_AI_ORDERS_COPILOT,
}

EIDON_ORDERS_CAPABILITY_REGISTRY_V1: dict[str, dict[str, Any]] = {
    EIDON_CAPABILITY_AI_ORDERS_RETRIEVE_REFERENCE: {
        "capability_code": EIDON_CAPABILITY_AI_ORDERS_RETRIEVE_REFERENCE,
        "plane": "OPERATIONAL",
        "surface_kind": "TENANT_API_CANONICAL",
        "module_scope": "ORDERS",
        "advisory_only": True,
        "human_confirmation_required": False,
        "intent_names": [ORDERS_COPILOT_INTENT_RETRIEVE_ORDER_REFERENCE],
        "canonical_endpoint_paths": [EIDON_ORDERS_RETRIEVE_REFERENCE_CANONICAL_ENDPOINT_PATH],
        "governance_relevant": False,
        "description": "Tenant-safe order reference retrieval surface.",
    },
    EIDON_CAPABILITY_AI_ORDERS_DOCUMENT_UNDERSTANDING: {
        "capability_code": EIDON_CAPABILITY_AI_ORDERS_DOCUMENT_UNDERSTANDING,
        "plane": "OPERATIONAL",
        "surface_kind": "TENANT_API_CANONICAL",
        "module_scope": "ORDERS",
        "advisory_only": True,
        "human_confirmation_required": True,
        "intent_names": [ORDERS_COPILOT_INTENT_DOCUMENT_UNDERSTANDING],
        "canonical_endpoint_paths": [EIDON_ORDERS_DOCUMENT_UNDERSTANDING_CANONICAL_ENDPOINT_PATH],
        "governance_relevant": False,
        "description": "Tenant-facing document understanding surface with advisory-only output.",
    },
    EIDON_CAPABILITY_AI_ORDERS_DRAFTING: {
        "capability_code": EIDON_CAPABILITY_AI_ORDERS_DRAFTING,
        "plane": "OPERATIONAL",
        "surface_kind": "TENANT_API_CANONICAL",
        "module_scope": "ORDERS",
        "advisory_only": True,
        "human_confirmation_required": True,
        "intent_names": [ORDERS_COPILOT_INTENT_ORDER_DRAFTING],
        "canonical_endpoint_paths": [EIDON_ORDERS_DRAFTING_CANONICAL_ENDPOINT_PATH],
        "governance_relevant": False,
        "description": "Tenant-facing order drafting assist surface.",
    },
    EIDON_CAPABILITY_AI_ORDERS_FEEDBACK: {
        "capability_code": EIDON_CAPABILITY_AI_ORDERS_FEEDBACK,
        "plane": "OPERATIONAL",
        "surface_kind": "TENANT_API_CANONICAL",
        "module_scope": "ORDERS",
        "advisory_only": True,
        "human_confirmation_required": True,
        "intent_names": [ORDERS_COPILOT_INTENT_ORDER_FEEDBACK],
        "canonical_endpoint_paths": [EIDON_ORDERS_FEEDBACK_CANONICAL_ENDPOINT_PATH],
        "governance_relevant": False,
        "description": "Tenant-facing order feedback surface with de-identified quality seam.",
    },
    EIDON_CAPABILITY_AI_ORDERS_COPILOT: {
        "capability_code": EIDON_CAPABILITY_AI_ORDERS_COPILOT,
        "plane": "OPERATIONAL",
        "surface_kind": "TENANT_API_CANONICAL",
        "module_scope": "ORDERS",
        "advisory_only": True,
        "human_confirmation_required": True,
        "intent_names": list(EIDON_ORDERS_COPILOT_SUPPORTED_INTENTS),
        "canonical_endpoint_paths": [EIDON_ORDERS_COPILOT_CANONICAL_ENDPOINT_PATH],
        "governance_relevant": False,
        "description": "Tenant-facing orchestration surface for Orders intents.",
    },
}

EIDON_CAPABILITY_REGISTRY_CONTRACT_V1 = {
    "contract_code": "EIDON_CAPABILITY_REGISTRY_CONTRACT_V1",
    "version": "v1",
    "slice": "EIDON_ORDERS_AI_VERTICAL",
    "capability_codes": list(EIDON_ORDERS_CAPABILITY_REGISTRY_V1.keys()),
    "rules": {
        "fail_closed_registry_lookup": True,
        "advisory_only": True,
        "no_finalize": True,
        "no_tenant_runtime_mutation": True,
    },
}


def _normalize_lookup_key(value: str | None) -> str:
    return str(value or "").strip()


def get_allowed_capability_codes() -> tuple[str, ...]:
    return tuple(EIDON_ORDERS_CAPABILITY_REGISTRY_V1.keys())


def get_capability_entry_or_fail(capability_code: str | None) -> dict[str, Any]:
    normalized = _normalize_lookup_key(capability_code)
    entry = EIDON_ORDERS_CAPABILITY_REGISTRY_V1.get(normalized)
    if entry is None:
        raise ValueError(EIDON_UNKNOWN_CAPABILITY_CODE)
    return dict(entry)


def resolve_capability_code_by_intent_or_fail(intent: str | None) -> str:
    normalized = _normalize_lookup_key(intent)
    capability_code = EIDON_ORDERS_INTENT_TO_CAPABILITY_CODE.get(normalized)
    if capability_code is None:
        raise ValueError(EIDON_ORDERS_COPILOT_UNSUPPORTED_INTENT_CODE)
    return capability_code


def resolve_capability_code_by_endpoint_path_or_fail(endpoint_path: str | None) -> str:
    normalized = _normalize_lookup_key(endpoint_path)
    capability_code = EIDON_ORDERS_CANONICAL_ENDPOINT_PATH_TO_CAPABILITY_CODE.get(normalized)
    if capability_code is None:
        raise ValueError(EIDON_UNKNOWN_CAPABILITY_ENDPOINT)
    return capability_code


def validate_registry_alignment_with_exposure_or_fail() -> bool:
    from app.modules.ai.eidon_capability_exposure_contract_v1 import EIDON_CAPABILITY_EXPOSURE_REGISTRY_V1

    registry_codes = set(EIDON_ORDERS_CAPABILITY_REGISTRY_V1.keys())
    exposure_codes = set(EIDON_CAPABILITY_EXPOSURE_REGISTRY_V1.keys())
    if registry_codes != exposure_codes:
        raise ValueError(EIDON_CAPABILITY_REGISTRY_EXPOSURE_MISMATCH)
    return True
