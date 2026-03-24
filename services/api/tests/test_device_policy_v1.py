from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from starlette.requests import Request

import app.core.policy_matrix as pm
from app.db.models import DeviceLease, License, Tenant
from app.db.session import get_engine, get_session_factory
from app.modules.guard.service import GuardService
from app.modules.licensing.service import service as licensing_service


@pytest.fixture
def db():
    if not str(os.getenv("DATABASE_URL") or "").strip():
        pytest.fail("DATABASE_URL is required for device_policy db-backed tests")
    get_engine.cache_clear()
    session = None
    try:
        session = get_session_factory()()
        session.execute(sa.text("SELECT 1"))
        insp = sa.inspect(session.bind)
        cols = {str(col.get("name")) for col in insp.get_columns("device_leases")}
    except Exception as exc:  # noqa: BLE001
        if session is not None:
            session.close()
        get_engine.cache_clear()
        pytest.fail(f"device_policy db unavailable: {exc.__class__.__name__}: {exc}")
    if "state" not in cols:
        session.close()
        get_engine.cache_clear()
        pytest.fail("device_policy_v1 schema not applied (missing device_leases.state)")
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        get_engine.cache_clear()


def _seed_tenant_with_core(db, *, tenant_id: str, core_plan: str = "CORE3") -> None:
    now = datetime.now(timezone.utc)
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        db.add(Tenant(id=tenant_id, name=f"Tenant {tenant_id}", is_active=True, created_at=now))
        db.flush()
    core = (
        db.query(License)
        .filter(
            License.tenant_id == tenant_id,
            License.license_type == "CORE",
            License.status == "ACTIVE",
            License.valid_from <= now,
            License.valid_to >= now,
        )
        .first()
    )
    if core is None:
        db.add(
            License(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                license_type="CORE",
                module_code=core_plan,
                status="ACTIVE",
                valid_from=now - timedelta(minutes=5),
                valid_to=now + timedelta(days=30),
                created_at=now,
            )
        )
    db.commit()


def _state(db, *, tenant_id: str, user_id: str, device_class: str) -> str | None:
    row = (
        db.query(DeviceLease)
        .filter(
            DeviceLease.tenant_id == tenant_id,
            DeviceLease.user_id == user_id,
            DeviceLease.device_class == device_class,
        )
        .first()
    )
    return str(row.state or "").upper() if row is not None else None


def _assert_state_active_invariant(db, *, tenant_id: str, user_id: str) -> None:
    rows = (
        db.query(DeviceLease)
        .filter(
            DeviceLease.tenant_id == tenant_id,
            DeviceLease.user_id == user_id,
        )
        .all()
    )
    for row in rows:
        state = str(row.state or "").upper()
        assert (state == "ACTIVE") == bool(row.is_active)


def _request(*, path: str, method: str = "GET", claims: dict | None = None, device_id: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if device_id:
        headers.append((b"x-device-id", str(device_id).encode("utf-8")))
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 9999),
        "server": ("test", 80),
        "route": SimpleNamespace(path=path),
    }
    req = Request(scope)
    req.state.claims = dict(
        claims
        or {
            "sub": "user@tenant.local",
            "tenant_id": "tenant-policy",
            "roles": ["TENANT_ADMIN"],
        }
    )
    return req


def test_desktop_then_mobile_keeps_single_active_and_two_slots(db) -> None:
    service = GuardService()
    tenant_id = f"tenant-{uuid.uuid4().hex[:10]}"
    user_id = "user-001"
    _seed_tenant_with_core(db, tenant_id=tenant_id, core_plan="CORE3")

    service.lease_device(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        device_id="desktop-01",
        device_class="desktop",
    )
    service.lease_device(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        device_id="mobile-01",
        device_class="mobile",
    )

    rows = (
        db.query(DeviceLease)
        .filter(DeviceLease.tenant_id == tenant_id, DeviceLease.user_id == user_id)
        .order_by(DeviceLease.device_class.asc())
        .all()
    )
    assert len(rows) == 2
    assert _state(db, tenant_id=tenant_id, user_id=user_id, device_class="mobile") == "ACTIVE"
    assert _state(db, tenant_id=tenant_id, user_id=user_id, device_class="desktop") == "PAUSED"
    _assert_state_active_invariant(db, tenant_id=tenant_id, user_id=user_id)
    assert licensing_service.count_active_leased_users(db, tenant_id) == 1


