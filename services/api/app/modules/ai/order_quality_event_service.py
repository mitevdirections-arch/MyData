from __future__ import annotations

from statistics import mean
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import EidonAIQualityEvent
from app.modules.ai.schemas import EidonFeedbackConfidenceAdjustmentDTO


EVENT_TYPE_ORDER_INTAKE_FEEDBACK_V1 = "ORDER_INTAKE_FEEDBACK_V1"


class EidonOrderQualityEventService:
    def _confidence_adjustments_summary(self, adjustments: list[EidonFeedbackConfidenceAdjustmentDTO]) -> dict[str, Any]:
        deltas: list[float] = []
        increase_count = 0
        decrease_count = 0
        unchanged_count = 0
        rationale_counts: dict[str, int] = {}

        for item in adjustments:
            from_conf = float(item.from_confidence)
            to_conf = float(item.to_confidence)
            delta = to_conf - from_conf
            deltas.append(delta)

            if delta > 0:
                increase_count += 1
            elif delta < 0:
                decrease_count += 1
            else:
                unchanged_count += 1

            rationale = str(item.rationale or "").strip().lower() or "unknown"
            rationale_counts[rationale] = int(rationale_counts.get(rationale, 0)) + 1

        if not deltas:
            return {
                "total_adjustments": 0,
                "increase_count": 0,
                "decrease_count": 0,
                "unchanged_count": 0,
                "avg_delta": 0.0,
                "min_delta": 0.0,
                "max_delta": 0.0,
                "rationale_counts": {},
            }

        return {
            "total_adjustments": len(deltas),
            "increase_count": increase_count,
            "decrease_count": decrease_count,
            "unchanged_count": unchanged_count,
            "avg_delta": round(float(mean(deltas)), 6),
            "min_delta": round(float(min(deltas)), 6),
            "max_delta": round(float(max(deltas)), 6),
            "rationale_counts": rationale_counts,
        }

    def write_order_intake_feedback_event(
        self,
        *,
        db: Session,
        tenant_id: str,
        template_fingerprint: str,
        confirmed_count: int,
        corrected_count: int,
        unresolved_count: int,
        human_confirmation_recorded: bool,
        confidence_adjustments: list[EidonFeedbackConfidenceAdjustmentDTO],
    ) -> EidonAIQualityEvent:
        tid = str(tenant_id or "").strip()
        if not tid:
            raise ValueError("missing_tenant_context")

        fingerprint = str(template_fingerprint or "").strip()
        if not fingerprint:
            raise ValueError("template_fingerprint_required")

        event = EidonAIQualityEvent(
            tenant_id=tid,
            event_type=EVENT_TYPE_ORDER_INTAKE_FEEDBACK_V1,
            template_fingerprint=fingerprint,
            confirmed_count=max(0, int(confirmed_count)),
            corrected_count=max(0, int(corrected_count)),
            unresolved_count=max(0, int(unresolved_count)),
            human_confirmation_recorded=bool(human_confirmation_recorded),
            confidence_adjustments_summary_json=self._confidence_adjustments_summary(confidence_adjustments),
        )
        db.add(event)
        if hasattr(db, "flush"):
            db.flush()
        return event


service = EidonOrderQualityEventService()
