# MyData â€” PARTNERS Module Blueprint & Full Module Documentation v1

**Snapshot:** 2026-03-19  
**Status:** Backend foundation implemented on `main`  
**Reference commit:** `e57ab74`  
**Migration:** `0032_partners_v1_foundation`

## ÐšÑ€Ð°Ñ‚ÑŠÐº Ð°Ñ€Ñ…Ð¸Ñ‚ÐµÐºÑ‚ÑƒÑ€ÐµÐ½ Ð¸Ð·Ð²Ð¾Ð´

PARTNERS Ð½Ðµ Ðµ Ð¿Ñ€Ð¾ÑÑ‚Ð¾ Ð°Ð´Ñ€ÐµÑÐ½Ð° ÐºÐ½Ð¸Ð³Ð°. Ð¢Ð¾Ð²Ð° Ðµ operational master-data Ð¼Ð¾Ð´ÑƒÐ» Ð·Ð° ÐºÐ¾Ð½Ñ‚Ñ€Ð°Ð³ÐµÐ½Ñ‚Ð¸, Ð²ÑŠÑ€Ð·Ð°Ð½ Ñ post-order rating, tenant-local trust memory Ð¸ Ð³Ð»Ð¾Ð±Ð°Ð»ÐµÐ½, Ð½Ð¾ Ð°Ð³Ñ€ÐµÐ³Ð¸Ñ€Ð°Ð½ reputation signal. ÐŸÐ°Ñ€Ñ‚Ð½ÑŒÐ¾Ñ€ÑŠÑ‚ Ð½Ðµ Ðµ Ð´Ð»ÑŠÐ¶ÐµÐ½ Ð´Ð° Ð±ÑŠÐ´Ðµ tenant Ð² Ð¿Ð»Ð°Ñ‚Ñ„Ð¾Ñ€Ð¼Ð°Ñ‚Ð°, Ð½Ð¾ ÐµÐ´Ð¸Ð½ Ð¸ ÑÑŠÑ‰ global company record Ð¼Ð¾Ð¶Ðµ Ð´Ð° Ð±ÑŠÐ´Ðµ ÑÐ²ÑŠÑ€Ð·Ð°Ð½ Ñ Ð¼Ð½Ð¾Ð³Ð¾ tenant-Ð¸ ÐµÐ´Ð½Ð¾Ð²Ñ€ÐµÐ¼ÐµÐ½Ð½Ð¾.

## 1. Ð‘Ð¸Ð·Ð½ÐµÑ Ñ†ÐµÐ» Ð¸ Ð¼Ð¾Ð´ÑƒÐ»Ð½Ð° Ñ€Ð¾Ð»Ñ

ÐœÐ¾Ð´ÑƒÐ»ÑŠÑ‚ Ð´Ð°Ð²Ð° Ð½Ð° Ð²ÑÐµÐºÐ¸ tenant ÑÐ¾Ð±ÑÑ‚Ð²ÐµÐ½ Ñ€ÐµÐ³Ð¸ÑÑ‚ÑŠÑ€ Ð½Ð° Ð¿Ð°Ñ€Ñ‚Ð½ÑŒÐ¾Ñ€Ð¸, Ñ ÐºÐ¾Ð¸Ñ‚Ð¾ Ñ€Ð°Ð±Ð¾Ñ‚Ð¸ Ð² ÐµÐ¶ÐµÐ´Ð½ÐµÐ²Ð½Ð°Ñ‚Ð° ÑÐ¸ Ð¾Ð¿ÐµÑ€Ð°Ñ‚Ð¸Ð²Ð½Ð° Ð´ÐµÐ¹Ð½Ð¾ÑÑ‚: Ð¿Ñ€ÐµÐ²Ð¾Ð·Ð²Ð°Ñ‡Ð¸, ÑÐ¿ÐµÐ´Ð¸Ñ‚Ð¾Ñ€Ð¸, ÑÐºÐ»Ð°Ð´Ð¾Ð²Ðµ, ÐºÐ»Ð¸ÐµÐ½Ñ‚Ð¸, Ð´Ð¾ÑÑ‚Ð°Ð²Ñ‡Ð¸Ñ†Ð¸, Ð¼Ð¸Ñ‚Ð½Ð¸Ñ‡ÐµÑÐºÐ¸ Ð¿Ð¾ÑÑ€ÐµÐ´Ð½Ð¸Ñ†Ð¸, Ð·Ð°ÑÑ‚Ñ€Ð°Ñ…Ð¾Ð²Ð°Ñ‚ÐµÐ»Ð¸ Ð¸ Ð´Ñ€ÑƒÐ³Ð¸ Ð²ÑŠÐ½ÑˆÐ½Ð¸ ÑÑ‚Ñ€Ð°Ð½Ð¸.

