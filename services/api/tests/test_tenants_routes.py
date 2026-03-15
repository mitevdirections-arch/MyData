from fastapi.testclient import TestClient

from app.main import app


def test_tenant_bootstrap_first_admin_route_registered(registered_paths: set[str]) -> None:
    paths = registered_paths
    assert '/admin/tenants/{tenant_id}/bootstrap-first-admin' in paths


def test_tenant_bootstrap_first_admin_requires_authorization() -> None:
    client = TestClient(app)
    r = client.post('/admin/tenants/tenant-test-001/bootstrap-first-admin', json={'user_id': 'admin@tenant.local'})
    assert r.status_code == 401
    assert (r.json() or {}).get('detail') == 'missing_authorization'