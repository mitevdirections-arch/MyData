from __future__ import annotations

from datetime import datetime, timezone

import app.modules.ai.order_quality_analysis_service as analysis_service_mod
import app.modules.ai.router as ai_router
from app.core.auth import create_access_token
from app.db.session import get_db_session
from app.main import app
from app.modules.ai.schemas import EidonQualitySummaryResponseDTO, EidonQualitySummaryRowDTO
from fastapi.testclient import TestClient


class _FakeQuery:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = list(rows)
        self.limit_value: int | None = None

    def filter(self, *_args, **_kwargs) -> "_FakeQuery":
        return self

    def group_by(self, *_args, **_kwargs) -> "_FakeQuery":
        return self

    def order_by(self, *_args, **_kwargs) -> "_FakeQuery":
        return self

    def limit(self, value: int) -> "_FakeQuery":
        self.limit_value = int(value)
        return self

    def all(self) -> list[tuple]:
        return list(self._rows)


class _FakeDB:
    def __init__(self, rows: list[tuple] | None = None) -> None:
        self.commits = 0
        self._rows = list(rows or [])
        self.query_obj: _FakeQuery | None = None

    def query(self, *_args, **_kwargs) -> _FakeQuery:
        self.query_obj = _FakeQuery(self._rows)
        return self.query_obj

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


