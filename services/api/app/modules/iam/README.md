# IAM Module (V2)

Purpose:
- Centralized permission registry + role templates.
- Effective access summary for current identity (`/iam/me/access`).
- Permission decision endpoint (`/iam/me/access/check`).
- RLS claim-context introspection (`/iam/admin/rls-context`).

Concepts:
- Workspace scope: `TENANT` or `PLATFORM`.
- Effective permissions = direct user permissions + assigned role permissions + token `perms`.
- Permission matching supports:
  - exact (`SECURITY.READ`)
  - wildcard namespace (`SECURITY.*`)
  - global wildcard (`*`)

RLS foundation:
- `app/core/rls.py` attaches tenant criteria to SELECTs when session has active tenant context.
- `SUPERADMIN` without support tenant context runs in global mode (bypass).
- `SUPERADMIN` with support tenant/session runs tenant-scoped mode.