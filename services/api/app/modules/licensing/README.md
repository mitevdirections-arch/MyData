# Licensing Module

Implements core/startup/module licensing, seat controls, issuance governance, and visual license identity.

## Invariants
- Core license is mandatory for protected business operations.
- Startup license lasts 30 days and is non-renewable.
- Startup trial is issued together with core (`STARTUP + CORE`).
- Module trial requires active core license.
- Core plan seat limit is enforced on active leased users.
- If core is not active, protected module operations are blocked (core fuse).

## Issuance Modes
Per-tenant issuance policy supports:
- `AUTO`: startup/core issuance is immediate.
- `SEMI`: creates request unless `admin_confirmed=true`; then issues immediately.
- `MANUAL`: always creates pending request; issuance only after explicit admin approval.

Default mode is controlled by setting `LICENSE_ISSUANCE_DEFAULT_MODE`.

## Visual License Code
Each issued license carries a structured code:
- Encoded module/license label
- Issue date (`YYYYMMDD`)
- First 4 chars of VAT (alphanumeric)
- Internal 4-char issuer marker

Format:
- `LIC-{LABEL}-{YYYYMMDD}-{VAT4}-{OURS4}`

## Endpoints
- `GET /licenses/active`
- `GET /licenses/core-entitlement`
- `GET /licenses/module-entitlement/{module_code}`
- `POST /licenses/admin/visual-code-preview`
- `GET /licenses/admin/issuance-policy?tenant_id=...`
- `PUT /licenses/admin/issuance-policy`
- `GET /licenses/admin/issue-requests`
- `POST /licenses/admin/issue-startup`
- `POST /licenses/admin/issue-core`
- `POST /licenses/admin/issue-requests/{request_id}/approve`
- `POST /licenses/admin/issue-requests/{request_id}/reject`
- `POST /licenses/admin/issue-module-trial`

## Module Self-Checks
- Startup (`STARTUP`) grants temporary full module access.
- Outside startup, each module must have an active module license (`MODULE_TRIAL` or other active license row with matching `module_code`).
- Missing module entitlement returns `402 module_license_required` and is written to audit as `security.module_entitlement_denied`.

Default module codes currently enforced:
- `PUBLIC_PORTAL` for `/admin/public-profile/*`
- `STORAGE` for `/admin/storage/*` and `/admin/storage/verification-docs/*`
- `INCIDENTS` for `/admin/incidents/*`
- `AI_COPILOT` for `/ai/tenant-copilot`