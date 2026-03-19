from __future__ import annotations

import pytest

import app.modules.orders.service as orders_service_module


class _FakeDB:
    def __init__(self) -> None:
        self.info: dict[str, object] = {}


def _allowed_entitlement() -> dict[str, object]:
    return {
        "allowed": True,
        "module_code": "MODULE_ORDERS",
        "reason": "module_license_active",
        "source": {"license_type": "MODULE", "license_id": "lic-1"},
        "valid_to": "2030-01-01T00:00:00+00:00",
    }


def test_orders_entitlement_session_cache_reuses_resolution(monkeypatch) -> None:
    db = _FakeDB()
    calls = {"count": 0}

    def _resolve(_db, _tenant_id: str, _module_code: str):
        calls["count"] += 1
        return _allowed_entitlement()

    monkeypatch.setattr(orders_service_module.licensing_service, "resolve_module_entitlement", _resolve)

    first = orders_service_module.service._entitlement(db, tenant_id="tenant-a")
    second = orders_service_module.service._entitlement(db, tenant_id="tenant-a")

    assert calls["count"] == 1
    assert first.model_dump() == second.model_dump()


def test_orders_entitlement_denied_is_not_cached(monkeypatch) -> None:
    db = _FakeDB()
    calls = {"count": 0}

    def _deny(_db, _tenant_id: str, _module_code: str):
        calls["count"] += 1
        return {
            "allowed": False,
            "module_code": "MODULE_ORDERS",
            "reason": "module_license_required",
            "source": None,
            "valid_to": None,
        }

    monkeypatch.setattr(orders_service_module.licensing_service, "resolve_module_entitlement", _deny)

    with pytest.raises(ValueError, match="module_license_required"):
        orders_service_module.service._entitlement(db, tenant_id="tenant-a")
    with pytest.raises(ValueError, match="module_license_required"):
        orders_service_module.service._entitlement(db, tenant_id="tenant-a")

    assert calls["count"] == 2
