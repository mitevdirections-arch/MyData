from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.auth import create_access_token
from app.core.settings import get_settings
from app.db.models import Order, WorkspaceUserRole
from app.db.session import get_engine, get_session_factory
from app.main import create_app


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _issue_dev_token(client: TestClient, payload: dict[str, object]) -> str:
    r = client.post("/auth/dev-token", json=payload)
    assert r.status_code == 200, r.text
    token = str((r.json() or {}).get("access_token") or "").strip()
    assert token
    return token


def _issue_claims_token(claims: dict[str, object]) -> str:
    return create_access_token(dict(claims), ttl_seconds=600)


def _bootstrap_tenant(client: TestClient, *, super_headers: dict[str, str], tenant_id: str) -> None:
    r = client.post(
        "/admin/tenants/bootstrap-demo",
        headers=super_headers,
        json={"tenant_id": tenant_id, "name": f"Role Separation {tenant_id}"},
    )
    assert r.status_code == 200, r.text
    assert (r.json() or {}).get("tenant_id") == tenant_id


def _bootstrap_first_admin(client: TestClient, *, super_headers: dict[str, str], tenant_id: str, user_id: str) -> None:
    r = client.post(
        f"/admin/tenants/{tenant_id}/bootstrap-first-admin",
        headers=super_headers,
        json={"user_id": user_id, "email": user_id, "allow_if_exists": True, "issue_credentials": False},
    )
    assert r.status_code == 200, r.text


def _issue_core_for_tenant(client: TestClient, *, super_headers: dict[str, str], tenant_id: str) -> None:
    r = client.post(
        "/licenses/admin/issue-core",
        headers=super_headers,
        json={"tenant_id": tenant_id, "plan_code": "CORE8", "valid_days": 30},
    )
    assert r.status_code == 200, r.text


def _issue_orders_trial(client: TestClient, *, super_headers: dict[str, str], tenant_id: str) -> None:
    r = client.post(
        "/licenses/admin/issue-module-trial",
        headers=super_headers,
        json={"tenant_id": tenant_id, "module_code": "MODULE_ORDERS"},
    )
    assert r.status_code == 200, r.text


def _upsert_user(client: TestClient, *, owner_headers: dict[str, str], user_id: str, first_name: str, last_name: str) -> None:
    r = client.put(
        f"/profile/admin/users/{user_id}",
        headers=owner_headers,
        json={
            "email": user_id,
            "first_name": first_name,
            "last_name": last_name,
            "employment_status": "ACTIVE",
        },
    )
    assert r.status_code == 200, r.text


def _set_user_roles(client: TestClient, *, owner_headers: dict[str, str], user_id: str, role_codes: list[str]) -> None:
    r = client.put(
        f"/profile/admin/users/{user_id}/roles",
        headers=owner_headers,
        json={"role_codes": role_codes},
    )
    assert r.status_code == 200, r.text


def _create_order(client: TestClient, *, headers: dict[str, str], idx: int, status: str) -> dict[str, object]:
    payload = {
        "order_no": f"ROLE-E2E-{idx:04d}",
        "status": status,
        "transport_mode": "ROAD",
        "direction": "OUTBOUND",
        "customer_name": "Carrier Ops",
        "pickup_location": "Sofia Hub",
        "delivery_location": "Plovdiv Hub",
        "cargo_description": "General cargo",
        "reference_no": f"TRK-{idx:03d}",
        "payload": {
            "truck_id": f"TRUCK-{idx:03d}",
            "fleet_size": 50,
            "warehouse": "WH-01",
        },
    }
    r = client.post("/orders", headers=headers, json=payload)
    assert r.status_code == 200, r.text
    return (r.json() or {}).get("order") or {}


def _count_orders(tenant_id: str) -> int:
    with get_session_factory()() as db:
        return int(db.query(Order).filter(Order.tenant_id == tenant_id).count())


def _has_tenant_admin_role(tenant_id: str, user_id: str) -> bool:
    with get_session_factory()() as db:
        row = (
            db.query(WorkspaceUserRole)
            .filter(
                WorkspaceUserRole.workspace_type == "TENANT",
                WorkspaceUserRole.workspace_id == tenant_id,
                WorkspaceUserRole.user_id == user_id,
                WorkspaceUserRole.role_code == "TENANT_ADMIN",
            )
            .first()
        )
        return row is not None


