# Profile Module

Purpose:
- Unified profile foundation for tenant admins and superadmins.
- Workspace organization profile (legal/contact/banking/presentation).
- Workspace RBAC primitives (roles, users, role assignment).
- User-domain profile layer (per-user profile, contacts, addresses, docs metadata, credentials).

Security model:
- `TENANT_ADMIN` manages tenant workspace.
- `SUPERADMIN` manages platform workspace.
- Superadmin tenant scope requires delegated support context (`support_tenant_id`) + active `support_session_id`.
- All write operations are audited.
- Route-level access is fail-closed via policy matrix.

Main endpoints:
- `GET/PUT /profile/me`
- `GET/PUT /profile/workspace`
- `GET/POST/PUT/DELETE /profile/workspace/contacts...`
- `GET/POST/PUT/DELETE /profile/workspace/addresses...`
- `GET /profile/admin/roles`
- `PUT /profile/admin/roles/{role_code}`
- `GET /profile/admin/users`
- `PUT /profile/admin/users/{user_id}`
- `GET /profile/admin/users/{user_id}`
- `PUT /profile/admin/users/{user_id}/roles`
- `GET/PUT /profile/admin/users/{user_id}/profile`
- `GET/POST/PUT/DELETE /profile/admin/users/{user_id}/contacts...`
- `GET/POST/PUT/DELETE /profile/admin/users/{user_id}/addresses...`
- `GET/POST/PUT/DELETE /profile/admin/users/{user_id}/documents...`
- `GET/POST/PUT/DELETE /profile/admin/users/{user_id}/next-of-kin...`
- `GET /profile/admin/users/{user_id}/credentials`
- `POST /profile/admin/users/{user_id}/credentials/issue`
- `POST /profile/admin/users/{user_id}/credentials/reset-password`
- `GET /superadmin/meta/tenants-overview`

Tables:
- `admin_profiles`
- `workspace_organization_profiles`
- `workspace_contact_points`
- `workspace_addresses`
- `workspace_roles`
- `workspace_users`
- `workspace_user_roles`
- `workspace_user_profiles`
- `workspace_user_contact_channels`
- `workspace_user_addresses`
- `workspace_user_documents`
- `workspace_user_credentials`
- `workspace_user_next_of_kin`


User profile contract (users domain):
- No company legal/presentation fields in user profile.
- Payroll block is personal employee payroll data:
  - `payroll.account_holder`
  - `payroll.iban`
  - `payroll.swift`
  - `payroll.bank_name`
  - `payroll.currency`
- Multi-contact lines via `workspace_user_contact_channels`:
  - Recommended `channel_type`: `WORK_EMAIL`, `PERSONAL_EMAIL`, `WORK_PHONE`, `PERSONAL_PHONE`, `WORK_MESSENGER`, `PERSONAL_MESSENGER`, `EMERGENCY_PHONE`, `OTHER`.
- Next-of-kin supports multiple records per user:
  - `full_name`, `relation`, `contact_email`, `contact_phone`, address fields, `is_primary`, `sort_order`, `metadata`.
