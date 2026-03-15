from __future__ import annotations

from typing import Any

import app.core.middleware as core_middleware
import app.modules.ai.orders_copilot_orchestration_service as orchestration_service_mod
import app.modules.ai.router as ai_router
import app.modules.ai.tenant_retrieval_action_guard as guard_mod
import app.modules.licensing.deps as licensing_deps
from app.core.auth import create_access_token
from app.core.policy_matrix import ROUTE_POLICY
from app.core.route_ownership import ROUTE_PLANE_OPERATIONAL, resolve_route_plane
from app.db.session import get_db_session
from app.main import app
from app.modules.ai.schemas import (
    EidonOrderRetrievalSummaryDTO,
    EidonRetrievalTraceabilityDTO,
)
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


class _StubResult:
    def __init__(
        self,
        *,
        dumped: dict[str, Any],
        warnings: list[str] | None = None,
        source_traceability: Any = None,
        authoritative_finalize_allowed: bool = False,
    ) -> None:
        self._dumped = dict(dumped)
        self.warnings = list(warnings or [])
        self.source_traceability = source_traceability
        self.authoritative_finalize_allowed = authoritative_finalize_allowed

    def model_dump(self, *, exclude_none: bool = True) -> dict[str, Any]:
        _ = exclude_none
        return dict(self._dumped)


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


def _retrieval_summary(order_id: str) -> EidonOrderRetrievalSummaryDTO:
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


