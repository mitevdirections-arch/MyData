# PARTNERS v1 Backend Handover

## Added scope
- New backend module: `PARTNERS` (tenant-local registry + ratings + global aggregate foundation).
- New DB foundation for:
  - global companies and global aggregated reputation
  - tenant partners registry and sub-resources (roles, addresses, bank accounts, contacts, documents)
  - order-linked partner ratings (with `order_id` reference-only in v1)
  - tenant-local partner rating summary
- Router + service + schemas for `PARTNERS`.
- RBAC permission hooks + policy matrix + route ownership entries.
- Marketplace module identity hook for `MODULE_PARTNERS`.

## Blueprint doc
- Extended module blueprint/reference: `docs/partners_module_blueprint_v1.md`

## New/changed tables
- `global_companies`
- `global_company_reputation`
- `tenant_partners`
- `tenant_partner_roles`
- `tenant_partner_addresses`
- `tenant_partner_bank_accounts`
- `tenant_partner_contacts`
- `tenant_partner_documents`
- `partner_order_ratings`
- `tenant_partner_rating_summary`

## Endpoints added
- `GET /partners`
- `POST /partners`
- `GET /partners/{partner_id}`
- `PUT /partners/{partner_id}`
- `POST /partners/{partner_id}/archive`
- `PUT /partners/{partner_id}/roles`
- `POST /partners/{partner_id}/blacklist`
- `POST /partners/{partner_id}/watchlist`
- `POST /partners/{partner_id}/ratings`
- `GET /partners/{partner_id}/rating-summary`
- `GET /partners/{partner_id}/global-signal`

## Locked contracts implemented
1. `tenant_partners.company_id` is owner tenant/company id.
2. `tenant_partners.global_company_id` is nullable FK to `global_companies.id`.
3. Dedupe contract (conservative, deterministic):
   - priority 1: exact `(country_code, vat_number)` when VAT exists
   - priority 2: exact `(country_code, registration_number)` when VAT missing and registration exists
   - priority 3: exact `(country_code, normalized_name)` only when VAT+registration are missing
   - if conflict/ambiguity -> do **not** merge; create new `global_companies` row
4. Rating:
   - `partner_order_ratings.order_id` is nullable
   - no terminal-order enforcement in backend v1
   - `order_id` persisted as reference only
5. Document metadata contract implemented in `tenant_partner_documents` per requested fields.

## Rating formula
- If `payment_expected = false`:
  - `overall = avg(execution_quality, communication_docs)`
- If `payment_expected = true`:
  - `overall = avg(execution_quality, communication_docs, payment_discipline)`

## Summary recompute behavior (sync, scoped)
- Tenant summary recompute:
  - only for affected `partner_id`
- Global summary recompute:
  - only for affected `global_company_id`
- No heavy background workers were added.

## Privacy and tenant boundaries
- `short_comment` remains tenant-local in rating records.
- Global signal endpoint exposes only aggregated values and company identity.
- No tenant-private notes/comments are exposed via global signal response.

## RBAC hooks added
- `PARTNERS.READ`
- `PARTNERS.WRITE`
- `PARTNERS.ARCHIVE`
- `PARTNERS.RATE`
- `PARTNERS.VIEW_GLOBAL_SIGNAL`
- `PARTNERS.MANAGE_BLACKLIST`

## Assumptions made
- `order_id` remains UUID reference-only in v1, without FK enforcement to Orders table.
- `global_company_reputation` is maintained via synchronous recompute in request path for scoped target only.
- Marketplace identity hook is satisfied by seeding `MODULE_PARTNERS` in marketplace catalog defaults.

## Left for phase 2
- Async/queued recompute pipeline for large-scale reputation refresh.
- Manual-review dedupe workflow and fuzzy matching.
- Advanced anti-abuse model for ratings.
- Deep Orders integration for strict completed-order gating.
