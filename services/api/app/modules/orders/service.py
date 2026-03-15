from __future__ import annotations

from datetime import datetime, timezone
import time
import uuid

from sqlalchemy.orm import Session

from app.core.perf_profile import record_segment
from app.db.models import Order
from app.modules.licensing.service import service as licensing_service
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
    OrderTakingOverDTO,
    OrdersListQueryDTO,
    OrdersListResponseDTO,
    OrderSummaryDTO,
)

ALLOWED_STATUS = {"DRAFT", "SUBMITTED", "ASSIGNED", "IN_TRANSIT", "DELIVERED", "CANCELLED"}
ALLOWED_TRANSPORT = {"ROAD", "SEA", "RAIL", "AIR", "MULTI"}
ALLOWED_DIRECTION = {"OUTBOUND", "INBOUND", "INTERNAL"}


class OrdersService:
    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _clean(self, value: object, max_len: int) -> str:
        return str(value or "").strip()[:max_len]

    def _status(self, value: object, default: str = "DRAFT") -> str:
        out = self._clean(value or default, 32).upper()
        if out not in ALLOWED_STATUS:
            raise ValueError("order_status_invalid")
        return out

    def _transport(self, value: object, default: str = "ROAD") -> str:
        out = self._clean(value or default, 16).upper()
        if out not in ALLOWED_TRANSPORT:
            raise ValueError("order_transport_mode_invalid")
        return out

    def _direction(self, value: object, default: str = "OUTBOUND") -> str:
        out = self._clean(value or default, 16).upper()
        if out not in ALLOWED_DIRECTION:
            raise ValueError("order_direction_invalid")
        return out

    def _limit(self, value: int | None, default: int = 200) -> int:
        raw = int(value if value is not None else default)
        return max(1, min(raw, 1000))

    def _order_no(self, payload: OrderCreateRequestDTO, now: datetime) -> str:
        raw = self._clean(payload.order_no, 64).upper()
        if raw:
            return raw
        return f"ORD-{now.strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"

    def _parse_dt(self, value: object, field: str) -> datetime | None:
        if value in (None, ""):
            return None
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field}_invalid_iso") from exc
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _as_opt_str(self, value: object) -> str | None:
        if value is None:
            return None
        return str(value)

    def _as_model(self, value: object, model_cls):
        if value is None:
            return None
        if isinstance(value, model_cls):
            return value
        if isinstance(value, dict):
            try:
                return model_cls.model_validate(value)
            except Exception:  # noqa: BLE001
                return None
        return None

    def _payload_blob_from_contract(self, payload: OrderCreateRequestDTO) -> dict[str, object]:
        out = dict(payload.payload) if isinstance(payload.payload, dict) else {}

        if payload.shipper is not None:
            out["shipper"] = payload.shipper.model_dump(exclude_none=True)
        if payload.consignee is not None:
            out["consignee"] = payload.consignee.model_dump(exclude_none=True)
        if payload.carrier is not None:
            out["carrier"] = payload.carrier.model_dump(exclude_none=True)
        if payload.taking_over is not None:
            out["taking_over"] = payload.taking_over.model_dump(exclude_none=True)
        if payload.place_of_delivery is not None:
            out["place_of_delivery"] = payload.place_of_delivery.model_dump(exclude_none=True)
        if payload.goods is not None:
            out["goods"] = payload.goods.model_dump(exclude_none=True)
        if payload.references is not None:
            out["references"] = payload.references.model_dump(exclude_none=True)
        if payload.instructions_formalities is not None:
            out["instructions_formalities"] = str(payload.instructions_formalities)
        if payload.is_dangerous_goods is not None:
            out["is_dangerous_goods"] = bool(payload.is_dangerous_goods)
        if payload.adr is not None:
            out["adr"] = payload.adr.model_dump(exclude_none=True)

        return out

    def _entitlement(self, db: Session, *, tenant_id: str) -> OrdersEntitlementDTO:
        started = time.perf_counter()
        raw = licensing_service.resolve_module_entitlement(db, tenant_id, "MODULE_ORDERS")
        record_segment("entitlement_ms", (time.perf_counter() - started) * 1000.0)
        if not bool(raw.get("allowed")):
            raise ValueError(str(raw.get("reason") or "module_license_required"))

        source_obj = raw.get("source")
        source = None
        if isinstance(source_obj, dict):
            source = OrdersEntitlementSourceDTO(
                license_type=self._as_opt_str(source_obj.get("license_type")),
                license_id=self._as_opt_str(source_obj.get("license_id")),
            )

        return OrdersEntitlementDTO(
            allowed=True,
            module_code=self._as_opt_str(raw.get("module_code")),
            reason=self._as_opt_str(raw.get("reason")),
            source=source,
            valid_to=self._as_opt_str(raw.get("valid_to")),
        )

    def _to_summary(self, row: Order) -> OrderSummaryDTO:
        payload_obj = dict(row.payload_json or {})

        shipper = self._as_model(payload_obj.get("shipper"), OrderPartyDTO)
        consignee = self._as_model(payload_obj.get("consignee"), OrderPartyDTO)
        carrier = self._as_model(payload_obj.get("carrier"), OrderPartyDTO)
        taking_over = self._as_model(payload_obj.get("taking_over"), OrderTakingOverDTO)
        place_of_delivery = self._as_model(payload_obj.get("place_of_delivery"), OrderPlaceOfDeliveryDTO)
        goods = self._as_model(payload_obj.get("goods"), OrderGoodsDTO)
        references = self._as_model(payload_obj.get("references"), OrderReferencesDTO)
        adr = self._as_model(payload_obj.get("adr"), OrderAdrDetailsDTO)

        is_dg_obj = payload_obj.get("is_dangerous_goods")
        is_dangerous_goods = bool(is_dg_obj) if isinstance(is_dg_obj, bool) else None

        instructions_obj = payload_obj.get("instructions_formalities")
        instructions_formalities = str(instructions_obj) if instructions_obj is not None else None

        return OrderSummaryDTO(
            id=str(row.id),
            tenant_id=row.tenant_id,
            order_no=row.order_no,
            status=row.status,
            transport_mode=row.transport_mode,
            direction=row.direction,
            shipper=shipper,
            consignee=consignee,
            carrier=carrier,
            taking_over=taking_over,
            place_of_delivery=place_of_delivery,
            goods=goods,
            references=references,
            instructions_formalities=instructions_formalities,
            is_dangerous_goods=is_dangerous_goods,
            adr=adr,
            customer_name=row.customer_name,
            pickup_location=row.pickup_location,
            delivery_location=row.delivery_location,
            cargo_description=row.cargo_description,
            reference_no=row.reference_no,
            scheduled_pickup_at=row.scheduled_pickup_at.isoformat() if row.scheduled_pickup_at else None,
            scheduled_delivery_at=row.scheduled_delivery_at.isoformat() if row.scheduled_delivery_at else None,
            payload=payload_obj,
            created_by=row.created_by,
            updated_by=row.updated_by,
            created_at=row.created_at.isoformat() if row.created_at else None,
            updated_at=row.updated_at.isoformat() if row.updated_at else None,
        )

    def _to_detail(self, row: Order) -> OrderDetailDTO:
        return OrderDetailDTO.model_validate(self._to_summary(row).model_dump())

    def create_order(
        self,
        db: Session,
        *,
        tenant_id: str,
        actor: str,
        payload: OrderCreateRequestDTO,
    ) -> OrderDetailResponseDTO:
        now = self._now()
        ent = self._entitlement(db, tenant_id=tenant_id)

        order_no = self._order_no(payload, now)
        exists = db.query(Order).filter(Order.tenant_id == tenant_id, Order.order_no == order_no).first()
        if exists is not None:
            raise ValueError("order_no_exists")

        row = Order(
            tenant_id=tenant_id,
            order_no=order_no,
            status=self._status(payload.status, default="DRAFT"),
            transport_mode=self._transport(payload.transport_mode, default="ROAD"),
            direction=self._direction(payload.direction, default="OUTBOUND"),
            customer_name=self._clean(payload.customer_name, 255) or None,
            pickup_location=self._clean(payload.pickup_location, 255) or None,
            delivery_location=self._clean(payload.delivery_location, 255) or None,
            cargo_description=self._clean(payload.cargo_description, 2000) or None,
            reference_no=self._clean(payload.reference_no, 128) or None,
            scheduled_pickup_at=self._parse_dt(payload.scheduled_pickup_at, "scheduled_pickup_at"),
            scheduled_delivery_at=self._parse_dt(payload.scheduled_delivery_at, "scheduled_delivery_at"),
            payload_json=self._payload_blob_from_contract(payload),
            created_by=self._clean(actor, 255) or "unknown",
            updated_by=self._clean(actor, 255) or "unknown",
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        db.flush()

        return OrderDetailResponseDTO(
            ok=True,
            tenant_id=tenant_id,
            order=self._to_detail(row),
            entitlement=ent,
        )

    def list_orders(
        self,
        db: Session,
        *,
        tenant_id: str,
        query: OrdersListQueryDTO,
    ) -> OrdersListResponseDTO:
        service_started = time.perf_counter()
        ent = self._entitlement(db, tenant_id=tenant_id)

        q = db.query(Order).filter(Order.tenant_id == tenant_id)
        if query.status:
            q = q.filter(Order.status == self._status(query.status, default="DRAFT"))

        query_started = time.perf_counter()
        rows = q.order_by(Order.created_at.desc()).limit(self._limit(query.limit)).all()
        record_segment("query_ms", (time.perf_counter() - query_started) * 1000.0)

        serialize_started = time.perf_counter()
        items = [self._to_summary(x) for x in rows]
        record_segment("serialize_ms", (time.perf_counter() - serialize_started) * 1000.0)
        record_segment("total_service_ms", (time.perf_counter() - service_started) * 1000.0)

        return OrdersListResponseDTO(
            ok=True,
            tenant_id=tenant_id,
            items=items,
            entitlement=ent,
        )

    def get_order(self, db: Session, *, tenant_id: str, order_id: str) -> OrderDetailResponseDTO:
        ent = self._entitlement(db, tenant_id=tenant_id)
        row = db.query(Order).filter(Order.id == order_id, Order.tenant_id == tenant_id).first()
        if row is None:
            raise ValueError("order_not_found")

        return OrderDetailResponseDTO(
            ok=True,
            tenant_id=tenant_id,
            order=self._to_detail(row),
            entitlement=ent,
        )


service = OrdersService()
