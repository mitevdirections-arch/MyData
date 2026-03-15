# DB and MinIO Bring-up Plan

## DB profile in use
- User: `mydata_migrator`
- Database: `mydata`
- Engine: CockroachDB on `127.0.0.1:26257`

## Migration flow
1. Copy `services/api/.env.example` to `services/api/.env`.
2. From `services/api`, run `pwsh ./scripts/db-upgrade.ps1`.
3. Verify tables: `tenants`, `licenses`, `guard_heartbeats`, `audit_log`.

## MinIO usage
Enable MinIO for storage module phase (presign/object workflows).

## Security notes
- Dev credentials are local-only.
- Production must use secret manager, rotated keys, private networking.