ÐšÐ»ÑŽÑ‡Ð¾Ð²Ð°Ñ‚Ð° Ñ€Ð°Ð·Ð»Ð¸ÐºÐ° ÑÐ¿Ñ€ÑÐ¼Ð¾ Company Profile Ðµ, Ñ‡Ðµ PARTNERS Ð¾Ð¿Ð¸ÑÐ²Ð° Ð²ÑŠÐ½ÑˆÐ½Ð¸Ñ‚Ðµ Ñ„Ð¸Ñ€Ð¼Ð¸ Ð¸ Ð¿Ð°Ð·Ð¸ Ð¾Ñ†ÐµÐ½ÐºÐ° Ð½Ð° Ñ€ÐµÐ°Ð»Ð½Ð°Ñ‚Ð° ÑÑŠÐ²Ð¼ÐµÑÑ‚Ð½Ð° Ñ€Ð°Ð±Ð¾Ñ‚Ð°: ÐºÐ°Ñ‡ÐµÑÑ‚Ð²Ð¾ Ð½Ð° Ð¸Ð·Ð¿ÑŠÐ»Ð½ÐµÐ½Ð¸Ðµ, ÐºÐ¾Ð¼ÑƒÐ½Ð¸ÐºÐ°Ñ†Ð¸Ñ/Ð´Ð¾ÐºÑƒÐ¼ÐµÐ½Ñ‚Ð¸ Ð¸, ÐºÐ¾Ð³Ð°Ñ‚Ð¾ Ðµ Ð¿Ñ€Ð¸Ð»Ð¾Ð¶Ð¸Ð¼Ð¾, Ð¿Ð»Ð°Ñ‚ÐµÐ¶Ð½Ð° Ð´Ð¸ÑÑ†Ð¸Ð¿Ð»Ð¸Ð½Ð°.

### 1.1 ÐžÑÐ½Ð¾Ð²Ð½Ð¸ Ð¿Ñ€Ð¸Ð½Ñ†Ð¸Ð¿Ð¸

- ÐŸÐ°Ñ€Ñ‚Ð½ÑŒÐ¾Ñ€ÑŠÑ‚ Ð½Ðµ Ðµ Ð·Ð°Ð´ÑŠÐ»Ð¶Ð¸Ñ‚ÐµÐ»Ð½Ð¾ tenant Ð² Ð¿Ð»Ð°Ñ‚Ñ„Ð¾Ñ€Ð¼Ð°Ñ‚Ð°.
- Ð•Ð´Ð½Ð° Ð¸ ÑÑŠÑ‰Ð° Ñ„Ð¸Ñ€Ð¼Ð° Ð¼Ð¾Ð¶Ðµ Ð´Ð° Ð±ÑŠÐ´Ðµ Ð¿Ð°Ñ€Ñ‚Ð½ÑŒÐ¾Ñ€ Ð½Ð° Ð¼Ð½Ð¾Ð³Ð¾ tenant-Ð¸ ÐµÐ´Ð½Ð¾Ð²Ñ€ÐµÐ¼ÐµÐ½Ð½Ð¾.
- Tenant-private Ð±ÐµÐ»ÐµÐ¶ÐºÐ¸ Ð¸ ÐºÐ¾Ð¼ÐµÐ½Ñ‚Ð°Ñ€Ð¸ Ð¾ÑÑ‚Ð°Ð²Ð°Ñ‚ Ð»Ð¾ÐºÐ°Ð»Ð½Ð¸ Ð¸ Ð½Ðµ ÑÐµ Ð¿Ð¾ÐºÐ°Ð·Ð²Ð°Ñ‚ Ð³Ð»Ð¾Ð±Ð°Ð»Ð½Ð¾.
- Global layer Ð¿Ð°Ð·Ð¸ ÑÐ°Ð¼Ð¾ Ð°Ð³Ñ€ÐµÐ³Ð¸Ñ€Ð°Ð½Ð¸ ÑÐ¸Ð³Ð½Ð°Ð»Ð¸ Ð¸ identity-level Ð´Ð°Ð½Ð½Ð¸.
- Design-ÑŠÑ‚ Ñ‚Ñ€ÑÐ±Ð²Ð° Ð´Ð° Ð¿Ð¾Ð·Ð²Ð¾Ð»ÑÐ²Ð° Ð¿Ð¾-ÐºÑŠÑÐ½Ð¾ ÐµÐ´Ð½Ð° Ð¿Ð¾Ñ€ÑŠÑ‡ÐºÐ° Ð´Ð° Ð¸Ð¼Ð° Ð¿Ð¾Ð²ÐµÑ‡Ðµ Ð¾Ñ‚ ÐµÐ´Ð¸Ð½ Ð¸Ð·Ð¿ÑŠÐ»Ð½Ð¸Ñ‚ÐµÐ»/Ð¿Ð°Ñ€Ñ‚Ð½ÑŒÐ¾Ñ€.

