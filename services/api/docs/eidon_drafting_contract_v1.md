# EIDON Drafting Contract v1

Scope: `AI Tenant Runtime` drafting assistance boundaries only. No runtime behavior changes.

## Required Guarantees
- EIDON may prepare drafts, but may not finalize authoritative business actions or documents.
- Drafting targets are restricted to tenant-scoped, permission-visible draft payloads.
- Forbidden targets include cross-tenant objects, superadmin control actions, and security-sensitive system changes.
- Commit/finalization remains human-controlled with explicit confirmation.
- Field suggestions are limited to user-visible tenant fields; hidden or restricted fields must not be auto-filled.
- Suggestion sources must be traceable.
- Ambiguity in critical fields requires escalation to human clarification.

## Marker Binding
- Marker file: `app/modules/ai/surface_contract.py`
- Tenant surface marker key: `drafting_contract_ref`
- Expected value: `EIDON_DRAFTING_CONTRACT_V1:tenant_runtime`