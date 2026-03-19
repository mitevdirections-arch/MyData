from __future__ import annotations

from datetime import datetime, timezone

from app.modules.orders.schemas import OrdersListQueryDTO
import app.modules.orders.service as orders_service_module
from app.modules.orders.service import service


class _FakeMappingsResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.executed_stmt = None
        self.info: dict[str, object] = {}

    def execute(self, stmt):
        self.executed_stmt = stmt
        return _FakeMappingsResult(self._rows)

    def query(self, *_args, **_kwargs):
        raise AssertionError("list_orders should use execute(...).mappings() path")


def _allowed_entitlement(*_args, **_kwargs) -> dict[str, object]:
    return {
        "allowed": True,
        "module_code": "MODULE_ORDERS",
        "reason": "module_license_active",
        "source": {"license_type": "MODULE_PAID", "license_id": "lic-orders-001"},
        "valid_to": "2027-01-01T00:00:00+00:00",
    }


def _row_mapping() -> dict[str, object]:
    now = datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc)
    return {
        "id": "ord-001",
        "tenant_id": "tenant-a",
        "order_no": "ORD-001",
        "status": "DRAFT",
        "transport_mode": "ROAD",
        "direction": "OUTBOUND",
        "customer_name": "Carrier Ops",
        "pickup_location": "Sofia Hub",
        "delivery_location": "Plovdiv Hub",
        "cargo_description": "General cargo",
        "reference_no": "REF-001",
        "scheduled_pickup_at": now,
        "scheduled_delivery_at": now,
        "payload_json": {
            "seed": True,
            "references": {"customer_reference": "CUST-001"},
            "goods": {"goods_description": "General cargo", "packages_count": 2},
        },
        "created_by": "owner@tenant.local",
        "updated_by": "owner@tenant.local",
        "created_at": now,
        "updated_at": now,
    }


def test_orders_list_uses_execute_mappings_and_keeps_contract(monkeypatch) -> None:
    monkeypatch.setattr(orders_service_module.licensing_service, "resolve_module_entitlement", _allowed_entitlement)

    db = _FakeSession([_row_mapping()])
    out = service.list_orders(
        db,  # type: ignore[arg-type]
        tenant_id="tenant-a",
        query=OrdersListQueryDTO(status="DRAFT", limit=10),
    )

    assert db.executed_stmt is not None
    sql_text = str(db.executed_stmt)
    assert "FROM orders" in sql_text
    assert "ORDER BY orders.created_at DESC" in sql_text
    assert "orders.status" in sql_text
    assert int(getattr(db.executed_stmt, "_limit_clause").value) == 10

    assert out.ok is True
    assert out.tenant_id == "tenant-a"
    assert len(out.items) == 1
    item = out.items[0]
    assert item.order_no == "ORD-001"
    assert item.payload.get("seed") is True
    assert item.references is not None
    assert item.references.customer_reference == "CUST-001"


def test_orders_summary_mapping_parity_with_object_path(monkeypatch) -> None:
    monkeypatch.setattr(orders_service_module.licensing_service, "resolve_module_entitlement", _allowed_entitlement)

    row = _row_mapping()

    class _Obj:
        pass

    obj = _Obj()
    for key, value in row.items():
        setattr(obj, key, value)

    from_mapping = service._to_summary(row)
    from_object = service._to_summary(obj)
    assert from_mapping.model_dump() == from_object.model_dump()

