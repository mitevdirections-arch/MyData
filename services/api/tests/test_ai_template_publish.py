from __future__ import annotations

import uuid
from datetime import datetime, timezone

import app.modules.ai.router as ai_router
from app.core.auth import create_access_token
from app.db import Base, models
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
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.tenant_id = "tenant-ai-001"
        self.source_capability = "EIDON_ORDER_INTAKE_FEEDBACK_LOOP_V1"
        self.submission_shape_version = "v1"
        self.pattern_version = "v1-feedback"
        self.template_fingerprint = "tpl-publish-001"
        self.status = "REVIEW_APPROVED"
        self.review_required = True
        self.quality_score = 92
        self.authoritative_publish_allowed = False
        self.rollback_from_submission_id = None
        self.de_identified_pattern_features_json = {
            "confirmed_count": 8,
            "corrected_count": 2,
            "layout_class": "CMR_STD",
        }
        self.raw_tenant_document_included = False


def _token(*, roles: list[str], perms: list[str] | None = None, tenant_id: str | None = "platform") -> str:
    claims: dict[str, object] = {
        "sub": "superadmin@ops.local" if "SUPERADMIN" in roles else "tenant@tenant.local",
        "roles": roles,
    }
    if perms is not None:
        claims["perms"] = perms
    if tenant_id is not None:
        claims["tenant_id"] = tenant_id
    return create_access_token(claims)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _publish_response() -> EidonTemplatePublishResponseDTO:
    ts = datetime.now(timezone.utc).isoformat()
    return EidonTemplatePublishResponseDTO(
        ok=True,
        decision="PUBLISH_ARTIFACT_CREATED",
        artifact=EidonPublishedPatternArtifactRecordDTO(
            id="a86e6fa1-5940-41a4-b356-42d429566901",
            source_submission_id="ff96f2e3-0f6c-4794-9fc6-e5ca0619ef8d",
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


def test_ai_template_publish_model_exists() -> None:
    assert hasattr(models, "EidonPatternPublishArtifact")
    assert models.EidonPatternPublishArtifact.__tablename__ == "eidon_pattern_publish_artifacts"
    assert "eidon_pattern_publish_artifacts" in set(Base.metadata.tables.keys())


def test_ai_template_publish_route_and_openapi_contract(registered_paths: set[str]) -> None:
    assert "/ai/superadmin-copilot/template-submissions/{submission_id}/publish" in registered_paths
    schema = app.openapi()
    route = (
        (((schema.get("paths") or {}).get("/ai/superadmin-copilot/template-submissions/{submission_id}/publish") or {})
         .get("post"))
        or {}
    )
    req_ref = ((((route.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref") or ""
    res_ref = (((((route.get("responses") or {}).get("200") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref") or ""
    assert req_ref.endswith("/EidonTemplatePublishRequestDTO")
    assert res_ref.endswith("/EidonTemplatePublishResponseDTO")


def test_ai_template_publish_superadmin_only_enforcement(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ai_router.order_template_publish_service, "publish", lambda **_kwargs: _publish_response())
    try:
        client = TestClient(app)
        tenant_token = _token(roles=["TENANT_ADMIN"], perms=["AI.COPILOT"], tenant_id="tenant-ai-001")
        r = client.post(
            "/ai/superadmin-copilot/template-submissions/ff96f2e3-0f6c-4794-9fc6-e5ca0619ef8d/publish",
            headers=_headers(tenant_token),
            json={"publish_note": "publish this pattern", "publish_shape_version": "v1"},
        )
        assert r.status_code == 403, r.text
        assert (r.json() or {}).get("detail") == "superadmin_required"
    finally:
        app.dependency_overrides.clear()


def test_ai_template_publish_approve_to_publish_happy_path(monkeypatch) -> None:
    svc = EidonTemplatePublishService()
    db = _FakeDB()
    source = _SubmissionRow()

    monkeypatch.setattr(svc, "_load_submission", lambda _db, _submission_id: source)
    monkeypatch.setattr(svc, "_find_existing_artifact", lambda _db, _source_submission_id: None)

    out = svc.publish(
        db=db,
        submission_id=str(source.id),
        actor="superadmin@ops.local",
        payload=EidonTemplatePublishRequestDTO(publish_note="approved->publish", publish_shape_version="v1"),
    )

    assert out.ok is True
    assert out.decision == "PUBLISH_ARTIFACT_CREATED"
    assert out.artifact.source_submission_status == "REVIEW_APPROVED"
    assert out.artifact.quality_score == 92
    assert out.artifact.authoritative_publish_allowed is False
    assert out.authoritative_publish_allowed is False
    assert len(db.added) == 1

    dumped = out.model_dump()
    assert "raw_tenant_document_included" not in str(dumped).lower()
