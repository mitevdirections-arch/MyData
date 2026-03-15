# AI Module

Provides policy-constrained assistant endpoints for tenants and superadmins.

## Invariants
- AI outputs are advisory unless explicitly approved.
- All assistant interactions are audit-logged.
- AI is contract-bound (`AI_CONTRACT_V1`) and does not override system truth.

## Tenant Runtime Capability: EIDON Order Draft Assist v1
- Endpoint: `POST /ai/tenant-copilot/order-draft-assist`
- Scope: tenant-local, permission-allowed context only.
- Output: structured drafting assistance only (no authoritative finalize).
- External integrations: disabled in this cycle.

## Tenant Runtime Capability: EIDON Order Document Intake v1
- Endpoint: `POST /ai/tenant-copilot/order-document-intake`
- Input: normalized document intake (`extracted_text`, optional metadata/hints).
- Output: structured `draft_order_candidate` plus CMR/ADR readiness and template-learning candidate.
- External integrations: disabled in this cycle.

## Tenant Runtime Capability: EIDON Order Intake Feedback Loop v1
- Endpoint: `POST /ai/tenant-copilot/order-intake-feedback`
- Input: tenant user confirmation/corrections over `draft_order_candidate`.
- Output: `tenant_local_learning_candidate` and de-identified `global_pattern_submission_candidate` (prepare-only; no global submission engine in this cycle).
- External integrations: disabled in this cycle.

## Tenant Runtime Capability: EIDON Template Submission Staging v1
- Endpoint: `POST /ai/tenant-copilot/template-submissions/stage`
- Input: de-identified `global_pattern_submission_candidate` from feedback loop.
- Output: staged, review-required submission record for foundation-controlled future registry flow.
- Rules: no raw tenant document, no authoritative publish in this cycle.

## Foundation Review Control: EIDON Template Review Control v1
- Queue endpoint: `GET /ai/superadmin-copilot/template-submissions/queue`
- Read endpoint: `GET /ai/superadmin-copilot/template-submissions/{submission_id}`
- Review decisions: `POST .../{submission_id}/approve` and `POST .../{submission_id}/reject`
- Rules: superadmin-only, explicit status transitions, no raw tenant document exposure, no global rollout in this cycle.

## AI Retrieval Contract v1
Tenant runtime retrieval boundaries are defined in `retrieval_contract_v1.py` and bound via `AI_SURFACE_CONTRACT_V1.tenant_runtime.retrieval_contract_ref`.

## EIDON Drafting Contract v1
Tenant drafting boundaries are defined in `eidon_drafting_contract_v1.py` and bound via `AI_SURFACE_CONTRACT_V1.tenant_runtime.drafting_contract_ref`.

## EIDON Template Learning Contract v1
Tenant template-learning boundaries are defined in `eidon_template_learning_contract_v1.py` and bound via `AI_SURFACE_CONTRACT_V1.tenant_runtime.template_learning_contract_ref`.
