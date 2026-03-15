from __future__ import annotations


EIDON_PATTERN_PUBLISH_CONTRACT_V1 = {
    "contract_code": "EIDON_PATTERN_PUBLISH_CONTRACT_V1",
    "version": "v1",
    "flow": {
        "source_status_required": "REVIEW_APPROVED",
        "transition": "approved_submission_to_versioned_publish_artifact",
        "publish_not_rollout_rule": "publish_artifact_creation_does_not_trigger_distribution_or_rollout",
    },
    "data_safety": {
        "de_identified_only_rule": "publish_artifact_must_use_de_identified_pattern_features_only",
        "no_raw_tenant_data_rule": "raw_tenant_documents_or_raw_text_must_not_be_present_in_publish_artifact",
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
        "fail_closed": True,
    },
}
