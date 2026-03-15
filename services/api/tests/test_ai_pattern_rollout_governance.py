from __future__ import annotations

import uuid
from datetime import datetime, timezone

import app.modules.ai.router as ai_router
from app.core.auth import create_access_token
from app.db import Base, models
from app.db.session import get_db_session
from app.main import app
from app.modules.ai.order_pattern_rollout_governance_service import EidonPatternRolloutGovernanceService
from app.modules.ai.schemas import (
    EidonPatternRolloutGovernanceRecordDTO,
    EidonPatternRolloutGovernanceRequestDTO,
    EidonPatternRolloutGovernanceResponseDTO,
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


class _DistributionRow:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.tenant_id = "tenant-ai-001"
        self.template_fingerprint = "tpl-rollout-001"
        self.pattern_version = "v1-feedback"
        self.distribution_status = "DISTRIBUTION_RECORDED"
        self.authoritative_publish_allowed = False
        self.distribution_meta_json = {
            "distribution_shape_version": "v1",
            "distribution_not_rollout": True,
            "distribution_not_activation": True,
            "metadata_only": True,
            "distribution_meta": {"review_batch": "2026-03-15"},
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


def _rollout_response() -> EidonPatternRolloutGovernanceResponseDTO:
    ts = datetime.now(timezone.utc).isoformat()
    return EidonPatternRolloutGovernanceResponseDTO(
        ok=True,
        decision="ROLLOUT_GOVERNANCE_RECORDED",
        record=EidonPatternRolloutGovernanceRecordDTO(
            id="6d17f23a-ad6d-4f70-b8f9-fec9f07fbe63",
            distribution_record_id="9b95315e-b638-4b76-b54d-c005c0182cb6",
            tenant_id="tenant-ai-001",
            template_fingerprint="tpl-rollout-001",
            pattern_version="v1-feedback",
            governance_status="ROLLOUT_GOVERNANCE_RECORDED",
            eligibility_decision="ELIGIBLE",
            governance_note="governance recorded",
            governance_meta={"risk_band": "low"},
            rollback_from_governance_record_id=None,
            recorded_by="superadmin@ops.local",
            recorded_at=ts,
            authoritative_publish_allowed=False,
        ),
        authoritative_publish_allowed=False,
        no_authoritative_publish_rule="eidon_pattern_rollout_governance_metadata_only_no_authoritative_publish",
        no_rollout_rule="rollout_governance_record_creation_does_not_trigger_rollout_execution",
        no_activation_rule="rollout_governance_record_creation_does_not_trigger_activation",
        no_tenant_runtime_mutation_rule="rollout_governance_record_must_not_mutate_tenant_runtime_state",
        system_truth_rule="ai_does_not_override_system_truth",
    )


def test_ai_pattern_rollout_governance_model_exists() -> None:
    assert hasattr(models, "EidonPatternRolloutGovernanceRecord")
    assert models.EidonPatternRolloutGovernanceRecord.__tablename__ == "eidon_pattern_rollout_governance_records"
    assert "eidon_pattern_rollout_governance_records" in set(Base.metadata.tables.keys())


def test_ai_pattern_rollout_governance_route_and_openapi_contract(registered_paths: set[str]) -> None:
    path = "/ai/superadmin-copilot/distribution-records/{record_id}/rollout-governance"
    assert path in registered_paths
    schema = app.openapi()
    route = (((schema.get("paths") or {}).get(path) or {}).get("post") or {})
    req_ref = ((((route.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref") or ""
    res_ref = (((((route.get("responses") or {}).get("200") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref") or ""
    assert req_ref.endswith("/EidonPatternRolloutGovernanceRequestDTO")
    assert res_ref.endswith("/EidonPatternRolloutGovernanceResponseDTO")


def test_ai_pattern_rollout_governance_superadmin_only_enforcement(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ai_router.order_pattern_rollout_governance_service,
        "record_rollout_governance",
        lambda **_kwargs: _rollout_response(),
    )
    try:
        client = TestClient(app)
        tenant_token = _token(roles=["TENANT_ADMIN"], perms=["AI.COPILOT"], tenant_id="tenant-ai-001")
        r = client.post(
            "/ai/superadmin-copilot/distribution-records/9b95315e-b638-4b76-b54d-c005c0182cb6/rollout-governance",
            headers=_headers(tenant_token),
            json={"eligibility_decision": "ELIGIBLE"},
        )
        assert r.status_code == 403, r.text
        assert (r.json() or {}).get("detail") == "superadmin_required"
    finally:
        app.dependency_overrides.clear()


def test_ai_pattern_rollout_governance_happy_path_distribution_record_immutable(monkeypatch) -> None:
    svc = EidonPatternRolloutGovernanceService()
    db = _FakeDB()
    distribution = _DistributionRow()
    snapshot = (
        distribution.tenant_id,
        distribution.template_fingerprint,
        distribution.pattern_version,
        distribution.distribution_status,
        distribution.authoritative_publish_allowed,
        dict(distribution.distribution_meta_json),
    )

    monkeypatch.setattr(svc, "_load_distribution_record", lambda _db, _record_id: distribution)
    monkeypatch.setattr(svc, "_find_existing_governance_record", lambda _db, distribution_record_id: None)
    monkeypatch.setattr(svc, "_ensure_rollback_reference_exists", lambda _db, _record_id: None)

    out = svc.record_rollout_governance(
        db=db,
        record_id=str(distribution.id),
        actor="superadmin@ops.local",
        payload=EidonPatternRolloutGovernanceRequestDTO(
            eligibility_decision="ELIGIBLE",
            governance_note="eligible by governance",
            governance_meta={"risk_band": "low"},
        ),
    )

    assert out.ok is True
    assert out.decision == "ROLLOUT_GOVERNANCE_RECORDED"
    assert out.record.governance_status == "ROLLOUT_GOVERNANCE_RECORDED"
    assert out.record.eligibility_decision == "ELIGIBLE"
    assert out.record.authoritative_publish_allowed is False
    assert out.authoritative_publish_allowed is False
    assert out.no_rollout_rule == "rollout_governance_record_creation_does_not_trigger_rollout_execution"
    assert out.no_activation_rule == "rollout_governance_record_creation_does_not_trigger_activation"
    assert out.no_tenant_runtime_mutation_rule == "rollout_governance_record_must_not_mutate_tenant_runtime_state"
    assert len(db.added) == 1

    assert snapshot == (
        distribution.tenant_id,
        distribution.template_fingerprint,
        distribution.pattern_version,
        distribution.distribution_status,
        distribution.authoritative_publish_allowed,
        dict(distribution.distribution_meta_json),
    )

    dumped = str(out.model_dump()).lower()
    assert "raw_document" not in dumped
    assert "extracted_text" not in dumped
    assert "source_traceability" not in dumped
