# Support Module

Purpose:
- Controlled tenant-initiated support access ("open door").
- Superadmin can enter tenant scope only through active support session.
- Short-lived support-scoped bearer token issuance.

Flow:
1. Tenant admin creates support request (`NEW` or `DOOR_OPEN`).
2. Tenant opens door for limited time (`DOOR_OPEN`).
3. Superadmin starts support session (`SESSION_ACTIVE`).
4. Superadmin issues support-scoped token bound to tenant + session.
5. Tenant/superadmin closes session and request.

Security invariants:
- No support session: no superadmin tenant-scope access.
- Support token includes `support_tenant_id` + `support_session_id`.
- Session expiry auto-invalidates tenant support access.
- All state changes are audit-logged.

Tables:
- `support_requests`
- `support_sessions`

Main endpoints:
- Tenant: `POST/GET /support/tenant/requests`
- Tenant: `POST /support/tenant/requests/{id}/open-door`
- Tenant: `POST /support/tenant/requests/{id}/close`
- Superadmin: `GET /support/superadmin/requests`
- Superadmin: `POST /support/superadmin/requests/{id}/start-session`
- Superadmin: `GET /support/superadmin/sessions`
- Superadmin: `POST /support/superadmin/sessions/{id}/end`
- Superadmin: `POST /support/superadmin/sessions/{id}/issue-token`