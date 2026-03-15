from __future__ import annotations

import uuid
from datetime import datetime, timezone

import app.modules.ai.router as ai_router
from app.core.auth import create_access_token
from app.db import Base, models
from app.db.session import get_db_session
from app.main import app
from app.modules.ai.order_pattern_activation_service import EidonPatternActivationService
from app.modules.ai.schemas import (
    EidonPatternActivationRecordDTO,
    EidonPatternActivationRequestDTO,
    EidonPatternActivationResponseDTO,
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


class _RolloutGovernanceRow:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.tenant_id = "tenant-ai-001"
        self.template_fingerprint = "tpl-activation-001"
        self.pattern_version = "v1-feedback"
        self.governance_status = "ROLLOUT_GOVERNANCE_RECORDED"
        self.eligibility_decision = "ELIGIBLE"
        self.authoritative_publish_allowed = False
        self.governance_meta_json = {
            "governance_shape_version": "v1",
            "governance_not_rollout_execution": True,
            "governance_not_activation": True,
            "metadata_only": True,
            "eligibility_decision": "ELIGIBLE",
            "governance_meta": {"risk_band": "low"},
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


def _activation_response() -> EidonPatternActivationResponseDTO:
    ts = datetime.now(timezone.utc).isoformat()
    return EidonPatternActivationResponseDTO(
        ok=True,
        decision="ACTIVATION_RECORDED",
        record=EidonPatternActivationRecordDTO(
            id="9cdbe665-f2dc-4f27-8715-f9bf6b8875ea",
            rollout_governance_record_id="78cfcf8b-7fe9-4708-9bbf-1308c7d6fb10",
            tenant_id="tenant-ai-001",
            template_fingerprint="tpl-activation-001",
            pattern_version="v1-feedback",
            activation_status="ACTIVATION_RECORDED",
            activation_note="metadata activation recorded",
            activation_meta={"release_window": "manual"},
            rollback_from_activation_record_id=None,
            recorded_by="superadmin@ops.local",
            recorded_at=ts,
            authoritative_publish_allowed=False,
        ),
        authoritative_publish_allowed=False,
        no_authoritative_publish_rule="eidon_pattern_activation_metadata_only_no_authoritative_publish",
        no_runtime_enablement_rule="activation_record_creation_does_not_trigger_runtime_enablement",
        no_activation_worker_rule="activation_record_creation_does_not_trigger_worker_or_scheduler",
        no_tenant_runtime_mutation_rule="activation_record_must_not_mutate_tenant_runtime_state",
        system_truth_rule="ai_does_not_override_system_truth",
    )


def test_ai_pattern_activation_model_exists() -> None:
    assert hasattr(models, "EidonPatternActivationRecord")
    assert models.EidonPatternActivationRecord.__tablename__ == "eidon_pattern_activation_records"
    assert "eidon_pattern_activation_records" in set(Base.metadata.tables.keys())


def test_ai_pattern_activation_route_and_openapi_contract(registered_paths: set[str]) -> None:
    path = "/ai/superadmin-copilot/rollout-governance-records/{record_id}/activation-record"
    assert path in registered_paths
    schema = app.openapi()
    route = (((schema.get("paths") or {}).get(path) or {}).get("post") or {})
    req_ref = ((((route.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref") or ""
    res_ref = (((((route.get("responses") or {}).get("200") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref") or ""
    assert req_ref.endswith("/EidonPatternActivationRequestDTO")
    assert res_ref.endswith("/EidonPatternActivationResponseDTO")


def test_ai_pattern_activation_superadmin_only_enforcement(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ai_router.order_pattern_activation_service,
        "record_activation",
        lambda **_kwargs: _activation_response(),
    )
    try:
        client = TestClient(app)
        tenant_token = _token(roles=["TENANT_ADMIN"], perms=["AI.COPILOT"], tenant_id="tenant-ai-001")
        r = client.post(
            "/ai/superadmin-copilot/rollout-governance-records/78cfcf8b-7fe9-4708-9bbf-1308c7d6fb10/activation-record",
            headers=_headers(tenant_token),
            json={"activation_note": "x"},
        )
        assert r.status_code == 403, r.text
        assert (r.json() or {}).get("detail") == "superadmin_required"
    finally:
        app.dependency_overrides.clear()


def test_ai_pattern_activation_happy_path_governance_record_immutable(monkeypatch) -> None:
    svc = EidonPatternActivationService()
    db = _FakeDB()
    rollout_governance = _RolloutGovernanceRow()
    snapshot = (
        rollout_governance.tenant_id,
        rollout_governance.template_fingerprint,
        rollout_governance.pattern_version,
        rollout_governance.governance_status,
        rollout_governance.eligibility_decision,
        rollout_governance.authoritative_publish_allowed,
        dict(rollout_governance.governance_meta_json),
    )

    monkeypatch.setattr(svc, "_load_rollout_governance_record", lambda _db, _record_id: rollout_governance)
    monkeypatch.setattr(svc, "_find_existing_activation_record", lambda _db, rollout_governance_record_id: None)
    monkeypatch.setattr(svc, "_ensure_rollback_reference_exists", lambda _db, _record_id: None)

    out = svc.record_activation(
        db=db,
        record_id=str(rollout_governance.id),
        actor="superadmin@ops.local",
        payload=EidonPatternActivationRequestDTO(
            activation_note="ready for controlled enablement window",
            activation_meta={"release_window": "manual"},
        ),
    )

    assert out.ok is True
    assert out.decision == "ACTIVATION_RECORDED"
    assert out.record.activation_status == "ACTIVATION_RECORDED"
    assert out.record.authoritative_publish_allowed is False
    assert out.authoritative_publish_allowed is False
    assert out.no_runtime_enablement_rule == "activation_record_creation_does_not_trigger_runtime_enablement"
    assert out.no_activation_worker_rule == "activation_record_creation_does_not_trigger_worker_or_scheduler"
    assert out.no_tenant_runtime_mutation_rule == "activation_record_must_not_mutate_tenant_runtime_state"
    assert len(db.added) == 1

    assert snapshot == (
        rollout_governance.tenant_id,
        rollout_governance.template_fingerprint,
        rollout_governance.pattern_version,
        rollout_governance.governance_status,
        rollout_governance.eligibility_decision,
        rollout_governance.authoritative_publish_allowed,
        dict(rollout_governance.governance_meta_json),
    )

    dumped = str(out.model_dump()).lower()
    assert "raw_document" not in dumped
    assert "extracted_text" not in dumped
    assert "source_traceability" not in dumped

