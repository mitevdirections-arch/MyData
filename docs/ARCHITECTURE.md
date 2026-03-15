# Architecture Overview

## Runtime
- API: FastAPI + Pydantic v2.
- DB: PostgreSQL-compatible (CockroachDB-ready).
- Object storage: S3-compatible (MinIO in dev).
- Queue/events: planned for phase 2.

## Core Domains
1. Tenancy
2. Licensing and entitlements
3. Guard and heartbeat validation
4. Public profile publishing controls
5. Profile and workspace administration (admin profiles, org profiles, roles/users).
6. I18N and locale policy.
7. AI copilots (tenant and superadmin)

## Module Contract
Each module provides:
- `router.py` (API surface)
- `service.py` (domain logic)
- `schemas.py` (I/O contracts)
- `README.md` (purpose, boundaries, invariants)

## Security Boundaries
- Every request carries tenant context (JWT claim + header verification).
- Core license check is mandatory for protected routes.
- Guard status can deny access independently.
- All admin actions are audited.
