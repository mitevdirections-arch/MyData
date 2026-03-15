# Storage Policy Module

Company policy implemented:
- Zero retention for customer files.
- Metadata-only in DB.
- Temporary verification documents only (exception path).
- Short retention with mandatory expiration and delete tracking.

Endpoints:
- /admin/storage/policy
- /admin/storage/verification-docs/*
