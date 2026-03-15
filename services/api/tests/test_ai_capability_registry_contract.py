from __future__ import annotations

import app.modules.ai.eidon_capability_registry_contract_v1 as capability_registry_mod
import app.modules.ai.eidon_orders_intent_contract_v1 as intent_contract_mod
import app.modules.ai.orders_copilot_orchestration_service as orchestration_service_mod
from app.core.policy_matrix import ROUTE_POLICY
from app.core.route_ownership import ROUTE_PLANE_OPERATIONAL, resolve_route_plane
from app.main import app


def test_capability_registry_contract_contains_expected_entries_and_advisory_only() -> None:
    expected_codes = {
        "AI.ORDERS.RETRIEVE_REFERENCE",
        "AI.ORDERS.DOCUMENT_UNDERSTANDING",
        "AI.ORDERS.DRAFTING",
        "AI.ORDERS.FEEDBACK",
        "AI.ORDERS.COPILOT",
    }
    assert set(capability_registry_mod.get_allowed_capability_codes()) == expected_codes
    assert set(capability_registry_mod.EIDON_ORDERS_CAPABILITY_REGISTRY_V1.keys()) == expected_codes

    for capability_code in expected_codes:
        entry = capability_registry_mod.get_capability_entry_or_fail(capability_code)
        assert entry.get("advisory_only") is True
        assert entry.get("plane") == "OPERATIONAL"
        assert entry.get("module_scope") == "ORDERS"

    assert (
        capability_registry_mod.get_capability_entry_or_fail("AI.ORDERS.RETRIEVE_REFERENCE").get(
            "human_confirmation_required"
        )
        is False
    )
    for capability_code in {
        "AI.ORDERS.DOCUMENT_UNDERSTANDING",
        "AI.ORDERS.DRAFTING",
        "AI.ORDERS.FEEDBACK",
        "AI.ORDERS.COPILOT",
    }:
        assert capability_registry_mod.get_capability_entry_or_fail(capability_code).get("human_confirmation_required") is True


def test_capability_registry_intent_contract_and_orchestration_are_aligned() -> None:
    assert set(capability_registry_mod.EIDON_ORDERS_COPILOT_SUPPORTED_INTENTS) == set(
        intent_contract_mod.EIDON_ORDERS_COPILOT_SUPPORTED_INTENTS
    )
    assert dict(capability_registry_mod.EIDON_ORDERS_INTENT_TO_CAPABILITY_CODE) == dict(
        intent_contract_mod.EIDON_ORDERS_COPILOT_INTENT_TO_CAPABILITY_CODE
    )
    assert (
        orchestration_service_mod.UNSUPPORTED_ORDERS_COPILOT_INTENT
        == capability_registry_mod.EIDON_ORDERS_COPILOT_UNSUPPORTED_INTENT_CODE
    )

    for intent in capability_registry_mod.EIDON_ORDERS_COPILOT_SUPPORTED_INTENTS:
        resolved_from_registry = capability_registry_mod.resolve_capability_code_by_intent_or_fail(intent)
        resolved_from_intent_contract = intent_contract_mod.resolve_orders_copilot_capability_code_or_fail(intent)
        assert resolved_from_registry == resolved_from_intent_contract

    unsupported_error = None
    try:
        capability_registry_mod.resolve_capability_code_by_intent_or_fail("not_supported")
    except ValueError as exc:  # pragma: no cover - explicit fail-closed contract assertion
        unsupported_error = str(exc)
    assert unsupported_error == capability_registry_mod.EIDON_ORDERS_COPILOT_UNSUPPORTED_INTENT_CODE


def test_capability_registry_canonical_endpoints_match_openapi_policy_and_ownership() -> None:
    schema = app.openapi()
    openapi_paths = set((schema.get("paths") or {}).keys())

    for endpoint_path, capability_code in capability_registry_mod.EIDON_ORDERS_CANONICAL_ENDPOINT_PATH_TO_CAPABILITY_CODE.items():
        assert endpoint_path in openapi_paths
        assert capability_registry_mod.resolve_capability_code_by_endpoint_path_or_fail(endpoint_path) == capability_code
        assert ("POST", endpoint_path) in ROUTE_POLICY
        assert resolve_route_plane("POST", endpoint_path) == ROUTE_PLANE_OPERATIONAL

    unknown_endpoint_error = None
    try:
        capability_registry_mod.resolve_capability_code_by_endpoint_path_or_fail("/ai/tenant-copilot/not-real")
    except ValueError as exc:  # pragma: no cover - explicit fail-closed contract assertion
        unknown_endpoint_error = str(exc)
    assert unknown_endpoint_error == capability_registry_mod.EIDON_UNKNOWN_CAPABILITY_ENDPOINT