## 2. ÐžÐ±Ñ…Ð²Ð°Ñ‚ Ð½Ð° v1

Ð’ÑŠÐ² v1 Ð¼Ð¾Ð´ÑƒÐ»ÑŠÑ‚ Ð¿Ð¾ÐºÑ€Ð¸Ð²Ð° backend foundation, Ð±ÐµÐ· heavy UI Ñ€ÐµÐ°Ð»Ð¸Ð·Ð°Ñ†Ð¸Ñ Ð¸ Ð±ÐµÐ· Orders redesign.

## 3. Ð”Ð¾Ð¼ÐµÐ¹Ð½ Ð¼Ð¾Ð´ÐµÐ»

### 3.1 Ð“Ð»Ð¾Ð±Ð°Ð»ÐµÐ½ ÑÐ»Ð¾Ð¹

- `global_companies`
- `global_company_reputation`

### 3.2 Tenant ÑÐ»Ð¾Ð¹

- `tenant_partners`
- `tenant_partner_roles`
- `tenant_partner_addresses`
- `tenant_partner_bank_accounts`
- `tenant_partner_contacts`
- `tenant_partner_documents`

### 3.3 Rating ÑÐ»Ð¾Ð¹

- `partner_order_ratings`
- `tenant_partner_rating_summary`

## 4. Ð—Ð°ÐºÐ»ÑŽÑ‡ÐµÐ½Ð¸ Ð°Ñ€Ñ…Ð¸Ñ‚ÐµÐºÑ‚ÑƒÑ€Ð½Ð¸ Ñ€ÐµÑˆÐµÐ½Ð¸Ñ

### 4.1 `company_id` Ð¸ `global_company_id`

Ð’ `tenant_partners` ÑÐµÐ¼Ð°Ð½Ñ‚Ð¸ÐºÐ°Ñ‚Ð° Ðµ Ð·Ð°ÐºÐ»ÑŽÑ‡ÐµÐ½Ð° Ñ‚Ð°ÐºÐ°:

- `company_id` = owner tenant/company id
- `global_company_id` = nullable FK ÐºÑŠÐ¼ `global_companies.id`
- `company_id` Ð½Ðµ Ðµ Ð¸ Ð½Ðµ Ñ‚Ñ€ÑÐ±Ð²Ð° Ð´Ð° ÑÐµ Ñ‚ÑŠÐ»ÐºÑƒÐ²Ð° ÐºÐ°Ñ‚Ð¾ global company reference

### 4.2 Dedupe contract

Dedupe Ðµ ÐºÐ¾Ð½ÑÐµÑ€Ð²Ð°Ñ‚Ð¸Ð²ÐµÐ½, deterministic Ð¸ Ð½Ð°Ñ€Ð¾Ñ‡Ð½Ð¾ Ð½Ðµ Ðµ aggressive.

ÐŸÑ€Ð¸Ð¾Ñ€Ð¸Ñ‚ÐµÑ‚:

1. exact match Ð¿Ð¾ `(country_code, vat_number)`, Ð°ÐºÐ¾ VAT Ðµ Ð½Ð°Ð»Ð¸Ñ‡ÐµÐ½
2. Ð¸Ð½Ð°Ñ‡Ðµ exact match Ð¿Ð¾ `(country_code, registration_number)`, Ð°ÐºÐ¾ registration Ðµ Ð½Ð°Ð»Ð¸Ñ‡ÐµÐ½
3. Ð¸Ð½Ð°Ñ‡Ðµ fallback Ð¿Ð¾ `(country_code, normalized_name)` ÑÐ°Ð¼Ð¾ Ð°ÐºÐ¾ Ð»Ð¸Ð¿ÑÐ²Ð°Ñ‚ VAT Ð¸ registration Ð¸ `normalized_name` Ðµ exact match

ÐŸÑ€Ð¸ ÐºÐ¾Ð½Ñ„Ð»Ð¸ÐºÑ‚ Ð¸Ð»Ð¸ ÑÑŠÐ¼Ð½ÐµÐ½Ð¸Ðµ:
- Ð½Ðµ merge-Ð²Ð°Ð¼Ðµ
- ÑÑŠÐ·Ð´Ð°Ð²Ð°Ð¼Ðµ Ð½Ð¾Ð² `global_companies` record

### 4.3 Rating Ð¸ order linkage

