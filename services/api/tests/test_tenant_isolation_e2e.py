from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.auth import create_access_token
from app.core.settings import get_settings
from app.db.models import WorkspaceContactPoint
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


def _bootstrap_tenant(client: TestClient, *, super_headers: dict[str, str], tenant_id: str) -> None:
    r = client.post(
        "/admin/tenants/bootstrap-demo",
        headers=super_headers,
        json={"tenant_id": tenant_id, "name": f"Isolation {tenant_id}"},
    )
    assert r.status_code == 200, r.text
    assert (r.json() or {}).get("tenant_id") == tenant_id


def _issue_core_for_tenant(client: TestClient, *, super_headers: dict[str, str], tenant_id: str) -> None:
    r = client.post(
        "/licenses/admin/issue-core",
        headers=super_headers,
        json={"tenant_id": tenant_id, "plan_code": "CORE8", "valid_days": 30},
    )
    assert r.status_code == 200, r.text
    body = r.json() or {}
    license_obj = body.get("license") or {}
    assert str(license_obj.get("license_id") or "").strip()
def _create_contact(client: TestClient, *, headers: dict[str, str], label: str, email: str) -> dict[str, object]:
    payload = {
        "contact_kind": "GENERAL",
        "label": label,
        "email": email,
        "is_primary": True,
        "is_public": False,
    }
    r = client.post("/profile/workspace/contacts", headers=headers, json=payload)
    assert r.status_code == 200, r.text
    item = (r.json() or {}).get("item") or {}
    assert str(item.get("id") or "").strip()
    return item


