# Marketplace Module

Backend foundation for paid module sales.

## Scope
- Module catalog management
- Offer and promotion management
- Tenant purchase requests
- Superadmin approve/reject flow
- License issuance integration for approved purchases

## Main Endpoints
- `GET /marketplace/catalog`
- `GET /marketplace/offers/active`
- `POST /marketplace/purchase-requests`
- `GET /marketplace/purchase-requests`
- `GET /marketplace/admin/catalog`
- `PUT /marketplace/admin/catalog/{module_code}`
- `GET /marketplace/admin/offers`
- `POST /marketplace/admin/offers`
- `PUT /marketplace/admin/offers/{offer_id}`
- `GET /marketplace/admin/purchase-requests`
- `POST /marketplace/admin/purchase-requests/{request_id}/approve`
- `POST /marketplace/admin/purchase-requests/{request_id}/reject`