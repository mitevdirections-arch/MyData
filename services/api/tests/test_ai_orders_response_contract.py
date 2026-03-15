from __future__ import annotations

from typing import Any

import app.modules.ai.eidon_orders_response_contract_v1 as response_contract_mod
import app.modules.ai.orders_copilot_orchestration_service as orchestration_service_mod


class _StubResult:
    def __init__(
        self,
        *,
        dumped: dict[str, Any],
        warnings: list[str] | None = None,
        source_traceability: Any = None,
        authoritative_finalize_allowed: bool = False,
    ) -> None:
        self._dumped = dict(dumped)
        self.warnings = list(warnings or [])
        self.source_traceability = source_traceability
        self.authoritative_finalize_allowed = authoritative_finalize_allowed

    def model_dump(self, *, exclude_none: bool = True) -> dict[str, Any]:
        _ = exclude_none
        return dict(self._dumped)


def _sample_surface_payloads() -> dict[str, dict[str, Any]]:
    return {
        response_contract_mod.EIDON_ORDERS_RESPONSE_SURFACE_RETRIEVE_REFERENCE: {
            "authoritative_finalize_allowed": False,
            "warnings": [],
            "source_traceability": {
                "retrieval_class": "tenant_visible_order_reference_lookup",
                "retrieval_marker": "summary_only_guarded_reference_lookup",
                "guard_outcome": "allow",
            },
        },
        response_contract_mod.EIDON_ORDERS_RESPONSE_SURFACE_DOCUMENT_UNDERSTANDING: {
            "authoritative_finalize_allowed": False,
            "warnings": ["missing_required_fields_detected"],
            "source_traceability": [{"field_path": "shipper.legal_name", "source_class": "normalized_document_input"}],
            "human_confirmation_required_items": ["authoritative_business_document_finalize"],
        },
        response_contract_mod.EIDON_ORDERS_RESPONSE_SURFACE_DRAFTING: {
            "authoritative_finalize_allowed": False,
            "warnings": ["ambiguous_fields_require_human_clarification"],
            "source_traceability": [{"field_path": "carrier.legal_name", "source_class": "draft_context"}],
            "human_confirmation_required_items": ["order_submission_or_state_transition"],
        },
        response_contract_mod.EIDON_ORDERS_RESPONSE_SURFACE_FEEDBACK: {
            "authoritative_finalize_allowed": False,
            "warnings": ["corrected_field_same_as_previous:order_no"],
            "source_traceability": [{"field_path": "order_no", "source_class": "tenant_user_feedback"}],
            "human_confirmation_recorded": True,
        },
        response_contract_mod.EIDON_ORDERS_RESPONSE_SURFACE_COPILOT: {
            "authoritative_finalize_allowed": False,
            "warnings": [],
            "source_traceability": [{"field_path": "request_context", "source_class": "stub"}],
            "result": {"capability": "stubbed"},
        },
    }


def test_orders_response_contract_allows_canonical_summary_safe_payloads() -> None:
    for surface_code, payload in _sample_surface_payloads().items():
        response_contract_mod.enforce_orders_response_contract_or_fail(
            surface_code=surface_code,
            response=payload,
        )


def test_orders_response_contract_fail_closed_on_contract_violations() -> None:
    payload = _sample_surface_payloads()[response_contract_mod.EIDON_ORDERS_RESPONSE_SURFACE_DOCUMENT_UNDERSTANDING]

    err_authoritative = None
    try:
        response_contract_mod.enforce_orders_response_contract_or_fail(
            surface_code=response_contract_mod.EIDON_ORDERS_RESPONSE_SURFACE_DOCUMENT_UNDERSTANDING,
            response={**payload, "authoritative_finalize_allowed": True},
        )
    except ValueError as exc:  # pragma: no cover - explicit fail-closed contract assertion
        err_authoritative = str(exc)
    assert err_authoritative == response_contract_mod.EIDON_ORDERS_RESPONSE_CONTRACT_VIOLATION

    err_raw = None
    try:
        response_contract_mod.enforce_orders_response_contract_or_fail(
            surface_code=response_contract_mod.EIDON_ORDERS_RESPONSE_SURFACE_DOCUMENT_UNDERSTANDING,
            response={**payload, "raw_document_payload": {"x": 1}},
        )
    except ValueError as exc:  # pragma: no cover - explicit fail-closed contract assertion
        err_raw = str(exc)
    assert err_raw == response_contract_mod.EIDON_ORDERS_RESPONSE_CONTRACT_VIOLATION

    err_human = None
    try:
        response_contract_mod.enforce_orders_response_contract_or_fail(
            surface_code=response_contract_mod.EIDON_ORDERS_RESPONSE_SURFACE_FEEDBACK,
            response={
                "authoritative_finalize_allowed": False,
                "warnings": [],
                "source_traceability": [],
            },
        )
    except ValueError as exc:  # pragma: no cover - explicit fail-closed contract assertion
        err_human = str(exc)
    assert err_human == response_contract_mod.EIDON_ORDERS_RESPONSE_CONTRACT_VIOLATION


def test_orders_copilot_orchestration_fail_closed_on_response_contract_violation(monkeypatch) -> None:
    monkeypatch.setattr(
        orchestration_service_mod.order_document_intake_service,
        "ingest",
        lambda **_kwargs: _StubResult(
            dumped={"capability": "EIDON_ORDER_DOCUMENT_INTAKE_V1", "raw_document_blob": "forbidden"},
            warnings=["missing_required_fields_detected"],
            source_traceability=[
                {"field_path": "request_context", "source_class": "stub", "source_ref": "summary_only"}
            ],
            authoritative_finalize_allowed=False,
        ),
    )

    err = None
    try:
        orchestration_service_mod.service.orchestrate(
            db=object(),  # type: ignore[arg-type]
            tenant_id="tenant-ai-001",
            intent="document_understanding",
            payload={"extracted_text": "Shipper: A"},
        )
    except ValueError as exc:  # pragma: no cover - explicit fail-closed contract assertion
        err = str(exc)
    assert err == response_contract_mod.EIDON_ORDERS_RESPONSE_CONTRACT_VIOLATION
