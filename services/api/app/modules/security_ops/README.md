# Security Ops Module

Superadmin-only security operations endpoints.

## Scope
- Security posture report (prod guardrails + secret fingerprints)
- Key lifecycle/version visibility
- Emergency tenant kill-switch (locks tenant + suspends licenses + revokes bot credentials)
- Structured security events feed
- Security alert queue listing
- Dispatch-once processing for queued alerts
- Manual requeue/fail operations
- Test incident + queued alert generation

## Endpoints
- `GET /superadmin/security/posture`
- `GET /superadmin/security/keys/lifecycle`
- `POST /superadmin/security/kill-switch/tenant/{tenant_id}`
- `GET /superadmin/security/events`
- `POST /superadmin/security/alerts/test-incident`
- `GET /superadmin/security/alerts/queue`
- `POST /superadmin/security/alerts/dispatch-once`
- `POST /superadmin/security/alerts/{alert_id}/requeue`
- `POST /superadmin/security/alerts/{alert_id}/fail-now`