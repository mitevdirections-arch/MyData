from __future__ import annotations


AI_RETRIEVAL_CONTRACT_V1 = {
    "contract_code": "AI_RETRIEVAL_CONTRACT_V1",
    "version": "v1",
    "surfaces": {
        "tenant_runtime": {
            "allowed_retrieval_scope": [
                "tenant_scoped_objects_user_can_access_directly",
                "tenant_scoped_policy_and_entitlement_context",
                "tenant_scoped_support_runtime_context",
            ],
            "forbidden_retrieval_scope": [
                "cross_tenant_objects_or_metadata",
                "superadmin_private_control_surface_context",
                "hidden_or_soft_deleted_objects_outside_user_visibility",
                "raw_secret_material_and_credentials",
            ],
            "tenant_boundary_rule": "retrieval_must_remain_strictly_within_requesting_tenant_boundary",
            "permission_filtered_visibility_rule": "retrieval_results_must_be_filtered_by_requesting_user_permissions",
            "no_cross_tenant_rule": "cross_tenant_retrieval_is_forbidden_and_must_fail_closed",
            "no_hidden_object_inference_rule": "retrieval_response_semantics_must_not_reveal_hidden_object_existence",
            "allowed_source_classes": [
                "tenant_business_entities_with_direct_user_access",
                "tenant_profile_and_support_runtime_documents",
                "tenant_public_or_shared_policy_metadata",
            ],
            "forbidden_source_classes": [
                "other_tenant_business_entities",
                "superadmin_only_control_objects",
                "security_secrets_and_private_keys",
            ],
            "result_traceability_auditability_requirement": "every_retrieval_invocation_must_be_audit_logged_with_actor_tenant_sources_and_filters",
            "cannot_exceed_requesting_user_direct_access_rule": "ai_retrieval_must_not_return_anything_the_requesting_user_cannot_access_directly",
        }
    },
}