@pytest.mark.integration
def test_tenant_isolation_workspace_contacts_e2e(monkeypatch) -> None:
    if not _truthy(os.getenv("TENANT_ISOLATION_E2E_ENABLED")):
        pytest.skip("TENANT_ISOLATION_E2E_ENABLED is not true")

    if not str(os.getenv("DATABASE_URL") or "").strip():
        pytest.fail("DATABASE_URL is required for tenant isolation e2e")

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("AUTH_DEV_TOKEN_ENABLED", "true")
    monkeypatch.setenv("SUPERADMIN_STEP_UP_ENABLED", "false")

    get_settings.cache_clear()
    get_engine.cache_clear()

    try:
        client = TestClient(create_app())

        suffix = uuid.uuid4().hex[:10]
        tenant_a = f"tenant-iso-a-{suffix}"
        tenant_b = f"tenant-iso-b-{suffix}"

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

        token_a = _issue_dev_token(
            client,
            {
                "sub": f"admin+{suffix}@{tenant_a}.local",
                "roles": ["TENANT_ADMIN"],
                "tenant_id": tenant_a,
            },
        )
        token_b = _issue_dev_token(
            client,
            {
                "sub": f"admin+{suffix}@{tenant_b}.local",
                "roles": ["TENANT_ADMIN"],
                "tenant_id": tenant_b,
            },
        )

        headers_a = _auth_headers(token_a)
        headers_b = _auth_headers(token_b)

        contact_a = _create_contact(
            client,
            headers=headers_a,
            label=f"A-{suffix}",
            email=f"a-{suffix}@tenant.local",
        )
        contact_b = _create_contact(
            client,
            headers=headers_b,
            label=f"B-{suffix}",
            email=f"b-{suffix}@tenant.local",
        )

        id_a = str(contact_a.get("id"))
        id_b = str(contact_b.get("id"))
        label_b_before = str(contact_b.get("label") or "")

        # A read own = allow, list scope = no B leak.
        list_a = client.get("/profile/workspace/contacts", headers=headers_a)
        assert list_a.status_code == 200, list_a.text
        body_a = list_a.json() or {}
        assert body_a.get("workspace_type") == "TENANT"
        assert body_a.get("workspace_id") == tenant_a
        ids_a = {str(x.get("id")) for x in list(body_a.get("items") or [])}
        assert id_a in ids_a
        assert id_b not in ids_a

        # A write/update/delete against B resource = fail-closed.
        update_foreign = client.put(
            f"/profile/workspace/contacts/{id_b}",
            headers=headers_a,
            json={"label": "tamper-should-fail"},
        )
        assert update_foreign.status_code == 404, update_foreign.text
        assert (update_foreign.json() or {}).get("detail") == "contact_not_found"

        delete_foreign = client.delete(f"/profile/workspace/contacts/{id_b}", headers=headers_a)
        assert delete_foreign.status_code == 404, delete_foreign.text
        assert (delete_foreign.json() or {}).get("detail") == "contact_not_found"

        # Cross-tenant ID probing must be semantics-equal (no inference leak).
        random_id = str(uuid.uuid4())
        update_random = client.put(
            f"/profile/workspace/contacts/{random_id}",
            headers=headers_a,
            json={"label": "probe-random"},
        )
        delete_random = client.delete(f"/profile/workspace/contacts/{random_id}", headers=headers_a)

        assert update_random.status_code == update_foreign.status_code == 404
        assert delete_random.status_code == delete_foreign.status_code == 404
        assert (update_random.json() or {}).get("detail") == (update_foreign.json() or {}).get("detail") == "contact_not_found"
        assert (delete_random.json() or {}).get("detail") == (delete_foreign.json() or {}).get("detail") == "contact_not_found"

        # Missing tenant context = fail-closed.
        missing_ctx_token = create_access_token(
            {
                "sub": f"missingctx+{suffix}@tenant.local",
                "roles": ["TENANT_ADMIN"],
                "tenant_id": "",
            },
            ttl_seconds=120,
        )
        missing_ctx = client.get("/profile/workspace/contacts", headers=_auth_headers(missing_ctx_token))
        assert missing_ctx.status_code == 403, missing_ctx.text
        assert (missing_ctx.json() or {}).get("detail") == "missing_tenant_context"

        # Forged tenant header must be blocked before handler.
        forged_header = dict(headers_a)
        forged_header["X-Tenant-ID"] = tenant_b
        forged_ctx = client.get("/profile/workspace/contacts", headers=forged_header)
        assert forged_ctx.status_code == 403, forged_ctx.text
        assert (forged_ctx.json() or {}).get("detail") == "tenant_context_mismatch"

        # Forged superadmin tenant claim (without support session) must be blocked for TENANT scope.
        forged_super_token = create_access_token(
            {
                "sub": f"superforge+{suffix}@ops.local",
                "roles": ["SUPERADMIN"],
                "tenant_id": tenant_a,
            },
            ttl_seconds=120,
        )
        forged_super = client.get(
            "/profile/workspace/contacts?workspace=TENANT",
            headers=_auth_headers(forged_super_token),
        )
        assert forged_super.status_code == 403, forged_super.text
        assert (forged_super.json() or {}).get("detail") == "support_session_required_for_tenant_scope"

        # Admin/system exception path: superadmin platform scope is explicit and isolated.
        platform_contact = _create_contact(
            client,
            headers=super_headers,
            label=f"PLATFORM-{suffix}",
            email=f"platform-{suffix}@ops.local",
        )
        platform_id = str(platform_contact.get("id"))

        super_list = client.get("/profile/workspace/contacts", headers=super_headers)
        assert super_list.status_code == 200, super_list.text
        super_body = super_list.json() or {}
        assert super_body.get("workspace_type") == "PLATFORM"
        assert super_body.get("workspace_id") == "platform"
        super_ids = {str(x.get("id")) for x in list(super_body.get("items") or [])}
        assert platform_id in super_ids

        list_a_after = client.get("/profile/workspace/contacts", headers=headers_a)
        assert list_a_after.status_code == 200, list_a_after.text
        ids_a_after = {str(x.get("id")) for x in list((list_a_after.json() or {}).get("items") or [])}
        assert platform_id not in ids_a_after
        assert id_b not in ids_a_after

        # Verify denied cross-tenant writes had no DB side effects on B row.
        with get_session_factory()() as db:
            row_b = db.query(WorkspaceContactPoint).filter(WorkspaceContactPoint.id == uuid.UUID(id_b)).first()
            assert row_b is not None
            assert str(row_b.workspace_type) == "TENANT"
            assert str(row_b.workspace_id) == tenant_b
            assert str(row_b.label or "") == label_b_before

    finally:
        get_settings.cache_clear()
        get_engine.cache_clear()
