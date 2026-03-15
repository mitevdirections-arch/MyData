# Incidents Module

Purpose:
- Tenant reports technical incidents/crashes.
- Superadmin gets cross-tenant visibility and workflow (ack/resolve).

Endpoints:
- `POST /admin/incidents`
- `GET /admin/incidents`
- `GET /admin/incidents/{id}`
- `GET /superadmin/incidents`
- `POST /superadmin/incidents/{id}/ack`
- `POST /superadmin/incidents/{id}/resolve`

Security:
- Tenant endpoints require tenant-admin claims.
- Superadmin endpoints require superadmin claims.
- All state changes are audit-logged.
