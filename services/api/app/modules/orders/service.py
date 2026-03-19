from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import os
import time
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.perf_profile import get_recorded_segment, record_segment
from app.core.perf_sql_trace import sql_trace_zone
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
    def _orders_breakdown_enabled(self) -> bool:
        raw = str(os.getenv("MYDATA_PERF_ORDERS_BREAKDOWN", "0")).strip().lower()
        return raw in {"1", "true", "yes", "on"}

    def _access_breakdown_enabled(self) -> bool:
        raw = str(os.getenv("MYDATA_PERF_ACCESS_BREAKDOWN", "0")).strip().lower()
        return raw in {"1", "true", "yes", "on"}

    def _record_access_envelope_total(self) -> None:
        if not self._access_breakdown_enabled():
            return
        tenant_authz_ms = get_recorded_segment("tenant_db_authz_ms")
        entitlement_ms = get_recorded_segment("entitlement_ms")
        target_total = max(0.0, tenant_authz_ms + entitlement_ms)
        current_total = get_recorded_segment("access_envelope_total_ms")
        delta = target_total - current_total
        if delta > 0.0:
            record_segment("access_envelope_total_ms", delta)

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

    def _row_get(self, row: object, field: str):
        if isinstance(row, Mapping):
            return row.get(field)
        return getattr(row, field, None)

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
        access_breakdown = self._access_breakdown_enabled()
        cache_key = ("orders_entitlement", str(tenant_id).strip(), "MODULE_ORDERS")
        cache = None
        if isinstance(getattr(db, "info", None), dict):
            cache = db.info.setdefault("_mydata_orders_service_cache", {})
            cached = cache.get(cache_key)
            if isinstance(cached, OrdersEntitlementDTO):
                record_segment("entitlement_cache_hit", 1.0)
                record_segment("entitlement_ms", 0.0)
                if access_breakdown:
                    record_segment("entitlement_sql_ms", 0.0)
                    record_segment("entitlement_session_ms", 0.0)
                    record_segment("entitlement_wrapper_ms", 0.0)
                    record_segment("entitlement_decision_ms", 0.0)
                    self._record_access_envelope_total()
                return cached.model_copy(deep=True)

        record_segment("entitlement_cache_miss", 1.0)
        sql_before_ms = get_recorded_segment("sql_query_ms_entitlement") if access_breakdown else 0.0
        wrapper_started = time.perf_counter()
        started = time.perf_counter()
        with sql_trace_zone("entitlement"):
            raw = licensing_service.resolve_module_entitlement(db, tenant_id, "MODULE_ORDERS")
        entitlement_ms = (time.perf_counter() - started) * 1000.0
        record_segment("entitlement_ms", entitlement_ms)
        if not bool(raw.get("allowed")):
            if access_breakdown:
                sql_after_ms = get_recorded_segment("sql_query_ms_entitlement")
                sql_ms = max(0.0, sql_after_ms - sql_before_ms)
                wrapper_ms = max(0.0, (time.perf_counter() - wrapper_started) * 1000.0 - sql_ms)
                record_segment("entitlement_sql_ms", sql_ms)
                record_segment("entitlement_session_ms", 0.0)
                record_segment("entitlement_wrapper_ms", wrapper_ms)
                record_segment("entitlement_decision_ms", 0.0)
                self._record_access_envelope_total()
            raise ValueError(str(raw.get("reason") or "module_license_required"))

        decision_started = time.perf_counter()
        source_obj = raw.get("source")
        source = None
        if isinstance(source_obj, dict):
            source = OrdersEntitlementSourceDTO(
                license_type=self._as_opt_str(source_obj.get("license_type")),
                license_id=self._as_opt_str(source_obj.get("license_id")),
            )

        out = OrdersEntitlementDTO(
            allowed=True,
            module_code=self._as_opt_str(raw.get("module_code")),
            reason=self._as_opt_str(raw.get("reason")),
            source=source,
            valid_to=self._as_opt_str(raw.get("valid_to")),
        )
        if access_breakdown:
            decision_ms = (time.perf_counter() - decision_started) * 1000.0
            sql_after_ms = get_recorded_segment("sql_query_ms_entitlement")
            sql_ms = max(0.0, sql_after_ms - sql_before_ms)
            wrapper_ms = max(0.0, (time.perf_counter() - wrapper_started) * 1000.0 - sql_ms)
            record_segment("entitlement_sql_ms", sql_ms)
            record_segment("entitlement_session_ms", 0.0)
            record_segment("entitlement_wrapper_ms", wrapper_ms)
            record_segment("entitlement_decision_ms", decision_ms)
            self._record_access_envelope_total()
        if isinstance(cache, dict):
            cache[cache_key] = out.model_copy(deep=True)
        return out

    def _to_summary(self, row: Order | Mapping[str, object]) -> OrderSummaryDTO:
        payload_raw = self._row_get(row, "payload_json")
        payload_obj = dict(payload_raw) if isinstance(payload_raw, dict) else {}
        scheduled_pickup_at = self._row_get(row, "scheduled_pickup_at")
        scheduled_delivery_at = self._row_get(row, "scheduled_delivery_at")
        created_at = self._row_get(row, "created_at")
        updated_at = self._row_get(row, "updated_at")

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
            id=str(self._row_get(row, "id")),
            tenant_id=str(self._row_get(row, "tenant_id") or ""),
            order_no=str(self._row_get(row, "order_no") or ""),
            status=str(self._row_get(row, "status") or ""),
            transport_mode=str(self._row_get(row, "transport_mode") or ""),
            direction=str(self._row_get(row, "direction") or ""),
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
            customer_name=self._row_get(row, "customer_name"),
            pickup_location=self._row_get(row, "pickup_location"),
            delivery_location=self._row_get(row, "delivery_location"),
            cargo_description=self._row_get(row, "cargo_description"),
            reference_no=self._row_get(row, "reference_no"),
            scheduled_pickup_at=scheduled_pickup_at.isoformat() if scheduled_pickup_at else None,
            scheduled_delivery_at=scheduled_delivery_at.isoformat() if scheduled_delivery_at else None,
            payload=payload_obj,
            created_by=self._row_get(row, "created_by"),
            updated_by=self._row_get(row, "updated_by"),
            created_at=created_at.isoformat() if created_at else None,
            updated_at=updated_at.isoformat() if updated_at else None,
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
        breakdown_enabled = self._orders_breakdown_enabled()
        ent = self._entitlement(db, tenant_id=tenant_id)

        stmt = select(
            Order.id,
            Order.tenant_id,
            Order.order_no,
            Order.status,
            Order.transport_mode,
            Order.direction,
            Order.customer_name,
            Order.pickup_location,
            Order.delivery_location,
            Order.cargo_description,
            Order.reference_no,
            Order.scheduled_pickup_at,
            Order.scheduled_delivery_at,
            Order.payload_json,
            Order.created_by,
            Order.updated_by,
            Order.created_at,
            Order.updated_at,
        ).where(Order.tenant_id == tenant_id)
        if query.status:
            stmt = stmt.where(Order.status == self._status(query.status, default="DRAFT"))

        query_started = time.perf_counter()
        rows = db.execute(stmt.order_by(Order.created_at.desc()).limit(self._limit(query.limit))).mappings().all()
        query_ms = (time.perf_counter() - query_started) * 1000.0
        record_segment("query_ms", query_ms)
        if breakdown_enabled:
            record_segment("orders_query_ms", query_ms)

        serialize_started = time.perf_counter()
        items = [self._to_summary(x) for x in rows]
        materialize_ms = (time.perf_counter() - serialize_started) * 1000.0
        record_segment("serialize_ms", materialize_ms)
        if breakdown_enabled:
            record_segment("orders_materialize_ms", materialize_ms)

        dto_started = time.perf_counter()
        out = OrdersListResponseDTO(
            ok=True,
            tenant_id=tenant_id,
            items=items,
            entitlement=ent,
        )
        dto_ms = (time.perf_counter() - dto_started) * 1000.0
        total_service_ms = (time.perf_counter() - service_started) * 1000.0
        record_segment("total_service_ms", total_service_ms)
        if breakdown_enabled:
            record_segment("orders_serialize_ms", dto_ms)
            record_segment("orders_service_ms", total_service_ms)

        return out

    def get_order(self, db: Session, *, tenant_id: str, order_id: str) -> OrderDetailResponseDTO:
        service_started = time.perf_counter()
        breakdown_enabled = self._orders_breakdown_enabled()
        ent = self._entitlement(db, tenant_id=tenant_id)
        query_started = time.perf_counter()
        row = db.query(Order).filter(Order.id == order_id, Order.tenant_id == tenant_id).first()
        query_ms = (time.perf_counter() - query_started) * 1000.0
        if breakdown_enabled:
            record_segment("orders_query_ms", query_ms)
        if row is None:
            raise ValueError("order_not_found")

        materialize_started = time.perf_counter()
        order_detail = self._to_detail(row)
        materialize_ms = (time.perf_counter() - materialize_started) * 1000.0
        dto_started = time.perf_counter()
        out = OrderDetailResponseDTO(
            ok=True,
            tenant_id=tenant_id,
            order=order_detail,
            entitlement=ent,
        )
        dto_ms = (time.perf_counter() - dto_started) * 1000.0
        if breakdown_enabled:
            total_service_ms = (time.perf_counter() - service_started) * 1000.0
            record_segment("orders_materialize_ms", materialize_ms)
            record_segment("orders_serialize_ms", dto_ms)
            record_segment("orders_service_ms", total_service_ms)
        return out


service = OrdersService()
