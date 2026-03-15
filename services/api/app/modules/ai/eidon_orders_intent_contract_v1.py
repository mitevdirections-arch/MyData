from __future__ import annotations

from app.modules.ai.eidon_capability_exposure_contract_v1 import (
    is_copilot_routable_capability_or_fail,
    is_orchestration_entrypoint_capability_or_fail,
)
from app.modules.ai.eidon_capability_registry_contract_v1 import (
    EIDON_ORDERS_COPILOT_SUPPORTED_INTENTS,
    EIDON_ORDERS_COPILOT_UNSUPPORTED_INTENT_CODE,
    EIDON_ORDERS_INTENT_TO_CAPABILITY_CODE,
    ORDERS_COPILOT_INTENT_DOCUMENT_UNDERSTANDING,
    ORDERS_COPILOT_INTENT_ORDER_DRAFTING,
    ORDERS_COPILOT_INTENT_ORDER_FEEDBACK,
    ORDERS_COPILOT_INTENT_RETRIEVE_ORDER_REFERENCE,
    resolve_capability_code_by_intent_or_fail,
)

EIDON_ORDERS_COPILOT_INTENT_TO_CAPABILITY_CODE: dict[str, str] = dict(EIDON_ORDERS_INTENT_TO_CAPABILITY_CODE)
ORDERS_COPILOT_INTENT_EXPOSURE_VIOLATION = "orders_copilot_intent_exposure_violation"

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
    "intent_to_capability_code": dict(EIDON_ORDERS_COPILOT_INTENT_TO_CAPABILITY_CODE),
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


def resolve_orders_copilot_capability_code_or_fail(intent: str | None) -> str:
    capability_code = resolve_capability_code_by_intent_or_fail(normalize_orders_copilot_intent(intent))
    if is_orchestration_entrypoint_capability_or_fail(capability_code):
        raise ValueError(ORDERS_COPILOT_INTENT_EXPOSURE_VIOLATION)
    if not is_copilot_routable_capability_or_fail(capability_code):
        raise ValueError(ORDERS_COPILOT_INTENT_EXPOSURE_VIOLATION)
    return capability_code
