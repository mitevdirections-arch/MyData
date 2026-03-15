from fastapi.testclient import TestClient

from app.main import app


def test_provisioning_route_registered(registered_paths: set[str]) -> None:
    paths = registered_paths
    assert '/superadmin/provisioning/tenant/run' in paths


def test_provisioning_route_requires_authorization() -> None:
    client = TestClient(app)
    r = client.post('/superadmin/provisioning/tenant/run', json={'tenant_id': 'tenant-test-001'})
    assert r.status_code == 401
    assert (r.json() or {}).get('detail') == 'missing_authorization'