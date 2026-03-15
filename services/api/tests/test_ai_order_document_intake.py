from __future__ import annotations

import app.core.middleware as core_middleware
import app.modules.ai.order_document_intake_service as intake_service_mod
import app.modules.ai.router as ai_router
import app.modules.licensing.deps as licensing_deps
from app.core.auth import create_access_token
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


def test_ai_order_document_intake_route_and_openapi_contract(registered_paths: set[str]) -> None:
    assert "/ai/tenant-copilot/order-document-intake" in registered_paths

    schema = app.openapi()
    route = ((schema.get("paths") or {}).get("/ai/tenant-copilot/order-document-intake") or {}).get("post") or {}

    req_ref = ((((route.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref") or ""
    res_ref = (((((route.get("responses") or {}).get("200") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref") or ""

    assert req_ref.endswith("/EidonOrderDocumentIntakeRequestDTO")
    assert res_ref.endswith("/EidonOrderDocumentIntakeResponseDTO")

    components = ((schema.get("components") or {}).get("schemas") or {})
    assert "EidonOrderDocumentIntakeRequestDTO" in components
    assert "EidonOrderDocumentIntakeResponseDTO" in components
    assert "EidonTemplateLearningCandidateDTO" in components


def test_ai_order_document_intake_extraction_to_structured_draft(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)

    payload = {
        "extracted_text": """
Order No: ORD-DOC-001
Shipper: Shipper OOD
Consignee: Consignee OOD
Carrier: Carrier AD
Taking Over Place: Sofia Terminal
Taking Over Date: 2026-03-12
Delivery Place: Plovdiv Terminal
Goods: Paint
Packages: 12
Packing: PALLETS
Marks: MK-001
Gross Weight Kg: 1200.5
Volume M3: 10.2
Dangerous Goods: YES
UN Number: UN1263
ADR Class: 3
Packing Group: II
Proper Shipping Name: PAINT
""",
        "document_metadata": {
            "document_type": "CMR",
            "document_id": "doc-001",
            "source_channel": "EMAIL",
            "locale": "bg",
            "file_name": "cmr-doc-001.txt",
        },
        "field_hints": {
            "shipper.address.address_line_1": "bul. Tsarigradsko shose 1",
            "shipper.address.city": "Sofia",
            "shipper.address.postal_code": "1000",
            "shipper.address.country_code": "BG",
            "consignee.address.address_line_1": "ul. Vitosha 10",
            "consignee.address.city": "Plovdiv",
            "consignee.address.postal_code": "4000",
            "consignee.address.country_code": "BG",
            "carrier.address.address_line_1": "ul. Kozloduy 5",
            "carrier.address.city": "Sofia",
            "carrier.address.postal_code": "1000",
            "carrier.address.country_code": "BG",
            "direction": "OUTBOUND",
            "transport_mode": "ROAD",
        },
    }

    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        r = client.post("/ai/tenant-copilot/order-document-intake", headers=_headers(token), json=payload)
        assert r.status_code == 200, r.text

        body = r.json() or {}
        assert body.get("ok") is True
        assert body.get("capability") == "EIDON_ORDER_DOCUMENT_INTAKE_V1"

        draft = body.get("draft_order_candidate") or {}
        assert draft.get("order_no") == "ORD-DOC-001"
        assert ((draft.get("goods") or {}).get("packages_count")) == 12
        assert ((draft.get("goods") or {}).get("gross_weight_kg")) == 1200.5
        assert draft.get("is_dangerous_goods") is True
        assert ((draft.get("adr") or {}).get("un_number")) == "UN1263"

        assert (body.get("cmr_readiness") or {}).get("ready") is True
        assert (body.get("adr_readiness") or {}).get("ready") is True

        extracted = body.get("extracted_fields") or []
        assert len(extracted) >= 8

        assert str(body.get("template_fingerprint") or "").strip() != ""
        tl = body.get("template_learning_candidate") or {}
        assert tl.get("template_fingerprint") == body.get("template_fingerprint")
        assert tl.get("raw_tenant_document_included") is False

        assert body.get("authoritative_finalize_allowed") is False
        assert str(body.get("no_authoritative_finalize_rule") or "").strip() != ""
        assert "extracted_text" not in body
        assert "document_metadata" not in body
        assert "layout_hints" not in body
        assert "field_hints" not in body
        dumped = str(body).lower()
        assert "raw_document_blob" not in dumped
        assert "raw_document_payload" not in dumped

        assert db.commits == 1
    finally:
        app.dependency_overrides.clear()


def test_ai_order_document_intake_ambiguity_and_missing_handling(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)

    payload = {
        "extracted_text": """
Shipper: Shipper OOD
Consignee: Consignee OOD
Carrier: Carrier AD
Goods: TBD
Packages: 5
Dangerous Goods: YES
""",
        "field_hints": {
            "carrier.legal_name": "Carrier OOD",
        },
    }

    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        r = client.post("/ai/tenant-copilot/order-document-intake", headers=_headers(token), json=payload)
        assert r.status_code == 200, r.text

        body = r.json() or {}
        ambiguous = set(body.get("ambiguous_fields") or [])
        assert "carrier.legal_name" in ambiguous
        assert "goods.goods_description" in ambiguous

        missing = set(body.get("missing_required_fields") or [])
        assert "goods.packing_method" in missing
        assert "goods.marks_numbers" in missing

        adr = body.get("adr_readiness") or {}
        assert adr.get("applicable") is True
        assert adr.get("ready") is False
        assert "adr.un_number" in set(adr.get("missing_fields") or [])
    finally:
        app.dependency_overrides.clear()


def test_ai_order_document_intake_action_boundary_violation_fail_closed(monkeypatch) -> None:
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

    payload = {
        "extracted_text": "Shipper: A",
    }

    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        denied = client.post("/ai/tenant-copilot/order-document-intake", headers=_headers(token), json=payload)
        assert denied.status_code == 400, denied.text
        assert (denied.json() or {}).get("detail") == AI_ACTION_BOUNDARY_VIOLATION
    finally:
        app.dependency_overrides.clear()


def test_ai_order_document_intake_tenant_safe_behavior(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)

    payload = {
        "extracted_text": "Shipper: A",
    }

    try:
        client = TestClient(app)

        no_perm_token = _token(tenant_id="tenant-ai-001", perms=[])
        denied = client.post("/ai/tenant-copilot/order-document-intake", headers=_headers(no_perm_token), json=payload)
        assert denied.status_code == 403, denied.text
        assert str((denied.json() or {}).get("detail") or "").startswith("permission_required:AI.COPILOT")

        no_tenant_token = _token(tenant_id=None, perms=["AI.COPILOT"])
        missing_ctx = client.post("/ai/tenant-copilot/order-document-intake", headers=_headers(no_tenant_token), json=payload)
        assert missing_ctx.status_code == 403, missing_ctx.text
        assert (missing_ctx.json() or {}).get("detail") == "missing_tenant_context"
    finally:
        app.dependency_overrides.clear()
