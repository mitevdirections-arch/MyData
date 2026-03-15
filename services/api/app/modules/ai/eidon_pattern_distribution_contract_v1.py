from __future__ import annotations


EIDON_PATTERN_DISTRIBUTION_CONTRACT_V1 = {
    "contract_code": "EIDON_PATTERN_DISTRIBUTION_CONTRACT_V1",
    "version": "v1",
    "flow": {
        "transition": "published_artifact_to_distribution_record",
        "distribution_not_rollout_rule": "distribution_record_creation_does_not_trigger_rollout",
        "distribution_not_activation_rule": "distribution_record_creation_does_not_trigger_activation",
        "no_tenant_runtime_mutation_rule": "distribution_record_must_not_mutate_tenant_runtime_state",
    },
    "data_safety": {
        "metadata_first_rule": "distribution_record_contains_governance_metadata_only",
        "no_raw_tenant_data_rule": "raw_tenant_documents_or_raw_text_must_not_be_present_in_distribution_record",
        "authoritative_publish_allowed": False,
    },
    "rollback_contract": {
        "mode": "metadata_only",
        "engine_enabled": False,
        "rule": "rollback_metadata_may_be_recorded_but_no_distribution_rollback_engine_is_enabled_in_v1",
    },
    "control_surface": {
        "plane": "FOUNDATION",
        "superadmin_only": True,
        "append_only": True,
        "fail_closed": True,
    },
}
