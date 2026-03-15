from __future__ import annotations

import app.modules.ai.router as ai_router
import app.modules.ai.order_template_review_service as review_service_mod
from app.core.auth import create_access_token
from app.db.session import get_db_session
from app.main import app
from app.modules.ai.schemas import (
    EidonTemplateReviewDecisionResponseDTO,
    EidonTemplateReviewQueueItemDTO,
    EidonTemplateReviewQueueResponseDTO,
    EidonTemplateReviewReadResponseDTO,
    EidonTemplateReviewRecordDTO,
)
from fastapi.testclient import TestClient


class _FakeDB:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _Row:
    def __init__(self, *, status: str = "STAGED_REVIEW_REQUIRED", raw: bool = False) -> None:
        self.id = "0f5e7ca3-6b9f-4f77-8e2a-a351f9f7c001"
        self.tenant_id = "tenant-ai-001"
        self.source_capability = "EIDON_ORDER_INTAKE_FEEDBACK_LOOP_V1"
        self.submission_shape_version = "v1"
        self.pattern_version = "v1-feedback"
        self.template_fingerprint = "tpl-review-001"
        self.status = status
        self.review_required = True
        self.quality_score = None
        self.authoritative_publish_allowed = False
        self.rollback_from_submission_id = None
        self.source_traceability_json = [
            {
                "field_path": "goods.packages_count",
                "source_class": "tenant_user_feedback",
                "source_ref": "tenant_feedback:channel=UI_REVIEW",
            }
        ]
        self.warnings_json = []
        self.submitted_by = "worker@tenant.local"
        self.reviewed_by = None
        self.reviewed_at = None
        self.review_note = None
        self.created_at = None
        self.updated_at = None
        self.raw_tenant_document_included = raw


def _token(*, roles: list[str], perms: list[str] | None = None, tenant_id: str | None = "platform") -> str:
    claims: dict[str, object] = {
        "sub": "superadmin@ops.local" if "SUPERADMIN" in roles else "user@tenant.local",
        "roles": roles,
    }
    if perms is not None:
        claims["perms"] = perms
    if tenant_id is not None:
        claims["tenant_id"] = tenant_id
    return create_access_token(claims)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _record() -> EidonTemplateReviewRecordDTO:
    return EidonTemplateReviewRecordDTO(
        id="0f5e7ca3-6b9f-4f77-8e2a-a351f9f7c001",
        tenant_id="tenant-ai-001",
        source_capability="EIDON_ORDER_INTAKE_FEEDBACK_LOOP_V1",
        submission_shape_version="v1",
        pattern_version="v1-feedback",
        template_fingerprint="tpl-review-001",
        status="STAGED_REVIEW_REQUIRED",
        review_required=True,
        quality_score=None,
        submitted_by="worker@tenant.local",
        reviewed_by=None,
        reviewed_at=None,
        created_at="2026-03-15T10:00:00+00:00",
        updated_at="2026-03-15T10:00:00+00:00",
        raw_tenant_document_included=False,
        review_note=None,
        authoritative_publish_allowed=False,
        rollback_capable=True,
        rollback_from_submission_id=None,
        source_traceability=[],
        warnings=[],
    )