@pytest.mark.integration
def test_intra_tenant_role_separation_e2e(monkeypatch) -> None:
    if not _truthy(os.getenv("ROLE_SEPARATION_E2E_ENABLED")):
        pytest.skip("ROLE_SEPARATION_E2E_ENABLED is not true")
    if not str(os.getenv("DATABASE_URL") or "").strip():
        pytest.skip("DATABASE_URL is required for role separation e2e")

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("AUTH_DEV_TOKEN_ENABLED", "true")
    monkeypatch.setenv("SUPERADMIN_STEP_UP_ENABLED", "false")

    get_settings.cache_clear()
    get_engine.cache_clear()

    try:
        client = TestClient(create_app())
        suffix = uuid.uuid4().hex[:10]
        tenant_id = f"tenant-role-{suffix}"

        owner_sub = f"owner+{suffix}@{tenant_id}.local"
        dispatcher_sub = f"dispatcher+{suffix}@{tenant_id}.local"
        driver_sub = f"driver+{suffix}@{tenant_id}.local"
        warehouse_sub = f"warehouse+{suffix}@{tenant_id}.local"
        limited_sub = f"staff+{suffix}@{tenant_id}.local"

        super_token = _issue_dev_token(
            client,
            {
                "sub": f"superadmin+{suffix}@ops.local",
                "roles": ["SUPERADMIN"],
                "tenant_id": "platform",
            },
        )
        super_headers = _auth_headers(super_token)

        _bootstrap_tenant(client, super_headers=super_headers, tenant_id=tenant_id)
        _issue_core_for_tenant(client, super_headers=super_headers, tenant_id=tenant_id)
        _issue_orders_trial(client, super_headers=super_headers, tenant_id=tenant_id)
        _bootstrap_first_admin(client, super_headers=super_headers, tenant_id=tenant_id, user_id=owner_sub)

        owner_token = _issue_dev_token(
            client,
            {
                "sub": owner_sub,
                "roles": ["TENANT_ADMIN"],
                "tenant_id": tenant_id,
            },
        )
        owner_headers = _auth_headers(owner_token)

        _upsert_user(client, owner_headers=owner_headers, user_id=dispatcher_sub, first_name="Ops", last_name="Dispatcher")
        _upsert_user(client, owner_headers=owner_headers, user_id=driver_sub, first_name="Fleet", last_name="Driver")
        _upsert_user(client, owner_headers=owner_headers, user_id=warehouse_sub, first_name="Stock", last_name="Warehouse")
        _upsert_user(client, owner_headers=owner_headers, user_id=limited_sub, first_name="Office", last_name="Limited")

        _set_user_roles(client, owner_headers=owner_headers, user_id=dispatcher_sub, role_codes=["DISPATCHER"])
        _set_user_roles(client, owner_headers=owner_headers, user_id=driver_sub, role_codes=["DRIVER"])
        _set_user_roles(client, owner_headers=owner_headers, user_id=warehouse_sub, role_codes=["WAREHOUSE_OPERATOR"])
        _set_user_roles(client, owner_headers=owner_headers, user_id=limited_sub, role_codes=[])

        first_order_id = ""
        for i in range(50):
            status = "DRAFT" if i < 40 else "SUBMITTED"
            row = _create_order(client, headers=owner_headers, idx=i, status=status)
            if i == 0:
                first_order_id = str(row.get("id") or "")
        assert first_order_id

        # owner/admin allow path + list/filter/pagination contract
        owner_list_draft = client.get("/orders?status=DRAFT&limit=10", headers=owner_headers)
        assert owner_list_draft.status_code == 200, owner_list_draft.text
        owner_items = list((owner_list_draft.json() or {}).get("items") or [])
        assert len(owner_items) == 10
        assert all(str(x.get("status") or "") == "DRAFT" for x in owner_items)

        owner_get = client.get(f"/orders/{first_order_id}", headers=owner_headers)
        assert owner_get.status_code == 200, owner_get.text

        c_create = client.post(
            "/profile/workspace/contacts",
            headers=owner_headers,
            json={"contact_kind": "GENERAL", "label": "HQ", "email": f"hq-{suffix}@tenant.local", "is_primary": True, "is_public": False},
        )
        assert c_create.status_code == 200, c_create.text
        contact_id = str(((c_create.json() or {}).get("item") or {}).get("id") or "")
        assert contact_id

        c_update = client.put(
            f"/profile/workspace/contacts/{contact_id}",
            headers=owner_headers,
            json={"label": "HQ Main"},
        )
        assert c_update.status_code == 200, c_update.text

        c_delete = client.delete(f"/profile/workspace/contacts/{contact_id}", headers=owner_headers)
        assert c_delete.status_code == 200, c_delete.text

        dispatcher_token = _issue_claims_token(
            {
                "sub": dispatcher_sub,
                "roles": ["DISPATCHER"],
                "tenant_id": tenant_id,
                "perms": ["IAM.READ", "IAM.WRITE"],
            }
        )
        dispatcher_headers = _auth_headers(dispatcher_token)

        # dispatcher operational allow path
        disp_access = client.get("/iam/me/access", headers=dispatcher_headers)
        assert disp_access.status_code == 200, disp_access.text
        disp_body = disp_access.json() or {}
        eff = list((((disp_body.get("permissions") or {}).get("effective_permissions")) or []))
        assert "ORDERS.READ" in eff
        assert "ORDERS.WRITE" in eff

        disp_check = client.post(
            "/iam/me/access/check",
            headers=dispatcher_headers,
            json={"permission_code": "ORDERS.WRITE"},
        )
        assert disp_check.status_code == 200, disp_check.text
        assert bool((disp_check.json() or {}).get("allowed")) is True

        # dispatcher operational allow path on /orders
        disp_list = client.get("/orders?status=DRAFT&limit=5", headers=dispatcher_headers)
        assert disp_list.status_code == 200, disp_list.text
        disp_items = list((disp_list.json() or {}).get("items") or [])
        assert len(disp_items) <= 5
        assert all(str(x.get("status") or "") == "DRAFT" for x in disp_items)

        disp_get_real = client.get(f"/orders/{first_order_id}", headers=dispatcher_headers)
        assert disp_get_real.status_code == 200, disp_get_real.text

        disp_get_random = client.get(f"/orders/{uuid.uuid4()}", headers=dispatcher_headers)
        assert disp_get_random.status_code == 404, disp_get_random.text
        assert (disp_get_random.json() or {}).get("detail") == "order_not_found"

        disp_create = client.post(
            "/orders",
            headers=dispatcher_headers,
            json={
                "order_no": f"ROLE-DISP-{suffix}",
                "status": "DRAFT",
                "transport_mode": "ROAD",
                "direction": "OUTBOUND",
            },
        )
        assert disp_create.status_code == 200, disp_create.text

        # role escalation attempt
        esc = client.put(
            f"/profile/admin/users/{dispatcher_sub}/roles",
            headers=dispatcher_headers,
            json={"role_codes": ["TENANT_ADMIN"]},
        )
        assert esc.status_code == 403, esc.text
        assert (esc.json() or {}).get("detail") == "tenant_admin_required"
        assert _has_tenant_admin_role(tenant_id, dispatcher_sub) is False

        driver_token = _issue_dev_token(
            client,
            {
                "sub": driver_sub,
                "roles": ["DRIVER"],
                "tenant_id": tenant_id,
            },
        )
        driver_headers = _auth_headers(driver_token)

        before = _count_orders(tenant_id)
        drv_write = client.post(
            "/orders",
            headers=driver_headers,
            json={"order_no": f"DRV-{suffix}", "status": "DRAFT", "transport_mode": "ROAD", "direction": "OUTBOUND"},
        )
        assert drv_write.status_code == 403, drv_write.text
        assert str((drv_write.json() or {}).get("detail") or "").startswith("permission_required:ORDERS.WRITE")
        after = _count_orders(tenant_id)
        assert after == before

        drv_list = client.get("/orders?limit=5", headers=driver_headers)
        assert drv_list.status_code == 200, drv_list.text

        drv_get = client.get(f"/orders/{first_order_id}", headers=driver_headers)
        assert drv_get.status_code == 200, drv_get.text

        drv_profile_write = client.post(
            "/profile/workspace/contacts",
            headers=driver_headers,
            json={"contact_kind": "GENERAL", "label": "Driver", "email": f"drv-{suffix}@tenant.local"},
        )
        assert drv_profile_write.status_code == 403, drv_profile_write.text
        assert str((drv_profile_write.json() or {}).get("detail") or "").startswith("permission_required:PROFILE.WRITE")

        warehouse_token = _issue_dev_token(
            client,
            {
                "sub": warehouse_sub,
                "roles": ["WAREHOUSE_OPERATOR"],
                "tenant_id": tenant_id,
            },
        )
        warehouse_headers = _auth_headers(warehouse_token)

        wh_list = client.get("/orders?limit=5", headers=warehouse_headers)
        assert wh_list.status_code == 403, wh_list.text
        assert str((wh_list.json() or {}).get("detail") or "").startswith("permission_required:ORDERS.READ")

        limited_token = _issue_dev_token(
            client,
            {
                "sub": limited_sub,
                "roles": ["USER"],
                "tenant_id": tenant_id,
            },
        )
        limited_headers = _auth_headers(limited_token)

        limited_iam = client.get("/iam/me/access", headers=limited_headers)
        assert limited_iam.status_code == 403, limited_iam.text
        assert str((limited_iam.json() or {}).get("detail") or "").startswith("permission_required:IAM.READ")

        limited_list = client.get("/orders?limit=5", headers=limited_headers)
        assert limited_list.status_code == 403, limited_list.text
        assert str((limited_list.json() or {}).get("detail") or "").startswith("permission_required:ORDERS.READ")

        limited_get_real = client.get(f"/orders/{first_order_id}", headers=limited_headers)
        limited_get_random = client.get(f"/orders/{uuid.uuid4()}", headers=limited_headers)
        assert limited_get_real.status_code == 403
        assert limited_get_random.status_code == 403
        assert (limited_get_real.json() or {}).get("detail") == (limited_get_random.json() or {}).get("detail")

        # forged context/header attempts
        forged_hdr = dict(dispatcher_headers)
        forged_hdr["X-Tenant-ID"] = "tenant-forged-ctx"
        forged_ctx = client.get("/iam/me/access", headers=forged_hdr)
        assert forged_ctx.status_code == 403, forged_ctx.text
        assert (forged_ctx.json() or {}).get("detail") == "tenant_context_mismatch"

        forged_orders = client.get("/orders?limit=1", headers=forged_hdr)
        assert forged_orders.status_code == 403, forged_orders.text
        assert (forged_orders.json() or {}).get("detail") == "tenant_context_mismatch"

        no_tenant_token = _issue_claims_token(
            {
                "sub": dispatcher_sub,
                "roles": ["DISPATCHER"],
                "perms": ["ORDERS.READ", "ORDERS.WRITE"],
            }
        )
        no_tenant_headers = _auth_headers(no_tenant_token)
        no_tenant_req = client.get("/orders?limit=1", headers=no_tenant_headers)
        assert no_tenant_req.status_code == 403, no_tenant_req.text
        assert (no_tenant_req.json() or {}).get("detail") == "missing_tenant_context"

        before_forged = _count_orders(tenant_id)
        forged_claims_token = _issue_claims_token(
            {
                "sub": limited_sub,
                "roles": ["USER"],
                "tenant_id": tenant_id,
                "perms": ["ORDERS.READ", "ORDERS.WRITE"],
            }
        )
        forged_claims_headers = _auth_headers(forged_claims_token)
        forged_write = client.post(
            "/orders",
            headers=forged_claims_headers,
            json={"order_no": f"FORGED-{suffix}", "status": "DRAFT", "transport_mode": "ROAD", "direction": "OUTBOUND"},
        )
        assert forged_write.status_code == 403, forged_write.text
        assert str((forged_write.json() or {}).get("detail") or "").startswith("permission_required:ORDERS.WRITE")
        assert _count_orders(tenant_id) == before_forged

        forged_ws = client.get("/iam/me/access?workspace=PLATFORM", headers=dispatcher_headers)
        assert forged_ws.status_code == 403, forged_ws.text
        assert (forged_ws.json() or {}).get("detail") == "platform_workspace_requires_superadmin"

    finally:
        get_settings.cache_clear()
        get_engine.cache_clear()


