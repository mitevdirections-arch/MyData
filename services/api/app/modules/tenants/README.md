# Tenants Module

Manages tenant lifecycle, tenant metadata, and admin controls.

## Invariants
- Tenant IDs are immutable UUIDs.
- Tenant stage transitions are validated.
- Tenant admin actions must be auditable.
