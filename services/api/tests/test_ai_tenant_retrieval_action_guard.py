from __future__ import annotations

import app.core.middleware as core_middleware
import app.modules.ai.order_draft_assist_service as draft_assist_service_mod
import app.modules.ai.order_intake_feedback_service as intake_feedback_service_mod
import app.modules.ai.router as ai_router
import app.modules.ai.tenant_retrieval_action_guard as guard_mod
import app.modules.licensing.deps as licensing_deps
from app.core.auth import create_access_token
from app.db.session import get_db_session
from app.main import app
from fastapi.testclient import TestClient


class _FakeDB:
    def __init__(self, *, fail_on_add: bool = False) -> None:
        self.commits = 0
        self.added: list[object] = []
        self.fail_on_add = bool(fail_on_add)

    def add(self, obj: object) -> None:
        if self.fail_on_add:
            raise RuntimeError("db_add_failed")
        self.added.append(obj)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1


def _token(*, tenant_id: str | None, perms: list[str], sub: str = "worker@tenant.local") -> str:
    claims: dict[str, object] = {
        "sub": sub,
        "roles": ["WORKER"],
        "perms": perms,
    }
    if tenant_id is not None:
        claims["tenant_id"] = tenant_id
    return create_access_token(claims)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _allow_entitlement(_db, *, tenant_id: str, module_code: str) -> dict[str, object]:
    return {
        "allowed": True,
        "module_code": module_code,
        "reason": "module_license_active",
        "source": {"license_type": "MODULE_PAID", "license_id": "lic-ai-copilot"},
        "valid_to": "2026-12-31T00:00:00+00:00",
    }


def test_guard_service_allows_tenant_visible_order_reference(monkeypatch) -> None:
    svc = guard_mod.TenantRetrievalActionGuard()
    monkeypatch.setattr(
        svc,
        "_order_reference_visible_for_tenant",
        lambda **_kwargs: True,
    )
    out = svc.validate_order_reference_access(
        db=object(),  # type: ignore[arg-type]
        tenant_id="tenant-ai-001",
        order_reference_id="ord-visible-001",
    )
    assert out.allowed is True
    assert out.code == "allow"


def test_guard_service_hidden_object_safe_deny_for_missing_and_inaccessible(monkeypatch) -> None:
    svc = guard_mod.TenantRetrievalActionGuard()
    monkeypatch.setattr(
        svc,
        "_order_reference_visible_for_tenant",
        lambda **_kwargs: False,
    )

    missing_err: str | None = None
    inaccessible_err: str | None = None
    try:
        svc.validate_order_reference_access(
            db=object(),  # type: ignore[arg-type]
            tenant_id="tenant-ai-001",
            order_reference_id=None,
        )
    except ValueError as exc:
        missing_err = str(exc)

    try:
        svc.validate_order_reference_access(
            db=object(),  # type: ignore[arg-type]
            tenant_id="tenant-ai-001",
            order_reference_id="ord-hidden-001",
        )
    except ValueError as exc:
        inaccessible_err = str(exc)

    assert missing_err == guard_mod.OBJECT_REFERENCE_NOT_ACCESSIBLE
    assert inaccessible_err == guard_mod.OBJECT_REFERENCE_NOT_ACCESSIBLE


def test_draft_assist_guard_allow_valid_reference_no_success_regression(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        draft_assist_service_mod.tenant_retrieval_action_guard,
        "validate_order_reference_access",
        lambda **_kwargs: guard_mod.TenantRetrievalActionGuardResult(allowed=True, code="allow"),
    )

    payload = {
        "existing_order_draft_context": {
            "id": "ord-visible-001",
            "tenant_id": "tenant-ai-001",
            "order_no": "ORD-AI-CTX-001",
            "status": "DRAFT",
            "transport_mode": "ROAD",
            "direction": "OUTBOUND",
            "goods": {
                "goods_description": "General cargo",
                "packages_count": 10,
                "packing_method": "PALLETS",
                "marks_numbers": "MRK-001",
                "gross_weight_kg": 1000.0,
                "volume_m3": 12.5,
            },
            "is_dangerous_goods": False,
        }
    }
    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        r = client.post("/ai/tenant-copilot/order-draft-assist", headers=_headers(token), json=payload)
        assert r.status_code == 200, r.text
        assert (r.json() or {}).get("ok") is True
    finally:
        app.dependency_overrides.clear()


