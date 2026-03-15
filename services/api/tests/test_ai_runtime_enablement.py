from __future__ import annotations

import uuid
from datetime import datetime, timezone

import app.modules.ai.router as ai_router
from app.core.auth import create_access_token
from app.db import Base, models
from app.db.session import get_db_session
from app.main import app
from app.modules.ai.order_runtime_enablement_service import EidonRuntimeEnablementService
from app.modules.ai.schemas import (
    EidonRuntimeEnablementRecordDTO,
    EidonRuntimeEnablementRequestDTO,
    EidonRuntimeEnablementResponseDTO,
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


class _ActivationRow:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.tenant_id = "tenant-ai-001"
        self.template_fingerprint = "tpl-runtime-001"
        self.pattern_version = "v1-feedback"
        self.activation_status = "ACTIVATION_RECORDED"
        self.authoritative_publish_allowed = False
        self.activation_meta_json = {
            "activation_shape_version": "v1",
            "activation_not_runtime_enablement": True,
            "activation_not_worker_execution": True,
            "metadata_only": True,
            "activation_meta": {"release_window": "manual"},
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


def _runtime_enablement_response() -> EidonRuntimeEnablementResponseDTO:
    ts = datetime.now(timezone.utc).isoformat()
    return EidonRuntimeEnablementResponseDTO(
        ok=True,
        decision="RUNTIME_ENABLEMENT_RECORDED",
        record=EidonRuntimeEnablementRecordDTO(
            id="4f2d0534-9c37-4c84-ae79-28fd385262f0",
            activation_record_id="88f63266-40e3-4c54-a250-e4b8a43913f4",
            tenant_id="tenant-ai-001",
            template_fingerprint="tpl-runtime-001",
            pattern_version="v1-feedback",
            runtime_enablement_status="RUNTIME_ENABLEMENT_RECORDED",
            runtime_decision="ENABLEABLE",
            runtime_note="metadata decision only",
            runtime_meta={"change_window": "manual"},
            rollback_from_runtime_enablement_record_id=None,
            recorded_by="superadmin@ops.local",
            recorded_at=ts,
            authoritative_publish_allowed=False,
        ),
        authoritative_publish_allowed=False,
        no_authoritative_publish_rule="eidon_runtime_enablement_metadata_only_no_authoritative_publish",
        no_actual_runtime_enablement_rule="runtime_enablement_record_creation_does_not_trigger_actual_runtime_enablement",
        no_runtime_worker_rule="runtime_enablement_record_creation_does_not_trigger_worker_or_scheduler",
        no_tenant_runtime_mutation_rule="runtime_enablement_record_must_not_mutate_tenant_runtime_state",
        system_truth_rule="ai_does_not_override_system_truth",
    )


def test_ai_runtime_enablement_model_exists() -> None:
    assert hasattr(models, "EidonRuntimeEnablementRecord")
    assert models.EidonRuntimeEnablementRecord.__tablename__ == "eidon_runtime_enablement_records"
    assert "eidon_runtime_enablement_records" in set(Base.metadata.tables.keys())


def test_ai_runtime_enablement_route_and_openapi_contract(registered_paths: set[str]) -> None:
    path = "/ai/superadmin-copilot/activation-records/{record_id}/runtime-enablement-record"
    assert path in registered_paths
    schema = app.openapi()
    route = (((schema.get("paths") or {}).get(path) or {}).get("post") or {})
    req_ref = ((((route.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref") or ""
    res_ref = (((((route.get("responses") or {}).get("200") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref") or ""
    assert req_ref.endswith("/EidonRuntimeEnablementRequestDTO")
    assert res_ref.endswith("/EidonRuntimeEnablementResponseDTO")


def test_ai_runtime_enablement_superadmin_only_enforcement(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ai_router.order_runtime_enablement_service,
        "record_runtime_enablement",
        lambda **_kwargs: _runtime_enablement_response(),
    )
    try:
        client = TestClient(app)
        tenant_token = _token(roles=["TENANT_ADMIN"], perms=["AI.COPILOT"], tenant_id="tenant-ai-001")
        r = client.post(
            "/ai/superadmin-copilot/activation-records/88f63266-40e3-4c54-a250-e4b8a43913f4/runtime-enablement-record",
            headers=_headers(tenant_token),
            json={"runtime_decision": "ENABLEABLE"},
        )
        assert r.status_code == 403, r.text
        assert (r.json() or {}).get("detail") == "superadmin_required"
    finally:
        app.dependency_overrides.clear()


def test_ai_runtime_enablement_happy_path_activation_record_immutable(monkeypatch) -> None:
    svc = EidonRuntimeEnablementService()
    db = _FakeDB()
    activation = _ActivationRow()
    snapshot = (
        activation.tenant_id,
        activation.template_fingerprint,
        activation.pattern_version,
        activation.activation_status,
        activation.authoritative_publish_allowed,
        dict(activation.activation_meta_json),
    )

    monkeypatch.setattr(svc, "_load_activation_record", lambda _db, _record_id: activation)
    monkeypatch.setattr(svc, "_find_existing_runtime_enablement_record", lambda _db, activation_record_id: None)
    monkeypatch.setattr(svc, "_ensure_rollback_reference_exists", lambda _db, _record_id: None)

    out = svc.record_runtime_enablement(
        db=db,
        record_id=str(activation.id),
        actor="superadmin@ops.local",
        payload=EidonRuntimeEnablementRequestDTO(
            runtime_decision="ENABLEABLE",
            runtime_note="runtime governance recorded",
            runtime_meta={"change_window": "manual"},
        ),
    )

    assert out.ok is True
    assert out.decision == "RUNTIME_ENABLEMENT_RECORDED"
    assert out.record.runtime_enablement_status == "RUNTIME_ENABLEMENT_RECORDED"
    assert out.record.runtime_decision == "ENABLEABLE"
    assert out.record.authoritative_publish_allowed is False
    assert out.authoritative_publish_allowed is False
    assert out.no_actual_runtime_enablement_rule == "runtime_enablement_record_creation_does_not_trigger_actual_runtime_enablement"
    assert out.no_runtime_worker_rule == "runtime_enablement_record_creation_does_not_trigger_worker_or_scheduler"
    assert out.no_tenant_runtime_mutation_rule == "runtime_enablement_record_must_not_mutate_tenant_runtime_state"
    assert len(db.added) == 1

    assert snapshot == (
        activation.tenant_id,
        activation.template_fingerprint,
        activation.pattern_version,
        activation.activation_status,
        activation.authoritative_publish_allowed,
        dict(activation.activation_meta_json),
    )

    dumped = str(out.model_dump()).lower()
    assert "raw_document" not in dumped
    assert "extracted_text" not in dumped
    assert "source_traceability" not in dumped
