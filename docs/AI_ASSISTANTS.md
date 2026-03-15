# AI Assistants Design

## Tenant Copilot
- Helps create orders/CMR/invoices.
- Validates missing fields before submit.
- Suggests route/operational optimizations.
- Never bypasses business rules.

## Superadmin Copilot
- Detects anomalies in tenant usage/licensing/guard telemetry.
- Produces root-cause summaries with evidence references.
- Suggests enforcement actions (never auto-executes destructive action).

## Safety Constraints
- Tool calls are policy-gated.
- Every AI decision produces audit metadata.
- PII-safe prompts and redaction layer.
- No direct DB write from raw model output.
