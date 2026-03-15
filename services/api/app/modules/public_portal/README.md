# Public Portal Module

Public-facing experience foundation for both workspace types:
- `TENANT` (client company)
- `PLATFORM` (superadmin/public MyData site)

## What Is Stored
- Visibility settings per workspace (`public_workspace_settings`)
- Public page draft/published content (`public_page_drafts`, `public_page_published`)
- Brand assets metadata (`public_brand_assets`)

No customer business files are stored here. Assets are uploaded to object storage (MinIO/S3) via signed URLs.

## Logo Handling
- There is no hardcoded/default logo in tenant/superadmin profile rows.
- Active logo is managed as a public brand asset (`asset_kind=LOGO`).
- Upload target bucket: `STORAGE_BUCKET_PUBLIC_ASSETS` (default: `mydata-public-assets`).
- Object key pattern:
  - `public-assets/{workspace_type}/{workspace_id}/logo/{asset_id}/{file_name}`

### Admin Flow (BFF-safe)
1. Request upload slot:
   - `POST /admin/public-profile/assets/logo/presign-upload`
2. Upload file directly to MinIO using returned signed `PUT` URL.
3. Confirm upload and activate logo:
   - `POST /admin/public-profile/assets/{asset_id}/mark-uploaded`
4. List assets:
   - `GET /admin/public-profile/assets?asset_kind=LOGO`

Only ACTIVE logo is used in public payload.

## Public Page Flow
1. Load editor state:
   - `GET /admin/public-profile/editor`
2. Save draft:
   - `PUT /admin/public-profile/editor/draft`
3. Publish immutable version:
   - `POST /admin/public-profile/editor/publish`
4. Public read:
   - Tenant: `GET /public/profile/{tenant_id}`
   - Generic workspace: `GET /public/site/{workspace_type}/{workspace_id}`

## Security Invariants
- Admin endpoints require entitlement `PUBLIC_PORTAL` and admin claims.
- Workspace scope resolution enforces strict boundary between tenant/platform.
- Public reads serve published content if available, otherwise generated default profile view.
- Logo URLs are short-lived signed URLs (no anonymous bucket exposure).