from __future__ import annotations

import app.core.middleware as core_middleware
import app.modules.ai.router as ai_router
import app.modules.licensing.deps as licensing_deps
from app.core.auth import create_access_token
from app.db import Base, models
from app.db.session import get_db_session
from app.main import app
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


def _payload_base() -> dict[str, object]:
    return {
        "source_capability": "EIDON_ORDER_INTAKE_FEEDBACK_LOOP_V1",
        "source_template_fingerprint": "tpl-stage-001",
        "global_pattern_submission_candidate": {
            "eligible": True,
            "pattern_version": "v1-feedback",
            "template_fingerprint": "tpl-stage-001",
            "de_identified_pattern_features": {
                "confirmed_count": 2,
                "corrected_count": 1,
                "unresolved_count": 1,
                "human_confirmation_recorded": True,
            },
            "learn_globally_act_locally_rule": "learn_globally_from_patterns_act_locally_within_tenant_boundaries",
            "raw_tenant_document_included": False,
            "submission_blocked_reason": "global_submission_engine_not_enabled_in_this_cycle",
        },
        "tenant_source_traceability": [
            {
                "field_path": "goods.packages_count",
                "source_class": "tenant_user_feedback",
                "source_ref": "tenant_feedback:channel=UI_REVIEW",
            }
        ],
        "human_confirmation_recorded": True,
        "submission_shape_version": "v1",
    }


def test_ai_template_submission_staging_model_exists() -> None:
    assert hasattr(models, "EidonTemplateSubmissionStaging")
    assert models.EidonTemplateSubmissionStaging.__tablename__ == "eidon_template_submission_staging"
    assert "eidon_template_submission_staging" in set(Base.metadata.tables.keys())


def test_ai_template_submission_staging_route_and_openapi_contract(registered_paths: set[str]) -> None:
    assert "/ai/tenant-copilot/template-submissions/stage" in registered_paths
    schema = app.openapi()
    route = ((schema.get("paths") or {}).get("/ai/tenant-copilot/template-submissions/stage") or {}).get("post") or {}
    req_ref = ((((route.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref") or ""
    res_ref = (((((route.get("responses") or {}).get("200") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref") or ""
    assert req_ref.endswith("/EidonTemplateSubmissionStagingRequestDTO")
    assert res_ref.endswith("/EidonTemplateSubmissionStagingResponseDTO")


def test_ai_template_submission_staging_review_required_and_no_authoritative_publish(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    payload = _payload_base()
    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        r = client.post("/ai/tenant-copilot/template-submissions/stage", headers=_headers(token), json=payload)
        assert r.status_code == 200, r.text
        body = r.json() or {}

        assert body.get("ok") is True
        assert body.get("capability") == "EIDON_TEMPLATE_SUBMISSION_STAGING_V1"
        staged = body.get("staged_submission") or {}
        assert staged.get("status") == "STAGED_REVIEW_REQUIRED"
        assert staged.get("review_required") is True
        assert staged.get("quality_score") is None
        assert staged.get("rollback_capable") is True
        assert staged.get("authoritative_publish_allowed") is False
        assert staged.get("raw_tenant_document_included") is False
        assert body.get("authoritative_publish_allowed") is False
        assert str(body.get("no_authoritative_publish_rule") or "").strip() != ""
        assert str(body.get("no_raw_document_rule") or "").strip() != ""

        gp = body.get("global_pattern_submission_candidate") or {}
        assert gp.get("raw_tenant_document_included") is False

        assert len(db.added) == 1
        row = db.added[0]
        assert bool(getattr(row, "raw_tenant_document_included")) is False
        assert getattr(row, "status") == "STAGED_REVIEW_REQUIRED"
        assert bool(getattr(row, "review_required")) is True
        assert bool(getattr(row, "authoritative_publish_allowed")) is False
        assert db.commits == 1
    finally:
        app.dependency_overrides.clear()


def test_ai_template_submission_staging_rejects_non_deidentified_submission(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    payload = _payload_base()
    bad = ((payload.get("global_pattern_submission_candidate") or {}).get("de_identified_pattern_features") or {})
    bad["extracted_text"] = "RAW-TEXT-NOT-ALLOWED"
    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        r = client.post("/ai/tenant-copilot/template-submissions/stage", headers=_headers(token), json=payload)
        assert r.status_code == 400, r.text
        assert str((r.json() or {}).get("detail") or "").startswith("non_deidentified_feature_key:")
    finally:
        app.dependency_overrides.clear()


def test_ai_template_submission_staging_rejects_raw_document_and_requires_human_confirmation(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])

        p_raw = _payload_base()
        gp = p_raw.get("global_pattern_submission_candidate") or {}
        gp["raw_tenant_document_included"] = True
        r_raw = client.post("/ai/tenant-copilot/template-submissions/stage", headers=_headers(token), json=p_raw)
        assert r_raw.status_code == 400, r_raw.text
        assert (r_raw.json() or {}).get("detail") == "raw_tenant_document_not_allowed"

        p_human = _payload_base()
        p_human["human_confirmation_recorded"] = False
        r_human = client.post("/ai/tenant-copilot/template-submissions/stage", headers=_headers(token), json=p_human)
        assert r_human.status_code == 400, r_human.text
        assert (r_human.json() or {}).get("detail") == "human_confirmation_required"
    finally:
        app.dependency_overrides.clear()


def test_ai_template_submission_staging_tenant_safe_behavior(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    payload = _payload_base()
    try:
        client = TestClient(app)

        no_perm_token = _token(tenant_id="tenant-ai-001", perms=[])
        denied = client.post("/ai/tenant-copilot/template-submissions/stage", headers=_headers(no_perm_token), json=payload)
        assert denied.status_code == 403, denied.text
        assert str((denied.json() or {}).get("detail") or "").startswith("permission_required:AI.COPILOT")

        no_tenant_token = _token(tenant_id=None, perms=["AI.COPILOT"])
        missing_ctx = client.post("/ai/tenant-copilot/template-submissions/stage", headers=_headers(no_tenant_token), json=payload)
        assert missing_ctx.status_code == 403, missing_ctx.text
        assert (missing_ctx.json() or {}).get("detail") == "missing_tenant_context"
    finally:
        app.dependency_overrides.clear()
