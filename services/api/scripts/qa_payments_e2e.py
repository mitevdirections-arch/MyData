from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any
import urllib.error
import urllib.request


def _j(method: str, url: str, *, headers: dict[str, str] | None = None, payload: dict[str, Any] | None = None, timeout: float = 15.0) -> dict[str, Any]:
    data = None
    req_headers = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url=url, method=method.upper(), data=data)
    for k, v in req_headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        body = resp.read().decode("utf-8")
        return json.loads(body) if body.strip() else {}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _dev_token(base: str, *, sub: str, roles: list[str], tenant_id: str) -> str:
    out = _j("POST", f"{base}/auth/dev-token", payload={"sub": sub, "roles": roles, "tenant_id": tenant_id})
    tok = str(out.get("access_token") or "").strip()
    if not tok:
        raise RuntimeError("dev_token_missing")
    return tok


def _pick_not_entitled(items: list[dict[str, Any]]) -> str | None:
    for item in items:
        ent = item.get("entitlement") if isinstance(item, dict) else None
        allowed = bool((ent or {}).get("allowed")) if isinstance(ent, dict) else False
        if not allowed:
            code = str(item.get("module_code") or "").strip().upper()
            if code:
                return code
    return None


def _seed_workspace_profile(base: str, headers: dict[str, str], *, workspace: str | None, legal_name: str, vat: str, city: str) -> None:
    payload = {
        "legal": {
            "legal_name": legal_name,
            "vat_number": vat,
            "registration_number": "REG-001",
            "company_size_hint": "SMB",
            "industry": "TRANSPORT",
        },
        "contacts": {
            "email": "billing@example.local",
            "phone": "+359888000111",
            "website_url": "https://example.local",
        },
        "address": {
            "country_code": "BG",
            "line1": "bul. Tsarigradsko shose 1",
            "line2": "",
            "city": city,
            "postal_code": "1000",
        },
        "banking": {
            "account_holder": legal_name,
            "iban": "BG80BNBG96611020345678",
            "swift": "BNBGBGSD",
            "bank_name": "BNB",
            "currency": "BGN",
        },
    }
    suffix = "?workspace=platform" if workspace == "platform" else ""
    _j("PUT", f"{base}/profile/workspace{suffix}", headers=headers, payload=payload)


