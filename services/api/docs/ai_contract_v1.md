# AI Contract v1

AI Contract v1 defines hard boundaries for both AI surfaces:
- `AI Tenant Runtime` (`/ai/tenant-copilot`)
- `AI Superadmin Control` (`/ai/superadmin-copilot`)

## Canonical rules

- AI is role-aware and contract-bound by surface.
- AI is tenant-safe and fail-closed on missing/invalid scope.
- AI suggestions are advisory; AI does not override system truth.
- Human confirmation is required before any action with real system or business effect.
- Every AI invocation must be audit-logged.

## Minimum contract dimensions per surface

- allowed context scope
- forbidden context scope
- allowed suggestion types
- forbidden action classes
- human-confirmation-required actions
- auditability requirement
- tenant isolation requirement
- superadmin-only capabilities
- explicit `ai_does_not_override_system_truth` rule