- `order_id` Ðµ nullable Ð²ÑŠÐ² v1
- backend Ð½Ðµ enforce-Ð²Ð° terminal order status Ð²ÑŠÐ² v1
- Ð°ÐºÐ¾ `order_id` Ðµ Ð¿Ð¾Ð´Ð°Ð´ÐµÐ½, Ñ‚Ð¾Ð¹ ÑÐµ Ð¿Ð°Ð·Ð¸ ÐºÐ°Ñ‚Ð¾ reference only
- UI workflow Ð¿Ð¾-ÐºÑŠÑÐ½Ð¾ Ñ‰Ðµ Ð¾Ñ‚Ð²Ð°Ñ€Ñ rating dialog ÑÐ»ÐµÐ´ completed order

### 4.4 Document metadata contract

Ð’ `tenant_partner_documents` v1 ÑÐµ Ð¿Ð°Ð·ÑÑ‚ ÑÐ°Ð¼Ð¾ metadata Ð¿Ð¾Ð»ÐµÑ‚Ð°:

- `id`
- `company_id`
- `partner_id`
- `doc_type`
- `file_name`
- `content_type`
- `size_bytes`
- `storage_key`
- `uploaded_by_user_id`
- `note`
- `created_at`
- `archived_at`

## 5. Ð ÐµÐ¹Ñ‚Ð¸Ð½Ð³ Ð»Ð¾Ð³Ð¸ÐºÐ° Ð¸ summary Ð¼Ð¾Ð´ÐµÐ»

### 5.1 Ð¡ÐºÐ°Ð»Ð°Ñ‚Ð°

Ð’ÑÐ¸Ñ‡ÐºÐ¸ Ð·Ð²ÐµÐ·Ð´Ð¸ ÑÐ° Ð¿Ð¾ ÑÐºÐ°Ð»Ð° Ð¾Ñ‚ 1 Ð´Ð¾ 6, ÐºÑŠÐ´ÐµÑ‚Ð¾ 6 Ðµ Ð½Ð°Ð¹-Ð²Ð¸ÑÐ¾ÐºÐ° Ð¾Ñ†ÐµÐ½ÐºÐ°.

### 5.2 Ð¤Ð¾Ñ€Ð¼ÑƒÐ»Ð° Ð·Ð° overall score

- Ð°ÐºÐ¾ `payment_expected = false`  
  `overall = avg(execution_quality, communication_docs)`

- Ð°ÐºÐ¾ `payment_expected = true`  
  `overall = avg(execution_quality, communication_docs, payment_discipline)`

### 5.3 ÐšÐ°ÐºÐ²Ð¾ ÑÐµ Ð°Ð³Ñ€ÐµÐ³Ð¸Ñ€Ð°

- **tenant-local overall** â€” summary Ð·Ð° ÐºÐ¾Ð½ÐºÑ€ÐµÑ‚Ð½Ð¸Ñ partner record Ð² ÐºÐ¾Ð½ÐºÑ€ÐµÑ‚Ð½Ð¸Ñ tenant
- **global overall** â€” summary Ð½Ð° Ð½Ð¸Ð²Ð¾ global company Ð½Ð° Ð±Ð°Ð·Ð° ratings Ð¾Ñ‚ ÑÐ²ÑŠÑ€Ð·Ð°Ð½Ð¸Ñ‚Ðµ tenant partner records

### 5.4 Summary recompute strategy

Ð—Ð° Ð´Ð° Ð½ÑÐ¼Ð° Ð¸Ð·Ð»Ð¸ÑˆÐµÐ½ runtime tax, recompute-ÑŠÑ‚ Ðµ scoped Ð¸ sync:

- tenant summary ÑÐµ Ð¾Ð±Ð½Ð¾Ð²ÑÐ²Ð° ÑÐ°Ð¼Ð¾ Ð·Ð° Ð·Ð°ÑÐµÐ³Ð½Ð°Ñ‚ `partner_id`
- global summary ÑÐµ Ð¾Ð±Ð½Ð¾Ð²ÑÐ²Ð° ÑÐ°Ð¼Ð¾ Ð·Ð° Ð·Ð°ÑÐµÐ³Ð½Ð°Ñ‚ `global_company_id`
- Ð½Ðµ ÑÐµ Ð¿Ñ€Ð°Ð²ÑÑ‚ full scans Ð¸ global recompute Ð½Ð° Ñ†ÑÐ»Ð°Ñ‚Ð° Ð±Ð°Ð·Ð° Ð¿Ñ€Ð¸ ÐµÐ´Ð¸Ð½Ð¸Ñ‡Ð½Ð° rating Ð¿Ñ€Ð¾Ð¼ÑÐ½Ð°

## 6. Privacy, visibility Ð¸ trust boundaries

