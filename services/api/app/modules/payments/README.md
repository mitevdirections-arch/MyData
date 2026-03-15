# Payments Module

Deferred payment foundation for marketplace licensing flow.

## Tenant Endpoints
- `GET /admin/payments/credit-account`
- `GET /admin/payments/invoices`
- `GET /admin/payments/invoices/{invoice_id}/document`
- `GET /admin/payments/invoice-template`
- `PUT /admin/payments/invoice-template`
- `POST /admin/payments/invoice-template/preview`

## Superadmin Endpoints
- `GET /superadmin/payments/credit-accounts`
- `PUT /superadmin/payments/credit-accounts/{tenant_id}`
- `GET /superadmin/payments/invoice-template/{tenant_id}`
- `PUT /superadmin/payments/invoice-template/{tenant_id}`
- `GET /superadmin/payments/invoices`
- `GET /superadmin/payments/invoices/{invoice_id}/document`
- `POST /superadmin/payments/invoices/{invoice_id}/mark-paid`
- `POST /superadmin/payments/overdue/run-once`

## Deferred v1 Rules
- Deferred mode must be explicitly enabled per tenant.
- Credit limit enforcement is strict (`open_exposure + new_charge <= credit_limit`).
- Overdue invoices can auto-enable account hold (`overdue_hold`).
- Marketplace AUTO/APPROVE flows can create deferred invoices before license issuance.
- Only metadata is stored (no card PAN/CVV storage).

## Invoice Template Engine v1
- Default template: `EU_VAT_V1` (EU VAT requisites baseline).
- Optional country profile: `BG_VAT_V1` (Bulgarian numeric invoice numbering profile).
- Policy is tenant-configurable (`WARN` or `STRICT` enforcement).
- Every new deferred invoice stores a compliance document snapshot (`compliance_json`) with:
  - required fields matrix,
  - missing fields list,
  - legal basis references,
  - validation result.
