from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import case, desc, func
from sqlalchemy.orm import Session

from app.db.models import EidonAIQualityEvent
from app.modules.ai.schemas import EidonQualitySummaryResponseDTO, EidonQualitySummaryRowDTO

DEFAULT_EVENT_TYPE = "ORDER_INTAKE_FEEDBACK_V1"
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _normalized_event_type(value: str | None) -> str:
    raw = str(value or "").strip()
    return raw or DEFAULT_EVENT_TYPE


def _normalized_limit(value: int) -> int:
    try:
        parsed = int(value)
    except Exception:  # noqa: BLE001
        parsed = DEFAULT_LIMIT
    return max(1, min(parsed, MAX_LIMIT))


class EidonOrderQualityAnalysisService:
    def summarize(
        self,
        *,
        db: Session,
        event_type: str = DEFAULT_EVENT_TYPE,
        limit: int = DEFAULT_LIMIT,
    ) -> EidonQualitySummaryResponseDTO:
        event_type_norm = _normalized_event_type(event_type)
        limit_norm = _normalized_limit(limit)

        rows = (
            db.query(
                EidonAIQualityEvent.template_fingerprint.label("template_fingerprint"),
                func.count(EidonAIQualityEvent.id).label("event_count"),
                func.coalesce(func.sum(EidonAIQualityEvent.confirmed_count), 0).label("total_confirmed_count"),
                func.coalesce(func.sum(EidonAIQualityEvent.corrected_count), 0).label("total_corrected_count"),
                func.coalesce(func.sum(EidonAIQualityEvent.unresolved_count), 0).label("total_unresolved_count"),
                func.coalesce(
                    func.sum(
                        case((EidonAIQualityEvent.human_confirmation_recorded.is_(True), 1), else_=0)
                    ),
                    0,
                ).label("human_confirmation_true_count"),
                func.max(EidonAIQualityEvent.created_at).label("last_event_at"),
            )
            .filter(EidonAIQualityEvent.event_type == event_type_norm)
            .group_by(EidonAIQualityEvent.template_fingerprint)
            .order_by(desc("event_count"), desc("last_event_at"))
            .limit(limit_norm)
            .all()
        )

        out_rows: list[EidonQualitySummaryRowDTO] = []
        for item in list(rows or []):
            template_fingerprint = str(item[0] or "")
            event_count = int(item[1] or 0)
            total_confirmed_count = int(item[2] or 0)
            total_corrected_count = int(item[3] or 0)
            total_unresolved_count = int(item[4] or 0)
            human_confirmation_true_count = int(item[5] or 0)
            last_event_at_raw = item[6]

            denominator = total_confirmed_count + total_corrected_count + total_unresolved_count
            correction_rate = (float(total_corrected_count) / float(denominator)) if denominator > 0 else None

            last_event_at: str | None = None
            if isinstance(last_event_at_raw, datetime):
                last_event_at = last_event_at_raw.isoformat()

            out_rows.append(
                EidonQualitySummaryRowDTO(
                    template_fingerprint=template_fingerprint,
                    event_count=event_count,
                    total_confirmed_count=total_confirmed_count,
                    total_corrected_count=total_corrected_count,
                    total_unresolved_count=total_unresolved_count,
                    human_confirmation_true_count=human_confirmation_true_count,
                    correction_rate=correction_rate,
                    last_event_at=last_event_at,
                )
            )

        return EidonQualitySummaryResponseDTO(
            ok=True,
            event_type=event_type_norm,
            limit=limit_norm,
            rows=out_rows,
            generated_at=_now_utc().isoformat(),
        )


service = EidonOrderQualityAnalysisService()
