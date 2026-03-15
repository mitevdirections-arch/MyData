from __future__ import annotations


EIDON_PATTERN_ACTIVATION_CONTRACT_V1 = {
    "contract_code": "EIDON_PATTERN_ACTIVATION_CONTRACT_V1",
    "version": "v1",
    "flow": {
        "transition": "rollout_governance_record_to_activation_record",
        "activation_record_not_runtime_enablement_rule": "activation_record_creation_does_not_trigger_runtime_enablement",
        "activation_record_not_worker_rule": "activation_record_creation_does_not_trigger_worker_or_scheduler",
        "no_tenant_runtime_mutation_rule": "activation_record_must_not_mutate_tenant_runtime_state",
    },
    "data_safety": {
        "metadata_first_rule": "activation_record_contains_activation_metadata_only",
        "no_raw_tenant_data_rule": "raw_tenant_documents_or_raw_text_must_not_be_present_in_activation_record",
        "authoritative_publish_allowed": False,
    },
    "rollback_contract": {
        "mode": "metadata_only",
        "engine_enabled": False,
        "rule": "rollback_metadata_may_be_recorded_but_no_runtime_enablement_or_rollback_engine_is_enabled_in_v1",
    },
    "control_surface": {
        "plane": "FOUNDATION",
        "superadmin_only": True,
        "append_only": True,
        "fail_closed": True,
    },
}