def test_orders_copilot_route_openapi_policy_and_ownership_contract(registered_paths: set[str]) -> None:
    assert "/ai/tenant-copilot/orders-copilot" in registered_paths

    schema = app.openapi()
    route = ((schema.get("paths") or {}).get("/ai/tenant-copilot/orders-copilot") or {}).get("post") or {}
    req_ref = (
        ((((route.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref")
        or ""
    )
    res_ref = (
        (((((route.get("responses") or {}).get("200") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref")
        or ""
    )
    assert req_ref.endswith("/EidonOrdersCopilotRequestDTO")
    assert res_ref.endswith("/EidonOrdersCopilotResponseDTO")

    assert ("POST", "/ai/tenant-copilot/orders-copilot") in ROUTE_POLICY
    assert resolve_route_plane("POST", "/ai/tenant-copilot/orders-copilot") == ROUTE_PLANE_OPERATIONAL


def test_orders_copilot_service_routes_retrieve_intent_via_existing_seam(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        orchestration_service_mod.order_retrieval_execution_service,
        "retrieve_order_reference",
        lambda **kwargs: (calls.append(dict(kwargs)), _retrieval_summary("ord-visible-001"))[1],
    )

    out = orchestration_service_mod.service.orchestrate(
        db=object(),  # type: ignore[arg-type]
        tenant_id="tenant-ai-001",
        intent="retrieve_order_reference",
        payload={"order_id": "ord-visible-001"},
    )

    assert out.ok is True
    assert out.intent == "retrieve_order_reference"
    assert out.authoritative_finalize_allowed is False
    assert out.result.get("object_id") == "ord-visible-001"
    assert len(calls) == 1
    assert calls[0].get("tenant_id") == "tenant-ai-001"
    assert calls[0].get("order_reference_id") == "ord-visible-001"


def test_orders_copilot_service_routes_document_understanding_intent_via_existing_seam(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        orchestration_service_mod.order_document_intake_service,
        "ingest",
        lambda **kwargs: (
            calls.append(dict(kwargs)),
                _StubResult(
                    dumped={"capability": "EIDON_ORDER_DOCUMENT_INTAKE_V1", "ok": True},
                    warnings=["missing_required_fields_detected"],
                    source_traceability=[
                        {"field_path": "request_context", "source_class": "stub", "source_ref": "summary_only"}
                    ],
                ),
            )[1],
        )

    out = orchestration_service_mod.service.orchestrate(
        db=object(),  # type: ignore[arg-type]
        tenant_id="tenant-ai-001",
        intent="document_understanding",
        payload={"extracted_text": "Shipper: A"},
    )

    assert out.ok is True
    assert out.intent == "document_understanding"
    assert out.authoritative_finalize_allowed is False
    assert out.result.get("capability") == "EIDON_ORDER_DOCUMENT_INTAKE_V1"
    assert out.warnings == ["missing_required_fields_detected"]
    assert isinstance(out.source_traceability, list)
    assert len(calls) == 1
    assert calls[0].get("tenant_id") == "tenant-ai-001"


def test_orders_copilot_service_routes_order_drafting_and_feedback_intents_via_existing_seams(monkeypatch) -> None:
    draft_calls = {"count": 0}
    feedback_calls = {"count": 0}

    monkeypatch.setattr(
        orchestration_service_mod.order_draft_assist_service,
        "assist",
        lambda **kwargs: (
            draft_calls.__setitem__("count", draft_calls["count"] + 1),
                _StubResult(
                    dumped={"capability": "EIDON_ORDER_DRAFT_ASSIST_V1", "ok": True},
                    warnings=[],
                    source_traceability=[
                        {"field_path": "request_context", "source_class": "stub", "source_ref": "summary_only"}
                    ],
                ),
            )[1],
        )
    monkeypatch.setattr(
        orchestration_service_mod.order_intake_feedback_service,
        "apply_feedback",
        lambda **kwargs: (
            feedback_calls.__setitem__("count", feedback_calls["count"] + 1),
                _StubResult(
                    dumped={"capability": "EIDON_ORDER_INTAKE_FEEDBACK_LOOP_V1", "ok": True},
                    warnings=[],
                    source_traceability=[
                        {"field_path": "request_context", "source_class": "stub", "source_ref": "summary_only"}
                    ],
                ),
            )[1],
        )

    draft_out = orchestration_service_mod.service.orchestrate(
        db=object(),  # type: ignore[arg-type]
        tenant_id="tenant-ai-001",
        intent="order_drafting",
        payload={
            "order_draft_input": {
                "order_no": "ORD-DRFT-001",
                "status": "DRAFT",
                "transport_mode": "ROAD",
                "direction": "OUTBOUND",
            }
        },
    )
    feedback_out = orchestration_service_mod.service.orchestrate(
        db=object(),  # type: ignore[arg-type]
        tenant_id="tenant-ai-001",
        intent="order_feedback",
        payload={
            "original_template_fingerprint": "tpl-fp-001",
            "proposed_draft_order_candidate": {"order_no": "ORD-FB-001"},
            "user_confirmed_fields": ["order_no"],
        },
    )

    assert draft_out.intent == "order_drafting"
    assert feedback_out.intent == "order_feedback"
    assert draft_out.authoritative_finalize_allowed is False
    assert feedback_out.authoritative_finalize_allowed is False
    assert draft_calls["count"] == 1
    assert feedback_calls["count"] == 1


def test_orders_copilot_service_fail_closed_unsupported_intent_and_authoritative_violation(monkeypatch) -> None:
    unsupported_err: str | None = None
    try:
        orchestration_service_mod.service.orchestrate(
            db=object(),  # type: ignore[arg-type]
            tenant_id="tenant-ai-001",
            intent="unknown_intent",
            payload={},
        )
    except ValueError as exc:
        unsupported_err = str(exc)
    assert unsupported_err == orchestration_service_mod.UNSUPPORTED_ORDERS_COPILOT_INTENT

    monkeypatch.setattr(
        orchestration_service_mod.order_document_intake_service,
        "ingest",
        lambda **_kwargs: _StubResult(
            dumped={"ok": True},
            authoritative_finalize_allowed=True,
        ),
    )

    auth_err: str | None = None
    try:
        orchestration_service_mod.service.orchestrate(
            db=object(),  # type: ignore[arg-type]
            tenant_id="tenant-ai-001",
            intent="document_understanding",
            payload={"extracted_text": "Shipper: A"},
        )
    except ValueError as exc:
        auth_err = str(exc)
    assert auth_err == orchestration_service_mod.ORDERS_COPILOT_AUTHORITATIVE_FINALIZE_VIOLATION


def test_orders_copilot_endpoint_happy_path_for_all_intents_and_no_raw_leakage(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)

    def _orchestrate_stub(*, db, tenant_id: str, intent: str, payload: dict[str, Any]):
        _ = (db, payload)
        return orchestration_service_mod.EidonOrdersCopilotResponseDTO(
            ok=True,
            tenant_id=tenant_id,
            capability="EIDON_ORDERS_COPILOT_ORCHESTRATION_V1",
            intent=intent,
                result={"capability": "stubbed"},
                authoritative_finalize_allowed=False,
                warnings=[],
                source_traceability=[
                    {"field_path": "request_context", "source_class": "stub", "source_ref": "summary_only"}
                ],
                no_authoritative_finalize_rule="eidon_prepare_only_no_authoritative_finalize",
                no_action_execution_rule="eidon_advisory_only_no_action_execution",
                system_truth_rule="ai_does_not_override_system_truth",
        )

    monkeypatch.setattr(ai_router.orders_copilot_orchestration_service, "orchestrate", _orchestrate_stub)

    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        intents = (
            ("retrieve_order_reference", {"order_id": "ord-visible-001"}),
            ("document_understanding", {"extracted_text": "Shipper: A"}),
            ("order_drafting", {"order_draft_input": {"order_no": "ORD-DRFT-001", "status": "DRAFT", "transport_mode": "ROAD", "direction": "OUTBOUND"}}),
            ("order_feedback", {"original_template_fingerprint": "tpl-fp-001", "proposed_draft_order_candidate": {"order_no": "ORD-FB-001"}, "user_confirmed_fields": ["order_no"]}),
        )
        for intent, payload in intents:
            r = client.post(
                "/ai/tenant-copilot/orders-copilot",
                headers=_headers(token),
                json={"intent": intent, "payload": payload},
            )
            assert r.status_code == 200, r.text
            body = r.json() or {}
            assert body.get("ok") is True
            assert body.get("intent") == intent
            assert body.get("authoritative_finalize_allowed") is False
            dumped = str(body).lower()
            assert "raw_document_blob" not in dumped
            assert "raw_document_payload" not in dumped
            assert "extracted_text" not in dumped
        assert db.commits == 4
    finally:
        app.dependency_overrides.clear()


def test_orders_copilot_endpoint_fail_closed_missing_tenant_unsupported_and_hidden_object_safe(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)

    def _deny_retrieval(*, db, tenant_id: str, intent: str, payload: dict[str, Any]):
        _ = (db, tenant_id, payload)
        if intent == "retrieve_order_reference":
            raise ValueError(guard_mod.OBJECT_REFERENCE_NOT_ACCESSIBLE)
        raise ValueError(orchestration_service_mod.UNSUPPORTED_ORDERS_COPILOT_INTENT)

    monkeypatch.setattr(ai_router.orders_copilot_orchestration_service, "orchestrate", _deny_retrieval)

    try:
        client = TestClient(app)

        token_no_tenant = _token(tenant_id=None, perms=["AI.COPILOT"])
        r_no_tenant = client.post(
            "/ai/tenant-copilot/orders-copilot",
            headers=_headers(token_no_tenant),
            json={"intent": "retrieve_order_reference", "payload": {"order_id": "ord-visible-001"}},
        )
        assert r_no_tenant.status_code == 403, r_no_tenant.text
        assert (r_no_tenant.json() or {}).get("detail") == "missing_tenant_context"

        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        r_unsupported = client.post(
            "/ai/tenant-copilot/orders-copilot",
            headers=_headers(token),
            json={"intent": "not_supported", "payload": {}},
        )
        assert r_unsupported.status_code == 400, r_unsupported.text
        assert (r_unsupported.json() or {}).get("detail") == orchestration_service_mod.UNSUPPORTED_ORDERS_COPILOT_INTENT

        r_missing = client.post(
            "/ai/tenant-copilot/orders-copilot",
            headers=_headers(token),
            json={"intent": "retrieve_order_reference", "payload": {"order_id": ""}},
        )
        r_hidden = client.post(
            "/ai/tenant-copilot/orders-copilot",
            headers=_headers(token),
            json={"intent": "retrieve_order_reference", "payload": {"order_id": "ord-hidden-001"}},
        )
        assert r_missing.status_code == 403, r_missing.text
        assert r_hidden.status_code == 403, r_hidden.text
        assert (r_missing.json() or {}).get("detail") == guard_mod.OBJECT_REFERENCE_NOT_ACCESSIBLE
        assert (r_hidden.json() or {}).get("detail") == guard_mod.OBJECT_REFERENCE_NOT_ACCESSIBLE
        assert "ord-hidden-001" not in str((r_hidden.json() or {}).get("detail") or "")
    finally:
        app.dependency_overrides.clear()
