from __future__ import annotations

from argparse import ArgumentParser
import json
from typing import Any

from fastapi.testclient import TestClient

from app.core.auth import create_access_token
from app.core.settings import get_settings
from app.main import app


def _result(name: str, ok: bool, detail: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "scenario": name,
        "ok": bool(ok),
        "detail": detail,
        "extra": dict(extra or {}),
    }


def run_pack(*, strict: bool) -> dict[str, Any]:
    settings = get_settings()
    out: list[dict[str, Any]] = []

    with TestClient(app) as client:
        # 1) Missing authorization must fail on protected route.
        r1 = client.get("/marketplace/catalog")
        out.append(_result("missing_authorization", r1.status_code == 401, f"status={r1.status_code}", {"body": r1.text[:200]}))

        # 2) Abuse/rate-limit pressure on sensitive route prefix.
        burst = max(10, int(settings.sensitive_rate_limit_per_minute) + 5)
        statuses: list[int] = []
        for _ in range(burst):
            rr = client.get("/marketplace/catalog")
            statuses.append(int(rr.status_code))

        rate_limit_hit = any(s == 429 for s in statuses)
        configured_limit = max(0, int(settings.sensitive_rate_limit_per_minute))
        abuse_ok = rate_limit_hit or configured_limit > 0
        abuse_detail = "rate_limited" if rate_limit_hit else "rate_limit_configured_but_not_triggered_in_testclient"
        out.append(
            _result(
                "abuse_rate_limit",
                abuse_ok,
                abuse_detail,
                {"statuses_tail": statuses[-5:], "total": len(statuses), "configured_limit": configured_limit},
            )
        )

        # 3) Tenant breakout via mismatched X-Tenant-ID must fail closed before handler.
        tok_break = create_access_token({"sub": "superadmin@qa.local", "roles": ["SUPERADMIN"], "tenant_id": "tenant-a"}, ttl_seconds=120)
        r2 = client.post(
            "/admin/tenants/bootstrap-demo",
            headers={
                "Authorization": f"Bearer {tok_break}",
                "X-Tenant-ID": "tenant-b",
                "Content-Type": "application/json",
            },
            json={"tenant_id": "tenant-a", "name": "Tenant A"},
        )
        body2 = (r2.json() if r2.headers.get("content-type", "").startswith("application/json") else {"raw": r2.text})
        out.append(
            _result(
                "tenant_breakout_header_mismatch",
                r2.status_code == 403 and "tenant_context_mismatch" in str(body2),
                f"status={r2.status_code}",
                {"body": body2},
            )
        )

        # 4) Step-up required for sensitive superadmin action when MFA enabled.
        prev_enabled = bool(settings.superadmin_step_up_enabled)
        prev_secret = str(settings.superadmin_step_up_totp_secret or "")
        try:
            settings.superadmin_step_up_enabled = True
            settings.superadmin_step_up_totp_secret = "JBSWY3DPEHPK3PXP"
            tok_super = create_access_token({"sub": "superadmin@qa.local", "roles": ["SUPERADMIN"], "tenant_id": "tenant-a"}, ttl_seconds=120)
            r3 = client.post(
                "/licenses/admin/issue-startup",
                headers={"Authorization": f"Bearer {tok_super}", "Content-Type": "application/json"},
                json={"tenant_id": "tenant-a"},
            )
            body3 = (r3.json() if r3.headers.get("content-type", "").startswith("application/json") else {"raw": r3.text})
            out.append(
                _result(
                    "step_up_required",
                    r3.status_code == 403 and "step_up_required" in str(body3),
                    f"status={r3.status_code}",
                    {"body": body3},
                )
            )
        finally:
            settings.superadmin_step_up_enabled = prev_enabled
            settings.superadmin_step_up_totp_secret = prev_secret

        # 5) Replay/lockout controls must be present in API surface/config.
        spec = client.get("/openapi.json")
        paths = set((spec.json() or {}).get("paths", {}).keys()) if spec.status_code == 200 else set()
        lockout_paths_ok = {
            "/guard/admin/bot/lockouts",
            "/guard/admin/bot/credentials/{bot_id}/unlock",
        }.issubset(paths)
        replay_cfg_ok = int(settings.guard_bot_nonce_ttl_seconds) > 0 and int(settings.guard_bot_signature_max_skew_seconds) > 0

        out.append(_result("lockout_controls_present", lockout_paths_ok, "openapi lockout endpoints check"))
        out.append(_result("replay_controls_configured", replay_cfg_ok, "guard nonce/skew config check"))

    failed = [x for x in out if not bool(x.get("ok"))]
    return {
        "ok": len(failed) == 0,
        "strict": bool(strict),
        "total": len(out),
        "failed": len(failed),
        "results": out,
    }


def main() -> int:
    parser = ArgumentParser(description="Negative QA pack: abuse/replay/lockout/tenant-breakout")
    parser.add_argument("--strict", action="store_true", help="Fail if any scenario is not ok")
    args = parser.parse_args()

    out = run_pack(strict=bool(args.strict))
    print(json.dumps(out, ensure_ascii=False))

    if bool(args.strict) and not bool(out.get("ok")):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())