- Tenant-private comments Ð¸ notes Ð¾ÑÑ‚Ð°Ð²Ð°Ñ‚ Ð»Ð¾ÐºÐ°Ð»Ð½Ð¸.
- Ð“Ð»Ð¾Ð±Ð°Ð»Ð½Ð¸ÑÑ‚ ÑÐ»Ð¾Ð¹ Ð¿Ð°Ð·Ð¸ ÑÐ°Ð¼Ð¾ Ð°Ð³Ñ€ÐµÐ³Ð¸Ñ€Ð°Ð½Ð¸ ÑÑ‚Ð¾Ð¹Ð½Ð¾ÑÑ‚Ð¸.
- ÐÑÐ¼Ð° global blacklist Ð²ÑŠÐ² v1.
- Tenant blacklist Ðµ Ð»Ð¾ÐºÐ°Ð»ÐµÐ½.
- Ð“Ð»Ð¾Ð±Ð°Ð»Ð½Ð¸ÑÑ‚ ÑÐ»Ð¾Ð¹ Ð¼Ð¾Ð¶Ðµ Ð´Ð° Ð¿Ð¾ÐºÐ°Ð·Ð²Ð° aggregated risk signal, Ð½Ð¾ Ð½Ðµ Ð¸ ÑÑƒÑ€Ð¾Ð²Ð¸ cross-tenant ÐºÐ¾Ð¼ÐµÐ½Ñ‚Ð°Ñ€Ð¸.

## 7. API surface â€” backend foundation

ÐšÑŠÐ¼ Ñ‚ÐµÐºÑƒÑ‰Ð¸Ñ snapshot backend surface-ÑŠÑ‚ Ð½Ð° PARTNERS Ðµ ÑÐ»ÐµÐ´Ð½Ð¸ÑÑ‚:

- `GET /partners`
- `POST /partners`
- `GET /partners/{partner_id}`
- `PUT /partners/{partner_id}`
- `POST /partners/{partner_id}/archive`
- `POST /partners/{partner_id}/blacklist`
- `POST /partners/{partner_id}/watchlist`
- `PUT /partners/{partner_id}/roles`
- `POST /partners/{partner_id}/ratings`
- `GET /partners/{partner_id}/rating-summary`
- `GET /partners/{partner_id}/global-signal`

### 7.1 OpenAPI DTOs

Ð’ OpenAPI ÑÐ° Ð½Ð°Ð»Ð¸Ñ‡Ð½Ð¸ DTO-Ñ‚Ð° ÐºÐ°Ñ‚Ð¾:

- `PartnerCreateRequestDTO`
- `PartnerUpdateRequestDTO`
- `PartnerDetailResponseDTO`
- `PartnerRatingCreateRequestDTO`
- `PartnerRatingSummaryResponseDTO`
- `PartnerGlobalSignalResponseDTO`
- `GlobalCompanySignalDTO`
- DTO-Ñ‚Ð° Ð·Ð° Ð°Ð´Ñ€ÐµÑÐ¸, ÐºÐ¾Ð½Ñ‚Ð°ÐºÑ‚Ð¸, Ð±Ð°Ð½ÐºÐ¾Ð²Ð¸ Ð´Ð°Ð½Ð½Ð¸, Ð´Ð¾ÐºÑƒÐ¼ÐµÐ½Ñ‚Ð¸ Ð¸ Ñ€Ð¾Ð»Ð¸

## 8. UI blueprint

### 8.1 Partners list screen

- Search bar: name / VAT / country / registration number
- Ð¤Ð¸Ð»Ñ‚Ñ€Ð¸: role, status, blacklist/watchlist, country
- ÐšÐ¾Ð»Ð¾Ð½Ð¸: Name, Roles, Country, VAT, Avg rating, Orders count, Payment signal, Status
- Quick actions: View, Edit, Archive, Blacklist/Watchlist

### 8.2 Partner 360

ÐŸÑ€ÐµÐ¿Ð¾Ñ€ÑŠÑ‡Ð°Ð½Ð¸ Ñ‚Ð°Ð±Ð¾Ð²Ðµ:

- Overview
- Addresses
- Bank details
- Contacts
- Documents
- Ratings
- Activity

### 8.3 Rating dialog ÑÐ»ÐµÐ´ Ð·Ð°Ð²ÑŠÑ€ÑˆÐµÐ½Ð° Ð¿Ð¾Ñ€ÑŠÑ‡ÐºÐ°

ÐšÐ¾Ð³Ð°Ñ‚Ð¾ Orders Ð±ÑŠÐ´Ðµ Ð´Ð¾Ð²ÑŠÑ€ÑˆÐµÐ½ ÑÑ‚Ñ€ÑƒÐºÑ‚ÑƒÑ€Ð½Ð¾, ÑÐ»ÐµÐ´ completed/closed workflow UI Ñ‚Ñ€ÑÐ±Ð²Ð° Ð´Ð° Ð¼Ð¾Ð¶Ðµ Ð´Ð° Ð¾Ñ‚Ð²Ð¾Ñ€Ð¸ rating dialog Ñ:

