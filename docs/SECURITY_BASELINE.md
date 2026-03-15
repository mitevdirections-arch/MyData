# Security Baseline (Phase 0)

## Mandatory Controls
- JWT with short TTL and key rotation policy.
- Strict RBAC for tenant admin and superadmin.
- Deny-by-default route protection.
- Security headers middleware.
- Request correlation IDs.
- Immutable audit trail for sensitive actions.
- Secrets only from environment/secret manager.

## Hard Rules
- No default credentials in production.
- No dev endpoints enabled in production.
- No cross-tenant reads/writes.
- No plaintext secrets in logs.

## Next Security Phases
1. mTLS service-to-service.
2. WAF + adaptive rate limiting.
3. DAST/SAST in CI with fail gates.
4. Automated threat detection on audit stream.
