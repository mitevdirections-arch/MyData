# MyData API Environment And Secret Policy

## Purpose
This policy defines how configuration and secrets are handled across `dev`, `stage`, and `prod` for MyData API.

Security priority:
- truth and traceability
- no hardcoded secrets
- no credential leaks in git, logs, or docs
- fail-closed startup when required security config is missing

## Scope
Applies to:
- `C:\Users\mitev\OneDrive\Документи\MyData\services\api`
- application runtime settings
- migration runtime (`alembic`)
- local scripts used to start API and run tests

## Source Of Truth By Environment
1. `dev` (local):
- `.env` is allowed as local runtime source.
- `.env` is local-only and must never be committed.
- `.env.example` is template-only and must not contain real credentials.

2. `stage`:
- prefer injected environment variables or secret manager.
- avoid long-lived secrets in files on disk.

3. `prod`:
- required source is orchestrator/secret manager injected environment.
- do not rely on committed files for secrets.
- do not rely on `.env` file for production secret distribution.

## Hardcode Rules
Allowed in code:
- enum values
- non-secret feature defaults (timeouts, limits, booleans)
- official public endpoint defaults (for example VIES WSDL URL)

Forbidden in code/docs/examples:
- real passwords, API keys, signing secrets, private keys
- connection strings containing embedded credentials
- copied tenant/customer secrets

## Mandatory Local Keys (`dev`)
Minimum keys that must exist for secure local startup:
- `DATABASE_URL`
- `JWT_SECRET`
- `STORAGE_ACCESS_KEY`
- `STORAGE_SECRET_KEY`
- `STORAGE_GRANT_SECRET`
- `GUARD_BOT_SIGNING_MASTER_SECRET`

If any mandatory key is missing:
- startup/checks must fail closed
- do not silently fallback to insecure defaults

## Git And Leak Prevention
- `.env` must stay ignored by git.
- only `.env.example` can be committed.
- never paste real secrets in markdown docs, runbooks, or logs.
- redact secrets in screenshots or command output.

## Alembic And Runtime Consistency
- API runtime and Alembic must read the same local config source in `dev`.
- local migration commands must work without retyping `DATABASE_URL` each time.
- if `.env` is absent, commands should fail with explicit message, not with implicit insecure fallback.

## Rotation And Operational Hygiene
- rotate local dev secrets periodically.
- rotate stage/prod secrets through secret manager controls.
- immediately rotate any secret that appears in logs, chat, commit history, or artifacts.

## Verification Checklist
Before shipping changes:
1. `git status --short` does not include `.env`.
2. `py -m alembic current` works with expected environment source.
3. `py -m pytest` critical security tests pass.
4. no real secrets appear in changed files.

## Incident Rule
If secret leakage is suspected:
1. stop sharing affected logs/artifacts
2. rotate compromised secrets immediately
3. revoke active tokens if relevant
4. document incident and remediation actions
