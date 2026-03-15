from __future__ import annotations

import app.modules.ai.eidon_orders_intent_contract_v1 as intent_contract_mod
import app.modules.ai.orders_copilot_orchestration_service as orchestration_service_mod
from app.main import app


def test_orders_intent_contract_registry_is_canonical_and_service_aligned() -> None:
    expected = {
        "retrieve_order_reference",
        "document_understanding",
        "order_drafting",
        "order_feedback",
    }
    assert set(intent_contract_mod.EIDON_ORDERS_COPILOT_SUPPORTED_INTENTS) == expected
    assert set(orchestration_service_mod.SUPPORTED_ORDERS_COPILOT_INTENTS) == expected
    assert (
        orchestration_service_mod.UNSUPPORTED_ORDERS_COPILOT_INTENT
        == intent_contract_mod.EIDON_ORDERS_COPILOT_UNSUPPORTED_INTENT_CODE
    )

    for intent in expected:
        assert intent_contract_mod.is_supported_orders_copilot_intent(intent) is True
    assert intent_contract_mod.is_supported_orders_copilot_intent("not_supported") is False


def test_orders_intent_contract_openapi_surface_reflects_registry() -> None:
    schema = app.openapi()
    route = ((schema.get("paths") or {}).get("/ai/tenant-copilot/orders-copilot") or {}).get("post") or {}
    req_ref = (
        ((((route.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref")
        or ""
    )
    assert req_ref

    schema_name = req_ref.rsplit("/", 1)[-1]
    req_schema = (((schema.get("components") or {}).get("schemas") or {}).get(schema_name) or {})
    intent_schema = ((req_schema.get("properties") or {}).get("intent") or {})
    enum_values = set(intent_schema.get("enum") or [])

    assert enum_values == set(intent_contract_mod.EIDON_ORDERS_COPILOT_SUPPORTED_INTENTS)