def test_mobile_then_desktop_demotes_mobile_to_background_reachable(db) -> None:
    service = GuardService()
    tenant_id = f"tenant-{uuid.uuid4().hex[:10]}"
    user_id = "user-002"
    _seed_tenant_with_core(db, tenant_id=tenant_id, core_plan="CORE3")

    service.lease_device(db, tenant_id=tenant_id, user_id=user_id, device_id="mobile-02", device_class="mobile")
    service.lease_device(db, tenant_id=tenant_id, user_id=user_id, device_id="desktop-02", device_class="desktop")

    assert _state(db, tenant_id=tenant_id, user_id=user_id, device_class="desktop") == "ACTIVE"
    assert _state(db, tenant_id=tenant_id, user_id=user_id, device_class="mobile") == "BACKGROUND_REACHABLE"
    _assert_state_active_invariant(db, tenant_id=tenant_id, user_id=user_id)


def test_manual_logout_keeps_peer_as_candidate_only(db) -> None:
    service = GuardService()
    tenant_id = f"tenant-{uuid.uuid4().hex[:10]}"
    user_id = "user-003"
    _seed_tenant_with_core(db, tenant_id=tenant_id, core_plan="CORE3")

    service.lease_device(db, tenant_id=tenant_id, user_id=user_id, device_id="desktop-03", device_class="desktop")
    service.lease_device(db, tenant_id=tenant_id, user_id=user_id, device_id="mobile-03", device_class="mobile")
    out = service.logout_device(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        device_id="mobile-03",
        actor=user_id,
    )

    assert (out.get("device") or {}).get("state") == "LOGGED_OUT"
    assert _state(db, tenant_id=tenant_id, user_id=user_id, device_class="desktop") == "PAUSED"
    _assert_state_active_invariant(db, tenant_id=tenant_id, user_id=user_id)
    assert licensing_service.count_active_leased_users(db, tenant_id) == 0


def test_lazy_paused_desktop_auto_logout_on_request_time_check(db) -> None:
    service = GuardService()
    tenant_id = f"tenant-{uuid.uuid4().hex[:10]}"
    user_id = "user-004"
    _seed_tenant_with_core(db, tenant_id=tenant_id, core_plan="CORE3")

    service.lease_device(db, tenant_id=tenant_id, user_id=user_id, device_id="desktop-04", device_class="desktop")
    service.lease_device(db, tenant_id=tenant_id, user_id=user_id, device_id="mobile-04", device_class="mobile")

    desktop = (
        db.query(DeviceLease)
        .filter(
            DeviceLease.tenant_id == tenant_id,
            DeviceLease.user_id == user_id,
            DeviceLease.device_class == "desktop",
        )
        .first()
    )
    assert desktop is not None
    desktop.paused_at = datetime.now(timezone.utc) - timedelta(minutes=31)
    db.commit()

    out = service.assert_request_device_active(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        device_id="mobile-04",
    )
    assert out.get("state") == "ACTIVE"
    assert _state(db, tenant_id=tenant_id, user_id=user_id, device_class="desktop") == "LOGGED_OUT"
    _assert_state_active_invariant(db, tenant_id=tenant_id, user_id=user_id)


def test_db_invariant_rejects_inconsistent_state_is_active_row(db) -> None:
    service = GuardService()
    tenant_id = f"tenant-{uuid.uuid4().hex[:10]}"
    user_id = "user-005"
    _seed_tenant_with_core(db, tenant_id=tenant_id, core_plan="CORE3")

    service.lease_device(db, tenant_id=tenant_id, user_id=user_id, device_id="desktop-05", device_class="desktop")
    row = (
        db.query(DeviceLease)
        .filter(
            DeviceLease.tenant_id == tenant_id,
            DeviceLease.user_id == user_id,
            DeviceLease.device_class == "desktop",
        )
        .first()
    )
    assert row is not None
    row.state = "ACTIVE"
    row.is_active = False
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    fixed = db.query(DeviceLease).filter(DeviceLease.id == row.id).first()
    assert fixed is not None
    assert str(fixed.state or "").upper() == "ACTIVE"
    assert bool(fixed.is_active) is True
    _assert_state_active_invariant(db, tenant_id=tenant_id, user_id=user_id)