@pytest.mark.integration
def test_orders_tenant_isolation_proof_separate_from_role_separation(monkeypatch) -> None:
    if not _truthy(os.getenv("ROLE_SEPARATION_E2E_ENABLED")):
        pytest.skip("ROLE_SEPARATION_E2E_ENABLED is not true")
    if not str(os.getenv("DATABASE_URL") or "").strip():
        pytest.skip("DATABASE_URL is required for role separation e2e")

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("AUTH_DEV_TOKEN_ENABLED", "true")
    monkeypatch.setenv("SUPERADMIN_STEP_UP_ENABLED", "false")

    get_settings.cache_clear()
    get_engine.cache_clear()

    try:
        client = TestClient(create_app())
        suffix = uuid.uuid4().hex[:10]
        tenant_a = f"tenant-role-a-{suffix}"
        tenant_b = f"tenant-role-b-{suffix}"

        super_token = _issue_dev_token(
            client,
            {
                "sub": f"superadmin+{suffix}@ops.local",
                "roles": ["SUPERADMIN"],
                "tenant_id": "platform",
            },
        )
        super_headers = _auth_headers(super_token)

        _bootstrap_tenant(client, super_headers=super_headers, tenant_id=tenant_a)
        _bootstrap_tenant(client, super_headers=super_headers, tenant_id=tenant_b)
        _issue_core_for_tenant(client, super_headers=super_headers, tenant_id=tenant_a)
        _issue_core_for_tenant(client, super_headers=super_headers, tenant_id=tenant_b)
        _issue_orders_trial(client, super_headers=super_headers, tenant_id=tenant_a)
        _issue_orders_trial(client, super_headers=super_headers, tenant_id=tenant_b)

        owner_a_sub = f"owner-a+{suffix}@tenant.local"
        owner_b_sub = f"owner-b+{suffix}@tenant.local"
        _bootstrap_first_admin(client, super_headers=super_headers, tenant_id=tenant_a, user_id=owner_a_sub)
        _bootstrap_first_admin(client, super_headers=super_headers, tenant_id=tenant_b, user_id=owner_b_sub)

        owner_a = _auth_headers(
            _issue_dev_token(client, {"sub": owner_a_sub, "roles": ["TENANT_ADMIN"], "tenant_id": tenant_a})
        )
        owner_b = _auth_headers(
            _issue_dev_token(client, {"sub": owner_b_sub, "roles": ["TENANT_ADMIN"], "tenant_id": tenant_b})
        )

        order_a = _create_order(client, headers=owner_a, idx=1000, status="DRAFT")
        order_b = _create_order(client, headers=owner_b, idx=2000, status="DRAFT")

        id_a = str(order_a.get("id") or "")
        id_b = str(order_b.get("id") or "")
        assert id_a and id_b

        own_read = client.get(f"/orders/{id_a}", headers=owner_a)
        assert own_read.status_code == 200, own_read.text

        foreign_read = client.get(f"/orders/{id_b}", headers=owner_a)
        random_read = client.get(f"/orders/{uuid.uuid4()}", headers=owner_a)
        assert foreign_read.status_code == 404, foreign_read.text
        assert random_read.status_code == 404, random_read.text
        assert (foreign_read.json() or {}).get("detail") == "order_not_found"
        assert (random_read.json() or {}).get("detail") == "order_not_found"

        list_a = client.get("/orders?limit=100", headers=owner_a)
        assert list_a.status_code == 200, list_a.text
        ids = {str(x.get("id") or "") for x in list((list_a.json() or {}).get("items") or [])}
        assert id_a in ids
        assert id_b not in ids

    finally:
        get_settings.cache_clear()
        get_engine.cache_clear()
