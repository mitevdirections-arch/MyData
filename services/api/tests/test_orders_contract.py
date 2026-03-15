from __future__ import annotations

from fastapi.testclient import TestClient

import app.core.policy_matrix as pm
from app.core.auth import create_access_token
from app.db.session import get_db_session
from app.main import app
import app.modules.orders.router as orders_router
from app.modules.orders.schemas import (
    OrderAdrDetailsDTO,
    OrderCreateRequestDTO,
    OrderDetailDTO,
    OrderDetailResponseDTO,
    OrdersEntitlementDTO,
    OrdersEntitlementSourceDTO,
    OrderGoodsDTO,
    OrderPartyDTO,
    OrderPlaceOfDeliveryDTO,
    OrderReferencesDTO,
    OrderStructuredAddressDTO,
    OrderTakingOverDTO,
    OrdersListQueryDTO,
    OrdersListResponseDTO,
    OrderSummaryDTO,
)


LEGACY_ORDER_KEYS = {
    "id",
    "tenant_id",
    "order_no",
    "status",
    "transport_mode",
    "direction",
    "customer_name",
    "pickup_location",
    "delivery_location",
    "cargo_description",
    "reference_no",
    "scheduled_pickup_at",
    "scheduled_delivery_at",
    "payload",
    "created_by",
    "updated_by",
    "created_at",
    "updated_at",
}

CMR_ADR_MIN_KEYS = {
    "shipper",
    "consignee",
    "carrier",
    "taking_over",
    "place_of_delivery",
    "goods",
    "references",
    "instructions_formalities",
    "is_dangerous_goods",
    "adr",
}


class _FakeDB:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def _token(*, tenant_id: str = "tenant-ref-001", sub: str = "owner@tenant.local") -> str:
    return create_access_token({"sub": sub, "roles": ["TENANT_ADMIN"], "tenant_id": tenant_id})


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token()}"}


def _entitlement() -> OrdersEntitlementDTO:
    return OrdersEntitlementDTO(
        allowed=True,
        module_code="MODULE_ORDERS",
        reason="module_license_active",
        source=OrdersEntitlementSourceDTO(license_type="MODULE_PAID", license_id="lic-orders-001"),
        valid_to="2026-12-31T00:00:00+00:00",
    )


def _address() -> OrderStructuredAddressDTO:
    return OrderStructuredAddressDTO(
        address_line_1="bul. Tsarigradsko shose 1",
        address_line_2="fl. 2",
        city="Sofia",
        postal_code="1000",
        country_code="BG",
    )


def _party(name: str) -> OrderPartyDTO:
    return OrderPartyDTO(
        legal_name=name,
        vat_number="BG123456789",
        registration_number="205000001",
        address=_address(),
        contact_name="Ops Contact",
        contact_email="ops@example.local",
        contact_phone="+35929990000",
    )


def _summary(order_id: str = "ord-001") -> OrderSummaryDTO:
    return OrderSummaryDTO(
        id=order_id,
        tenant_id="tenant-ref-001",
        order_no="ORD-REF-001",
        status="DRAFT",
        transport_mode="ROAD",
        direction="OUTBOUND",
        shipper=_party("Shipper OOD"),
        consignee=_party("Consignee OOD"),
        carrier=_party("Carrier AD"),
        taking_over=OrderTakingOverDTO(place="Sofia Terminal", date="2026-03-10", address=_address()),
        place_of_delivery=OrderPlaceOfDeliveryDTO(place="Plovdiv Terminal", address=_address()),
        goods=OrderGoodsDTO(
            goods_description="General cargo",
            packages_count=24,
            packing_method="PALLETS",
            marks_numbers="MK-REF-001",
            gross_weight_kg=12400.5,
            volume_m3=54.2,
        ),
        references=OrderReferencesDTO(
            customer_reference="CUST-001",
            booking_reference="BOOK-001",
            contract_reference="CNTR-001",
            external_reference="EXT-001",
        ),
        instructions_formalities="Customs docs attached",
        is_dangerous_goods=True,
        adr=OrderAdrDetailsDTO(
            un_number="UN1203",
            adr_class="3",
            packing_group="II",
            proper_shipping_name="GASOLINE",
            adr_notes="ADR note",
        ),
        customer_name="Carrier Ops",
        pickup_location="Sofia Hub",
        delivery_location="Plovdiv Hub",
        cargo_description="General cargo",
        reference_no="REF-001",
        scheduled_pickup_at="2026-03-10T10:00:00+00:00",
        scheduled_delivery_at="2026-03-11T10:00:00+00:00",
        payload={"truck_id": "TRUCK-001", "fleet_size": 50},
        created_by="owner@tenant.local",
        updated_by="owner@tenant.local",
        created_at="2026-03-10T09:00:00+00:00",
        updated_at="2026-03-10T09:00:00+00:00",
    )


