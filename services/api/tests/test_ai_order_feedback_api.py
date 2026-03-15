from __future__ import annotations

import app.core.middleware as core_middleware
import app.modules.ai.order_intake_feedback_service as feedback_service_mod
import app.modules.ai.router as ai_router
import app.modules.ai.tenant_retrieval_action_guard as guard_mod
import app.modules.licensing.deps as licensing_deps
from app.core.auth import create_access_token
from app.core.policy_matrix import ROUTE_POLICY
from app.core.route_ownership import ROUTE_PLANE_OPERATIONAL, resolve_route_plane
from app.db import models
from app.db.session import get_db_session
from app.main import app
from app.modules.ai.tenant_action_boundary_guard import AI_ACTION_BOUNDARY_VIOLATION
from fastapi.testclient import TestClient


class _FakeDB:
    def __init__(self) -> None:
        self.commits = 0
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        return None

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


def _payload(*, order_id: str | None = None) -> dict[str, object]:
    candidate: dict[str, object] = {
        "order_no": "ORD-FB-API-001",
        "transport_mode": "ROAD",
        "direction": "OUTBOUND",
        "shipper": {"legal_name": "Shipper OOD"},
        "carrier": {"legal_name": "Carrier AD"},
        "goods": {
            "goods_description": "Paint",
            "packages_count": 12,
            "gross_weight_kg": 1200.5,
        },
        "is_dangerous_goods": False,
    }
    if order_id is not None:
        candidate["payload"] = {"order_id": order_id}
    return {
        "original_template_fingerprint": "tpl-fb-api-001",
        "proposed_draft_order_candidate": candidate,
        "user_confirmed_fields": ["shipper.legal_name"],
        "user_corrected_fields": {"goods.packages_count": 14},
        "unresolved_fields": [],
        "confirmation_metadata": {
            "confirmation_channel": "UI_REVIEW",
            "confirmed_by": "dispatcher@tenant.local",
            "confirmed_at": "2026-03-15T10:00:00+00:00",
        },
    }


def test_order_feedback_route_openapi_policy_and_ownership_contract(registered_paths: set[str]) -> None:
    assert "/ai/tenant-copilot/order-feedback" in registered_paths
    assert "/ai/tenant-copilot/order-intake-feedback" in registered_paths

    schema = app.openapi()
    route = ((schema.get("paths") or {}).get("/ai/tenant-copilot/order-feedback") or {}).get("post") or {}
    req_ref = (
        ((((route.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref")
        or ""
    )
    res_ref = (
        (((((route.get("responses") or {}).get("200") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref")
        or ""
    )
    assert req_ref.endswith("/EidonOrderIntakeFeedbackRequestDTO")
    assert res_ref.endswith("/EidonOrderIntakeFeedbackResponseDTO")

    assert ("POST", "/ai/tenant-copilot/order-feedback") in ROUTE_POLICY
    assert resolve_route_plane("POST", "/ai/tenant-copilot/order-feedback") == ROUTE_PLANE_OPERATIONAL


def test_order_feedback_happy_path_and_quality_event_seam(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)

    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        r = client.post("/ai/tenant-copilot/order-feedback", headers=_headers(token), json=_payload())
        assert r.status_code == 200, r.text
        body = r.json() or {}
        assert body.get("ok") is True
        assert body.get("capability") == "EIDON_ORDER_INTAKE_FEEDBACK_LOOP_V1"
        assert body.get("authoritative_finalize_allowed") is False
        assert body.get("human_confirmation_recorded") is True
        assert len(body.get("confirmed_mappings") or []) >= 1
        assert len(body.get("corrected_mappings") or []) >= 1
        assert isinstance(body.get("source_traceability") or [], list)
        dumped = str(body).lower()
        assert "extracted_text" not in dumped
        assert "raw_document_blob" not in dumped
        assert "raw_document_payload" not in dumped

        assert len(db.added) == 1
        event = db.added[0]
        assert isinstance(event, models.EidonAIQualityEvent)
        assert event.event_type == "ORDER_INTAKE_FEEDBACK_V1"
        assert event.template_fingerprint == "tpl-fb-api-001"
        assert event.human_confirmation_recorded is True
        assert db.commits == 1
    finally:
        app.dependency_overrides.clear()


def test_order_feedback_missing_tenant_context_fail_closed(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)

    try:
        client = TestClient(app)
        token = _token(tenant_id=None, perms=["AI.COPILOT"])
        r = client.post("/ai/tenant-copilot/order-feedback", headers=_headers(token), json=_payload())
        assert r.status_code == 403, r.text
        assert (r.json() or {}).get("detail") == "missing_tenant_context"
    finally:
        app.dependency_overrides.clear()


def test_order_feedback_action_boundary_violation_fail_closed(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        feedback_service_mod.tenant_action_boundary_guard,
        "enforce_advisory_only",
        lambda _out: (_ for _ in ()).throw(ValueError(AI_ACTION_BOUNDARY_VIOLATION)),
    )

    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        r = client.post("/ai/tenant-copilot/order-feedback", headers=_headers(token), json=_payload())
        assert r.status_code == 400, r.text
        assert (r.json() or {}).get("detail") == AI_ACTION_BOUNDARY_VIOLATION
    finally:
        app.dependency_overrides.clear()


def test_order_feedback_hidden_object_safe_deny_missing_vs_inaccessible(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        feedback_service_mod.order_retrieval_execution_service,
        "retrieve_order_reference",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError(guard_mod.OBJECT_REFERENCE_NOT_ACCESSIBLE)),
    )

    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        r_missing = client.post("/ai/tenant-copilot/order-feedback", headers=_headers(token), json=_payload(order_id=""))
        r_hidden = client.post("/ai/tenant-copilot/order-feedback", headers=_headers(token), json=_payload(order_id="ord-hidden-001"))
        assert r_missing.status_code == 403, r_missing.text
        assert r_hidden.status_code == 403, r_hidden.text
        assert (r_missing.json() or {}).get("detail") == guard_mod.OBJECT_REFERENCE_NOT_ACCESSIBLE
        assert (r_hidden.json() or {}).get("detail") == guard_mod.OBJECT_REFERENCE_NOT_ACCESSIBLE
        assert "ord-hidden-001" not in str((r_hidden.json() or {}).get("detail") or "")
    finally:
        app.dependency_overrides.clear()


def test_order_feedback_compatibility_path_still_works(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)

    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        r_old = client.post("/ai/tenant-copilot/order-intake-feedback", headers=_headers(token), json=_payload())
        r_new = client.post("/ai/tenant-copilot/order-feedback", headers=_headers(token), json=_payload())
        assert r_old.status_code == 200, r_old.text
        assert r_new.status_code == 200, r_new.text
        body_old = r_old.json() or {}
        body_new = r_new.json() or {}
        assert body_old.get("authoritative_finalize_allowed") is False
        assert body_new.get("authoritative_finalize_allowed") is False
    finally:
        app.dependency_overrides.clear()

