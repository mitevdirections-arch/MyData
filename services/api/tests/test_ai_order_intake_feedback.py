from __future__ import annotations

import app.core.middleware as core_middleware
import app.modules.ai.router as ai_router
import app.modules.licensing.deps as licensing_deps
from app.core.auth import create_access_token
from app.db import models
from app.db.session import get_db_session
from app.main import app
from fastapi.testclient import TestClient


class _FakeDB:
    def __init__(self, *, fail_on_add: bool = False) -> None:
        self.commits = 0
        self.added: list[object] = []
        self.fail_on_add = bool(fail_on_add)

    def add(self, obj: object) -> None:
        if self.fail_on_add:
            raise RuntimeError("db_add_failed")
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


def test_ai_order_intake_feedback_route_and_openapi_contract(registered_paths: set[str]) -> None:
    assert "/ai/tenant-copilot/order-intake-feedback" in registered_paths

    schema = app.openapi()
    route = ((schema.get("paths") or {}).get("/ai/tenant-copilot/order-intake-feedback") or {}).get("post") or {}

    req_ref = ((((route.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref") or ""
    res_ref = (((((route.get("responses") or {}).get("200") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref") or ""
    assert req_ref.endswith("/EidonOrderIntakeFeedbackRequestDTO")
    assert res_ref.endswith("/EidonOrderIntakeFeedbackResponseDTO")

    components = ((schema.get("components") or {}).get("schemas") or {})
    assert "EidonOrderIntakeFeedbackRequestDTO" in components
    assert "EidonOrderIntakeFeedbackResponseDTO" in components
    assert "EidonTenantLocalLearningCandidateDTO" in components
    assert "EidonGlobalPatternSubmissionCandidateDTO" in components


def test_ai_order_intake_feedback_confirmed_corrected_flow(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)

    payload = {
        "original_template_fingerprint": "tpl-fp-001",
        "original_template_learning_candidate": {
            "eligible": True,
            "pattern_version": "v1",
            "template_fingerprint": "tpl-fp-001",
            "extracted_field_paths": ["shipper.legal_name", "goods.packages_count"],
            "de_identified_pattern_features": {"line_count_bucket": 15},
            "learn_globally_act_locally_rule": "learn_globally_from_patterns_act_locally_within_tenant_boundaries",
            "raw_tenant_document_included": False,
        },
        "proposed_draft_order_candidate": {
            "order_no": "ORD-FB-001",
            "transport_mode": "ROAD",
            "direction": "OUTBOUND",
            "shipper": {"legal_name": "Shipper OOD"},
            "carrier": {"legal_name": "Carrier AD"},
            "goods": {
                "goods_description": "Paint",
                "packages_count": 12,
                "gross_weight_kg": 1200.5,
            },
            "is_dangerous_goods": True,
            "adr": {"adr_class": "3"},
        },
        "user_confirmed_fields": ["shipper.legal_name", "goods.goods_description"],
        "user_corrected_fields": {"goods.packages_count": 14, "carrier.legal_name": "Carrier AD New"},
        "unresolved_fields": ["adr.un_number"],
        "confirmation_metadata": {
            "confirmation_channel": "UI_REVIEW",
            "confirmed_by": "dispatcher@tenant.local",
            "confirmation_note": "validated by dispatcher",
            "confirmed_at": "2026-03-15T10:00:00+00:00",
        },
    }

    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        r = client.post("/ai/tenant-copilot/order-intake-feedback", headers=_headers(token), json=payload)
        assert r.status_code == 200, r.text

        body = r.json() or {}
        assert body.get("ok") is True
        assert body.get("capability") == "EIDON_ORDER_INTAKE_FEEDBACK_LOOP_V1"
        assert body.get("human_confirmation_recorded") is True

        confirmed = body.get("confirmed_mappings") or []
        corrected = body.get("corrected_mappings") or []
        unresolved = body.get("unresolved_mappings") or []
        assert any((x or {}).get("field_path") == "shipper.legal_name" for x in confirmed)
        assert any((x or {}).get("field_path") == "goods.packages_count" for x in corrected)
        assert any((x or {}).get("field_path") == "adr.un_number" for x in unresolved)

        local_candidate = body.get("tenant_local_learning_candidate") or {}
        global_candidate = body.get("global_pattern_submission_candidate") or {}
        assert local_candidate.get("template_fingerprint") == "tpl-fp-001"
        assert global_candidate.get("template_fingerprint") == "tpl-fp-001"
        assert local_candidate.get("raw_tenant_document_included") is False
        assert global_candidate.get("raw_tenant_document_included") is False

        # De-identified candidate shape only.
        de_id = global_candidate.get("de_identified_pattern_features") or {}
        assert "confirmed_count" in de_id
        assert "corrected_count" in de_id
        assert "unresolved_count" in de_id
        assert "extracted_text" not in de_id

        assert len(db.added) == 1
        event = db.added[0]
        assert isinstance(event, models.EidonAIQualityEvent)
        assert event.event_type == "ORDER_INTAKE_FEEDBACK_V1"
        assert event.template_fingerprint == "tpl-fp-001"
        assert event.confirmed_count == 2
        assert event.corrected_count == 2
        assert event.unresolved_count == 1
        assert event.human_confirmation_recorded is True

        summary = dict(event.confidence_adjustments_summary_json or {})
        assert summary.get("total_adjustments") == 5
        assert "rationale_counts" in summary
        dumped = str(summary).lower()
        assert "source_traceability" not in dumped
        assert "corrected_value" not in dumped
        assert "validated by dispatcher" not in dumped
        assert "carrier ad new" not in dumped

        assert body.get("authoritative_finalize_allowed") is False
        assert str(body.get("no_authoritative_finalize_rule") or "").strip() != ""
        assert db.commits == 1
    finally:
        app.dependency_overrides.clear()


def test_ai_order_intake_feedback_requires_human_confirmation_signal(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)

    payload = {
        "original_template_fingerprint": "tpl-fp-002",
        "proposed_draft_order_candidate": {"order_no": "ORD-FB-002"},
        "user_confirmed_fields": [],
        "user_corrected_fields": {},
        "unresolved_fields": [],
    }

    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        r = client.post("/ai/tenant-copilot/order-intake-feedback", headers=_headers(token), json=payload)
        assert r.status_code == 422, r.text
        assert "feedback_signal_required" in r.text
    finally:
        app.dependency_overrides.clear()


def test_ai_order_intake_feedback_tenant_safe_behavior(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)

    payload = {
        "original_template_fingerprint": "tpl-fp-003",
        "proposed_draft_order_candidate": {"order_no": "ORD-FB-003"},
        "user_confirmed_fields": ["order_no"],
    }

    try:
        client = TestClient(app)

        no_perm_token = _token(tenant_id="tenant-ai-001", perms=[])
        denied = client.post("/ai/tenant-copilot/order-intake-feedback", headers=_headers(no_perm_token), json=payload)
        assert denied.status_code == 403, denied.text
        assert str((denied.json() or {}).get("detail") or "").startswith("permission_required:AI.COPILOT")

        no_tenant_token = _token(tenant_id=None, perms=["AI.COPILOT"])
        missing_ctx = client.post("/ai/tenant-copilot/order-intake-feedback", headers=_headers(no_tenant_token), json=payload)
        assert missing_ctx.status_code == 403, missing_ctx.text
        assert (missing_ctx.json() or {}).get("detail") == "missing_tenant_context"
    finally:
        app.dependency_overrides.clear()


def test_ai_order_intake_feedback_fails_closed_when_quality_event_persistence_fails(monkeypatch) -> None:
    db = _FakeDB(fail_on_add=True)
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)

    payload = {
        "original_template_fingerprint": "tpl-fp-004",
        "proposed_draft_order_candidate": {"order_no": "ORD-FB-004"},
        "user_confirmed_fields": ["order_no"],
    }

    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        r = client.post("/ai/tenant-copilot/order-intake-feedback", headers=_headers(token), json=payload)
        assert r.status_code == 400, r.text
        assert (r.json() or {}).get("detail") == "quality_event_persistence_failed"
        assert db.commits == 0
    finally:
        app.dependency_overrides.clear()