def _detail(order_id: str = "ord-001") -> OrderDetailDTO:
    return OrderDetailDTO.model_validate(_summary(order_id).model_dump())


def test_orders_openapi_contract_v1() -> None:
    schema = app.openapi()
    paths = schema.get("paths") or {}

    get_orders = (((paths.get("/orders") or {}).get("get") or {}).get("responses") or {}).get("200") or {}
    post_orders = ((paths.get("/orders") or {}).get("post") or {})
    get_order = (((paths.get("/orders/{order_id}") or {}).get("get") or {}).get("responses") or {}).get("200") or {}

    get_orders_ref = ((((get_orders.get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref") or "")
    post_response_200 = (post_orders.get("responses") or {}).get("200") or {}
    post_orders_ref = ((((post_response_200.get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref") or "")
    post_body_ref = ((((post_orders.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref") or ""
    get_order_ref = ((((get_order.get("content") or {}).get("application/json") or {}).get("schema") or {}).get("$ref") or "")

    assert get_orders_ref.endswith("/OrdersListResponseDTO")
    assert post_orders_ref.endswith("/OrderDetailResponseDTO")
    assert post_body_ref.endswith("/OrderCreateRequestDTO")
    assert get_order_ref.endswith("/OrderDetailResponseDTO")

    components = ((schema.get("components") or {}).get("schemas") or {})
    assert "OrderSummaryDTO" in components
    assert "OrderDetailDTO" in components
    assert "OrderStructuredAddressDTO" in components
    assert "OrderPartyDTO" in components
    assert "OrderGoodsDTO" in components
    assert "OrderAdrDetailsDTO" in components

    create_schema = components.get("OrderCreateRequestDTO") or {}
    create_props = create_schema.get("properties") or {}
    for key in [
        "shipper",
        "consignee",
        "carrier",
        "taking_over",
        "place_of_delivery",
        "goods",
        "references",
        "instructions_formalities",
        "is_dangerous_goods",
        "adr",
    ]:
        assert key in create_props

    address_schema = components.get("OrderStructuredAddressDTO") or {}
    address_props = address_schema.get("properties") or {}
    for key in ["address_line_1", "city", "postal_code", "country_code"]:
        assert key in address_props


def test_orders_list_detail_contract_and_boundary_types(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db

    captured: dict[str, str] = {}

    def _fake_list_orders(_db, *, tenant_id: str, query: OrdersListQueryDTO) -> OrdersListResponseDTO:
        captured["list_query_type"] = type(query).__name__
        assert tenant_id == "tenant-ref-001"
        return OrdersListResponseDTO(
            ok=True,
            tenant_id=tenant_id,
            items=[_summary("ord-list-001")],
            entitlement=_entitlement(),
        )

    def _fake_get_order(_db, *, tenant_id: str, order_id: str) -> OrderDetailResponseDTO:
        assert tenant_id == "tenant-ref-001"
        return OrderDetailResponseDTO(
            ok=True,
            tenant_id=tenant_id,
            order=_detail(order_id),
            entitlement=_entitlement(),
        )

    def _fake_create_order(_db, *, tenant_id: str, actor: str, payload: OrderCreateRequestDTO) -> OrderDetailResponseDTO:
        captured["create_payload_type"] = type(payload).__name__
        assert tenant_id == "tenant-ref-001"
        assert actor == "owner@tenant.local"
        return OrderDetailResponseDTO(
            ok=True,
            tenant_id=tenant_id,
            order=_detail("ord-create-001"),
            entitlement=_entitlement(),
        )

    monkeypatch.setattr(orders_router.service, "list_orders", _fake_list_orders)
    monkeypatch.setattr(orders_router.service, "get_order", _fake_get_order)
    monkeypatch.setattr(orders_router.service, "create_order", _fake_create_order)
    monkeypatch.setattr(orders_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pm, "_tenant_db_effective_permissions", lambda *, claims: ["ORDERS.READ", "ORDERS.WRITE"])

    try:
        client = TestClient(app)

        list_resp = client.get("/orders?status=DRAFT&limit=10", headers=_headers())
        assert list_resp.status_code == 200, list_resp.text
        list_json = list_resp.json() or {}

        assert list_json.get("ok") is True
        assert list_json.get("tenant_id") == "tenant-ref-001"
        assert "items" in list_json
        assert "order" not in list_json
        assert list_json.get("entitlement", {}).get("reason") == "module_license_active"

        first = (list_json.get("items") or [])[0]
        assert LEGACY_ORDER_KEYS.issubset(set(first.keys()))
        assert CMR_ADR_MIN_KEYS.issubset(set(first.keys()))
        assert isinstance(((first.get("shipper") or {}).get("address") or {}).get("address_line_1"), str)
        assert isinstance(first.get("is_dangerous_goods"), bool)

        detail_resp = client.get("/orders/ord-list-001", headers=_headers())
        assert detail_resp.status_code == 200, detail_resp.text
        detail_json = detail_resp.json() or {}

        assert detail_json.get("ok") is True
        assert detail_json.get("tenant_id") == "tenant-ref-001"
        assert "order" in detail_json
        assert "items" not in detail_json
        order_obj = detail_json.get("order") or {}
        assert LEGACY_ORDER_KEYS.issubset(set(order_obj.keys()))
        assert CMR_ADR_MIN_KEYS.issubset(set(order_obj.keys()))

        create_resp = client.post(
            "/orders",
            headers=_headers(),
            json={
                "order_no": "ORD-REF-NEW",
                "status": "DRAFT",
                "transport_mode": "ROAD",
                "direction": "OUTBOUND",
                "shipper": {
                    "legal_name": "Shipper OOD",
                    "address": {
                        "address_line_1": "bul. Tsarigradsko shose 1",
                        "city": "Sofia",
                        "postal_code": "1000",
                        "country_code": "BG",
                    },
                },
                "consignee": {
                    "legal_name": "Consignee OOD",
                    "address": {
                        "address_line_1": "ul. Vitosha 10",
                        "city": "Plovdiv",
                        "postal_code": "4000",
                        "country_code": "BG",
                    },
                },
                "carrier": {
                    "legal_name": "Carrier AD",
                    "address": {
                        "address_line_1": "bul. Bulgaria 100",
                        "city": "Sofia",
                        "postal_code": "1404",
                        "country_code": "BG",
                    },
                },
                "taking_over": {"place": "Sofia Terminal", "date": "2026-03-10"},
                "place_of_delivery": {"place": "Plovdiv Terminal"},
                "goods": {
                    "goods_description": "General cargo",
                    "packages_count": 24,
                    "packing_method": "PALLETS",
                    "marks_numbers": "MK-REF-001",
                    "gross_weight_kg": 12400.5,
                    "volume_m3": 54.2,
                },
                "references": {
                    "customer_reference": "CUST-001",
                    "booking_reference": "BOOK-001",
                },
                "instructions_formalities": "Customs docs attached",
                "is_dangerous_goods": True,
                "adr": {
                    "un_number": "UN1203",
                    "adr_class": "3",
                    "packing_group": "II",
                    "proper_shipping_name": "GASOLINE",
                    "adr_notes": "ADR note",
                },
                "payload": {"truck_id": "TRUCK-NEW", "fleet_size": 50},
            },
        )
        assert create_resp.status_code == 200, create_resp.text
        create_json = create_resp.json() or {}
        assert LEGACY_ORDER_KEYS.issubset(set((create_json.get("order") or {}).keys()))
        assert CMR_ADR_MIN_KEYS.issubset(set((create_json.get("order") or {}).keys()))

        assert captured.get("list_query_type") == "OrdersListQueryDTO"
        assert captured.get("create_payload_type") == "OrderCreateRequestDTO"
    finally:
        app.dependency_overrides.pop(get_db_session, None)
