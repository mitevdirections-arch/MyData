from __future__ import annotations


EIDON_TEMPLATE_LEARNING_CONTRACT_V1 = {
    "contract_code": "EIDON_TEMPLATE_LEARNING_CONTRACT_V1",
    "version": "v1",
    "surfaces": {
        "tenant_runtime": {
            "allowed_global_learning_artifacts": [
                "de_identified_template_structures",
                "de_identified_field_layout_patterns",
                "non_tenant_specific_document_format_heuristics",
            ],
            "forbidden_learning_artifacts": [
                "raw_tenant_documents_or_attachments",
                "tenant_identifiers_or_business_payloads",
                "cross_tenant_business_context_fragments",
            ],
            "de_identified_pattern_only_rule": "global_learning_must_use_de_identified_pattern_intelligence_only",
            "no_raw_tenant_document_sharing_rule": "raw_tenant_documents_must_not_be_shared_or_reused_for_global_learning",
            "no_cross_tenant_business_data_rule": "cross_tenant_business_data_must_not_enter_global_learning",
            "tenant_local_override_rule": "tenant_local_policy_or_template_override_takes_precedence_over_global_patterns",
            "human_confirmed_learning_requirement": "promotion_of_new_global_patterns_requires_human_confirmation",
            "quality_scoring_rollback_requirement": "pattern_updates_require_quality_scoring_and_must_support_rollback",
            "versioned_pattern_update_rule": "global_pattern_updates_must_be_versioned_and_traceable",
            "learn_globally_act_locally_rule": "learn_globally_from_patterns_act_locally_within_tenant_boundaries",
        }
    },
}