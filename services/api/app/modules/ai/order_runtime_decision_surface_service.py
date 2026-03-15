from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.db.models import (
    EidonPatternActivationRecord,
    EidonPatternDistributionRecord,
    EidonPatternPublishArtifact,
    EidonPatternRolloutGovernanceRecord,
    EidonRuntimeEnablementRecord,
)
from app.modules.ai.schemas import (
    EidonRuntimeDecisionSurfaceResponseDTO,
    EidonRuntimeDecisionSurfaceRowDTO,
)

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _normalized_limit(value: int) -> int:
    try:
        parsed = int(value)
    except Exception:  # noqa: BLE001
        parsed = DEFAULT_LIMIT
    return max(1, min(parsed, MAX_LIMIT))


class EidonRuntimeDecisionSurfaceService:
    def summarize(
        self,
        *,
        db: Session,
        limit: int = DEFAULT_LIMIT,
    ) -> EidonRuntimeDecisionSurfaceResponseDTO:
        limit_norm = _normalized_limit(limit)

        rows = (
            db.query(
                EidonPatternPublishArtifact.template_fingerprint.label("template_fingerprint"),
                EidonPatternPublishArtifact.pattern_version.label("pattern_version"),
                func.max(case((EidonPatternPublishArtifact.id.isnot(None), 1), else_=0)).label("publish_recorded_i"),
                func.max(case((EidonPatternDistributionRecord.id.isnot(None), 1), else_=0)).label("distribution_recorded_i"),
                func.max(case((EidonPatternRolloutGovernanceRecord.id.isnot(None), 1), else_=0)).label(
                    "rollout_governance_recorded_i"
                ),
                func.max(EidonPatternRolloutGovernanceRecord.eligibility_decision).label("rollout_eligibility_decision"),
                func.max(case((EidonPatternActivationRecord.id.isnot(None), 1), else_=0)).label("activation_recorded_i"),
                func.max(case((EidonRuntimeEnablementRecord.id.isnot(None), 1), else_=0)).label(
                    "runtime_enablement_recorded_i"
                ),
                func.max(EidonRuntimeEnablementRecord.runtime_decision).label("runtime_decision"),
                func.max(EidonPatternPublishArtifact.published_at).label("published_at"),
                func.max(EidonPatternDistributionRecord.recorded_at).label("distribution_recorded_at"),
                func.max(EidonPatternRolloutGovernanceRecord.recorded_at).label("rollout_recorded_at"),
                func.max(EidonPatternActivationRecord.recorded_at).label("activation_recorded_at"),
                func.max(EidonRuntimeEnablementRecord.recorded_at).label("runtime_recorded_at"),
            )
            .outerjoin(
                EidonPatternDistributionRecord,
                EidonPatternDistributionRecord.publish_artifact_id == EidonPatternPublishArtifact.id,
            )
            .outerjoin(
                EidonPatternRolloutGovernanceRecord,
                EidonPatternRolloutGovernanceRecord.distribution_record_id == EidonPatternDistributionRecord.id,
            )
            .outerjoin(
                EidonPatternActivationRecord,
                EidonPatternActivationRecord.rollout_governance_record_id == EidonPatternRolloutGovernanceRecord.id,
            )
            .outerjoin(
                EidonRuntimeEnablementRecord,
                EidonRuntimeEnablementRecord.activation_record_id == EidonPatternActivationRecord.id,
            )
            .group_by(
                EidonPatternPublishArtifact.template_fingerprint,
                EidonPatternPublishArtifact.pattern_version,
            )
            .all()
        )

        out_rows: list[EidonRuntimeDecisionSurfaceRowDTO] = []
        for item in list(rows or []):
            template_fingerprint = str(item[0] or "")
            pattern_version = str(item[1] or "")
            publish_recorded = int(item[2] or 0) > 0
            distribution_recorded = int(item[3] or 0) > 0
            rollout_governance_recorded = int(item[4] or 0) > 0
            rollout_eligibility_decision = str(item[5]) if item[5] is not None else None
            activation_recorded = int(item[6] or 0) > 0
            runtime_enablement_recorded = int(item[7] or 0) > 0
            runtime_decision = str(item[8]) if item[8] is not None else None
            raw_ts = [item[9], item[10], item[11], item[12], item[13]]
            dt_values = [v for v in raw_ts if isinstance(v, datetime)]
            last_event_raw = max(dt_values) if dt_values else None

            last_governance_event_at: str | None = None
            if isinstance(last_event_raw, datetime):
                last_governance_event_at = last_event_raw.isoformat()

            out_rows.append(
                EidonRuntimeDecisionSurfaceRowDTO(
                    template_fingerprint=template_fingerprint,
                    pattern_version=pattern_version,
                    publish_recorded=publish_recorded,
                    distribution_recorded=distribution_recorded,
                    rollout_governance_recorded=rollout_governance_recorded,
                    rollout_eligibility_decision=rollout_eligibility_decision,
                    activation_recorded=activation_recorded,
                    runtime_enablement_recorded=runtime_enablement_recorded,
                    runtime_decision=runtime_decision,
                    last_governance_event_at=last_governance_event_at,
                )
            )

        out_rows.sort(key=lambda row: row.last_governance_event_at or "", reverse=True)
        out_rows = out_rows[:limit_norm]

        return EidonRuntimeDecisionSurfaceResponseDTO(
            ok=True,
            limit=limit_norm,
            rows=out_rows,
            generated_at=_now_utc().isoformat(),
        )


service = EidonRuntimeDecisionSurfaceService()
