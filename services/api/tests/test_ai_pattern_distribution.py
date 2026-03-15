from __future__ import annotations

import uuid
from datetime import datetime, timezone

import app.modules.ai.router as ai_router
from app.core.auth import create_access_token
from app.db import Base, models
from app.db.session import get_db_session
from app.main import app
from app.modules.ai.order_pattern_distribution_service import EidonPatternDistributionService
from app.modules.ai.schemas import (
    EidonPatternDistributionRecordDTO,
    EidonPatternDistributionRecordRequestDTO,
    EidonPatternDistributionResponseDTO,
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


class _ArtifactRow:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.tenant_id = "tenant-ai-001"
        self.template_fingerprint = "tpl-dist-001"
        self.pattern_version = "v1-feedback"
        self.source_submission_id = uuid.uuid4()
        self.authoritative_publish_allowed = False
        self.de_identified_pattern_features_json = {
            "confirmed_count": 8,
            "corrected_count": 2,
            "layout_class": "CMR_STD",
        }


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


def _distribution_response() -> EidonPatternDistributionResponseDTO:
    ts = datetime.now(timezone.utc).isoformat()
    return EidonPatternDistributionResponseDTO(
        ok=True,
        decision="DISTRIBUTION_RECORDED",
        record=EidonPatternDistributionRecordDTO(
            id="5d957d38-2037-4db8-87eb-a0980c34180a",
            publish_artifact_id="cb24c67b-4540-4f29-9f33-ba80cb7f5e1e",
            tenant_id="tenant-ai-001",
            template_fingerprint="tpl-dist-001",
            pattern_version="v1-feedback",
            distribution_status="DISTRIBUTION_RECORDED",
            distribution_note="governance approved",
            distribution_meta={"review_batch": "2026-03-15"},
            rollback_from_distribution_record_id=None,
            recorded_by="superadmin@ops.local",
            recorded_at=ts,
            authoritative_publish_allowed=False,
        ),
        authoritative_publish_allowed=False,
        no_authoritative_publish_rule="eidon_pattern_distribution_metadata_only_no_authoritative_publish",
        no_rollout_rule="distribution_record_creation_does_not_trigger_rollout",
        no_activation_rule="distribution_record_creation_does_not_trigger_activation",
        no_tenant_runtime_mutation_rule="distribution_record_must_not_mutate_tenant_runtime_state",
        system_truth_rule="ai_does_not_override_system_truth",
    )


def test_ai_pattern_distribution_model_exists() -> None:
    assert hasattr(models, "EidonPatternDistributionRecord")
    assert models.EidonPatternDistributionRecord.__tablename__ == "eidon_pattern_distribution_records"
    assert "eidon_pattern_distribution_records" in set(Base.metadata.tables.keys())


def test_ai_pattern_distribution_route_and_openapi_contract(registered_paths: set[str]) -> None:
    path = "/ai/superadmin-copilot/published-patterns/{artifact_id}/distribution-record"
    assert path in registered_paths
    schema = app.openapi()
    route = (((schema.get("paths") or {}).get(path) or {}).get("post") or {})
    req_ref = ((((route.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref") or ""
    res_ref = (((((route.get("responses") or {}).get("200") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref") or ""
    assert req_ref.endswith("/EidonPatternDistributionRecordRequestDTO")
    assert res_ref.endswith("/EidonPatternDistributionResponseDTO")


def test_ai_pattern_distribution_superadmin_only_enforcement(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ai_router.order_pattern_distribution_service,
        "record_distribution",
        lambda **_kwargs: _distribution_response(),
    )
    try:
        client = TestClient(app)
        tenant_token = _token(roles=["TENANT_ADMIN"], perms=["AI.COPILOT"], tenant_id="tenant-ai-001")
        r = client.post(
            "/ai/superadmin-copilot/published-patterns/cb24c67b-4540-4f29-9f33-ba80cb7f5e1e/distribution-record",
            headers=_headers(tenant_token),
            json={"distribution_note": "x"},
        )
        assert r.status_code == 403, r.text
        assert (r.json() or {}).get("detail") == "superadmin_required"
    finally:
        app.dependency_overrides.clear()


def test_ai_pattern_distribution_happy_path_immutable_publish_artifact(monkeypatch) -> None:
    svc = EidonPatternDistributionService()
    db = _FakeDB()
    artifact = _ArtifactRow()
    artifact_snapshot = (
        artifact.tenant_id,
        artifact.template_fingerprint,
        artifact.pattern_version,
        dict(artifact.de_identified_pattern_features_json),
        artifact.authoritative_publish_allowed,
    )

    monkeypatch.setattr(svc, "_load_publish_artifact", lambda _db, _artifact_id: artifact)
    monkeypatch.setattr(svc, "_find_record_by_artifact", lambda _db, publish_artifact_id: None)
    monkeypatch.setattr(svc, "_ensure_rollback_reference_exists", lambda _db, _record_id: None)

    out = svc.record_distribution(
        db=db,
        artifact_id=str(artifact.id),
        actor="superadmin@ops.local",
        payload=EidonPatternDistributionRecordRequestDTO(
            distribution_note="governance pass",
            distribution_meta={"review_batch": "2026-03-15", "risk_band": "low"},
        ),
    )

    assert out.ok is True
    assert out.decision == "DISTRIBUTION_RECORDED"
    assert out.record.distribution_status == "DISTRIBUTION_RECORDED"
    assert out.record.authoritative_publish_allowed is False
    assert out.authoritative_publish_allowed is False
    assert out.no_rollout_rule == "distribution_record_creation_does_not_trigger_rollout"
    assert out.no_activation_rule == "distribution_record_creation_does_not_trigger_activation"
    assert out.no_tenant_runtime_mutation_rule == "distribution_record_must_not_mutate_tenant_runtime_state"
    assert len(db.added) == 1

    # Publish artifact remains immutable.
    assert artifact_snapshot == (
        artifact.tenant_id,
        artifact.template_fingerprint,
        artifact.pattern_version,
        dict(artifact.de_identified_pattern_features_json),
        artifact.authoritative_publish_allowed,
    )

    dumped = str(out.model_dump()).lower()
    assert "raw_document" not in dumped
    assert "extracted_text" not in dumped
    assert "source_traceability" not in dumped
