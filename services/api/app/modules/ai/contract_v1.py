from __future__ import annotations


AI_CONTRACT_V1 = {
    "contract_code": "AI_CONTRACT_V1",
    "version": "v1",
    "ai_does_not_override_system_truth": True,
    "surfaces": {
        "tenant_runtime": {
            "allowed_context_scope": [
                "authenticated_tenant_claims_context",
                "tenant_scoped_entitlement_context",
                "tenant_scoped_support_context_when_applicable",
            ],
            "forbidden_context_scope": [
                "cross_tenant_data",
                "superadmin_private_control_context",
                "raw_secret_material",
                "direct_database_credentials",
            ],
            "allowed_suggestion_types": [
                "policy_constrained_advisory_text",
                "tenant_safe_troubleshooting_suggestions",
                "non_authoritative_operational_recommendations",
            ],
            "forbidden_action_classes": [
                "direct_state_mutation",
                "privilege_escalation",
                "cross_tenant_enumeration",
                "auth_bypass_or_token_issuance",
            ],
            "human_confirmation_required_actions": [
                "any_real_world_or_system_effecting_step",
                "execution_of_high_impact_operational_change",
            ],
            "auditability_requirement": "every_invocation_must_be_audit_logged_with_actor_and_tenant_scope",
            "tenant_isolation_requirement": "tenant_scope_only_and_fail_closed_on_missing_or_invalid_tenant_context",
            "superadmin_only_capabilities": [],
        },
        "superadmin_control": {
            "allowed_context_scope": [
                "superadmin_claims_context",
                "platform_governance_and_security_posture_context",
                "aggregated_anomaly_and_incident_context",
            ],
            "forbidden_context_scope": [
                "direct_tenant_runtime_impersonation_without_existing_system_controls",
                "raw_secret_material",
                "direct_database_credentials",
            ],
            "allowed_suggestion_types": [
                "governance_advisory_summary",
                "security_and_anomaly_triage_recommendations",
                "platform_level_operational_guidance",
            ],
            "forbidden_action_classes": [
                "direct_state_mutation",
                "policy_override_without_existing_system_authority",
                "bypass_of_existing_authz_or_route_policy",
            ],
            "human_confirmation_required_actions": [
                "any_step_that_may_change_tenant_or_platform_state",
                "any_security_sensitive_execution_step",
            ],
            "auditability_requirement": "every_invocation_must_be_audit_logged_with_actor_and_effect_scope",
            "tenant_isolation_requirement": "no_cross_tenant_data_action_without_explicit_existing_system_authority",
            "superadmin_only_capabilities": [
                "platform_wide_governance_recommendations",
                "security_posture_and_incident_triage_advice",
            ],
        },
    },
}
