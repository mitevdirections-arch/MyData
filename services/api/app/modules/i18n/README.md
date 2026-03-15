# I18N Module

Purpose:
- Built-in translation catalogs (no online translation dependency).
- Workspace locale policy for tenant and platform scopes.
- Effective locale resolution by precedence:
  1) explicit request locale
  2) admin profile preference
  3) workspace default locale
  4) workspace fallback locale

Endpoints:
- `GET /i18n/locales`
- `GET /i18n/catalog/{locale}`
- `GET /i18n/effective`
- `GET/PUT /admin/i18n/tenant-default`
- `GET/PUT /superadmin/i18n/platform-default`

Table:
- `i18n_workspace_policies`