- Execution quality: 1â€“6 Ð·Ð²ÐµÐ·Ð´Ð¸
- Communication & documents: 1â€“6 Ð·Ð²ÐµÐ·Ð´Ð¸
- Payment discipline: 1â€“6 Ð·Ð²ÐµÐ·Ð´Ð¸, ÑÐ°Ð¼Ð¾ Ð°ÐºÐ¾ `payment_expected = true`
- Short comment
- Issue flags ÐºÐ°Ñ‚Ð¾ quick checkboxes

### 8.4 Global signal panel

Ð’ partner overview Ð¸Ð¼Ð° ÑÐ¼Ð¸ÑÑŠÐ» Ð´Ð° ÑÐµ Ð¿Ð¾ÐºÐ°Ð·Ð²Ð° Ð¾Ñ‚Ð´ÐµÐ»ÐµÐ½ Ð¿Ð°Ð½ÐµÐ»:

- Known in platform: yes / no
- Seen across tenants: N
- Global reputation: X / 6
- Risk badges

## 9. RBAC Ð¸ Ð¼Ð¾Ð´ÑƒÐ»Ð½Ð° Ð»Ð¸Ñ†ÐµÐ½Ð·Ð½Ð° Ð¿Ð¾Ð·Ð¸Ñ†Ð¸Ñ

### 9.1 Permission codes

- `PARTNERS.READ`
- `PARTNERS.WRITE`
- `PARTNERS.ARCHIVE`
- `PARTNERS.RATE`
- `PARTNERS.VIEW_GLOBAL_SIGNAL`
- `PARTNERS.MANAGE_BLACKLIST`

### 9.2 Access model

Bank details, documents Ð¸ blacklist actions Ð¼Ð¾Ð¶Ðµ Ð¿Ð¾-ÐºÑŠÑÐ½Ð¾ Ð´Ð° Ð±ÑŠÐ´Ð°Ñ‚ Ð¾Ð³Ñ€Ð°Ð½Ð¸Ñ‡ÐµÐ½Ð¸ Ð¿Ð¾ role, Ð½Ð¾ v1 foundation Ð²ÐµÑ‡Ðµ Ð¸Ð¼Ð° policy hooks, Ð·Ð° Ð´Ð° ÑÐµ Ñ€Ð°Ð·ÑˆÐ¸Ñ€Ð¸ Ð±ÐµÐ· broad refactor.

### 9.3 Marketplace Ð¸ module identity

ÐœÐ¾Ð´ÑƒÐ»ÑŠÑ‚ Ñ‚Ñ€ÑÐ±Ð²Ð° Ð´Ð° ÑÑ‚Ð¾Ð¸ Ð² Marketplace ÐºÐ°Ñ‚Ð¾ operational module Ñ `module_code = PARTNERS`. Ð¢ÐµÐºÑƒÑ‰Ð°Ñ‚Ð° foundation Ð¸Ð½Ñ‚ÐµÐ³Ñ€Ð°Ñ†Ð¸Ñ Ðµ Ð¼Ð¸Ð½Ð¸Ð¼Ð°Ð»Ð½Ð° Ð¸ Ð½Ðµ Ð¿Ñ€Ð°Ð²Ð¸ licensing rewrite.

## 10. Ð˜Ð½Ñ‚ÐµÐ³Ñ€Ð°Ñ†Ð¸Ð¸

### 10.1 Orders

Orders Ð½Ðµ Ðµ Ñ„Ð¸Ð½Ð°Ð»Ð¸Ð·Ð¸Ñ€Ð°Ð½ ÑÑ‚Ñ€ÑƒÐºÑ‚ÑƒÑ€Ð½Ð¾ Ð¸ Ð·Ð°Ñ‚Ð¾Ð²Ð° v1 Ð½Ð°Ñ€Ð¾Ñ‡Ð½Ð¾ Ð½Ðµ Ð¿Ñ€Ð°Ð²Ð¸ hard dependency. ÐÑ€Ñ…Ð¸Ñ‚ÐµÐºÑ‚ÑƒÑ€Ð½Ð¾ Ð¾Ð±Ð°Ñ‡Ðµ PARTNERS Ñ‚Ñ€ÑÐ±Ð²Ð° Ð´Ð° ÑÐµ Ñ€Ð°Ð·Ð³Ð»ÐµÐ¶Ð´Ð° ÐºÐ°Ñ‚Ð¾ Ð±ÑŠÐ´ÐµÑ‰ source of truth Ð·Ð° order counterparties.

