from __future__ import annotations

import app.core.middleware as core_middleware
import app.modules.ai.eidon_orders_response_contract_v1 as response_contract_mod
import app.modules.ai.router as ai_router
import app.modules.ai.tenant_retrieval_action_guard as guard_mod
import app.modules.licensing.deps as licensing_deps
from app.core.auth import create_access_token
from app.core.policy_matrix import ROUTE_POLICY
from app.core.route_ownership import ROUTE_PLANE_OPERATIONAL, resolve_route_plane
from app.db.session import get_db_session
from app.main import app
from app.modules.ai.schemas import EidonOrderRetrievalSummaryDTO, EidonRetrievalTraceabilityDTO
from fastapi.testclient import TestClient


class _FakeDB:
    def __init__(self) -> None:
        self.commits = 0
        self.add_calls = 0
        self.flush_calls = 0

    def commit(self) -> None:
        self.commits += 1

    def add(self, _obj: object) -> None:
        self.add_calls += 1

    def flush(self) -> None:
        self.flush_calls += 1


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


def _summary(*, order_id: str) -> EidonOrderRetrievalSummaryDTO:
    return EidonOrderRetrievalSummaryDTO(
        object_type="order",
        object_id=order_id,
        template_fingerprint=None,
        retrieval_traceability=EidonRetrievalTraceabilityDTO(
            retrieval_class="tenant_visible_order_reference_lookup",
            retrieval_marker="summary_only_guarded_reference_lookup",
            guard_outcome="allow",
        ),
        tenant_visible=True,
    )


def test_ai_order_reference_retrieval_route_openapi_and_policy_contract(registered_paths: set[str]) -> None:
    assert "/ai/tenant-copilot/retrieve-order-reference" in registered_paths

    schema = app.openapi()
    route = ((schema.get("paths") or {}).get("/ai/tenant-copilot/retrieve-order-reference") or {}).get("post") or {}
    req_ref = (
        ((((route.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref")
        or ""
    )
    res_ref = (
        (((((route.get("responses") or {}).get("200") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref")
        or ""
    )
    assert req_ref.endswith("/EidonOrderReferenceRetrievalRequestDTO")
    assert res_ref.endswith("/EidonOrderReferenceRetrievalResponseDTO")

    assert ("POST", "/ai/tenant-copilot/retrieve-order-reference") in ROUTE_POLICY
    assert resolve_route_plane("POST", "/ai/tenant-copilot/retrieve-order-reference") == ROUTE_PLANE_OPERATIONAL


def test_ai_order_reference_retrieval_happy_path_minimal_response(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ai_router.order_retrieval_execution_service,
        "retrieve_order_reference",
        lambda **_kwargs: _summary(order_id="ord-visible-001"),
    )

    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        r = client.post(
            "/ai/tenant-copilot/retrieve-order-reference",
            headers=_headers(token),
            json={"order_id": "ord-visible-001"},
        )
        assert r.status_code == 200, r.text
        body = r.json() or {}
        assert body.get("ok") is True
        assert body.get("capability") == "EIDON_ORDER_REFERENCE_RETRIEVAL_V1"
        assert body.get("authoritative_finalize_allowed") is False
        result = body.get("result") or {}
        assert result.get("object_type") == "order"
        assert result.get("object_id") == "ord-visible-001"
        assert result.get("tenant_visible") is True
        assert (body.get("source_traceability") or {}).get("retrieval_marker") == "summary_only_guarded_reference_lookup"

        dumped = str(body).lower()
        assert "payload" not in dumped
        assert "source_traceability payload" not in dumped
        assert db.add_calls == 0
        assert db.flush_calls == 0
        assert db.commits == 1
    finally:
        app.dependency_overrides.clear()


def test_ai_order_reference_retrieval_hidden_object_safe_deny_missing_vs_inaccessible(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)

    def _deny(**_kwargs):
        raise ValueError(guard_mod.OBJECT_REFERENCE_NOT_ACCESSIBLE)

    monkeypatch.setattr(
        ai_router.order_retrieval_execution_service,
        "retrieve_order_reference",
        _deny,
    )

    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])

        r_missing = client.post(
            "/ai/tenant-copilot/retrieve-order-reference",
            headers=_headers(token),
            json={"order_id": ""},
        )
        r_inaccessible = client.post(
            "/ai/tenant-copilot/retrieve-order-reference",
            headers=_headers(token),
            json={"order_id": "ord-hidden-001"},
        )

        assert r_missing.status_code == 403, r_missing.text
        assert r_inaccessible.status_code == 403, r_inaccessible.text
        assert (r_missing.json() or {}).get("detail") == guard_mod.OBJECT_REFERENCE_NOT_ACCESSIBLE
        assert (r_inaccessible.json() or {}).get("detail") == guard_mod.OBJECT_REFERENCE_NOT_ACCESSIBLE
        assert "ord-hidden-001" not in str((r_inaccessible.json() or {}).get("detail") or "")
    finally:
        app.dependency_overrides.clear()


def test_ai_order_reference_retrieval_fail_closed_on_response_contract_violation(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ai_router.order_retrieval_execution_service,
        "retrieve_order_reference",
        lambda **_kwargs: _summary(order_id="ord-visible-001"),
    )
    monkeypatch.setattr(
        ai_router,
        "enforce_orders_response_contract_or_fail",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError(response_contract_mod.EIDON_ORDERS_RESPONSE_CONTRACT_VIOLATION)),
    )

    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        r = client.post(
            "/ai/tenant-copilot/retrieve-order-reference",
            headers=_headers(token),
            json={"order_id": "ord-visible-001"},
        )
        assert r.status_code == 400, r.text
        assert (r.json() or {}).get("detail") == response_contract_mod.EIDON_ORDERS_RESPONSE_CONTRACT_VIOLATION
    finally:
        app.dependency_overrides.clear()


def test_ai_order_reference_retrieval_permission_and_tenant_scope(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ai_router.order_retrieval_execution_service,
        "retrieve_order_reference",
        lambda **_kwargs: _summary(order_id="ord-visible-001"),
    )

    try:
        client = TestClient(app)

        no_perm_token = _token(tenant_id="tenant-ai-001", perms=[])
        denied = client.post(
            "/ai/tenant-copilot/retrieve-order-reference",
            headers=_headers(no_perm_token),
            json={"order_id": "ord-visible-001"},
        )
        assert denied.status_code == 403, denied.text
        assert str((denied.json() or {}).get("detail") or "").startswith("permission_required:AI.COPILOT")

        no_tenant_token = _token(tenant_id=None, perms=["AI.COPILOT"])
        missing_ctx = client.post(
            "/ai/tenant-copilot/retrieve-order-reference",
            headers=_headers(no_tenant_token),
            json={"order_id": "ord-visible-001"},
        )
        assert missing_ctx.status_code == 403, missing_ctx.text
        assert (missing_ctx.json() or {}).get("detail") == "missing_tenant_context"
    finally:
        app.dependency_overrides.clear()
