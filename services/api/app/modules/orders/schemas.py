from __future__ import annotations

from pydantic import BaseModel, Field


class OrdersEntitlementSourceDTO(BaseModel):
    license_type: str | None = None
    license_id: str | None = None


class OrdersEntitlementDTO(BaseModel):
    allowed: bool
    module_code: str | None = None
    reason: str | None = None
    source: OrdersEntitlementSourceDTO | None = None
    valid_to: str | None = None


class OrderStructuredAddressDTO(BaseModel):
    address_line_1: str
    address_line_2: str | None = None
    city: str
    postal_code: str
    country_code: str


class OrderPartyDTO(BaseModel):
    legal_name: str | None = None
    vat_number: str | None = None
    registration_number: str | None = None
    address: OrderStructuredAddressDTO | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None


class OrderTakingOverDTO(BaseModel):
    place: str | None = None
    date: str | None = None
    address: OrderStructuredAddressDTO | None = None


class OrderPlaceOfDeliveryDTO(BaseModel):
    place: str | None = None
    address: OrderStructuredAddressDTO | None = None


class OrderGoodsDTO(BaseModel):
    goods_description: str | None = None
    packages_count: int | None = Field(default=None, ge=0)
    packing_method: str | None = None
    marks_numbers: str | None = None
    gross_weight_kg: float | None = Field(default=None, ge=0)
    volume_m3: float | None = Field(default=None, ge=0)


class OrderAdrDetailsDTO(BaseModel):
    un_number: str | None = None
    adr_class: str | None = None
    packing_group: str | None = None
    proper_shipping_name: str | None = None
    adr_notes: str | None = None


class OrderReferencesDTO(BaseModel):
    customer_reference: str | None = None
    booking_reference: str | None = None
    contract_reference: str | None = None
    external_reference: str | None = None


class OrderSummaryDTO(BaseModel):
    id: str
    tenant_id: str
    order_no: str
    status: str
    transport_mode: str
    direction: str

    shipper: OrderPartyDTO | None = None
    consignee: OrderPartyDTO | None = None
    carrier: OrderPartyDTO | None = None
    taking_over: OrderTakingOverDTO | None = None
    place_of_delivery: OrderPlaceOfDeliveryDTO | None = None
    goods: OrderGoodsDTO | None = None
    references: OrderReferencesDTO | None = None
    instructions_formalities: str | None = None
    is_dangerous_goods: bool | None = None
    adr: OrderAdrDetailsDTO | None = None

    customer_name: str | None = None
    pickup_location: str | None = None
    delivery_location: str | None = None
    cargo_description: str | None = None
    reference_no: str | None = None
    scheduled_pickup_at: str | None = None
    scheduled_delivery_at: str | None = None

    payload: dict[str, object] = Field(default_factory=dict)

    created_by: str | None = None
    updated_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class OrderDetailDTO(OrderSummaryDTO):
    pass


class OrderCreateRequestDTO(BaseModel):
    order_no: str | None = None
    status: str | None = None
    transport_mode: str | None = None
    direction: str | None = None

    shipper: OrderPartyDTO | None = None
    consignee: OrderPartyDTO | None = None
    carrier: OrderPartyDTO | None = None
    taking_over: OrderTakingOverDTO | None = None
    place_of_delivery: OrderPlaceOfDeliveryDTO | None = None
    goods: OrderGoodsDTO | None = None
    references: OrderReferencesDTO | None = None
    instructions_formalities: str | None = None
    is_dangerous_goods: bool | None = None
    adr: OrderAdrDetailsDTO | None = None

    customer_name: str | None = None
    pickup_location: str | None = None
    delivery_location: str | None = None
    cargo_description: str | None = None
    reference_no: str | None = None
    scheduled_pickup_at: str | None = None
    scheduled_delivery_at: str | None = None

    # Transitional only: legacy flexible payload remains optional.
    payload: object | None = None


class OrdersListQueryDTO(BaseModel):
    status: str | None = None
    limit: int = 200


class OrdersListResponseDTO(BaseModel):
    ok: bool
    tenant_id: str
    items: list[OrderSummaryDTO] = Field(default_factory=list)
    entitlement: OrdersEntitlementDTO


class OrderDetailResponseDTO(BaseModel):
    ok: bool
    tenant_id: str
    order: OrderDetailDTO
    entitlement: OrdersEntitlementDTO
