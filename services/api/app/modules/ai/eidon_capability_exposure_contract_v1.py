from __future__ import annotations

from typing import Any

from app.modules.ai.eidon_capability_registry_contract_v1 import (
    EIDON_CAPABILITY_AI_ORDERS_COPILOT,
    EIDON_CAPABILITY_AI_ORDERS_DOCUMENT_UNDERSTANDING,
    EIDON_CAPABILITY_AI_ORDERS_DRAFTING,
    EIDON_CAPABILITY_AI_ORDERS_FEEDBACK,
    EIDON_CAPABILITY_AI_ORDERS_RETRIEVE_REFERENCE,
    EIDON_ORDERS_COPILOT_CANONICAL_ENDPOINT_PATH,
    EIDON_ORDERS_DOCUMENT_UNDERSTANDING_CANONICAL_ENDPOINT_PATH,
    EIDON_ORDERS_DRAFTING_CANONICAL_ENDPOINT_PATH,
    EIDON_ORDERS_FEEDBACK_CANONICAL_ENDPOINT_PATH,
    EIDON_ORDERS_RETRIEVE_REFERENCE_CANONICAL_ENDPOINT_PATH,
)


EIDON_UNKNOWN_EXPOSURE_CAPABILITY_CODE = "unknown_eidon_exposure_capability_code"
EIDON_UNKNOWN_EXPOSURE_ENDPOINT_PATH = "unknown_eidon_exposure_endpoint_path"

EIDON_CAPABILITY_EXPOSURE_REGISTRY_V1: dict[str, dict[str, Any]] = {
    EIDON_CAPABILITY_AI_ORDERS_RETRIEVE_REFERENCE: {
        "capability_code": EIDON_CAPABILITY_AI_ORDERS_RETRIEVE_REFERENCE,
        "tenant_direct_surface": True,
        "canonical_endpoint_path": EIDON_ORDERS_RETRIEVE_REFERENCE_CANONICAL_ENDPOINT_PATH,
        "copilot_routable": True,
        "orchestration_entrypoint": False,
        "advisory_only": True,
        "human_confirmation_required": False,
        "description": "Tenant-facing direct retrieval surface for visible order references.",
    },
    EIDON_CAPABILITY_AI_ORDERS_DOCUMENT_UNDERSTANDING: {
        "capability_code": EIDON_CAPABILITY_AI_ORDERS_DOCUMENT_UNDERSTANDING,
        "tenant_direct_surface": True,
        "canonical_endpoint_path": EIDON_ORDERS_DOCUMENT_UNDERSTANDING_CANONICAL_ENDPOINT_PATH,
        "copilot_routable": True,
        "orchestration_entrypoint": False,
        "advisory_only": True,
        "human_confirmation_required": True,
        "description": "Tenant-facing document understanding surface.",
    },
    EIDON_CAPABILITY_AI_ORDERS_DRAFTING: {
        "capability_code": EIDON_CAPABILITY_AI_ORDERS_DRAFTING,
        "tenant_direct_surface": True,
        "canonical_endpoint_path": EIDON_ORDERS_DRAFTING_CANONICAL_ENDPOINT_PATH,
        "copilot_routable": True,
        "orchestration_entrypoint": False,
        "advisory_only": True,
        "human_confirmation_required": True,
        "description": "Tenant-facing order drafting assist surface.",
    },
    EIDON_CAPABILITY_AI_ORDERS_FEEDBACK: {
        "capability_code": EIDON_CAPABILITY_AI_ORDERS_FEEDBACK,
        "tenant_direct_surface": True,
        "canonical_endpoint_path": EIDON_ORDERS_FEEDBACK_CANONICAL_ENDPOINT_PATH,
        "copilot_routable": True,
        "orchestration_entrypoint": False,
        "advisory_only": True,
        "human_confirmation_required": True,
        "description": "Tenant-facing order feedback surface.",
    },
    EIDON_CAPABILITY_AI_ORDERS_COPILOT: {
        "capability_code": EIDON_CAPABILITY_AI_ORDERS_COPILOT,
        "tenant_direct_surface": True,
        "canonical_endpoint_path": EIDON_ORDERS_COPILOT_CANONICAL_ENDPOINT_PATH,
        "copilot_routable": False,
        "orchestration_entrypoint": True,
        "advisory_only": True,
        "human_confirmation_required": True,
        "description": "Orders copilot orchestration entrypoint surface.",
    },
}

EIDON_CAPABILITY_EXPOSURE_CONTRACT_V1 = {
    "contract_code": "EIDON_CAPABILITY_EXPOSURE_CONTRACT_V1",
    "version": "v1",
    "capability_codes": list(EIDON_CAPABILITY_EXPOSURE_REGISTRY_V1.keys()),
    "rules": {
        "fail_closed_lookup": True,
        "advisory_only": True,
        "no_finalize": True,
        "no_tenant_runtime_mutation": True,
    },
}

EIDON_EXPOSURE_ENDPOINT_PATH_TO_CAPABILITY_CODE_V1: dict[str, str] = {
    str(entry["canonical_endpoint_path"]): str(entry["capability_code"])
    for entry in EIDON_CAPABILITY_EXPOSURE_REGISTRY_V1.values()
}


def _normalize_lookup_key(value: str | None) -> str:
    return str(value or "").strip()


def get_allowed_exposure_capability_codes() -> tuple[str, ...]:
    return tuple(EIDON_CAPABILITY_EXPOSURE_REGISTRY_V1.keys())


def get_exposure_entry_or_fail(capability_code: str | None) -> dict[str, Any]:
    normalized = _normalize_lookup_key(capability_code)
    entry = EIDON_CAPABILITY_EXPOSURE_REGISTRY_V1.get(normalized)
    if entry is None:
        raise ValueError(EIDON_UNKNOWN_EXPOSURE_CAPABILITY_CODE)
    return dict(entry)


def resolve_exposure_capability_code_by_endpoint_path_or_fail(endpoint_path: str | None) -> str:
    normalized = _normalize_lookup_key(endpoint_path)
    capability_code = EIDON_EXPOSURE_ENDPOINT_PATH_TO_CAPABILITY_CODE_V1.get(normalized)
    if capability_code is None:
        raise ValueError(EIDON_UNKNOWN_EXPOSURE_ENDPOINT_PATH)
    return capability_code


def is_copilot_routable_capability_or_fail(capability_code: str | None) -> bool:
    entry = get_exposure_entry_or_fail(capability_code)
    return bool(entry.get("copilot_routable"))


def is_orchestration_entrypoint_capability_or_fail(capability_code: str | None) -> bool:
    entry = get_exposure_entry_or_fail(capability_code)
    return bool(entry.get("orchestration_entrypoint"))

