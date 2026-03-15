from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Order

OBJECT_REFERENCE_NOT_ACCESSIBLE = "object_reference_not_accessible"
ORDER_REFERENCE_KEYS: tuple[str, ...] = ("order_id", "order_reference_id", "existing_order_id")


@dataclass(frozen=True)
class TenantRetrievalActionGuardResult:
    allowed: bool
    code: str


class TenantRetrievalActionGuard:
    def _normalize_ref(self, value: Any) -> str:
        return str(value or "").strip()

    def _order_reference_visible_for_tenant(
        self,
        *,
        db: Session,
        tenant_id: str,
        order_reference_id: str,
    ) -> bool:
        row = (
            db.query(Order.id)
            .filter(
                Order.id == order_reference_id,
                Order.tenant_id == tenant_id,
            )
            .first()
        )
        return row is not None

    def validate_order_reference_access(
        self,
        *,
        db: Session,
        tenant_id: str,
        order_reference_id: str | None,
    ) -> TenantRetrievalActionGuardResult:
        tenant_norm = self._normalize_ref(tenant_id)
        ref_norm = self._normalize_ref(order_reference_id)
        if not tenant_norm:
            raise ValueError("missing_tenant_context")
        if not ref_norm:
            raise ValueError(OBJECT_REFERENCE_NOT_ACCESSIBLE)

        if not self._order_reference_visible_for_tenant(
            db=db,
            tenant_id=tenant_norm,
            order_reference_id=ref_norm,
        ):
            raise ValueError(OBJECT_REFERENCE_NOT_ACCESSIBLE)

        return TenantRetrievalActionGuardResult(
            allowed=True,
            code="allow",
        )


def get_order_reference_from_existing_draft_context(payload: Any) -> str | None:
    ctx = getattr(payload, "existing_order_draft_context", None)
    if ctx is None:
        return None
    ref = str(getattr(ctx, "id", "") or "").strip()
    return ref or None


def has_existing_draft_context_path(payload: Any) -> bool:
    return getattr(payload, "existing_order_draft_context", None) is not None


def get_order_reference_from_feedback_payload(payload: Any) -> str | None:
    candidate = getattr(payload, "proposed_draft_order_candidate", None)
    candidate_payload = getattr(candidate, "payload", None)
    if not isinstance(candidate_payload, dict):
        return None
    for key in ORDER_REFERENCE_KEYS:
        if key not in candidate_payload:
            continue
        ref = str(candidate_payload.get(key) or "").strip()
        if ref:
            return ref
        return None
    return None


def has_feedback_order_reference_path(payload: Any) -> bool:
    candidate = getattr(payload, "proposed_draft_order_candidate", None)
    candidate_payload = getattr(candidate, "payload", None)
    if not isinstance(candidate_payload, dict):
        return False
    return any(key in candidate_payload for key in ORDER_REFERENCE_KEYS)


service = TenantRetrievalActionGuard()

