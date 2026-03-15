from __future__ import annotations

import uuid

import app.modules.ai.router as ai_router
from app.core.auth import create_access_token
from app.db.session import get_db_session
from app.main import app
from app.modules.ai.order_pattern_rollout_governance_service import EidonPatternRolloutGovernanceService
from app.modules.ai.schemas import EidonPatternRolloutGovernanceRequestDTO
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
    def __init__(self, *, meta: dict | None = None) -> None:
        self.id = uuid.uuid4()
        self.tenant_id = "tenant-ai-001"
        self.template_fingerprint = "tpl-rollout-001"
        self.pattern_version = "v1-feedback"
        self.distribution_status = "DISTRIBUTION_RECORDED"
        self.authoritative_publish_allowed = False
        self.distribution_meta_json = (
            dict(meta)
            if isinstance(meta, dict)
            else {
                "distribution_shape_version": "v1",
                "distribution_not_rollout": True,
                "distribution_not_activation": True,
                "metadata_only": True,
                "distribution_meta": {"review_batch": "2026-03-15"},
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


def test_ai_pattern_rollout_governance_fails_when_distribution_missing(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ai_router.order_pattern_rollout_governance_service,
        "record_rollout_governance",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("distribution_record_not_found")),
    )

    try:
        client = TestClient(app)
        super_token = _token(roles=["SUPERADMIN"], perms=["AI.COPILOT"])
        r = client.post(
            "/ai/superadmin-copilot/distribution-records/97b0706f-05d0-4f4f-807d-88f95de853df/rollout-governance",
            headers=_headers(super_token),
            json={"eligibility_decision": "ELIGIBLE"},
        )
        assert r.status_code == 404, r.text
        assert (r.json() or {}).get("detail") == "distribution_record_not_found"
    finally:
        app.dependency_overrides.clear()


def test_ai_pattern_rollout_governance_duplicate_record_denied(monkeypatch) -> None:
    svc = EidonPatternRolloutGovernanceService()
    db = _FakeDB()
    row = _DistributionRow()

    monkeypatch.setattr(svc, "_load_distribution_record", lambda _db, _record_id: row)
    monkeypatch.setattr(svc, "_find_existing_governance_record", lambda _db, distribution_record_id: object())
    monkeypatch.setattr(svc, "_ensure_rollback_reference_exists", lambda _db, _record_id: None)

    try:
        svc.record_rollout_governance(
            db=db,
            record_id=str(row.id),
            actor="superadmin@ops.local",
            payload=EidonPatternRolloutGovernanceRequestDTO(eligibility_decision="ELIGIBLE"),
        )
        raise AssertionError("expected rollout_governance_record_already_exists")
    except ValueError as exc:
        assert str(exc) == "rollout_governance_record_already_exists"
    assert db.added == []


def test_ai_pattern_rollout_governance_invalid_eligibility_decision_denied(monkeypatch) -> None:
    svc = EidonPatternRolloutGovernanceService()
    db = _FakeDB()
    row = _DistributionRow()

    monkeypatch.setattr(svc, "_load_distribution_record", lambda _db, _record_id: row)
    monkeypatch.setattr(svc, "_find_existing_governance_record", lambda _db, distribution_record_id: None)
    monkeypatch.setattr(svc, "_ensure_rollback_reference_exists", lambda _db, _record_id: None)

    try:
        svc.record_rollout_governance(
            db=db,
            record_id=str(row.id),
            actor="superadmin@ops.local",
            payload=EidonPatternRolloutGovernanceRequestDTO(eligibility_decision="ALLOW"),
        )
        raise AssertionError("expected invalid_eligibility_decision")
    except ValueError as exc:
        assert str(exc) == "invalid_eligibility_decision"
    assert db.added == []


def test_ai_pattern_rollout_governance_denies_rollout_activation_markers(monkeypatch) -> None:
    svc = EidonPatternRolloutGovernanceService()
    db = _FakeDB()
    row = _DistributionRow()

    monkeypatch.setattr(svc, "_load_distribution_record", lambda _db, _record_id: row)
    monkeypatch.setattr(svc, "_find_existing_governance_record", lambda _db, distribution_record_id: None)
    monkeypatch.setattr(svc, "_ensure_rollback_reference_exists", lambda _db, _record_id: None)

    try:
        svc.record_rollout_governance(
            db=db,
            record_id=str(row.id),
            actor="superadmin@ops.local",
            payload=EidonPatternRolloutGovernanceRequestDTO(
                eligibility_decision="NOT_ELIGIBLE",
                governance_meta={"rollout_plan": "phase-1", "activation_state": "pending"},
            ),
        )
        raise AssertionError("expected governance_meta_governance_violation")
    except ValueError as exc:
        assert str(exc) == "governance_meta_governance_violation"
    assert db.added == []


def test_ai_pattern_rollout_governance_denies_tenant_target_list(monkeypatch) -> None:
    svc = EidonPatternRolloutGovernanceService()
    db = _FakeDB()
    row = _DistributionRow()

    monkeypatch.setattr(svc, "_load_distribution_record", lambda _db, _record_id: row)
    monkeypatch.setattr(svc, "_find_existing_governance_record", lambda _db, distribution_record_id: None)
    monkeypatch.setattr(svc, "_ensure_rollback_reference_exists", lambda _db, _record_id: None)

    try:
        svc.record_rollout_governance(
            db=db,
            record_id=str(row.id),
            actor="superadmin@ops.local",
            payload=EidonPatternRolloutGovernanceRequestDTO(
                eligibility_decision="NOT_ELIGIBLE",
                governance_meta={"tenant_targets": ["tenant-a", "tenant-b"]},
            ),
        )
        raise AssertionError("expected governance_meta_governance_violation")
    except ValueError as exc:
        assert str(exc) == "governance_meta_governance_violation"
    assert db.added == []
