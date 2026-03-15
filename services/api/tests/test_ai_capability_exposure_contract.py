from __future__ import annotations

import app.modules.ai.eidon_capability_exposure_contract_v1 as exposure_contract_mod
import app.modules.ai.eidon_capability_registry_contract_v1 as capability_registry_mod
import app.modules.ai.eidon_orders_intent_contract_v1 as intent_contract_mod
import app.modules.ai.orders_copilot_orchestration_service as orchestration_service_mod
from app.core.policy_matrix import ROUTE_POLICY
from app.core.route_ownership import ROUTE_PLANE_OPERATIONAL, resolve_route_plane
from app.main import app


def test_capability_exposure_registry_has_expected_entries_and_flags() -> None:
    expected_codes = {
        "AI.ORDERS.RETRIEVE_REFERENCE",
        "AI.ORDERS.DOCUMENT_UNDERSTANDING",
        "AI.ORDERS.DRAFTING",
        "AI.ORDERS.FEEDBACK",
        "AI.ORDERS.COPILOT",
    }
    assert set(exposure_contract_mod.get_allowed_exposure_capability_codes()) == expected_codes
    assert set(exposure_contract_mod.EIDON_CAPABILITY_EXPOSURE_REGISTRY_V1.keys()) == expected_codes

    routable_codes = {
        code
        for code, entry in exposure_contract_mod.EIDON_CAPABILITY_EXPOSURE_REGISTRY_V1.items()
        if bool(entry.get("copilot_routable"))
    }
    assert routable_codes == {
        "AI.ORDERS.RETRIEVE_REFERENCE",
        "AI.ORDERS.DOCUMENT_UNDERSTANDING",
        "AI.ORDERS.DRAFTING",
        "AI.ORDERS.FEEDBACK",
    }

    copilot_entry = exposure_contract_mod.get_exposure_entry_or_fail("AI.ORDERS.COPILOT")
    assert copilot_entry.get("orchestration_entrypoint") is True
    assert copilot_entry.get("copilot_routable") is False

    for code in expected_codes:
        assert exposure_contract_mod.get_exposure_entry_or_fail(code).get("advisory_only") is True


def test_capability_exposure_endpoints_match_openapi_policy_and_ownership() -> None:
    schema = app.openapi()
    openapi_paths = set((schema.get("paths") or {}).keys())

    for endpoint_path, capability_code in exposure_contract_mod.EIDON_EXPOSURE_ENDPOINT_PATH_TO_CAPABILITY_CODE_V1.items():
        assert endpoint_path in openapi_paths
        assert exposure_contract_mod.resolve_exposure_capability_code_by_endpoint_path_or_fail(endpoint_path) == capability_code
        assert ("POST", endpoint_path) in ROUTE_POLICY
        assert resolve_route_plane("POST", endpoint_path) == ROUTE_PLANE_OPERATIONAL


def test_capability_exposure_intent_contract_and_fail_closed_behavior() -> None:
    for intent, capability_code in capability_registry_mod.EIDON_ORDERS_INTENT_TO_CAPABILITY_CODE.items():
        assert intent_contract_mod.resolve_orders_copilot_capability_code_or_fail(intent) == capability_code
        assert exposure_contract_mod.is_copilot_routable_capability_or_fail(capability_code) is True
        assert exposure_contract_mod.is_orchestration_entrypoint_capability_or_fail(capability_code) is False

    unsupported_error = None
    try:
        intent_contract_mod.resolve_orders_copilot_capability_code_or_fail("not_supported")
    except ValueError as exc:  # pragma: no cover - explicit fail-closed contract assertion
        unsupported_error = str(exc)
    assert unsupported_error == capability_registry_mod.EIDON_ORDERS_COPILOT_UNSUPPORTED_INTENT_CODE

    unknown_capability_error = None
    try:
        exposure_contract_mod.get_exposure_entry_or_fail("AI.ORDERS.NOT_REAL")
    except ValueError as exc:  # pragma: no cover - explicit fail-closed contract assertion
        unknown_capability_error = str(exc)
    assert unknown_capability_error == exposure_contract_mod.EIDON_UNKNOWN_EXPOSURE_CAPABILITY_CODE

    unknown_endpoint_error = None
    try:
        exposure_contract_mod.resolve_exposure_capability_code_by_endpoint_path_or_fail("/ai/tenant-copilot/not-real")
    except ValueError as exc:  # pragma: no cover - explicit fail-closed contract assertion
        unknown_endpoint_error = str(exc)
    assert unknown_endpoint_error == exposure_contract_mod.EIDON_UNKNOWN_EXPOSURE_ENDPOINT_PATH


def test_orders_intent_contract_fail_closed_when_intent_points_to_non_routable_entrypoint() -> None:
    intent_key = capability_registry_mod.ORDERS_COPILOT_INTENT_RETRIEVE_ORDER_REFERENCE
    original = capability_registry_mod.EIDON_ORDERS_INTENT_TO_CAPABILITY_CODE[intent_key]
    capability_registry_mod.EIDON_ORDERS_INTENT_TO_CAPABILITY_CODE[intent_key] = (
        capability_registry_mod.EIDON_CAPABILITY_AI_ORDERS_COPILOT
    )

    try:
        exposure_violation = None
        try:
            intent_contract_mod.resolve_orders_copilot_capability_code_or_fail(intent_key)
        except ValueError as exc:  # pragma: no cover - explicit fail-closed contract assertion
            exposure_violation = str(exc)
        assert exposure_violation == intent_contract_mod.ORDERS_COPILOT_INTENT_EXPOSURE_VIOLATION
    finally:
        capability_registry_mod.EIDON_ORDERS_INTENT_TO_CAPABILITY_CODE[intent_key] = original


def test_orchestration_service_refuses_non_routable_capability(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestration_service_mod,
        "resolve_orders_copilot_capability_code_or_fail",
        lambda _intent: capability_registry_mod.EIDON_CAPABILITY_AI_ORDERS_RETRIEVE_REFERENCE,
    )
    monkeypatch.setattr(
        orchestration_service_mod,
        "is_copilot_routable_capability_or_fail",
        lambda _capability: False,
    )

    err = None
    try:
        orchestration_service_mod.service.orchestrate(
            db=object(),  # type: ignore[arg-type]
            tenant_id="tenant-ai-001",
            intent="retrieve_order_reference",
            payload={"order_id": "ord-visible-001"},
        )
    except ValueError as exc:  # pragma: no cover - explicit fail-closed contract assertion
        err = str(exc)
    assert err == orchestration_service_mod.ORDERS_COPILOT_NON_ROUTABLE_CAPABILITY