def test_draft_assist_guard_hidden_object_safe_deny_missing_vs_inaccessible(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        draft_assist_service_mod.tenant_retrieval_action_guard,
        "validate_order_reference_access",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError(guard_mod.OBJECT_REFERENCE_NOT_ACCESSIBLE)),
    )

    payload_missing = {
        "existing_order_draft_context": {
            "id": "",
            "tenant_id": "tenant-ai-001",
            "order_no": "ORD-AI-CTX-002",
            "status": "DRAFT",
        }
    }
    payload_inaccessible = {
        "existing_order_draft_context": {
            "id": "ord-hidden-999",
            "tenant_id": "tenant-ai-001",
            "order_no": "ORD-AI-CTX-003",
            "status": "DRAFT",
        }
    }
    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])

        r_missing = client.post("/ai/tenant-copilot/order-draft-assist", headers=_headers(token), json=payload_missing)
        r_inaccessible = client.post("/ai/tenant-copilot/order-draft-assist", headers=_headers(token), json=payload_inaccessible)

        assert r_missing.status_code == 403, r_missing.text
        assert r_inaccessible.status_code == 403, r_inaccessible.text
        missing_detail = (r_missing.json() or {}).get("detail")
        inaccessible_detail = (r_inaccessible.json() or {}).get("detail")
        assert missing_detail == guard_mod.OBJECT_REFERENCE_NOT_ACCESSIBLE
        assert inaccessible_detail == guard_mod.OBJECT_REFERENCE_NOT_ACCESSIBLE
        assert "ord-hidden-999" not in str(inaccessible_detail or "")
    finally:
        app.dependency_overrides.clear()


def test_feedback_guard_allow_valid_reference_no_success_regression(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        intake_feedback_service_mod.tenant_retrieval_action_guard,
        "validate_order_reference_access",
        lambda **_kwargs: guard_mod.TenantRetrievalActionGuardResult(allowed=True, code="allow"),
    )

    payload = {
        "original_template_fingerprint": "tpl-fp-guard-001",
        "proposed_draft_order_candidate": {
            "order_no": "ORD-FB-GUARD-001",
            "payload": {"order_id": "ord-visible-001"},
        },
        "user_confirmed_fields": ["order_no"],
    }
    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        r = client.post("/ai/tenant-copilot/order-intake-feedback", headers=_headers(token), json=payload)
        assert r.status_code == 200, r.text
        assert (r.json() or {}).get("ok") is True
    finally:
        app.dependency_overrides.clear()


def test_feedback_guard_hidden_object_safe_deny_missing_vs_inaccessible(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db
    monkeypatch.setattr(licensing_deps.licensing_service, "resolve_module_entitlement", _allow_entitlement)
    monkeypatch.setattr(core_middleware.CoreEntitlementMiddleware, "_cache_get", lambda _self, _tenant_id, _now_mono: True)
    monkeypatch.setattr(ai_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        intake_feedback_service_mod.tenant_retrieval_action_guard,
        "validate_order_reference_access",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError(guard_mod.OBJECT_REFERENCE_NOT_ACCESSIBLE)),
    )

    payload_missing = {
        "original_template_fingerprint": "tpl-fp-guard-002",
        "proposed_draft_order_candidate": {
            "order_no": "ORD-FB-GUARD-002",
            "payload": {"order_id": ""},
        },
        "user_confirmed_fields": ["order_no"],
    }
    payload_inaccessible = {
        "original_template_fingerprint": "tpl-fp-guard-003",
        "proposed_draft_order_candidate": {
            "order_no": "ORD-FB-GUARD-003",
            "payload": {"order_id": "ord-hidden-111"},
        },
        "user_confirmed_fields": ["order_no"],
    }
    try:
        client = TestClient(app)
        token = _token(tenant_id="tenant-ai-001", perms=["AI.COPILOT"])
        r_missing = client.post("/ai/tenant-copilot/order-intake-feedback", headers=_headers(token), json=payload_missing)
        r_inaccessible = client.post("/ai/tenant-copilot/order-intake-feedback", headers=_headers(token), json=payload_inaccessible)

        assert r_missing.status_code == 403, r_missing.text
        assert r_inaccessible.status_code == 403, r_inaccessible.text
        missing_detail = (r_missing.json() or {}).get("detail")
        inaccessible_detail = (r_inaccessible.json() or {}).get("detail")
        assert missing_detail == guard_mod.OBJECT_REFERENCE_NOT_ACCESSIBLE
        assert inaccessible_detail == guard_mod.OBJECT_REFERENCE_NOT_ACCESSIBLE
        assert "ord-hidden-111" not in str(inaccessible_detail or "")
    finally:
        app.dependency_overrides.clear()