def test_ai_quality_summary_route_and_openapi_contract(registered_paths: set[str]) -> None:
    assert "/ai/superadmin-copilot/quality-events/summary" in registered_paths
    schema = app.openapi()
    route = ((schema.get("paths") or {}).get("/ai/superadmin-copilot/quality-events/summary") or {}).get("get") or {}
    ref = (((((route.get("responses") or {}).get("200") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref") or ""
    assert ref.endswith("/EidonQualitySummaryResponseDTO")


def test_ai_quality_summary_superadmin_only_access(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ai_router.order_quality_analysis_service,
        "summarize",
        lambda **_kwargs: EidonQualitySummaryResponseDTO(
            ok=True,
            event_type="ORDER_INTAKE_FEEDBACK_V1",
            limit=50,
            rows=[],
            generated_at="2026-03-15T00:00:00+00:00",
        ),
    )

    try:
        client = TestClient(app)
        tenant_token = _token(roles=["TENANT_ADMIN"], perms=["AI.COPILOT"], tenant_id="tenant-ai-001")
        r = client.get("/ai/superadmin-copilot/quality-events/summary", headers=_headers(tenant_token))
        assert r.status_code == 403, r.text
        assert (r.json() or {}).get("detail") == "superadmin_required"
    finally:
        app.dependency_overrides.clear()


def test_ai_quality_summary_happy_path_no_raw_leakage(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ai_router.order_quality_analysis_service,
        "summarize",
        lambda **_kwargs: EidonQualitySummaryResponseDTO(
            ok=True,
            event_type="ORDER_INTAKE_FEEDBACK_V1",
            limit=50,
            rows=[
                EidonQualitySummaryRowDTO(
                    template_fingerprint="tpl-a1",
                    event_count=5,
                    total_confirmed_count=11,
                    total_corrected_count=3,
                    total_unresolved_count=2,
                    human_confirmation_true_count=5,
                    correction_rate=0.1875,
                    last_event_at="2026-03-15T10:00:00+00:00",
                )
            ],
            generated_at="2026-03-15T10:00:01+00:00",
        ),
    )

    try:
        client = TestClient(app)
        super_token = _token(roles=["SUPERADMIN"], perms=["AI.COPILOT"], tenant_id="platform")
        r = client.get(
            "/ai/superadmin-copilot/quality-events/summary",
            headers=_headers(super_token),
            params={"event_type": "ORDER_INTAKE_FEEDBACK_V1", "limit": 50},
        )
        assert r.status_code == 200, r.text

        payload = r.json() or {}
        assert payload.get("event_type") == "ORDER_INTAKE_FEEDBACK_V1"
        assert payload.get("limit") == 50
        rows = payload.get("rows") or []
        assert len(rows) == 1
        row = rows[0] or {}
        assert set(row.keys()) == {
            "template_fingerprint",
            "event_count",
            "total_confirmed_count",
            "total_corrected_count",
            "total_unresolved_count",
            "human_confirmation_true_count",
            "correction_rate",
            "last_event_at",
        }
        dumped = str(payload).lower()
        assert "source_traceability" not in dumped
        assert "corrected_value" not in dumped
        assert "extracted_text" not in dumped
        assert "confidence_adjustments_summary_json" not in dumped
    finally:
        app.dependency_overrides.clear()


def test_ai_quality_summary_limit_guard(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    captured_limits: list[int] = []

    def _fake_summary(**kwargs) -> EidonQualitySummaryResponseDTO:
        captured_limits.append(int(kwargs.get("limit", -1)))
        return EidonQualitySummaryResponseDTO(
            ok=True,
            event_type=str(kwargs.get("event_type") or "ORDER_INTAKE_FEEDBACK_V1"),
            limit=int(kwargs.get("limit") or 0),
            rows=[],
            generated_at="2026-03-15T00:00:00+00:00",
        )

    monkeypatch.setattr(
        ai_router.order_quality_analysis_service,
        "summarize",
        _fake_summary,
    )

    try:
        client = TestClient(app)
        super_token = _token(roles=["SUPERADMIN"], perms=["AI.COPILOT"], tenant_id="platform")
        r_low = client.get("/ai/superadmin-copilot/quality-events/summary", headers=_headers(super_token), params={"limit": 0})
        assert r_low.status_code == 200, r_low.text
        assert (r_low.json() or {}).get("limit") == 1

        r_high = client.get("/ai/superadmin-copilot/quality-events/summary", headers=_headers(super_token), params={"limit": 201})
        assert r_high.status_code == 200, r_high.text
        assert (r_high.json() or {}).get("limit") == 200
        assert captured_limits == [1, 200]
    finally:
        app.dependency_overrides.clear()


def test_ai_quality_analysis_service_correction_rate_and_empty_result() -> None:
    svc = analysis_service_mod.EidonOrderQualityAnalysisService()
    dt = datetime(2026, 3, 15, 9, 30, tzinfo=timezone.utc)
    db = _FakeDB(
        rows=[
            ("tpl-001", 4, 10, 3, 2, 4, dt),
            ("tpl-zero", 1, 0, 0, 0, 0, None),
        ]
    )

    out = svc.summarize(db=db, event_type="ORDER_INTAKE_FEEDBACK_V1", limit=50)
    assert out.ok is True
    assert out.event_type == "ORDER_INTAKE_FEEDBACK_V1"
    assert out.limit == 50
    assert len(out.rows) == 2
    assert out.rows[0].correction_rate == 0.2
    assert out.rows[0].last_event_at == dt.isoformat()
    assert out.rows[1].correction_rate is None
    assert out.rows[1].last_event_at is None

    out_empty = svc.summarize(db=_FakeDB(rows=[]), event_type="ORDER_INTAKE_FEEDBACK_V1", limit=50)
    assert out_empty.ok is True
    assert out_empty.rows == []


def test_ai_quality_analysis_service_limit_clamping() -> None:
    svc = analysis_service_mod.EidonOrderQualityAnalysisService()

    db_low = _FakeDB(rows=[("tpl-001", 1, 0, 0, 0, 0, None)])
    out_low = svc.summarize(db=db_low, event_type="ORDER_INTAKE_FEEDBACK_V1", limit=0)
    assert out_low.limit == 1
    assert db_low.query_obj is not None
    assert db_low.query_obj.limit_value == 1

    db_high = _FakeDB(rows=[("tpl-001", 1, 0, 0, 0, 0, None)])
    out_high = svc.summarize(db=db_high, event_type="ORDER_INTAKE_FEEDBACK_V1", limit=999)
    assert out_high.limit == 200
    assert db_high.query_obj is not None
    assert db_high.query_obj.limit_value == 200