def test_ai_template_review_control_routes_and_openapi_contract(registered_paths: set[str]) -> None:
    assert "/ai/superadmin-copilot/template-submissions/queue" in registered_paths
    assert "/ai/superadmin-copilot/template-submissions/{submission_id}" in registered_paths
    assert "/ai/superadmin-copilot/template-submissions/{submission_id}/approve" in registered_paths
    assert "/ai/superadmin-copilot/template-submissions/{submission_id}/reject" in registered_paths

    schema = app.openapi()
    queue_route = ((schema.get("paths") or {}).get("/ai/superadmin-copilot/template-submissions/queue") or {}).get("get") or {}
    queue_ref = (((((queue_route.get("responses") or {}).get("200") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref") or ""
    assert queue_ref.endswith("/EidonTemplateReviewQueueResponseDTO")

    approve_route = ((schema.get("paths") or {}).get("/ai/superadmin-copilot/template-submissions/{submission_id}/approve") or {}).get("post") or {}
    req_ref = ((((approve_route.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref") or ""
    res_ref = (((((approve_route.get("responses") or {}).get("200") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref") or ""
    assert req_ref.endswith("/EidonTemplateReviewDecisionRequestDTO")
    assert res_ref.endswith("/EidonTemplateReviewDecisionResponseDTO")


def test_ai_template_review_control_superadmin_only_access(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ai_router.order_template_review_service,
        "list_queue",
        lambda **_kwargs: EidonTemplateReviewQueueResponseDTO(ok=True, items=[]),
    )

    try:
        client = TestClient(app)
        tenant_token = _token(roles=["TENANT_ADMIN"], perms=["AI.COPILOT"], tenant_id="tenant-ai-001")
        r = client.get("/ai/superadmin-copilot/template-submissions/queue", headers=_headers(tenant_token))
        assert r.status_code == 403, r.text
        assert (r.json() or {}).get("detail") == "superadmin_required"
    finally:
        app.dependency_overrides.clear()


def test_ai_template_review_control_queue_read_approve_reject_route_flow(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)

    queue_item = EidonTemplateReviewQueueItemDTO(**_record().model_dump())
    monkeypatch.setattr(
        ai_router.order_template_review_service,
        "list_queue",
        lambda **_kwargs: EidonTemplateReviewQueueResponseDTO(ok=True, items=[queue_item]),
    )
    monkeypatch.setattr(
        ai_router.order_template_review_service,
        "read_submission",
        lambda **_kwargs: EidonTemplateReviewReadResponseDTO(ok=True, submission=_record()),
    )
    monkeypatch.setattr(
        ai_router.order_template_review_service,
        "approve",
        lambda **_kwargs: EidonTemplateReviewDecisionResponseDTO(ok=True, decision="APPROVE", submission=_record()),
    )
    monkeypatch.setattr(
        ai_router.order_template_review_service,
        "reject",
        lambda **_kwargs: EidonTemplateReviewDecisionResponseDTO(ok=True, decision="REJECT", submission=_record()),
    )

    try:
        client = TestClient(app)
        super_token = _token(roles=["SUPERADMIN"], perms=["AI.COPILOT"], tenant_id="platform")

        q = client.get("/ai/superadmin-copilot/template-submissions/queue", headers=_headers(super_token))
        assert q.status_code == 200, q.text
        assert len((q.json() or {}).get("items") or []) == 1

        r = client.get("/ai/superadmin-copilot/template-submissions/0f5e7ca3-6b9f-4f77-8e2a-a351f9f7c001", headers=_headers(super_token))
        assert r.status_code == 200, r.text
        payload = r.json() or {}
        submission = payload.get("submission") or {}
        # No raw document content fields.
        assert "raw_document" not in str(payload).lower()
        assert "extracted_text" not in str(payload).lower()
        assert submission.get("raw_tenant_document_included") is False

        ap = client.post(
            "/ai/superadmin-copilot/template-submissions/0f5e7ca3-6b9f-4f77-8e2a-a351f9f7c001/approve",
            headers=_headers(super_token),
            json={"review_note": "looks good", "quality_score": 88},
        )
        assert ap.status_code == 200, ap.text
        assert (ap.json() or {}).get("decision") == "APPROVE"

        rej = client.post(
            "/ai/superadmin-copilot/template-submissions/0f5e7ca3-6b9f-4f77-8e2a-a351f9f7c001/reject",
            headers=_headers(super_token),
            json={"review_note": "not enough confidence", "quality_score": 22},
        )
        assert rej.status_code == 200, rej.text
        assert (rej.json() or {}).get("decision") == "REJECT"
    finally:
        app.dependency_overrides.clear()


def test_ai_template_review_control_fail_closed_route_errors(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ai_router.order_template_review_service,
        "read_submission",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("submission_not_found")),
    )
    monkeypatch.setattr(
        ai_router.order_template_review_service,
        "approve",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("invalid_status_transition")),
    )

    try:
        client = TestClient(app)
        super_token = _token(roles=["SUPERADMIN"], perms=["AI.COPILOT"], tenant_id="platform")

        r = client.get("/ai/superadmin-copilot/template-submissions/0f5e7ca3-6b9f-4f77-8e2a-a351f9f7c001", headers=_headers(super_token))
        assert r.status_code == 404, r.text
        assert (r.json() or {}).get("detail") == "submission_not_found"

        ap = client.post(
            "/ai/superadmin-copilot/template-submissions/0f5e7ca3-6b9f-4f77-8e2a-a351f9f7c001/approve",
            headers=_headers(super_token),
            json={"review_note": "x", "quality_score": 50},
        )
        assert ap.status_code == 400, ap.text
        assert (ap.json() or {}).get("detail") == "invalid_status_transition"
    finally:
        app.dependency_overrides.clear()


def test_ai_template_review_service_state_transitions_and_auditability_fields(monkeypatch) -> None:
    svc = review_service_mod.EidonTemplateReviewService()

    staged_row = _Row(status="STAGED_REVIEW_REQUIRED", raw=False)
    monkeypatch.setattr(svc, "_load", lambda _db, _sid: staged_row)
    approved = svc.approve(
        db=object(),
        submission_id="0f5e7ca3-6b9f-4f77-8e2a-a351f9f7c001",
        actor="superadmin@ops.local",
        review_note="approved by policy",
        quality_score=91,
    )
    assert approved.decision == "APPROVE"
    assert approved.submission.status == "REVIEW_APPROVED"
    assert approved.submission.reviewed_by == "superadmin@ops.local"
    assert approved.submission.reviewed_at is not None
    assert approved.submission.quality_score == 91
    assert approved.submission.authoritative_publish_allowed is False

    # Fail-closed: no transition from already decided state.
    try:
        svc.reject(
            db=object(),
            submission_id="0f5e7ca3-6b9f-4f77-8e2a-a351f9f7c001",
            actor="superadmin@ops.local",
            review_note="cannot reject after approve",
            quality_score=10,
        )
        raise AssertionError("expected invalid_status_transition")
    except ValueError as exc:
        assert str(exc) == "invalid_status_transition"

    staged_row2 = _Row(status="STAGED_REVIEW_REQUIRED", raw=False)
    monkeypatch.setattr(svc, "_load", lambda _db, _sid: staged_row2)
    rejected = svc.reject(
        db=object(),
        submission_id="0f5e7ca3-6b9f-4f77-8e2a-a351f9f7c001",
        actor="superadmin@ops.local",
        review_note="not enough quality",
        quality_score=25,
    )
    assert rejected.decision == "REJECT"
    assert rejected.submission.status == "REVIEW_REJECTED"
    assert rejected.submission.reviewed_by == "superadmin@ops.local"
    assert rejected.submission.reviewed_at is not None


def test_ai_template_review_service_fail_closed_for_invalid_submission_payload(monkeypatch) -> None:
    svc = review_service_mod.EidonTemplateReviewService()

    raw_row = _Row(status="STAGED_REVIEW_REQUIRED", raw=True)
    monkeypatch.setattr(svc, "_load", lambda _db, _sid: raw_row)
    try:
        svc.approve(
            db=object(),
            submission_id="0f5e7ca3-6b9f-4f77-8e2a-a351f9f7c001",
            actor="superadmin@ops.local",
            review_note="x",
            quality_score=50,
        )
        raise AssertionError("expected raw_tenant_document_not_allowed")
    except ValueError as exc:
        assert str(exc) == "raw_tenant_document_not_allowed"

    staged_row = _Row(status="STAGED_REVIEW_REQUIRED", raw=False)
    monkeypatch.setattr(svc, "_load", lambda _db, _sid: staged_row)
    try:
        svc.reject(
            db=object(),
            submission_id="0f5e7ca3-6b9f-4f77-8e2a-a351f9f7c001",
            actor="superadmin@ops.local",
            review_note="",
            quality_score=20,
        )
        raise AssertionError("expected review_note_required_for_reject")
    except ValueError as exc:
        assert str(exc) == "review_note_required_for_reject"
