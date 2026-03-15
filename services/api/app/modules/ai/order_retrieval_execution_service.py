from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Order
from app.modules.ai.schemas import (
    EidonOrderRetrievalSummaryDTO,
    EidonRetrievalTraceabilityDTO,
)
from app.modules.ai.tenant_retrieval_action_guard import (
    OBJECT_REFERENCE_NOT_ACCESSIBLE,
    service as tenant_retrieval_action_guard,
)


class EidonOrderRetrievalExecutionService:
    def _normalized(self, value: str | None) -> str:
        return str(value or "").strip()

    def retrieve_order_reference(
        self,
        *,
        db: Session,
        tenant_id: str,
        order_reference_id: str | None,
        template_fingerprint: str | None = None,
    ) -> EidonOrderRetrievalSummaryDTO:
        tenant_norm = self._normalized(tenant_id)
        ref_norm = self._normalized(order_reference_id)
        fingerprint_norm = self._normalized(template_fingerprint) or None

        guard_out = tenant_retrieval_action_guard.validate_order_reference_access(
            db=db,
            tenant_id=tenant_norm,
            order_reference_id=ref_norm,
        )

        resolved_id = (
            db.query(Order.id)
            .filter(
                Order.id == ref_norm,
                Order.tenant_id == tenant_norm,
            )
            .scalar()
        )
        if resolved_id is None:
            raise ValueError(OBJECT_REFERENCE_NOT_ACCESSIBLE)

        return EidonOrderRetrievalSummaryDTO(
            object_type="order",
            object_id=str(resolved_id),
            template_fingerprint=fingerprint_norm,
            retrieval_traceability=EidonRetrievalTraceabilityDTO(
                retrieval_class="tenant_visible_order_reference_lookup",
                retrieval_marker="summary_only_guarded_reference_lookup",
                guard_outcome=guard_out.code,
            ),
            tenant_visible=True,
        )


service = EidonOrderRetrievalExecutionService()
