# Provisioning Module

Superadmin orchestration layer for idempotent tenant foundation bootstrap.

## Endpoint
- `POST /superadmin/provisioning/tenant/run`

## Security
- Superadmin-only route.
- Policy-matrix protected (`TENANTS.WRITE`) with step-up requirement.

## What It Provisions
1. Tenant upsert (`tenant_id`, `name`, `vat_number`)
2. License issuance policy (`AUTO|SEMI|MANUAL`) and startup/core flow
3. Tenant admin + organization profile seed
4. Default tenant role templates seed
5. I18N workspace policy seed
6. Public-profile workspace settings + draft init (optional publish)
7. Guard bot credential bootstrap (idempotent)

## Minimal Payload
```json
{
  "tenant_id": "tenant-dev-001",
  "name": "Tenant Dev 001"
}
```

## Extended Payload Example
```json
{
  "tenant_id": "tenant-dev-001",
  "name": "Tenant Dev 001",
  "vat_number": "BG123456789",
  "issuance": {
    "mode": "SEMI",
    "issue_startup": true,
    "admin_confirmed": true
  },
  "admin": {
    "user_id": "admin@tenant.local",
    "display_name": "Tenant Admin"
  },
  "i18n": {
    "default_locale": "bg",
    "fallback_locale": "en",
    "enabled_locales": ["bg", "en"]
  },
  "public_profile": {
    "settings": {
      "show_company_info": true,
      "show_contacts": true,
      "show_fleet": false,
      "show_price_list": false,
      "show_working_hours": true
    },
    "publish_initial": false
  },
  "guard": {
    "issue_bot_credential": true,
    "label": "tenant-agent-primary"
  }
}
```
