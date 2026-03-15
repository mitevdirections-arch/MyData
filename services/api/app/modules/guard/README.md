# Guard Module

Adaptive heartbeat enforcement with behavior-based intervals, anti-abuse flags, signed bot telemetry, and lockout policy.

## Heartbeat Policy
- `STARTUP` heartbeat on app start.
- `KEEPALIVE` heartbeat while session is running.
- Optional `LOGOUT` heartbeat on exit.
- Base interval: 30 minutes.
- Good behavior multiplier:
  - Day 0-6: `x1`
  - Day 7-13: `x2`
  - Day 14-20: `x3`
  - Day 21+: `x4` (stays capped)
- Any abuse suspicion resets multiplier to `x1` and increments suspicion counter.
- Near license expiry, Guard tightens heartbeat interval with higher priority.

## Bot Credential Security
- Tenant admin issues Guard bot credentials (`bot_id`, `key_version`, signing secret).
- Bot requests can be cryptographically signed with HMAC-SHA256 headers.
- Nonce replay protection is enforced via DB (`guard_bot_nonces`).
- Credential lifecycle: issue / rotate / revoke / unlock.

Headers used when signature mode is enabled:
- `X-Bot-ID`
- `X-Bot-Key-Version`
- `X-Bot-Timestamp`
- `X-Bot-Nonce`
- `X-Bot-Signature`

## Lockout Policy
- Failed bot auth attempts are counted per credential.
- At threshold (`GUARD_BOT_FAILED_SIGNATURE_LIMIT`), credential enters lockout for `GUARD_BOT_LOCKOUT_SECONDS`.
- While locked, signed telemetry returns `423 bot_credential_locked`.
- Lockout auto-creates warning incident (`CRITICAL`, `SECURITY`, source `GUARD`) and audit event.
- Tenant admin can inspect lockouts and unlock credentials after remediation.

## Endpoints
- `POST /guard/heartbeat`
- `POST /guard/license-snapshot`
- `POST /guard/device/lease`
- `GET /guard/heartbeat/policy`
- `GET /guard/tenant-status`
- `GET /guard/admin/bot/credentials`
- `GET /guard/admin/bot/lockouts`
- `POST /guard/admin/bot/credentials/issue`
- `POST /guard/admin/bot/credentials/{bot_id}/rotate`
- `POST /guard/admin/bot/credentials/{bot_id}/revoke`
- `POST /guard/admin/bot/credentials/{bot_id}/unlock`
- `POST /guard/admin/bot/check-once`
- `GET /guard/admin/bot/checks`
- `GET /guard/admin/tenant-verify`
- `GET /guard/admin/audit`
- `GET /guard/admin/audit/verify`

## Bot/Guard Data Scope
Collected from tenant clients:
- `tenant_id` and `user_id` from auth token
- `device_id` provided by client app
- heartbeat `status`, `event`, and security `flags`
- active license snapshot (`active_license_codes`) from tenant bot/app
- lease metadata (`device_class`, timestamps)

Explicitly NOT collected:
- GPS / geo-location / IP-location for tracking
- MAC/serial/CPU/RAM/disk hardware fingerprint data
- customer files or file contents from tenant machines
- network scans of tenant infrastructure

License snapshot verification:
- Tenant bot sends active license codes in use.
- Guard compares them with active issued licenses in platform DB.
- Unknown/fake codes or missing core in client snapshot trigger security flag and audit trail.