def test_core3_limit_is_distinct_active_users(db) -> None:
    service = GuardService()
    tenant_id = f"tenant-{uuid.uuid4().hex[:10]}"
    _seed_tenant_with_core(db, tenant_id=tenant_id, core_plan="CORE3")

    service.lease_device(db, tenant_id=tenant_id, user_id="u1", device_id="u1-d", device_class="desktop")
    service.lease_device(db, tenant_id=tenant_id, user_id="u1", device_id="u1-m", device_class="mobile")
    service.lease_device(db, tenant_id=tenant_id, user_id="u2", device_id="u2-d", device_class="desktop")
    service.lease_device(db, tenant_id=tenant_id, user_id="u3", device_id="u3-d", device_class="desktop")

    assert licensing_service.count_active_leased_users(db, tenant_id) == 3
    with pytest.raises(ValueError, match="core_seat_limit_exceeded"):
        service.lease_device(db, tenant_id=tenant_id, user_id="u4", device_id="u4-d", device_class="desktop")


def test_parallel_activate_race_finishes_with_exactly_one_active(db) -> None:
    insp = sa.inspect(db.bind)
    indexes = {str(idx.get("name")) for idx in insp.get_indexes("device_leases")}
    if "uq_device_lease_one_active_user" not in indexes:
        pytest.skip("missing db guard uq_device_lease_one_active_user")

    tenant_id = f"tenant-{uuid.uuid4().hex[:10]}"
    user_id = "user-race-01"
    _seed_tenant_with_core(db, tenant_id=tenant_id, core_plan="CORE3")

    service = GuardService()
    service.lease_device(db, tenant_id=tenant_id, user_id=user_id, device_id="desktop-race", device_class="desktop")
    service.lease_device(db, tenant_id=tenant_id, user_id=user_id, device_id="mobile-race", device_class="mobile")

    session_factory = get_session_factory()

    def _activate(device_id: str) -> str:
        local = session_factory()
        try:
            GuardService().activate_device(
                local,
                tenant_id=tenant_id,
                user_id=user_id,
                device_id=device_id,
                actor=user_id,
            )
            return "ok"
        except ValueError as exc:
            return str(exc)
        finally:
            local.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(list(pool.map(_activate, ["desktop-race", "mobile-race"])))

    db.expire_all()
    rows = (
        db.query(DeviceLease)
        .filter(DeviceLease.tenant_id == tenant_id, DeviceLease.user_id == user_id)
        .all()
    )
    active_rows = [r for r in rows if str(r.state or "").upper() == "ACTIVE" and bool(r.is_active)]
    assert len(active_rows) == 1
    assert licensing_service.count_active_leased_users(db, tenant_id) == 1
    assert all(r in {"ok", "DEVICE_STATE_CONFLICT_RETRY"} for r in results)
    _assert_state_active_invariant(db, tenant_id=tenant_id, user_id=user_id)


def test_device_policy_denies_business_route_without_device_context(monkeypatch) -> None:
    req = _request(path="/orders", method="GET")
    monkeypatch.setattr(pm, "_tenant_db_effective_permissions", lambda *, claims: ["ORDERS.READ"])
    with pytest.raises(HTTPException) as exc:
        pm.enforce_request_policy(req)
    assert int(exc.value.status_code) == 403
    assert str(exc.value.detail) == "DEVICE_CONTEXT_REQUIRED"


def test_device_policy_denies_business_route_when_device_not_active(monkeypatch) -> None:
    req = _request(path="/orders", method="GET", device_id="device-x")
    monkeypatch.setattr(pm, "_tenant_db_effective_permissions", lambda *, claims: ["ORDERS.READ"])

    class _FakeDB:
        def close(self) -> None:
            return None

    monkeypatch.setattr(pm, "get_session_factory", lambda: (lambda: _FakeDB()))

    import app.modules.guard.service as guard_service_mod

    monkeypatch.setattr(
        guard_service_mod.service,
        "assert_request_device_active",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("DEVICE_NOT_ACTIVE")),
    )
    with pytest.raises(HTTPException) as exc:
        pm.enforce_request_policy(req)
    assert int(exc.value.status_code) == 403
    assert str(exc.value.detail) == "DEVICE_NOT_ACTIVE"
