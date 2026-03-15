from __future__ import annotations

import uuid

import app.modules.ai.router as ai_router
from app.core.auth import create_access_token
from app.db.session import get_db_session
from app.main import app
from app.modules.ai.order_runtime_enablement_service import EidonRuntimeEnablementService
from app.modules.ai.schemas import EidonRuntimeEnablementRequestDTO
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
    def __init__(self, *, meta: dict | None = None) -> None:
        self.id = uuid.uuid4()
        self.tenant_id = "tenant-ai-001"
        self.template_fingerprint = "tpl-runtime-001"
        self.pattern_version = "v1-feedback"
        self.activation_status = "ACTIVATION_RECORDED"
        self.authoritative_publish_allowed = False
        self.activation_meta_json = (
            dict(meta)
            if isinstance(meta, dict)
            else {
                "activation_shape_version": "v1",
                "activation_not_runtime_enablement": True,
                "activation_not_worker_execution": True,
                "metadata_only": True,
                "activation_meta": {"release_window": "manual"},
            }
        )


def _token(*, roles: list[str], perms: list[str] | None = None, tenant_id: str | None = "platform") -> str:
    claims: dict[str, object] = {"sub": "superadmin@ops.local", "roles": roles}
    if perms is not None:
        claims["perms"] = perms
    if tenant_id is not None:
        claims["tenant_id"] = tenant_id
    return create_access_token(claims)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_ai_runtime_enablement_fails_when_activation_record_missing(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ai_router.order_runtime_enablement_service,
        "record_runtime_enablement",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("activation_record_not_found")),
    )

    try:
        client = TestClient(app)
        super_token = _token(roles=["SUPERADMIN"], perms=["AI.COPILOT"])
        r = client.post(
            "/ai/superadmin-copilot/activation-records/97b0706f-05d0-4f4f-807d-88f95de853df/runtime-enablement-record",
            headers=_headers(super_token),
            json={"runtime_decision": "ENABLEABLE"},
        )
        assert r.status_code == 404, r.text
        assert (r.json() or {}).get("detail") == "activation_record_not_found"
    finally:
        app.dependency_overrides.clear()


def test_ai_runtime_enablement_duplicate_record_denied(monkeypatch) -> None:
    svc = EidonRuntimeEnablementService()
    db = _FakeDB()
    row = _ActivationRow()

    monkeypatch.setattr(svc, "_load_activation_record", lambda _db, _record_id: row)
    monkeypatch.setattr(svc, "_find_existing_runtime_enablement_record", lambda _db, activation_record_id: object())
    monkeypatch.setattr(svc, "_ensure_rollback_reference_exists", lambda _db, _record_id: None)

    try:
        svc.record_runtime_enablement(
            db=db,
            record_id=str(row.id),
            actor="superadmin@ops.local",
            payload=EidonRuntimeEnablementRequestDTO(runtime_decision="ENABLEABLE"),
        )
        raise AssertionError("expected runtime_enablement_record_already_exists")
    except ValueError as exc:
        assert str(exc) == "runtime_enablement_record_already_exists"
    assert db.added == []


def test_ai_runtime_enablement_invalid_runtime_decision_denied(monkeypatch) -> None:
    svc = EidonRuntimeEnablementService()
    db = _FakeDB()
    row = _ActivationRow()

    monkeypatch.setattr(svc, "_load_activation_record", lambda _db, _record_id: row)
    monkeypatch.setattr(svc, "_find_existing_runtime_enablement_record", lambda _db, activation_record_id: None)
    monkeypatch.setattr(svc, "_ensure_rollback_reference_exists", lambda _db, _record_id: None)

    try:
        svc.record_runtime_enablement(
            db=db,
            record_id=str(row.id),
            actor="superadmin@ops.local",
            payload=EidonRuntimeEnablementRequestDTO(runtime_decision="ALLOW_NOW"),
        )
        raise AssertionError("expected invalid_runtime_decision")
    except ValueError as exc:
        assert str(exc) == "invalid_runtime_decision"
    assert db.added == []


def test_ai_runtime_enablement_denies_rollout_activation_runtime_markers(monkeypatch) -> None:
    svc = EidonRuntimeEnablementService()
    db = _FakeDB()
    row = _ActivationRow()

    monkeypatch.setattr(svc, "_load_activation_record", lambda _db, _record_id: row)
    monkeypatch.setattr(svc, "_find_existing_runtime_enablement_record", lambda _db, activation_record_id: None)
    monkeypatch.setattr(svc, "_ensure_rollback_reference_exists", lambda _db, _record_id: None)

    try:
        svc.record_runtime_enablement(
            db=db,
            record_id=str(row.id),
            actor="superadmin@ops.local",
            payload=EidonRuntimeEnablementRequestDTO(
                runtime_decision="NOT_ENABLEABLE",
                runtime_meta={
                    "rollout_plan": "phase-2",
                    "activation_state": "pending",
                    "enable_runtime": True,
                    "runtime_apply": "now",
                },
            ),
        )
        raise AssertionError("expected runtime_meta_governance_violation")
    except ValueError as exc:
        assert str(exc) == "runtime_meta_governance_violation"
    assert db.added == []


def test_ai_runtime_enablement_denies_tenant_target_list(monkeypatch) -> None:
    svc = EidonRuntimeEnablementService()
    db = _FakeDB()
    row = _ActivationRow()

    monkeypatch.setattr(svc, "_load_activation_record", lambda _db, _record_id: row)
    monkeypatch.setattr(svc, "_find_existing_runtime_enablement_record", lambda _db, activation_record_id: None)
    monkeypatch.setattr(svc, "_ensure_rollback_reference_exists", lambda _db, _record_id: None)

    try:
        svc.record_runtime_enablement(
            db=db,
            record_id=str(row.id),
            actor="superadmin@ops.local",
            payload=EidonRuntimeEnablementRequestDTO(
                runtime_decision="NOT_ENABLEABLE",
                runtime_meta={"tenant_targets": ["tenant-a", "tenant-b"]},
            ),
        )
        raise AssertionError("expected runtime_meta_governance_violation")
    except ValueError as exc:
        assert str(exc) == "runtime_meta_governance_violation"
    assert db.added == []