Ð¦ÐµÐ»ÐµÐ²Ð¾Ñ‚Ð¾ Ñ€Ð°Ð·Ð²Ð¸Ñ‚Ð¸Ðµ Ðµ ÐµÐ´Ð½Ð° Ð¿Ð¾Ñ€ÑŠÑ‡ÐºÐ° Ð´Ð° Ð¼Ð¾Ð¶Ðµ Ð´Ð° Ð¸Ð¼Ð° Ð¿Ð¾Ð²ÐµÑ‡Ðµ Ð¾Ñ‚ ÐµÐ´Ð¸Ð½ Ð¿Ð°Ñ€Ñ‚Ð½ÑŒÐ¾Ñ€/Ð¸Ð·Ð¿ÑŠÐ»Ð½Ð¸Ñ‚ÐµÐ», Ð²ÐºÐ»ÑŽÑ‡Ð¸Ñ‚ÐµÐ»Ð½Ð¾ Ð¿Ñ€ÐµÐ²Ð¾Ð·Ð²Ð°Ñ‡, ÑÐºÐ»Ð°Ð´, Ð¿Ð¾Ð´Ð¸Ð·Ð¿ÑŠÐ»Ð½Ð¸Ñ‚ÐµÐ», Ð·Ð°ÑÑ‚Ñ€Ð°Ñ…Ð¾Ð²Ð°Ñ‚ÐµÐ» Ð¸Ð»Ð¸ Ð´Ñ€ÑƒÐ³Ð° Ñ€ÐµÐ»ÐµÐ²Ð°Ð½Ñ‚Ð½Ð° ÑÑ‚Ñ€Ð°Ð½Ð°.

### 10.2 EIDON

Global company registry Ðµ Ð¾ÑÐ½Ð¾Ð²Ð°Ñ‚Ð° EIDON Ð¿Ð¾-ÐºÑŠÑÐ½Ð¾ Ð´Ð° Ð¼Ð¾Ð¶Ðµ Ð´Ð° Ñ€Ð°Ð·Ð¿Ð¾Ð·Ð½Ð°Ð²Ð° Ð²ÐµÑ‡Ðµ ÑÑ€ÐµÑ‰Ð°Ð½Ð¸ Ñ„Ð¸Ñ€Ð¼Ð¸, Ð´Ð° Ð¸Ð·Ð²Ð»Ð¸Ñ‡Ð° aggregated signal Ð¸ Ð´Ð° Ð¿Ñ€ÐµÐ´ÑƒÐ¿Ñ€ÐµÐ¶Ð´Ð°Ð²Ð° Ð·Ð° Ñ€Ð¸ÑÐºÐ¾Ð²Ð¸ pattern-Ð¸, Ð±ÐµÐ· Ð´Ð° Ð½Ð°Ñ€ÑƒÑˆÐ°Ð²Ð° tenant privacy.

### 10.3 Future modules

- Autofleet / vehicles
- Costing / calculations / charges
- Documents and compliance
- Payments / receivables

## 11. ÐÐµÑ„ÑƒÐ½ÐºÑ†Ð¸Ð¾Ð½Ð°Ð»Ð½Ð¸ Ð¸Ð·Ð¸ÑÐºÐ²Ð°Ð½Ð¸Ñ Ð¸ guardrails

- scoped recompute only
- Ð±ÐµÐ· full scans Ð·Ð° summary updates
- Ð±ÐµÐ· heavy workers Ð²ÑŠÐ² v1
- Ð±ÐµÐ· Orders redesign Ð²ÑŠÐ² v1
- Ð±ÐµÐ· leak Ð½Ð° tenant-private comments/notes Ð² global layer
- conservative dedupe only

## 12. ÐŸÑ€ÐµÐ¿Ð¾Ñ€ÑŠÑ‡Ð°Ð½Ð° Ð¿ÑŠÑ‚Ð½Ð° ÐºÐ°Ñ€Ñ‚Ð°

### 12.1 Phase 1 â€” Ð²ÐµÑ‡Ðµ Ð¿Ð¾Ð»Ð¾Ð¶ÐµÐ½Ð° Ð¾ÑÐ½Ð¾Ð²Ð°

- Backend schema Ð¸ migration
- Models, service layer Ð¸ API routers
- Rating formula Ð¸ scoped summary recompute
- RBAC hooks
- Marketplace identity hook

### 12.2 Phase 2 â€” UI Ð¸ operational usability

- Partners list Ð¸ Partner 360 screens
- Role-aware forms
- Rating dialog ÑÐ»ÐµÐ´ order completion
- Search, filters Ð¸ empty states

### 12.3 Phase 3 â€” Global intelligence

- EIDON lookup
- Better dedupe tooling
- Risk badges Ð¸ aggregated trust signals
- Cross-tenant pattern intelligence Ð±ÐµÐ· leak Ð½Ð° private data

