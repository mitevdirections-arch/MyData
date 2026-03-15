import app.main as main_module
import pytest
from fastapi.testclient import TestClient

from app.core.settings import get_settings
from app.db.session import get_engine
from app.main import app, create_app


def _clear_runtime_caches() -> None:
    get_settings.cache_clear()
    get_engine.cache_clear()


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_healthz(client: TestClient) -> None:
    r = client.get('/healthz')
    assert r.status_code == 200
    assert r.json().get('ok') is True


def test_dev_token_issues_token(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_DEV_TOKEN_ENABLED", "true")
    get_settings.cache_clear()
    try:
        client = TestClient(app)
        r = client.post('/auth/dev-token', json={"sub": "tester@local", "roles": ["SUPERADMIN"], "tenant_id": "t1"})
        assert r.status_code == 200
        assert r.json().get('access_token')
    finally:
        get_settings.cache_clear()


def test_country_engine_template_us(client: TestClient) -> None:
    r = client.get('/public/country-engine/template/US')
    assert r.status_code == 200
    payload = r.json()
    assert payload['defaults']['unit_system'] == 'imperial'
    assert payload['defaults']['date_style'] == 'MDY'


def test_healthz_runtime_snapshot(client: TestClient) -> None:
    r = client.get('/healthz/runtime')
    assert r.status_code == 200
    payload = r.json()
    assert payload.get('ok') is True
    runtime = payload.get('runtime') or {}
    assert 'in_flight' in runtime
    assert 'totals' in runtime
    assert 'latency_ms' in runtime


def test_runtime_timing_headers_enabled(monkeypatch) -> None:
    monkeypatch.setenv('API_RUNTIME_TIMING_HEADERS_ENABLED', 'true')
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        r = client.get('/public/country-engine/version')
        assert r.status_code == 200
        assert 'X-Process-Time-Ms' in r.headers
        assert 'X-Queue-Wait-Ms' in r.headers
    finally:
        get_settings.cache_clear()



def test_readyz_missing_database_url_fail_closed(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    _clear_runtime_caches()
    try:
        client = TestClient(create_app())

        live = client.get('/healthz')
        assert live.status_code == 200
        assert live.json().get('ok') is True

        ready = client.get('/readyz')
        assert ready.status_code == 503
        rj = ready.json()
        assert rj.get('ready') is False
        assert ((rj.get('checks') or {}).get('db') or {}).get('detail') == 'database_url_missing'

        db = client.get('/healthz/db')
        assert db.status_code == 503
        assert db.json().get('detail') == 'database_url_missing'
    finally:
        _clear_runtime_caches()


def test_readyz_invalid_database_url_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv('DATABASE_URL', 'not-a-valid-db-url')
    _clear_runtime_caches()
    try:
        client = TestClient(create_app())
        ready = client.get('/readyz')
        assert ready.status_code == 503
        rj = ready.json()
        assert rj.get('ready') is False
        assert ((rj.get('checks') or {}).get('db') or {}).get('detail') == 'database_url_invalid'
    finally:
        _clear_runtime_caches()


def test_readyz_db_down_fail_closed(monkeypatch) -> None:
    class _BrokenEngine:
        def connect(self):
            raise OSError('connection refused')

    monkeypatch.setattr(main_module, 'get_engine', lambda: _BrokenEngine())

    client = TestClient(create_app())
    ready = client.get('/readyz')
    assert ready.status_code == 503
    rj = ready.json()
    assert rj.get('ready') is False
    assert ((rj.get('checks') or {}).get('db') or {}).get('detail') == 'db_connect_failed'


def test_readyz_happy_path(monkeypatch) -> None:
    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def exec_driver_sql(self, sql: str):
            assert sql == 'SELECT 1'

    class _HealthyEngine:
        def connect(self):
            return _Conn()

    monkeypatch.setattr(main_module, 'get_engine', lambda: _HealthyEngine())

    client = TestClient(create_app())

    ready = client.get('/readyz')
    assert ready.status_code == 200
    rj = ready.json()
    assert rj.get('ready') is True
    assert ((rj.get('checks') or {}).get('db') or {}).get('detail') == 'db_ready'

    db = client.get('/healthz/db')
    assert db.status_code == 200
    assert db.json().get('ok') is True
    assert db.json().get('detail') == 'db_ready'
