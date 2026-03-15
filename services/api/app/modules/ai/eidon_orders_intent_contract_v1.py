from __future__ import annotations


EIDON_ORDERS_COPILOT_UNSUPPORTED_INTENT_CODE = "unsupported_orders_copilot_intent"

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

EIDON_ORDERS_COPILOT_INTENT_TO_CAPABILITY_SURFACE: dict[str, str] = {
    ORDERS_COPILOT_INTENT_RETRIEVE_ORDER_REFERENCE: "EIDON_ORDER_REFERENCE_RETRIEVAL_SURFACE_V1",
    ORDERS_COPILOT_INTENT_DOCUMENT_UNDERSTANDING: "EIDON_DOCUMENT_UNDERSTANDING_SURFACE_V1",
    ORDERS_COPILOT_INTENT_ORDER_DRAFTING: "EIDON_ORDER_DRAFTING_SURFACE_V1",
    ORDERS_COPILOT_INTENT_ORDER_FEEDBACK: "EIDON_ORDER_FEEDBACK_SURFACE_V1",
}

EIDON_ORDERS_INTENT_CONTRACT_V1 = {
    "contract_code": "EIDON_ORDERS_INTENT_CONTRACT_V1",
    "version": "v1",
    "surface": {
        "route": "POST /ai/tenant-copilot/orders-copilot",
        "capability": "EIDON_ORDERS_COPILOT_ORCHESTRATION_V1",
        "tenant_facing": True,
        "plane": "OPERATIONAL",
    },
    "supported_intents": list(EIDON_ORDERS_COPILOT_SUPPORTED_INTENTS),
    "intent_to_capability_surface": dict(EIDON_ORDERS_COPILOT_INTENT_TO_CAPABILITY_SURFACE),
    "rules": {
        "unsupported_intent_fail_closed": True,
        "advisory_only": True,
        "no_finalize": True,
        "no_tenant_runtime_mutation": True,
    },
    "fail_closed": {
        "unsupported_intent_code": EIDON_ORDERS_COPILOT_UNSUPPORTED_INTENT_CODE,
    },
}


def normalize_orders_copilot_intent(intent: str | None) -> str:
    return str(intent or "").strip()


def is_supported_orders_copilot_intent(intent: str | None) -> bool:
    return normalize_orders_copilot_intent(intent) in EIDON_ORDERS_COPILOT_SUPPORTED_INTENTS

