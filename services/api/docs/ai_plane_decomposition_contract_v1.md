# AI Plane Decomposition Contract v1

This contract decomposes AI into two explicit surfaces without changing runtime endpoints.

## AI Tenant Runtime (Operational)

- Plane: `OPERATIONAL`
- Protected endpoint: `/ai/tenant-copilot`
- Intent: business-facing tenant AI runtime surface

## AI Superadmin Control (Foundation)

- Plane: `FOUNDATION`
- Protected endpoint: `/ai/superadmin-copilot`
- Intent: foundation-controlled AI control surface

## Runtime invariants

- No endpoint moves
- No prefix changes
- No auth semantics changes
- No launcher runtime entrypoint changes
