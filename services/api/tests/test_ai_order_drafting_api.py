from __future__ import annotations

import app.core.middleware as core_middleware
import app.modules.ai.router as ai_router
import app.modules.ai.tenant_retrieval_action_guard as guard_mod
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


def _draft_payload() -> dict[str, object]:
    return {
        "order_draft_input": {
            "order_no": "ORD-DRFT-001",
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
                "legal_name": "Consignee OOD",
                "address": {
                    "address_line_1": "ul. Vitosha 10",
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
                "date": "2026-03-15",
            },
            "place_of_delivery": {
                "place": "Plovdiv Terminal",
            },
            "goods": {
                "goods_description": "General cargo",
                "packages_count": 8,
            },
            "reference_no": "REF-DRFT-001",
            "is_dangerous_goods": False,
        }
    }


def test_order_drafting_route_openapi_policy_and_ownership_contract(registered_paths: set[str]) -> None:
    assert "/ai/tenant-copilot/order-drafting" in registered_paths
    assert "/ai/tenant-copilot/order-draft-assist" in registered_paths

    schema = app.openapi()
    route = ((schema.get("paths") or {}).get("/ai/tenant-copilot/order-drafting") or {}).get("post") or {}
    req_ref = (
        ((((route.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref")
        or ""
    )
    res_ref = (
        (((((route.get("responses") or {}).get("200") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref")
        or ""
    )
    assert req_ref.endswith("/EidonOrderDraftAssistRequestDTO")
    assert res_ref.endswith("/EidonOrderDraftAssistResponseDTO")

    assert ("POST", "/ai/tenant-copilot/order-drafting") in ROUTE_POLICY
    assert resolve_route_plane("POST", "/ai/tenant-copilot/order-drafting") == ROUTE_PLANE_OPERATIONAL


def test_order_drafting_happy_path_authoritative_false_and_no_raw_dump(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)

    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        r = client.post("/ai/tenant-copilot/order-drafting", headers=_headers(token), json=_draft_payload())
        assert r.status_code == 200, r.text
        body = r.json() or {}
        assert body.get("ok") is True
        assert body.get("capability") == "EIDON_ORDER_DRAFT_ASSIST_V1"
        assert body.get("authoritative_finalize_allowed") is False
        assert len(body.get("human_confirmation_required_items") or []) >= 1
        dumped = str(body).lower()
        assert "source_traceability payload" not in dumped
        assert "extracted_text" not in dumped
        assert db.commits == 1
    finally:
        app.dependency_overrides.clear()


def test_order_drafting_missing_tenant_context_fail_closed(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)

    try:
        client = TestClient(app)
        token = _token(tenant_id=None, perms=["AI.COPILOT"])
        r = client.post("/ai/tenant-copilot/order-drafting", headers=_headers(token), json=_draft_payload())
        assert r.status_code == 403, r.text
        assert (r.json() or {}).get("detail") == "missing_tenant_context"
    finally:
        app.dependency_overrides.clear()


def test_order_drafting_action_boundary_violation_fail_closed(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ai_router.order_draft_assist_service,
        "assist",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError(AI_ACTION_BOUNDARY_VIOLATION)),
    )

    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        r = client.post("/ai/tenant-copilot/order-drafting", headers=_headers(token), json=_draft_payload())
        assert r.status_code == 400, r.text
        assert (r.json() or {}).get("detail") == AI_ACTION_BOUNDARY_VIOLATION
    finally:
        app.dependency_overrides.clear()


def test_order_drafting_hidden_object_safe_deny_missing_vs_inaccessible(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ai_router.order_draft_assist_service,
        "assist",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError(guard_mod.OBJECT_REFERENCE_NOT_ACCESSIBLE)),
    )

    payload_missing = {
        "existing_order_draft_context": {
            "id": "",
            "order_no": "ORD-MISS-001",
            "status": "DRAFT",
            "transport_mode": "ROAD",
            "direction": "OUTBOUND",
        }
    }
    payload_inaccessible = {
        "existing_order_draft_context": {
            "id": "ord-hidden-001",
            "order_no": "ORD-HIDDEN-001",
            "status": "DRAFT",
            "transport_mode": "ROAD",
            "direction": "OUTBOUND",
        }
    }
    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        r_missing = client.post("/ai/tenant-copilot/order-drafting", headers=_headers(token), json=payload_missing)
        r_inaccessible = client.post("/ai/tenant-copilot/order-drafting", headers=_headers(token), json=payload_inaccessible)
        assert r_missing.status_code == 403, r_missing.text
        assert r_inaccessible.status_code == 403, r_inaccessible.text
        assert (r_missing.json() or {}).get("detail") == guard_mod.OBJECT_REFERENCE_NOT_ACCESSIBLE
        assert (r_inaccessible.json() or {}).get("detail") == guard_mod.OBJECT_REFERENCE_NOT_ACCESSIBLE
        assert "ord-hidden-001" not in str((r_inaccessible.json() or {}).get("detail") or "")
    finally:
        app.dependency_overrides.clear()


def test_order_drafting_compatibility_path_still_works(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)

    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        r_old = client.post("/ai/tenant-copilot/order-draft-assist", headers=_headers(token), json=_draft_payload())
        r_new = client.post("/ai/tenant-copilot/order-drafting", headers=_headers(token), json=_draft_payload())
        assert r_old.status_code == 200, r_old.text
        assert r_new.status_code == 200, r_new.text
        body_old = r_old.json() or {}
        body_new = r_new.json() or {}
        assert body_old.get("authoritative_finalize_allowed") is False
        assert body_new.get("authoritative_finalize_allowed") is False
    finally:
        app.dependency_overrides.clear()

