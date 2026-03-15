from fastapi.testclient import TestClient

from app.main import app


def test_i18n_locales() -> None:
    client = TestClient(app)
    r = client.get('/i18n/locales')
    assert r.status_code == 200
    payload = r.json()
    assert payload.get('ok') is True
    codes = {x.get('code') for x in payload.get('items') or []}
    assert 'en' in codes
    assert 'bg' in codes


def test_i18n_catalog_bg() -> None:
    client = TestClient(app)
    r = client.get('/i18n/catalog/bg')
    assert r.status_code == 200
    payload = r.json()
    assert payload.get('locale') == 'bg'
    assert isinstance(payload.get('messages'), dict)
    assert payload['messages'].get('common.ok')