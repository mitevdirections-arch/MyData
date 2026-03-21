# Device Policy v1 Backend Handover

## What Changed
- Added persistence-backed device state model on top of `device_leases`.
- Implemented centralized guard service transitions for claim/activate/demote/logout/revoke.
- Added request-time lazy auto-logout for paused desktop devices older than 30 minutes.
- Added protected business-path enforcement that requires `X-Device-ID` and ACTIVE device state.
- Corrected seat usage counting to `DISTINCT user_id` under ACTIVE-only semantics.
- Added minimal guard endpoints for device status, activate/resume, and logout.

## State Model
- `ACTIVE`
- `PAUSED`
- `BACKGROUND_REACHABLE`
- `LOGGED_OUT`
- `REVOKED`

Policy behavior:
- Desktop claim activates desktop and demotes mobile to `BACKGROUND_REACHABLE`.
- Mobile claim activates mobile and demotes desktop to `PAUSED`.
- Paused desktop auto-logs out after timeout (lazy check on request-time).
- Manual logout never auto-activates peer device.

## Enforcement
Active-only business enforcement is applied in policy layer for operational/business prefixes:
- `/orders`
- `/partners`
- `/support/tenant`
- `/ai/tenant-copilot`

Machine-readable deny codes:
- `DEVICE_CONTEXT_REQUIRED` when `X-Device-ID` is missing.
- `DEVICE_NOT_ACTIVE` when lease is missing/non-active.
- `DEVICE_REVOKED` when device is revoked.
- `DEVICE_LOGGED_OUT` when device is logged out.

Non-active safe control flow endpoints remain allowed:
- `/guard/heartbeat`
- `/guard/heartbeat/policy`
- `/guard/device/lease`
- `/guard/device/lease/me`
- `/guard/device/status`
- `/guard/device/activate`
- `/guard/device/logout`
- `/guard/tenant-status`

## Migration
- Added revision: `0035_device_policy_v1`
- Changes:
  - `device_leases` unique key moved from `(tenant_id, user_id)` to `(tenant_id, user_id, device_class)`.
  - Added state/timing fields (`state`, `state_changed_at`, `last_live_at`, `paused_at`, `background_reachable_at`, `logged_out_at`, `revoked_at`).
  - Added indexes for hot-path lookups:
    - `ix_device_lease_tenant_user_state`
    - `ix_device_lease_tenant_device`

## Notes
- This pass keeps seat logic and device logic separated.
- No EIDON/UI changes were made.
- No background worker was added; timeout is lazy and request-time checked.

## Phase 1.1 Hardening
- Added migration `0036_device_policy_v1_hardening` to tighten runtime/DB guarantees.
- Added hard invariant at DB level:
  - `state == ACTIVE` iff `is_active = true`
  - all non-ACTIVE states require `is_active = false`
- Added DB-level one-active guard:
  - partial unique index `uq_device_lease_one_active_user` on `(tenant_id, user_id)` where `state='ACTIVE'`.
- Added migration-time legacy normalization:
  - invalid/empty states normalized deterministically.
  - multiple ACTIVE rows per user are normalized to a single winner; peers are demoted safely.
- Added runtime hardening in guard lease service:
  - per-user row normalization before transitions/read checks.
  - conflict-safe commit path returning `DEVICE_STATE_CONFLICT_RETRY` on DB uniqueness race.
- Added guardrail tests:
  - DB-backed parallel activate race ensures final persisted single ACTIVE.
  - policy drift tests ensure operational routes remain inside device-enforced scope.
