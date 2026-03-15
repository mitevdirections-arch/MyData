# Orders Module (CMR/ADR Contract Minimum v1)

Orders is the canonical reference module for future operational modules.
This cycle introduces minimum CMR-ready and ADR-ready typed structure without changing workflow logic.

## Contract goals
- Typed `schemas.py` boundary between router and service.
- Explicit list vs detail response contracts.
- Minimum CMR structure in typed DTOs.
- Minimum ADR structure in typed DTOs.
- Preserve auth/authz/entitlement semantics and endpoint behavior 1:1.

## Endpoints
- `GET /orders` -> `OrdersListResponseDTO` (list/summary envelope)
- `POST /orders` -> `OrderDetailResponseDTO` (create + detail envelope)
- `GET /orders/{order_id}` -> `OrderDetailResponseDTO`

## CMR minimum typed sections
- Parties:
  - `shipper`
  - `consignee`
  - `carrier`
- Structured address (`OrderStructuredAddressDTO`):
  - `address_line_1`
  - `address_line_2` (optional)
  - `city`
  - `postal_code`
  - `country_code`
- Taking over / delivery:
  - `taking_over.place`
  - `taking_over.date`
  - `taking_over.address`
  - `place_of_delivery.place`
  - `place_of_delivery.address`
- Goods and packing (`OrderGoodsDTO`):
  - `goods_description`
  - `packages_count`
  - `packing_method`
  - `marks_numbers`
  - `gross_weight_kg`
  - `volume_m3`
- References and formalities:
  - `references` (`customer_reference`, `booking_reference`, `contract_reference`, `external_reference`)
  - `instructions_formalities`

## ADR minimum typed sections
- `is_dangerous_goods` (selectable flag)
- `adr` (`OrderAdrDetailsDTO`):
  - `un_number`
  - `adr_class`
  - `packing_group`
  - `proper_shipping_name`
  - `adr_notes`

## Transitional compatibility
- Legacy fields (`customer_name`, `pickup_location`, `delivery_location`, etc.) remain for backward-safe compatibility.
- `payload` remains optional transitional storage and must not be treated as the primary business contract.
