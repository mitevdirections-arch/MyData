from __future__ import annotations

import uuid
from datetime import datetime, timezone

import app.modules.ai.router as ai_router
from app.core.auth import create_access_token
from app.db.session import get_db_session
from app.main import app
from app.modules.ai.order_template_publish_service import EidonTemplatePublishService
from app.modules.ai.schemas import (
    EidonPublishedPatternArtifactRecordDTO,
    EidonTemplatePublishRequestDTO,
    EidonTemplatePublishResponseDTO,
)
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


class _SubmissionRow:
    def __init__(self, *, status: str = "REVIEW_APPROVED", features: dict | None = None) -> None:
        self.id = uuid.uuid4()
        self.tenant_id = "tenant-ai-001"
        self.source_capability = "EIDON_ORDER_INTAKE_FEEDBACK_LOOP_V1"
        self.submission_shape_version = "v1"
        self.pattern_version = "v1-feedback"
        self.template_fingerprint = "tpl-publish-001"
        self.status = status
        self.review_required = True
        self.quality_score = 81
        self.authoritative_publish_allowed = False
        self.rollback_from_submission_id = None
        self.de_identified_pattern_features_json = (
            features
            if features is not None
            else {
                "confirmed_count": 8,
                "corrected_count": 1,
            }
        )
        self.raw_tenant_document_included = False


def _token(*, roles: list[str], perms: list[str] | None = None, tenant_id: str | None = "platform") -> str:
    claims: dict[str, object] = {"sub": "superadmin@ops.local", "roles": roles}
    if perms is not None:
        claims["perms"] = perms
    if tenant_id is not None:
        claims["tenant_id"] = tenant_id
    return create_access_token(claims)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _publish_response_no_raw() -> EidonTemplatePublishResponseDTO:
    ts = datetime.now(timezone.utc).isoformat()
    return EidonTemplatePublishResponseDTO(
        ok=True,
        decision="PUBLISH_ARTIFACT_CREATED",
        artifact=EidonPublishedPatternArtifactRecordDTO(
            id="63199ea8-b67a-49cf-bbca-5ca31255d7a3",
            source_submission_id="1fe954af-1fef-4eaf-a0f6-d89374a9be67",
            tenant_id="tenant-ai-001",
            source_capability="EIDON_ORDER_INTAKE_FEEDBACK_LOOP_V1",
            submission_shape_version="v1",
            source_submission_status="REVIEW_APPROVED",
            pattern_version="v1-feedback",
            template_fingerprint="tpl-publish-001",
            quality_score=88,
            de_identified_pattern_features={"confirmed_count": 8},
            authoritative_publish_allowed=False,
            rollback_capable=True,
            rollback_from_submission_id=None,
            published_by="superadmin@ops.local",
            published_at=ts,
            created_at=ts,
            warnings=[],
        ),
        authoritative_publish_allowed=False,
        no_authoritative_publish_rule="eidon_pattern_publish_metadata_only_no_authoritative_publish",
        no_raw_document_rule="raw_tenant_document_not_allowed_in_publish_artifact",
        no_rollout_rule="publish_artifact_creation_does_not_trigger_distribution_or_rollout",
        system_truth_rule="ai_does_not_override_system_truth",
    )


def test_ai_template_publish_fails_from_non_approved_status(monkeypatch) -> None:
    svc = EidonTemplatePublishService()
    db = _FakeDB()
    source = _SubmissionRow(status="STAGED_REVIEW_REQUIRED")

    monkeypatch.setattr(svc, "_load_submission", lambda _db, _submission_id: source)
    monkeypatch.setattr(svc, "_find_existing_artifact", lambda _db, _source_submission_id: None)

    try:
        svc.publish(
            db=db,
            submission_id=str(source.id),
            actor="superadmin@ops.local",
            payload=EidonTemplatePublishRequestDTO(),
        )
        raise AssertionError("expected publish_requires_review_approved_status")
    except ValueError as exc:
        assert str(exc) == "publish_requires_review_approved_status"
    assert db.added == []


def test_ai_template_publish_fails_when_deidentified_features_missing(monkeypatch) -> None:
    svc = EidonTemplatePublishService()
    db = _FakeDB()
    source = _SubmissionRow(features={})

    monkeypatch.setattr(svc, "_load_submission", lambda _db, _submission_id: source)
    monkeypatch.setattr(svc, "_find_existing_artifact", lambda _db, _source_submission_id: None)

    try:
        svc.publish(
            db=db,
            submission_id=str(source.id),
            actor="superadmin@ops.local",
            payload=EidonTemplatePublishRequestDTO(),
        )
        raise AssertionError("expected de_identified_pattern_features_required")
    except ValueError as exc:
        assert str(exc) == "de_identified_pattern_features_required"
    assert db.added == []


def test_ai_template_publish_route_response_has_no_raw_document_leakage(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ai_router.order_template_publish_service, "publish", lambda **_kwargs: _publish_response_no_raw())

    try:
        client = TestClient(app)
        super_token = _token(roles=["SUPERADMIN"], perms=["AI.COPILOT"])
        r = client.post(
            "/ai/superadmin-copilot/template-submissions/1fe954af-1fef-4eaf-a0f6-d89374a9be67/publish",
            headers=_headers(super_token),
            json={"publish_note": "metadata only", "publish_shape_version": "v1"},
        )
        assert r.status_code == 200, r.text
        body = r.json() or {}
        artifact = body.get("artifact") or {}
        assert body.get("authoritative_publish_allowed") is False
        assert artifact.get("authoritative_publish_allowed") is False
        assert "raw_tenant_document_included" not in artifact
        assert "extracted_text" not in str(body).lower()
        assert db.commits == 1
    finally:
        app.dependency_overrides.clear()
