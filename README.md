# MyData ERP Platform

Security-first multi-tenant SaaS ERP backend for logistics, transport, warehousing, manufacturing, and trade.

## Principles
- Tenant isolation first.
- Core license required for all business actions.
- Startup license unlocks all modules for 30 days (non-renewable).
- App-in-app module architecture with explicit contracts.
- Auditability and deterministic operations.

## Repository Layout
- `services/api` - FastAPI backend.
- `docs` - architecture, security, roadmap, AI design.
- `scripts` - local run helpers.

## Quick Start
1. Create venv and install deps.
2. Set environment variables in `.env`.
3. Run `uvicorn app.main:app --reload --port 8100` from `services/api`.

## Non-goals (phase 0)
- No direct integration with external payment providers.
- No production secrets in repo.
