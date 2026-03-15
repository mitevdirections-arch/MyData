from __future__ import annotations


EIDON_DRAFTING_CONTRACT_V1 = {
    "contract_code": "EIDON_DRAFTING_CONTRACT_V1",
    "version": "v1",
    "surfaces": {
        "tenant_runtime": {
            "allowed_drafting_targets": [
                "order_creation_draft_payloads",
                "order_update_draft_payloads_within_user_permissions",
                "supporting_business_document_preparation_drafts",
            ],
            "forbidden_drafting_targets": [
                "cross_tenant_business_objects",
                "superadmin_control_actions_or_payloads",
                "security_sensitive_system_configurations",
            ],
            "draft_only_vs_commit_prohibited_boundary": "eidon_may_prepare_draft_payloads_but_may_not_commit_authoritative_state_changes",
            "required_human_confirmation_classes": [
                "order_submission_or_state_transition",
                "document_issue_publish_send_or_finalize_actions",
                "any_financial_or_legally_binding_action",
            ],
            "allowed_field_suggestion_scope": [
                "tenant_scoped_fields_visible_to_requesting_user",
                "non_authoritative_field_value_proposals",
                "formatting_and_consistency_hints",
            ],
            "forbidden_auto_fill_scope": [
                "hidden_or_permission_denied_fields",
                "cross_tenant_or_external_secret_data",
                "authoritative_fields_requiring_explicit_human_confirmation",
            ],
            "source_traceability_requirement": "every_draft_suggestion_must_include_traceable_source_context_or_explicit_unknown_marker",
            "ambiguity_escalation_rule": "when_critical_field_is_ambiguous_or_missing_eidon_must_request_human_clarification_and_stop_short_of_finalization",
            "prepare_only_no_authoritative_finalize_rule": "eidon_may_prepare_drafts_but_may_not_finalize_authoritative_business_actions_or_documents_on_its_own",
        }
    },
}