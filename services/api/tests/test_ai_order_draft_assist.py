from __future__ import annotations

import app.core.middleware as core_middleware
import app.modules.ai.router as ai_router
import app.modules.licensing.deps as licensing_deps
from app.core.auth import create_access_token
from app.db.session import get_db_session
from app.main import app
from fastapi.testclient import TestClient


class _FakeDB:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def _token(*, tenant_id: str | None, perms: list[str], sub: str = "worker@tenant.local") -> str:
    claims: dict[str, object] = {
        "sub": sub,
        "roles": ["WORKER"],
        "perms": perms,
    }
    if tenant_id is not None:
        claims["tenant_id"] = tenant_id
    return create_access_token(claims)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _allow_entitlement(_db, *, tenant_id: str, module_code: str) -> dict[str, object]:
    return {
        "allowed": True,
        "module_code": module_code,
        "reason": "module_license_active",
        "source": {"license_type": "MODULE_PAID", "license_id": "lic-ai-copilot"},
        "valid_to": "2026-12-31T00:00:00+00:00",
    }


def test_ai_order_draft_assist_route_registered(registered_paths: set[str]) -> None:
    assert "/ai/tenant-copilot/order-draft-assist" in registered_paths


def test_ai_order_draft_assist_structured_response_and_readiness(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)

    payload = {
        "order_draft_input": {
            "order_no": "ORD-AI-001",
            "status": "DRAFT",
            "transport_mode": "ROAD",
            "direction": "OUTBOUND",
            "shipper": {
                "legal_name": "Shipper OOD",
                "address": {
                    "address_line_1": "bul. Tsarigradsko shose 1",
                    "city": "Sofia",
                    "postal_code": "1000",
                    "country_code": "BG",
                },
            },
            "consignee": {
                "legal_name": "TBD",
                "address": {
                    "address_line_1": "",
                    "city": "Plovdiv",
                    "postal_code": "4000",
                    "country_code": "BG",
                },
            },
            "carrier": {
                "legal_name": "Carrier AD",
                "address": {
                    "address_line_1": "ul. Kozloduy 5",
                    "city": "Sofia",
                    "postal_code": "1000",
                    "country_code": "BG",
                },
            },
            "taking_over": {
                "place": "Sofia Terminal",
                "date": "2026-03-12",
            },
            "place_of_delivery": {
                "place": "Plovdiv Terminal",
            },
            "goods": {
                "goods_description": "?",
                "packages_count": 8,
            },
            "reference_no": "REF-AI-001",
            "is_dangerous_goods": True,
            "adr": {
                "adr_class": "3",
            },
        }
    }

    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        r = client.post("/ai/tenant-copilot/order-draft-assist", headers=_headers(token), json=payload)
        assert r.status_code == 200, r.text

        body = r.json() or {}
        expected_keys = {
            "ok",
            "tenant_id",
            "capability",
            "missing_required_fields",
            "ambiguous_fields",
            "cmr_readiness",
            "adr_readiness",
            "suggested_field_values",
            "human_confirmation_required_items",
            "source_traceability",
            "warnings",
            "authoritative_finalize_allowed",
            "no_authoritative_finalize_rule",
            "system_truth_rule",
        }
        assert expected_keys.issubset(set(body.keys()))

        assert body.get("ok") is True
        assert body.get("capability") == "EIDON_ORDER_DRAFT_ASSIST_V1"
        assert body.get("tenant_id") == "tenant-ai-001"

        missing = set(body.get("missing_required_fields") or [])
        assert "consignee.address.address_line_1" in missing
        assert "goods.packing_method" in missing
        assert "goods.gross_weight_kg" in missing

        ambiguous = set(body.get("ambiguous_fields") or [])
        assert "consignee.legal_name" in ambiguous
        assert "goods.goods_description" in ambiguous

        cmr = body.get("cmr_readiness") or {}
        adr = body.get("adr_readiness") or {}
        assert cmr.get("ready") is False
        assert adr.get("applicable") is True
        assert adr.get("ready") is False
        assert "adr.un_number" in set(adr.get("missing_fields") or [])

        assert body.get("authoritative_finalize_allowed") is False
        assert str(body.get("no_authoritative_finalize_rule") or "").strip() != ""

        suggestions = body.get("suggested_field_values") or []
        assert isinstance(suggestions, list)
        assert any((item or {}).get("field_path") == "goods.packing_method" for item in suggestions)

        traces = body.get("source_traceability") or []
        assert isinstance(traces, list)
        assert len(traces) > 0

        confirmations = set(body.get("human_confirmation_required_items") or [])
        assert "order_submission_or_state_transition" in confirmations
        assert "authoritative_business_document_finalize" in confirmations

        assert db.commits == 1
    finally:
        app.dependency_overrides.clear()


def test_ai_order_draft_assist_permission_safe_tenant_scope(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)

    payload = {
        "order_draft_input": {
            "order_no": "ORD-AI-002",
            "status": "DRAFT",
            "transport_mode": "ROAD",
            "direction": "OUTBOUND",
        }
    }

    try:
        client = TestClient(app)

        no_perm_token = _token(tenant_id="tenant-ai-001", perms=[])
        denied = client.post("/ai/tenant-copilot/order-draft-assist", headers=_headers(no_perm_token), json=payload)
        assert denied.status_code == 403, denied.text
        assert str((denied.json() or {}).get("detail") or "").startswith("permission_required:AI.COPILOT")

        no_tenant_token = _token(tenant_id=None, perms=["AI.COPILOT"])
        missing_ctx = client.post("/ai/tenant-copilot/order-draft-assist", headers=_headers(no_tenant_token), json=payload)
        assert missing_ctx.status_code == 403, missing_ctx.text
        assert (missing_ctx.json() or {}).get("detail") == "missing_tenant_context"
    finally:
        app.dependency_overrides.clear()


def test_ai_order_draft_assist_accepts_existing_order_context(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ai_router.order_draft_assist_service,
        "_guard_existing_order_reference",
        lambda **_kwargs: "allow",
    )

    payload = {
        "existing_order_draft_context": {
            "id": "ord-ai-ctx-1",
            "tenant_id": "tenant-ai-001",
            "order_no": "ORD-AI-CTX-001",
            "status": "DRAFT",
            "transport_mode": "ROAD",
            "direction": "OUTBOUND",
            "goods": {
                "goods_description": "General cargo",
                "packages_count": 10,
                "packing_method": "PALLETS",
                "marks_numbers": "MRK-001",
                "gross_weight_kg": 1000.0,
                "volume_m3": 12.5,
            },
            "is_dangerous_goods": False,
        }
    }

    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        r = client.post("/ai/tenant-copilot/order-draft-assist", headers=_headers(token), json=payload)
        assert r.status_code == 200, r.text
        body = r.json() or {}
        assert body.get("ok") is True
        assert body.get("tenant_id") == "tenant-ai-001"
    finally:
        app.dependency_overrides.clear()
