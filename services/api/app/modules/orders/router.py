from __future__ import annotations

import os
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.auth import require_tenant_context
from app.core.perf_profile import is_request_profile_active, record_segment
from app.db.session import get_db_session
from app.modules.orders.schemas import (
    OrderCreateRequestDTO,
    OrderDetailResponseDTO,
    OrdersListQueryDTO,
    OrdersListResponseDTO,
)
from app.modules.orders.service import service

router = APIRouter(prefix="/orders", tags=["orders"])


def _err_status(detail: str) -> int:
    if detail in {"order_not_found"}:
        return 404
    if detail in {"order_no_exists"}:
        return 409
    if detail in {"core_required", "core_license_required", "module_license_required"}:
        return 402
    return 400


def _is_retryable_txn_error(exc: OperationalError) -> bool:
    msg = str(getattr(exc, "orig", exc) or exc).lower()
    markers = (
        "retry_serializable",
        "restart transaction",
        "transactionretry",
        "serializationfailure",
    )
    return any(marker in msg for marker in markers)


def _orders_breakdown_enabled() -> bool:
    raw = str(os.getenv("MYDATA_PERF_ORDERS_BREAKDOWN", "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


@router.get("", response_model=OrdersListResponseDTO)
def list_orders(
    status: str | None = None,
    limit: int = 200,
    claims: dict[str, object] = Depends(require_tenant_context),
    db: Session = Depends(get_db_session),
) -> OrdersListResponseDTO | JSONResponse:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    query = OrdersListQueryDTO(status=status, limit=limit)

    try:
        out = service.list_orders(db, tenant_id=tenant_id, query=query)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_err_status(detail), detail=detail) from exc

    if is_request_profile_active():
        encode_started = time.perf_counter()
        response = JSONResponse(content=jsonable_encoder(out))
        record_segment("response_encode_ms", (time.perf_counter() - encode_started) * 1000.0)
        return response

    return out


@router.post("", response_model=OrderDetailResponseDTO)
def create_order(
    payload: OrderCreateRequestDTO,
    claims: dict[str, object] = Depends(require_tenant_context),
    db: Session = Depends(get_db_session),
) -> OrderDetailResponseDTO:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    try:
        out = service.create_order(db, tenant_id=tenant_id, actor=actor, payload=payload)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_err_status(detail), detail=detail) from exc

    row = out.order
    write_audit(
        db,
        action="orders.created",
        actor=actor,
        tenant_id=tenant_id,
        target=f"orders/{row.id}",
        metadata={
            "order_no": row.order_no,
            "status": row.status,
            "transport_mode": row.transport_mode,
            "entitlement_reason": out.entitlement.reason,
        },
    )
    db.commit()
    return out


@router.get("/{order_id}", response_model=OrderDetailResponseDTO)
def get_order(
    order_id: str,
    claims: dict[str, object] = Depends(require_tenant_context),
    db: Session = Depends(get_db_session),
) -> OrderDetailResponseDTO:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    try:
        out = service.get_order(db, tenant_id=tenant_id, order_id=order_id)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_err_status(detail), detail=detail) from exc

    row = out.order
    extra_sql_started = time.perf_counter()
    try:
        write_audit(
            db,
            action="orders.read",
            actor=actor,
            tenant_id=tenant_id,
            target=f"orders/{row.id}",
            metadata={"order_no": row.order_no, "status": row.status},
        )
        db.commit()
        return out
    except OperationalError as exc:
        db.rollback()
        if _is_retryable_txn_error(exc):
            # Best-effort read audit under Cockroach retry pressure; never fail GET payload after successful read.
            record_segment("orders_read_audit_retry_exhausted", 1.0)
            return out
        raise
    finally:
        if _orders_breakdown_enabled():
            record_segment("orders_extra_sql_count", 1.0)
            record_segment("orders_extra_sql_ms", (time.perf_counter() - extra_sql_started) * 1000.0)