def run_flow(*, api_base: str, tenant_id: str) -> dict[str, Any]:
    base = str(api_base).rstrip("/")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    qa_tenant = f"{tenant_id}-{run_id}"
    steps: list[dict[str, Any]] = []

    try:
        super_token = _dev_token(base, sub="superadmin@ops.local", roles=["SUPERADMIN"], tenant_id="platform")
        super_h = _bearer(super_token)

        _j("POST", f"{base}/admin/tenants/bootstrap-demo", headers=super_h, payload={"tenant_id": qa_tenant, "name": f"QA {qa_tenant}", "vat_number": "BG987654321"})
        steps.append({"step": "bootstrap_tenant", "ok": True, "tenant_id": qa_tenant})

        _seed_workspace_profile(base, super_h, workspace="platform", legal_name="MyData Platform AD", vat="BG123456789", city="Sofia")
        steps.append({"step": "seed_platform_profile", "ok": True})

        core = _j("POST", f"{base}/licenses/admin/issue-core", headers=super_h, payload={"tenant_id": qa_tenant, "plan_code": "CORE8", "valid_days": 30})
        steps.append({"step": "issue_core", "ok": True, "license": core.get("license")})

        _j("PUT", f"{base}/licenses/admin/issuance-policy", headers=super_h, payload={"tenant_id": qa_tenant, "mode": "AUTO"})
        steps.append({"step": "issuance_policy_auto", "ok": True})

        _j(
            "PUT",
            f"{base}/superadmin/payments/credit-accounts/{qa_tenant}",
            headers=super_h,
            payload={
                "payment_mode": "DEFERRED",
                "status": "ACTIVE",
                "credit_limit_minor": 200000,
                "currency": "EUR",
                "terms_days": 30,
                "grace_days": 3,
                "auto_hold_on_overdue": True,
            },
        )
        steps.append({"step": "credit_account_deferred", "ok": True})

        tenant_token = _dev_token(base, sub="admin@tenant.local", roles=["TENANT_ADMIN"], tenant_id=qa_tenant)
        tenant_h = _bearer(tenant_token)

        _seed_workspace_profile(base, tenant_h, workspace=None, legal_name=f"Tenant {qa_tenant} OOD", vat="BG555666777", city="Plovdiv")
        steps.append({"step": "seed_tenant_profile", "ok": True})

        _j(
            "PUT",
            f"{base}/admin/payments/invoice-template",
            headers=tenant_h,
            payload={
                "template_code": "BG_VAT_V1",
                "numbering_mode": "BG_NUMERIC10",
                "vat_mode": "STANDARD",
                "vat_rate_percent": 20,
                "enforcement_mode": "STRICT",
                "country_code": "BG",
            },
        )
        steps.append({"step": "invoice_template_bg_strict", "ok": True})

        cat = _j("GET", f"{base}/marketplace/catalog", headers=tenant_h)
        target = _pick_not_entitled(list(cat.get("items") or [])) if isinstance(cat, dict) else None
        if not target:
            raise RuntimeError("no_non_entitled_module_available")

        buy = _j(
            "POST",
            f"{base}/marketplace/purchase-requests",
            headers=tenant_h,
            payload={"module_code": target, "valid_days": 30, "note": "qa payments e2e"},
        )
        if str(buy.get("flow") or "").upper() != "ISSUED":
            raise RuntimeError(f"unexpected_purchase_flow:{buy.get('flow')}")

        invoice = (buy.get("payment") or {}).get("invoice") or {}
        invoice_id = str(invoice.get("id") or "").strip()
        if not invoice_id:
            raise RuntimeError("invoice_id_missing")

        doc = _j("GET", f"{base}/superadmin/payments/invoices/{invoice_id}/document", headers=super_h)
        compliance = (((doc.get("document") or {}).get("compliance") or {}) if isinstance(doc, dict) else {})
        template_code = (((doc.get("document") or {}).get("template") or {}).get("template_code"))
        if not (bool(compliance.get("valid")) and str(template_code or "").upper() == "BG_VAT_V1"):
            raise RuntimeError("invoice_compliance_or_template_invalid")

        steps.append(
            {
                "step": "invoice_document_compliance",
                "ok": True,
                "invoice_id": invoice_id,
                "template_code": template_code,
                "compliance": compliance,
            }
        )

        paid = _j("POST", f"{base}/superadmin/payments/invoices/{invoice_id}/mark-paid", headers=super_h, payload={"method": "BANK", "reference": f"QA-{run_id}"})
        steps.append({"step": "mark_paid", "ok": bool((paid.get("invoice") or {}).get("status") == "PAID")})

        overdue = _j("POST", f"{base}/superadmin/payments/overdue/run-once?limit=200", headers=super_h)
        steps.append({"step": "overdue_run_once", "ok": bool((overdue.get("result") or {}).get("ok", True)), "result": overdue.get("result")})

        return {"ok": True, "tenant_id": qa_tenant, "steps": steps}
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8")
        except Exception:  # noqa: BLE001
            body = ""
        return {
            "ok": False,
            "tenant_id": qa_tenant,
            "steps": steps,
            "error": {"type": "http", "status": int(getattr(exc, "code", 0) or 0), "body": body[:1000]},
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "tenant_id": qa_tenant, "steps": steps, "error": {"type": "runtime", "detail": str(exc)}}


def main() -> int:
    parser = argparse.ArgumentParser(description="Payments E2E: core -> deferred purchase -> strict invoice -> paid")
    parser.add_argument("--api-base", default="http://127.0.0.1:8100", help="API base URL")
    parser.add_argument("--tenant-id", default="tenant-pay-e2e", help="Tenant id prefix for run")
    parser.add_argument("--strict", action="store_true", help="Exit 1 on failure")
    args = parser.parse_args()

    out = run_flow(api_base=str(args.api_base), tenant_id=str(args.tenant_id))
    print(json.dumps(out, ensure_ascii=False))
    if bool(args.strict) and not bool(out.get("ok")):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
