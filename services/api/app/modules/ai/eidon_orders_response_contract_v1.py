from __future__ import annotations

from typing import Any


EIDON_ORDERS_RESPONSE_CONTRACT_VIOLATION = "eidon_orders_response_contract_violation"

EIDON_ORDERS_RESPONSE_SURFACE_RETRIEVE_REFERENCE = "orders_retrieve_reference"
EIDON_ORDERS_RESPONSE_SURFACE_DOCUMENT_UNDERSTANDING = "orders_document_understanding"
EIDON_ORDERS_RESPONSE_SURFACE_DRAFTING = "orders_drafting"
EIDON_ORDERS_RESPONSE_SURFACE_FEEDBACK = "orders_feedback"
EIDON_ORDERS_RESPONSE_SURFACE_COPILOT = "orders_copilot"

EIDON_ORDERS_RESPONSE_SURFACES_V1: tuple[str, ...] = (
    EIDON_ORDERS_RESPONSE_SURFACE_RETRIEVE_REFERENCE,
    EIDON_ORDERS_RESPONSE_SURFACE_DOCUMENT_UNDERSTANDING,
    EIDON_ORDERS_RESPONSE_SURFACE_DRAFTING,
    EIDON_ORDERS_RESPONSE_SURFACE_FEEDBACK,
    EIDON_ORDERS_RESPONSE_SURFACE_COPILOT,
)

_RAW_OUTPUT_DENY_MARKERS: set[str] = {
    "extracted_text",
    "raw_document_blob",
    "raw_document_payload",
    "document_blob",
    "raw_payload",
    "raw_text",
    "raw_content",
}

EIDON_ORDERS_RESPONSE_CONTRACT_V1 = {
    "contract_code": "EIDON_ORDERS_RESPONSE_CONTRACT_V1",
    "version": "v1",
    "surfaces": list(EIDON_ORDERS_RESPONSE_SURFACES_V1),
    "rules": {
        "authoritative_finalize_allowed_must_be_false": True,
        "warnings_summary_safe": True,
        "source_traceability_summary_safe": True,
        "human_confirmation_markers_surface_specific": True,
        "no_raw_output_markers": sorted(_RAW_OUTPUT_DENY_MARKERS),
        "advisory_only": True,
        "no_finalize": True,
        "no_tenant_runtime_mutation": True,
    },
    "fail_closed": {
        "violation_code": EIDON_ORDERS_RESPONSE_CONTRACT_VIOLATION,
    },
}


def _normalized(value: Any) -> str:
    return str(value or "").strip()


def _normalized_lower(value: Any) -> str:
    return _normalized(value).lower()


def _to_plain(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return _to_plain(value.model_dump(exclude_none=True))
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for raw_key, raw_val in value.items():
            out[_normalized(raw_key)] = _to_plain(raw_val)
        return out
    if isinstance(value, (list, tuple, set)):
        return [_to_plain(x) for x in value]
    return value


def _collect_forbidden_output_markers(value: Any, out: set[str]) -> None:
    if isinstance(value, dict):
        for raw_key, raw_val in value.items():
            key_norm = _normalized_lower(raw_key)
            if key_norm in _RAW_OUTPUT_DENY_MARKERS:
                out.add(key_norm)
            _collect_forbidden_output_markers(raw_val, out)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            _collect_forbidden_output_markers(item, out)


def _warnings_summary_safe_or_fail(data: dict[str, Any]) -> None:
    warnings = data.get("warnings")
    if not isinstance(warnings, list):
        raise ValueError(EIDON_ORDERS_RESPONSE_CONTRACT_VIOLATION)
    for item in warnings:
        if not isinstance(item, str):
            raise ValueError(EIDON_ORDERS_RESPONSE_CONTRACT_VIOLATION)
        if not _normalized(item):
            raise ValueError(EIDON_ORDERS_RESPONSE_CONTRACT_VIOLATION)


def _source_traceability_summary_safe_or_fail(data: dict[str, Any]) -> None:
    if "source_traceability" not in data:
        raise ValueError(EIDON_ORDERS_RESPONSE_CONTRACT_VIOLATION)
    traceability = data.get("source_traceability")
    if traceability is None:
        return
    if not isinstance(traceability, (dict, list)):
        raise ValueError(EIDON_ORDERS_RESPONSE_CONTRACT_VIOLATION)
    violations: set[str] = set()
    _collect_forbidden_output_markers(traceability, violations)
    if violations:
        raise ValueError(EIDON_ORDERS_RESPONSE_CONTRACT_VIOLATION)


def _human_confirmation_markers_or_fail(*, surface_code: str, data: dict[str, Any]) -> None:
    if surface_code in (
        EIDON_ORDERS_RESPONSE_SURFACE_DOCUMENT_UNDERSTANDING,
        EIDON_ORDERS_RESPONSE_SURFACE_DRAFTING,
    ):
        items = data.get("human_confirmation_required_items")
        if not isinstance(items, list):
            raise ValueError(EIDON_ORDERS_RESPONSE_CONTRACT_VIOLATION)
        for item in items:
            if not isinstance(item, str):
                raise ValueError(EIDON_ORDERS_RESPONSE_CONTRACT_VIOLATION)
            if not _normalized(item):
                raise ValueError(EIDON_ORDERS_RESPONSE_CONTRACT_VIOLATION)
        return

    if surface_code == EIDON_ORDERS_RESPONSE_SURFACE_FEEDBACK:
        if not isinstance(data.get("human_confirmation_recorded"), bool):
            raise ValueError(EIDON_ORDERS_RESPONSE_CONTRACT_VIOLATION)
        return

    # Retrieval and copilot wrappers intentionally do not require extra human markers.


def enforce_orders_response_contract_or_fail(*, surface_code: str, response: Any) -> None:
    surface_norm = _normalized(surface_code)
    if surface_norm not in EIDON_ORDERS_RESPONSE_SURFACES_V1:
        raise ValueError(EIDON_ORDERS_RESPONSE_CONTRACT_VIOLATION)

    data = _to_plain(response)
    if not isinstance(data, dict):
        raise ValueError(EIDON_ORDERS_RESPONSE_CONTRACT_VIOLATION)

    if data.get("authoritative_finalize_allowed") is not False:
        raise ValueError(EIDON_ORDERS_RESPONSE_CONTRACT_VIOLATION)

    _warnings_summary_safe_or_fail(data)
    _source_traceability_summary_safe_or_fail(data)
    _human_confirmation_markers_or_fail(surface_code=surface_norm, data=data)

    violations: set[str] = set()
    _collect_forbidden_output_markers(data, violations)
    if violations:
        raise ValueError(EIDON_ORDERS_RESPONSE_CONTRACT_VIOLATION)
