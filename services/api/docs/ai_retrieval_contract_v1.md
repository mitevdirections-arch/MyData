# AI Retrieval Contract v1

Scope: `AI Tenant Runtime` retrieval behavior contract only. No runtime behavior changes.

## Required Guarantees
- Allowed retrieval scope is tenant-scoped and permission-filtered.
- Forbidden retrieval scope includes cross-tenant, superadmin-private, hidden-object, and secret sources.
- Tenant boundary is strict and fail-closed.
- Retrieval visibility is permission-filtered per requesting user.
- No cross-tenant retrieval under any condition.
- No hidden-object inference via response semantics.
- Retrieval results are traceable and audit-logged.
- AI retrieval cannot reveal anything the requesting user cannot access directly.

## Marker Binding
- Marker file: `app/modules/ai/surface_contract.py`
- Tenant surface marker key: `retrieval_contract_ref`
- Expected value: `AI_RETRIEVAL_CONTRACT_V1:tenant_runtime`