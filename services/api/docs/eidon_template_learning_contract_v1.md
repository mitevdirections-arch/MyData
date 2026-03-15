# EIDON Template Learning Contract v1

Scope: `AI Tenant Runtime` template-learning boundaries only. No runtime behavior changes.

## Required Guarantees
- Global learning accepts de-identified template/pattern intelligence only.
- Raw tenant documents and tenant business payloads are forbidden learning artifacts.
- No cross-tenant business data in global learning.
- Tenant-local overrides take precedence over global patterns.
- New global learning/pattern promotion requires human confirmation.
- Pattern updates require quality scoring and rollback capability.
- Pattern updates are versioned and traceable.
- Explicit operating rule: learn globally from patterns, act locally within tenant boundaries.

## Marker Binding
- Marker file: `app/modules/ai/surface_contract.py`
- Tenant surface marker key: `template_learning_contract_ref`
- Expected value: `EIDON_TEMPLATE_LEARNING_CONTRACT_V1:tenant_runtime`