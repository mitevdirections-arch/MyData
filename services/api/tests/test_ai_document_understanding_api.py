from __future__ import annotations

import app.core.middleware as core_middleware
import app.modules.ai.order_document_intake_service as intake_service_mod
import app.modules.ai.router as ai_router
import app.modules.licensing.deps as licensing_deps
from app.core.auth import create_access_token
from app.core.policy_matrix import ROUTE_POLICY
from app.core.route_ownership import ROUTE_PLANE_OPERATIONAL, resolve_route_plane
from app.db.session import get_db_session
from app.main import app
from app.modules.ai.tenant_action_boundary_guard import AI_ACTION_BOUNDARY_VIOLATION
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


def _payload() -> dict[str, object]:
    return {
        "extracted_text": """
Order No: ORD-DOC-CANON-001
Shipper: Shipper OOD
Consignee: Consignee OOD
Carrier: Carrier AD
Taking Over Place: Sofia
Taking Over Date: 2026-03-15
Delivery Place: Plovdiv
Goods: Paint
Packages: 10
Packing: PALLETS
Marks: MK-100
Gross Weight Kg: 1000
Volume M3: 8
""",
        "document_metadata": {
            "document_type": "CMR",
            "source_channel": "EMAIL",
            "locale": "bg",
        },
        "field_hints": {
            "direction": "OUTBOUND",
            "transport_mode": "ROAD",
            "shipper.address.address_line_1": "line 1",
            "shipper.address.city": "Sofia",
            "shipper.address.postal_code": "1000",
            "shipper.address.country_code": "BG",
            "consignee.address.address_line_1": "line 2",
            "consignee.address.city": "Plovdiv",
            "consignee.address.postal_code": "4000",
            "consignee.address.country_code": "BG",
            "carrier.address.address_line_1": "line 3",
            "carrier.address.city": "Sofia",
            "carrier.address.postal_code": "1000",
            "carrier.address.country_code": "BG",
        },
    }


def test_document_understanding_route_openapi_policy_and_ownership_contract(registered_paths: set[str]) -> None:
    assert "/ai/tenant-copilot/document-understanding" in registered_paths
    assert "/ai/tenant-copilot/order-document-intake" in registered_paths

    schema = app.openapi()
    route = ((schema.get("paths") or {}).get("/ai/tenant-copilot/document-understanding") or {}).get("post") or {}
    req_ref = (
        ((((route.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref")
        or ""
    )
    res_ref = (
        (((((route.get("responses") or {}).get("200") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref")
        or ""
    )
    assert req_ref.endswith("/EidonOrderDocumentIntakeRequestDTO")
    assert res_ref.endswith("/EidonOrderDocumentIntakeResponseDTO")

    assert ("POST", "/ai/tenant-copilot/document-understanding") in ROUTE_POLICY
    assert resolve_route_plane("POST", "/ai/tenant-copilot/document-understanding") == ROUTE_PLANE_OPERATIONAL


def test_document_understanding_happy_path_no_raw_and_advisory_only(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)

    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        r = client.post("/ai/tenant-copilot/document-understanding", headers=_headers(token), json=_payload())
        assert r.status_code == 200, r.text
        body = r.json() or {}
        assert body.get("ok") is True
        assert body.get("capability") == "EIDON_ORDER_DOCUMENT_INTAKE_V1"
        assert body.get("authoritative_finalize_allowed") is False
        assert len(body.get("human_confirmation_required_items") or []) >= 1
        tl = body.get("template_learning_candidate") or {}
        assert tl.get("raw_tenant_document_included") is False

        assert "extracted_text" not in body
        assert "document_metadata" not in body
        dumped = str(body).lower()
        assert "raw_document_blob" not in dumped
        assert "raw_document_payload" not in dumped
        assert db.commits == 1
    finally:
        app.dependency_overrides.clear()


def test_document_understanding_missing_tenant_context_fail_closed(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)

    try:
        client = TestClient(app)
        token = _token(tenant_id=None, perms=["AI.COPILOT"])
        r = client.post("/ai/tenant-copilot/document-understanding", headers=_headers(token), json=_payload())
        assert r.status_code == 403, r.text
        assert (r.json() or {}).get("detail") == "missing_tenant_context"
    finally:
        app.dependency_overrides.clear()


def test_document_understanding_action_boundary_violation_fail_closed(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        intake_service_mod.tenant_action_boundary_guard,
        "enforce_advisory_only",
        lambda _out: (_ for _ in ()).throw(ValueError(AI_ACTION_BOUNDARY_VIOLATION)),
    )

    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        r = client.post("/ai/tenant-copilot/document-understanding", headers=_headers(token), json={"extracted_text": "Shipper: A"})
        assert r.status_code == 400, r.text
        assert (r.json() or {}).get("detail") == AI_ACTION_BOUNDARY_VIOLATION
    finally:
        app.dependency_overrides.clear()


def test_order_document_intake_compatibility_path_still_works(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)

    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        r_old = client.post("/ai/tenant-copilot/order-document-intake", headers=_headers(token), json=_payload())
        r_new = client.post("/ai/tenant-copilot/document-understanding", headers=_headers(token), json=_payload())
        assert r_old.status_code == 200, r_old.text
        assert r_new.status_code == 200, r_new.text
        body_old = r_old.json() or {}
        body_new = r_new.json() or {}
        assert body_old.get("capability") == "EIDON_ORDER_DOCUMENT_INTAKE_V1"
        assert body_new.get("capability") == "EIDON_ORDER_DOCUMENT_INTAKE_V1"
        assert body_old.get("authoritative_finalize_allowed") is False
        assert body_new.get("authoritative_finalize_allowed") is False
    finally:
        app.dependency_overrides.clear()

