from __future__ import annotations


EIDON_DOCUMENT_UNDERSTANDING_CONTRACT_V1 = {
    "contract_code": "EIDON_DOCUMENT_UNDERSTANDING_CONTRACT_V1",
    "version": "v1",
    "surface": {
        "route": "POST /ai/tenant-copilot/order-document-intake",
        "capability": "EIDON_ORDER_DOCUMENT_INTAKE_V1",
        "tenant_facing": True,
        "plane": "OPERATIONAL",
    },
    "input": {
        "required": [
            "extracted_text",
        ],
        "optional": [
            "document_metadata",
            "layout_hints",
            "field_hints",
        ],
    },
    "output": {
        "fields": [
            "draft_order_candidate",
            "extracted_fields",
            "missing_required_fields",
            "ambiguous_fields",
            "cmr_readiness",
            "adr_readiness",
            "warnings",
            "source_traceability",
            "template_fingerprint",
            "template_learning_candidate",
            "human_confirmation_required_items",
            "authoritative_finalize_allowed",
        ],
        "authoritative_finalize_allowed": False,
    },
    "rules": {
        "document_understanding_not_action_execution": True,
        "no_finalize": True,
        "no_tenant_runtime_mutation": True,
        "advisory_only": True,
        "human_confirmation_required": True,
        "de_identified_learning_boundary": True,
    },
    "fail_closed": {
        "missing_tenant_context": "deny_403",
        "action_boundary_violation": "ai_action_boundary_violation",
        "raw_output_violation": "document_understanding_raw_output_violation",
    },
}

