from __future__ import annotations


EIDON_PATTERN_ROLLOUT_GOVERNANCE_CONTRACT_V1 = {
    "contract_code": "EIDON_PATTERN_ROLLOUT_GOVERNANCE_CONTRACT_V1",
    "version": "v1",
    "flow": {
        "transition": "distribution_record_to_rollout_governance_record",
        "governance_not_rollout_execution_rule": "rollout_governance_record_creation_does_not_trigger_rollout_execution",
        "governance_not_activation_rule": "rollout_governance_record_creation_does_not_trigger_activation",
        "no_tenant_runtime_mutation_rule": "rollout_governance_record_must_not_mutate_tenant_runtime_state",
    },
    "data_safety": {
        "metadata_first_rule": "rollout_governance_record_contains_governance_metadata_only",
        "no_raw_tenant_data_rule": "raw_tenant_documents_or_raw_text_must_not_be_present_in_rollout_governance_record",
        "authoritative_publish_allowed": False,
    },
    "rollback_contract": {
        "mode": "metadata_only",
        "engine_enabled": False,
        "rule": "rollback_metadata_may_be_recorded_but_no_rollout_rollback_engine_is_enabled_in_v1",
    },
    "control_surface": {
        "plane": "FOUNDATION",
        "superadmin_only": True,
        "append_only": True,
        "fail_closed": True,
    },
}

