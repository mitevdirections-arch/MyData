from __future__ import annotations

from datetime import datetime, timezone

import app.modules.ai.order_runtime_decision_surface_service as decision_surface_service_mod
import app.modules.ai.router as ai_router
from app.core.auth import create_access_token
from app.db.session import get_db_session
from app.main import app
from app.modules.ai.schemas import (
    EidonRuntimeDecisionSurfaceResponseDTO,
    EidonRuntimeDecisionSurfaceRowDTO,
)
from fastapi.testclient import TestClient


class _FakeQuery:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = list(rows)

    def outerjoin(self, *_args, **_kwargs) -> "_FakeQuery":
        return self

    def group_by(self, *_args, **_kwargs) -> "_FakeQuery":
        return self

    def all(self) -> list[tuple]:
        return list(self._rows)


class _FakeDB:
    def __init__(self, rows: list[tuple] | None = None) -> None:
        self.commits = 0
        self._rows = list(rows or [])

    def query(self, *_args, **_kwargs) -> _FakeQuery:
        return _FakeQuery(self._rows)

    def commit(self) -> None:
        self.commits += 1


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


def test_ai_runtime_decision_surface_route_and_openapi_contract(registered_paths: set[str]) -> None:
    assert "/ai/superadmin-copilot/runtime-decision-surface" in registered_paths
    schema = app.openapi()
    route = ((schema.get("paths") or {}).get("/ai/superadmin-copilot/runtime-decision-surface") or {}).get("get") or {}
    ref = (((((route.get("responses") or {}).get("200") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref") or ""
    assert ref.endswith("/EidonRuntimeDecisionSurfaceResponseDTO")


def test_ai_runtime_decision_surface_superadmin_only_access(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ai_router.order_runtime_decision_surface_service,
        "summarize",
        lambda **_kwargs: EidonRuntimeDecisionSurfaceResponseDTO(
            ok=True,
            limit=50,
            rows=[],
            generated_at="2026-03-15T00:00:00+00:00",
        ),
    )

    try:
        client = TestClient(app)
        tenant_token = _token(roles=["TENANT_ADMIN"], perms=["AI.COPILOT"], tenant_id="tenant-ai-001")
        r = client.get("/ai/superadmin-copilot/runtime-decision-surface", headers=_headers(tenant_token))
        assert r.status_code == 403, r.text
        assert (r.json() or {}).get("detail") == "superadmin_required"
    finally:
        app.dependency_overrides.clear()


def test_ai_runtime_decision_surface_happy_path_no_raw_leakage(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ai_router.order_runtime_decision_surface_service,
        "summarize",
        lambda **_kwargs: EidonRuntimeDecisionSurfaceResponseDTO(
            ok=True,
            limit=50,
            rows=[
                EidonRuntimeDecisionSurfaceRowDTO(
                    template_fingerprint="tpl-a1",
                    pattern_version="v1",
                    publish_recorded=True,
                    distribution_recorded=True,
                    rollout_governance_recorded=True,
                    rollout_eligibility_decision="ELIGIBLE",
                    activation_recorded=True,
                    runtime_enablement_recorded=True,
                    runtime_decision="ENABLEABLE",
                    last_governance_event_at="2026-03-15T10:00:00+00:00",
                )
            ],
            generated_at="2026-03-15T10:00:01+00:00",
        ),
    )

    try:
        client = TestClient(app)
        super_token = _token(roles=["SUPERADMIN"], perms=["AI.COPILOT"], tenant_id="platform")
        r = client.get(
            "/ai/superadmin-copilot/runtime-decision-surface",
            headers=_headers(super_token),
            params={"limit": 50},
        )
        assert r.status_code == 200, r.text

        payload = r.json() or {}
        assert payload.get("limit") == 50
        rows = payload.get("rows") or []
        assert len(rows) == 1
        row = rows[0] or {}
        assert set(row.keys()) == {
            "template_fingerprint",
            "pattern_version",
            "publish_recorded",
            "distribution_recorded",
            "rollout_governance_recorded",
            "rollout_eligibility_decision",
            "activation_recorded",
            "runtime_enablement_recorded",
            "runtime_decision",
            "last_governance_event_at",
        }
        dumped = str(payload).lower()
        assert "source_traceability" not in dumped
        assert "distribution_meta" not in dumped
        assert "activation_meta" not in dumped
        assert "runtime_meta" not in dumped
        assert "corrected_value" not in dumped
        assert "extracted_text" not in dumped
    finally:
        app.dependency_overrides.clear()


def test_ai_runtime_decision_surface_limit_guard(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    captured_limits: list[int] = []

    def _fake_summary(**kwargs) -> EidonRuntimeDecisionSurfaceResponseDTO:
        captured_limits.append(int(kwargs.get("limit", -1)))
        return EidonRuntimeDecisionSurfaceResponseDTO(
            ok=True,
            limit=int(kwargs.get("limit") or 0),
            rows=[],
            generated_at="2026-03-15T00:00:00+00:00",
        )

    monkeypatch.setattr(
        ai_router.order_runtime_decision_surface_service,
        "summarize",
        _fake_summary,
    )

    try:
        client = TestClient(app)
        super_token = _token(roles=["SUPERADMIN"], perms=["AI.COPILOT"], tenant_id="platform")
        r_low = client.get("/ai/superadmin-copilot/runtime-decision-surface", headers=_headers(super_token), params={"limit": 0})
        assert r_low.status_code == 200, r_low.text
        assert (r_low.json() or {}).get("limit") == 1

        r_high = client.get("/ai/superadmin-copilot/runtime-decision-surface", headers=_headers(super_token), params={"limit": 201})
        assert r_high.status_code == 200, r_high.text
        assert (r_high.json() or {}).get("limit") == 200
        assert captured_limits == [1, 200]
    finally:
        app.dependency_overrides.clear()


def test_runtime_decision_surface_service_empty_result_handling() -> None:
    svc = decision_surface_service_mod.EidonRuntimeDecisionSurfaceService()
    out = svc.summarize(db=_FakeDB(rows=[]), limit=50)
    assert out.ok is True
    assert out.limit == 50
    assert out.rows == []


def test_runtime_decision_surface_service_happy_path_sorting_and_summary() -> None:
    svc = decision_surface_service_mod.EidonRuntimeDecisionSurfaceService()
    dt_publish = datetime(2026, 3, 15, 9, 0, tzinfo=timezone.utc)
    dt_dist = datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc)
    dt_rollout = datetime(2026, 3, 15, 11, 0, tzinfo=timezone.utc)
    dt_activation = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
    dt_runtime = datetime(2026, 3, 15, 13, 0, tzinfo=timezone.utc)

    rows = [
        (
            "tpl-older",
            "v0",
            1,
            0,
            0,
            None,
            0,
            0,
            None,
            datetime(2026, 3, 15, 8, 0, tzinfo=timezone.utc),
            None,
            None,
            None,
            None,
        ),
        (
            "tpl-001",
            "v1",
            1,
            1,
            1,
            "ELIGIBLE",
            1,
            1,
            "ENABLEABLE",
            dt_publish,
            dt_dist,
            dt_rollout,
            dt_activation,
            dt_runtime,
        ),
    ]
    out = svc.summarize(db=_FakeDB(rows=rows), limit=50)

    assert out.ok is True
    assert out.limit == 50
    assert len(out.rows) == 2
    assert out.rows[0].template_fingerprint == "tpl-001"
    assert out.rows[0].pattern_version == "v1"
    assert out.rows[0].publish_recorded is True
    assert out.rows[0].distribution_recorded is True
    assert out.rows[0].rollout_governance_recorded is True
    assert out.rows[0].rollout_eligibility_decision == "ELIGIBLE"
    assert out.rows[0].activation_recorded is True
    assert out.rows[0].runtime_enablement_recorded is True
    assert out.rows[0].runtime_decision == "ENABLEABLE"
    assert out.rows[0].last_governance_event_at == dt_runtime.isoformat()
    assert out.rows[1].template_fingerprint == "tpl-older"