## 13. Acceptance snapshot Ð·Ð° Ñ‚ÐµÐºÑƒÑ‰Ð¾Ñ‚Ð¾ ÑÑŠÑÑ‚Ð¾ÑÐ½Ð¸Ðµ

ÐšÑŠÐ¼ Ñ‚ÐµÐºÑƒÑ‰Ð¸Ñ snapshot backend foundation Ðµ ÑƒÑÐ¿ÐµÑˆÐ½Ð¾ Ð·Ð°Ñ‚Ð²Ð¾Ñ€ÐµÐ½.

- migration `0032_partners_v1_foundation` = Ð¿Ñ€Ð¸Ð»Ð¾Ð¶ÐµÐ½Ð°
- API startup = ÑƒÑÐ¿ÐµÑˆÐµÐ½
- PARTNERS routes = Ð½Ð°Ð»Ð¸Ñ‡Ð½Ð¸ Ð² OpenAPI
- PARTNERS schemas = Ð½Ð°Ð»Ð¸Ñ‡Ð½Ð¸ Ð² OpenAPI
- targeted PARTNERS test pack = PASS
- commit = `e57ab74`

## 14. Ð Ð¸ÑÐºÐ¾Ð²Ðµ Ð¸ Ð¾Ñ‚Ð²Ð¾Ñ€ÐµÐ½Ð¸ Ñ‚Ð¾Ñ‡ÐºÐ¸

- Ð¢Ð¾Ñ‡Ð½Ð¾ÑÑ‚Ñ‚Ð° Ð½Ð° dedupe Ñ‰Ðµ Ð·Ð°Ð²Ð¸ÑÐ¸ Ð¾Ñ‚ ÐºÐ°Ñ‡ÐµÑÑ‚Ð²Ð¾Ñ‚Ð¾ Ð½Ð° Ð²Ñ…Ð¾Ð´Ð½Ð¸Ñ‚Ðµ Ñ„Ð¸Ñ€Ð¼ÐµÐ½Ð¸ Ð´Ð°Ð½Ð½Ð¸.
- Ð“Ð»Ð¾Ð±Ð°Ð»Ð½Ð¸ÑÑ‚ reputation signal Ñ‚Ñ€ÑÐ±Ð²Ð° Ð´Ð° Ð¾ÑÑ‚Ð°Ð½Ðµ Ð°Ð³Ñ€ÐµÐ³Ð¸Ñ€Ð°Ð½ Ð¸ Ð¿Ñ€Ð°Ð²Ð½Ð¾ Ð¿Ñ€ÐµÐ´Ð¿Ð°Ð·Ð»Ð¸Ð².
- Orders Ñ‚Ñ€ÑÐ±Ð²Ð° Ð´Ð° Ð±ÑŠÐ´Ðµ Ð·Ð°Ð²ÑŠÑ€ÑˆÐµÐ½ Ñ‚Ð°ÐºÐ°, Ñ‡Ðµ Ð´Ð° Ð¿Ð¾Ð´Ð´ÑŠÑ€Ð¶Ð° multi-party linkage.
- ÐŸÑ€Ð¸ future UI Ðµ Ð½ÑƒÐ¶Ð½Ð¾ Ð´Ð° Ð¸Ð¼Ð° role-aware field visibility Ð·Ð° bank/docs/blacklist actions.

## 15. ÐŸÑ€Ð°ÐºÑ‚Ð¸Ñ‡ÐµÑÐºÐ¾ Ð·Ð°ÐºÐ»ÑŽÑ‡ÐµÐ½Ð¸Ðµ

PARTNERS v1 Ðµ Ð¿Ñ€Ð°Ð²Ð¸Ð»Ð½Ð¾ Ð¿Ð¾Ð·Ð¸Ñ†Ð¸Ð¾Ð½Ð¸Ñ€Ð°Ð½ ÐºÐ°Ñ‚Ð¾ operational marketplace module. ÐœÐ¾Ð´ÑƒÐ»ÑŠÑ‚ Ð²ÐµÑ‡Ðµ Ð¸Ð¼Ð° backend foundation, ÐºÐ¾ÑÑ‚Ð¾ Ð¿Ð¾Ð·Ð²Ð¾Ð»ÑÐ²Ð° Ð´Ð° ÑÐµ ÑÑ‚Ñ€Ð¾Ð¸ UI Ð¸ Ð¿Ð¾-ÐºÑŠÑÐ½Ð¾ Ð´Ð° ÑÐµ Ð´Ð¾Ð±Ð°Ð²ÑÑ‚ EIDON Ð¸ global reputation capabilities Ð±ÐµÐ· broad refactor.

