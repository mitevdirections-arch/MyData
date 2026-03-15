from __future__ import annotations

import uuid

import app.modules.ai.router as ai_router
from app.core.auth import create_access_token
from app.db.session import get_db_session
from app.main import app
from app.modules.ai.order_pattern_distribution_service import EidonPatternDistributionService
from app.modules.ai.schemas import EidonPatternDistributionRecordRequestDTO
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
    def __init__(self, *, features: dict | None = None) -> None:
        self.id = uuid.uuid4()
        self.tenant_id = "tenant-ai-001"
        self.template_fingerprint = "tpl-dist-001"
        self.pattern_version = "v1-feedback"
        self.source_submission_id = uuid.uuid4()
        self.authoritative_publish_allowed = False
        self.de_identified_pattern_features_json = (
            dict(features)
            if isinstance(features, dict)
            else {"confirmed_count": 8, "corrected_count": 2}
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


def test_ai_pattern_distribution_fails_when_artifact_missing(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ai_router.order_pattern_distribution_service,
        "record_distribution",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("publish_artifact_not_found")),
    )

    try:
        client = TestClient(app)
        super_token = _token(roles=["SUPERADMIN"], perms=["AI.COPILOT"])
        r = client.post(
            "/ai/superadmin-copilot/published-patterns/97b0706f-05d0-4f4f-807d-88f95de853df/distribution-record",
            headers=_headers(super_token),
            json={"distribution_note": "x"},
        )
        assert r.status_code == 404, r.text
        assert (r.json() or {}).get("detail") == "publish_artifact_not_found"
    finally:
        app.dependency_overrides.clear()


def test_ai_pattern_distribution_duplicate_record_denied(monkeypatch) -> None:
    svc = EidonPatternDistributionService()
    db = _FakeDB()
    artifact = _ArtifactRow()

    monkeypatch.setattr(svc, "_load_publish_artifact", lambda _db, _artifact_id: artifact)
    monkeypatch.setattr(svc, "_find_record_by_artifact", lambda _db, publish_artifact_id: object())
    monkeypatch.setattr(svc, "_ensure_rollback_reference_exists", lambda _db, _record_id: None)

    try:
        svc.record_distribution(
            db=db,
            artifact_id=str(artifact.id),
            actor="superadmin@ops.local",
            payload=EidonPatternDistributionRecordRequestDTO(distribution_note="dup"),
        )
        raise AssertionError("expected distribution_record_already_exists")
    except ValueError as exc:
        assert str(exc) == "distribution_record_already_exists"
    assert db.added == []


def test_ai_pattern_distribution_fails_on_raw_contract_violation(monkeypatch) -> None:
    svc = EidonPatternDistributionService()
    db = _FakeDB()
    artifact = _ArtifactRow(features={"raw_text_snippet": "do-not-store"})

    monkeypatch.setattr(svc, "_load_publish_artifact", lambda _db, _artifact_id: artifact)
    monkeypatch.setattr(svc, "_find_record_by_artifact", lambda _db, publish_artifact_id: None)
    monkeypatch.setattr(svc, "_ensure_rollback_reference_exists", lambda _db, _record_id: None)

    try:
        svc.record_distribution(
            db=db,
            artifact_id=str(artifact.id),
            actor="superadmin@ops.local",
            payload=EidonPatternDistributionRecordRequestDTO(distribution_note="x"),
        )
        raise AssertionError("expected publish_artifact_contains_raw_tenant_data")
    except ValueError as exc:
        assert str(exc) == "publish_artifact_contains_raw_tenant_data"
    assert db.added == []


def test_ai_pattern_distribution_fails_on_raw_distribution_meta(monkeypatch) -> None:
    svc = EidonPatternDistributionService()
    db = _FakeDB()
    artifact = _ArtifactRow()

    monkeypatch.setattr(svc, "_load_publish_artifact", lambda _db, _artifact_id: artifact)
    monkeypatch.setattr(svc, "_find_record_by_artifact", lambda _db, publish_artifact_id: None)
    monkeypatch.setattr(svc, "_ensure_rollback_reference_exists", lambda _db, _record_id: None)

    try:
        svc.record_distribution(
            db=db,
            artifact_id=str(artifact.id),
            actor="superadmin@ops.local",
            payload=EidonPatternDistributionRecordRequestDTO(
                distribution_note="x",
                distribution_meta={"source_traceability_dump": "do-not-store"},
            ),
        )
        raise AssertionError("expected distribution_meta_contains_raw_tenant_data")
    except ValueError as exc:
        assert str(exc) == "distribution_meta_contains_raw_tenant_data"
    assert db.added == []


def test_ai_pattern_distribution_fails_on_rollout_activation_markers(monkeypatch) -> None:
    svc = EidonPatternDistributionService()
    db = _FakeDB()
    artifact = _ArtifactRow()

    monkeypatch.setattr(svc, "_load_publish_artifact", lambda _db, _artifact_id: artifact)
    monkeypatch.setattr(svc, "_find_record_by_artifact", lambda _db, publish_artifact_id: None)
    monkeypatch.setattr(svc, "_ensure_rollback_reference_exists", lambda _db, _record_id: None)

    try:
        svc.record_distribution(
            db=db,
            artifact_id=str(artifact.id),
            actor="superadmin@ops.local",
            payload=EidonPatternDistributionRecordRequestDTO(
                distribution_note="x",
                distribution_meta={"rollout_plan": "phase-1", "activation_state": "pending"},
            ),
        )
        raise AssertionError("expected distribution_meta_governance_violation")
    except ValueError as exc:
        assert str(exc) == "distribution_meta_governance_violation"
    assert db.added == []


def test_ai_pattern_distribution_fails_on_tenant_target_list(monkeypatch) -> None:
    svc = EidonPatternDistributionService()
    db = _FakeDB()
    artifact = _ArtifactRow()

    monkeypatch.setattr(svc, "_load_publish_artifact", lambda _db, _artifact_id: artifact)
    monkeypatch.setattr(svc, "_find_record_by_artifact", lambda _db, publish_artifact_id: None)
    monkeypatch.setattr(svc, "_ensure_rollback_reference_exists", lambda _db, _record_id: None)

    try:
        svc.record_distribution(
            db=db,
            artifact_id=str(artifact.id),
            actor="superadmin@ops.local",
            payload=EidonPatternDistributionRecordRequestDTO(
                distribution_note="x",
                distribution_meta={"tenant_targets": ["tenant-a", "tenant-b"]},
            ),
        )
        raise AssertionError("expected distribution_meta_governance_violation")
    except ValueError as exc:
        assert str(exc) == "distribution_meta_governance_violation"
    assert db.added == []
