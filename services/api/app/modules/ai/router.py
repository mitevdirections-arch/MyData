from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.auth import require_claims, require_superadmin
from app.db.session import get_db_session
from app.modules.ai.eidon_orders_response_contract_v1 import (
    EIDON_ORDERS_RESPONSE_CONTRACT_VIOLATION,
    EIDON_ORDERS_RESPONSE_SURFACE_RETRIEVE_REFERENCE,
    enforce_orders_response_contract_or_fail,
)
from app.modules.ai.order_document_intake_service import service as order_document_intake_service
from app.modules.ai.order_draft_assist_service import service as order_draft_assist_service
from app.modules.ai.order_retrieval_execution_service import service as order_retrieval_execution_service
from app.modules.ai.orders_copilot_orchestration_service import (
    service as orders_copilot_orchestration_service,
)
from app.modules.ai.order_pattern_activation_service import service as order_pattern_activation_service
from app.modules.ai.order_runtime_enablement_service import service as order_runtime_enablement_service
from app.modules.ai.order_runtime_decision_surface_service import service as order_runtime_decision_surface_service
from app.modules.ai.order_intake_feedback_service import service as order_intake_feedback_service
from app.modules.ai.order_pattern_distribution_service import service as order_pattern_distribution_service
from app.modules.ai.order_pattern_rollout_governance_service import service as order_pattern_rollout_governance_service
from app.modules.ai.order_quality_analysis_service import service as order_quality_analysis_service
from app.modules.ai.order_template_publish_service import service as order_template_publish_service
from app.modules.ai.order_template_review_service import service as order_template_review_service
from app.modules.ai.order_template_submission_staging_service import service as order_template_submission_staging_service
from app.modules.ai.tenant_action_boundary_guard import AI_ACTION_BOUNDARY_VIOLATION
from app.modules.ai.tenant_retrieval_action_guard import (
    OBJECT_REFERENCE_NOT_ACCESSIBLE,
    has_existing_draft_context_path,
    has_feedback_order_reference_path,
)
from app.modules.ai.schemas import (
    EidonPatternDistributionRecordRequestDTO,
    EidonPatternDistributionResponseDTO,
    EidonPatternActivationRequestDTO,
    EidonPatternActivationResponseDTO,
    EidonRuntimeEnablementRequestDTO,
    EidonRuntimeEnablementResponseDTO,
    EidonPatternRolloutGovernanceRequestDTO,
    EidonPatternRolloutGovernanceResponseDTO,
    EidonQualitySummaryResponseDTO,
    EidonRuntimeDecisionSurfaceResponseDTO,
    EidonOrderDocumentIntakeRequestDTO,
    EidonOrderDocumentIntakeResponseDTO,
    EidonOrderDraftAssistRequestDTO,
    EidonOrderDraftAssistResponseDTO,
    EidonOrdersCopilotRequestDTO,
    EidonOrdersCopilotResponseDTO,
    EidonOrderReferenceRetrievalRequestDTO,
    EidonOrderReferenceRetrievalResponseDTO,
    EidonOrderIntakeFeedbackRequestDTO,
    EidonOrderIntakeFeedbackResponseDTO,
    EidonTemplateReviewDecisionRequestDTO,
    EidonTemplateReviewDecisionResponseDTO,
    EidonTemplatePublishRequestDTO,
    EidonTemplatePublishResponseDTO,
    EidonTemplateReviewQueueResponseDTO,
    EidonTemplateReviewReadResponseDTO,
    EidonTemplateSubmissionStagingRequestDTO,
    EidonTemplateSubmissionStagingResponseDTO,
)
from app.modules.licensing.deps import require_module_entitlement

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/tenant-copilot")
def tenant_copilot(
    payload: dict[str, Any],
    _entitlement: dict[str, Any] = Depends(require_module_entitlement("AI_COPILOT")),
    claims: dict[str, Any] = Depends(require_claims),
) -> dict[str, Any]:
    tenant_id = claims.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt_required")

    write_audit(
        action="ai.tenant_copilot",
        actor=claims.get("sub", "unknown"),
        tenant_id=str(tenant_id),
        target="ai/tenant",
        metadata={"prompt_len": len(prompt)},
    )

    return {
        "ok": True,
        "mode": "tenant",
        "policy": "advisory_only",
        "message": "Suggestion prepared under tenant policy constraints.",
    }


@router.post("/tenant-copilot/orders-copilot", response_model=EidonOrdersCopilotResponseDTO)
def tenant_copilot_orders_copilot(
    payload: EidonOrdersCopilotRequestDTO,
    _entitlement: dict[str, Any] = Depends(require_module_entitlement("AI_COPILOT")),
    claims: dict[str, Any] = Depends(require_claims),
    db: Session = Depends(get_db_session),
) -> EidonOrdersCopilotResponseDTO:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    intent_norm = str(payload.intent or "").strip()
    retrieval_path = intent_norm == "retrieve_order_reference"

    try:
        out = orders_copilot_orchestration_service.orchestrate(
            db=db,
            tenant_id=tenant_id,
            intent=intent_norm,
            payload=payload.payload,
        )
    except ValueError as exc:
        detail = str(exc)
        write_audit(
            db,
            action="ai.tenant_orders_copilot_deny",
            actor=actor,
            tenant_id=tenant_id,
            target="ai/tenant-copilot/orders-copilot",
            metadata={
                "orders_copilot_surface": "canonical",
                "orders_copilot_intent": intent_norm,
                "orders_copilot_outcome": "deny",
                "orders_copilot_deny_code": detail,
                "orders_copilot_traceability": "summary_only",
                "retrieval_object_type": "order" if retrieval_path else "not_applicable",
            },
        )
        db.commit()
        status_code = 403 if detail == OBJECT_REFERENCE_NOT_ACCESSIBLE else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    write_audit(
        db,
        action="ai.tenant_orders_copilot",
        actor=actor,
        tenant_id=tenant_id,
        target="ai/tenant-copilot/orders-copilot",
        metadata={
            "orders_copilot_surface": "canonical",
            "orders_copilot_intent": out.intent,
            "orders_copilot_outcome": "allow",
            "orders_copilot_traceability": "summary_only",
            "retrieval_object_type": "order" if out.intent == "retrieve_order_reference" else "not_applicable",
            "authoritative_finalize_allowed": out.authoritative_finalize_allowed,
            "warnings_count": len(out.warnings),
        },
    )
    db.commit()
    return out


@router.post("/tenant-copilot/retrieve-order-reference", response_model=EidonOrderReferenceRetrievalResponseDTO)
def tenant_copilot_retrieve_order_reference(
    payload: EidonOrderReferenceRetrievalRequestDTO,
    _entitlement: dict[str, Any] = Depends(require_module_entitlement("AI_COPILOT")),
    claims: dict[str, Any] = Depends(require_claims),
    db: Session = Depends(get_db_session),
) -> EidonOrderReferenceRetrievalResponseDTO:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    try:
        result = order_retrieval_execution_service.retrieve_order_reference(
            db=db,
            tenant_id=tenant_id,
            order_reference_id=payload.order_id,
            template_fingerprint=None,
        )
    except ValueError as exc:
        detail = str(exc)
        if detail == OBJECT_REFERENCE_NOT_ACCESSIBLE:
            write_audit(
                db,
                action="ai.tenant_order_reference_retrieval_deny",
                actor=actor,
                tenant_id=tenant_id,
                target="ai/tenant-copilot/retrieve-order-reference",
                metadata={
                    "retrieval_execution": "deny",
                    "retrieval_object_type": "order",
                    "retrieval_traceability": "summary_only",
                },
            )
            db.commit()
            raise HTTPException(status_code=403, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    out = EidonOrderReferenceRetrievalResponseDTO(
        ok=True,
        tenant_id=tenant_id,
        capability="EIDON_ORDER_REFERENCE_RETRIEVAL_V1",
        result=result,
        authoritative_finalize_allowed=False,
        warnings=[],
        source_traceability=result.retrieval_traceability,
        no_authoritative_finalize_rule="eidon_prepare_only_no_authoritative_finalize",
        system_truth_rule="ai_does_not_override_system_truth",
    )
    try:
        enforce_orders_response_contract_or_fail(
            surface_code=EIDON_ORDERS_RESPONSE_SURFACE_RETRIEVE_REFERENCE,
            response=out,
        )
    except ValueError as exc:
        detail = str(exc)
        if detail != EIDON_ORDERS_RESPONSE_CONTRACT_VIOLATION:
            raise
        raise HTTPException(status_code=400, detail=detail) from exc

    write_audit(
        db,
        action="ai.tenant_order_reference_retrieval",
        actor=actor,
        tenant_id=tenant_id,
        target="ai/tenant-copilot/retrieve-order-reference",
        metadata={
            "retrieval_execution": "allow",
            "retrieval_object_type": "order",
            "retrieval_traceability": "summary_only",
            "authoritative_finalize_allowed": out.authoritative_finalize_allowed,
        },
    )
    db.commit()
    return out


@router.post("/tenant-copilot/order-draft-assist", response_model=EidonOrderDraftAssistResponseDTO)
def tenant_copilot_order_draft_assist(
    payload: EidonOrderDraftAssistRequestDTO,
    _entitlement: dict[str, Any] = Depends(require_module_entitlement("AI_COPILOT")),
    claims: dict[str, Any] = Depends(require_claims),
    db: Session = Depends(get_db_session),
) -> EidonOrderDraftAssistResponseDTO:
    return _run_tenant_order_drafting_surface(
        payload=payload,
        claims=claims,
        db=db,
        action_success="ai.tenant_order_draft_assist",
        action_guard_deny="ai.tenant_order_draft_assist_guard_deny",
        action_boundary_deny="ai.tenant_order_draft_assist_action_boundary_deny",
        target="ai/tenant-copilot/order-draft-assist",
        surface_marker="compatibility",
    )


@router.post("/tenant-copilot/order-drafting", response_model=EidonOrderDraftAssistResponseDTO)
def tenant_copilot_order_drafting(
    payload: EidonOrderDraftAssistRequestDTO,
    _entitlement: dict[str, Any] = Depends(require_module_entitlement("AI_COPILOT")),
    claims: dict[str, Any] = Depends(require_claims),
    db: Session = Depends(get_db_session),
) -> EidonOrderDraftAssistResponseDTO:
    return _run_tenant_order_drafting_surface(
        payload=payload,
        claims=claims,
        db=db,
        action_success="ai.tenant_order_drafting",
        action_guard_deny="ai.tenant_order_drafting_guard_deny",
        action_boundary_deny="ai.tenant_order_drafting_action_boundary_deny",
        target="ai/tenant-copilot/order-drafting",
        surface_marker="canonical",
    )


def _run_tenant_order_drafting_surface(
    *,
    payload: EidonOrderDraftAssistRequestDTO,
    claims: dict[str, Any],
    db: Session,
    action_success: str,
    action_guard_deny: str,
    action_boundary_deny: str,
    target: str,
    surface_marker: str,
) -> EidonOrderDraftAssistResponseDTO:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    draft_context_path_used = has_existing_draft_context_path(payload)
    try:
        out = order_draft_assist_service.assist(db=db, tenant_id=tenant_id, payload=payload)
    except ValueError as exc:
        detail = str(exc)
        if detail == OBJECT_REFERENCE_NOT_ACCESSIBLE:
            write_audit(
                db,
                action=action_guard_deny,
                actor=actor,
                tenant_id=tenant_id,
                target=target,
                metadata={
                    "retrieval_action_guard": detail,
                    "retrieval_execution": "deny",
                    "retrieval_object_type": "order",
                    "retrieval_traceability": "summary_only",
                    "order_drafting_surface": surface_marker,
                },
            )
            db.commit()
        if detail == AI_ACTION_BOUNDARY_VIOLATION:
            write_audit(
                db,
                action=action_boundary_deny,
                actor=actor,
                tenant_id=tenant_id,
                target=target,
                metadata={
                    "tenant_action_boundary": detail,
                    "order_drafting_surface": surface_marker,
                },
            )
            db.commit()
        status_code = 403 if detail == OBJECT_REFERENCE_NOT_ACCESSIBLE else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    write_audit(
        db,
        action=action_success,
        actor=actor,
        tenant_id=tenant_id,
        target=target,
        metadata={
            "missing_required_fields": len(out.missing_required_fields),
            "ambiguous_fields": len(out.ambiguous_fields),
            "cmr_ready": out.cmr_readiness.ready,
            "adr_ready": out.adr_readiness.ready,
            "adr_applicable": out.adr_readiness.applicable,
            "authoritative_finalize_allowed": out.authoritative_finalize_allowed,
            "retrieval_action_guard": "allow" if draft_context_path_used else "not_applicable",
            "retrieval_execution": "allow" if draft_context_path_used else "not_applicable",
            "retrieval_object_type": "order" if draft_context_path_used else "not_applicable",
            "retrieval_traceability": "summary_only" if draft_context_path_used else "not_applicable",
            "tenant_action_boundary": "advisory_only",
            "order_drafting_surface": surface_marker,
        },
    )
    db.commit()
    return out


@router.post("/tenant-copilot/order-document-intake", response_model=EidonOrderDocumentIntakeResponseDTO)
def tenant_copilot_order_document_intake(
    payload: EidonOrderDocumentIntakeRequestDTO,
    _entitlement: dict[str, Any] = Depends(require_module_entitlement("AI_COPILOT")),
    claims: dict[str, Any] = Depends(require_claims),
    db: Session = Depends(get_db_session),
) -> EidonOrderDocumentIntakeResponseDTO:
    return _run_tenant_document_understanding_surface(
        payload=payload,
        claims=claims,
        db=db,
        action_success="ai.tenant_order_document_intake",
        action_deny="ai.tenant_order_document_intake_action_boundary_deny",
        target="ai/tenant-copilot/order-document-intake",
        surface_marker="compatibility",
    )


@router.post("/tenant-copilot/document-understanding", response_model=EidonOrderDocumentIntakeResponseDTO)
def tenant_copilot_document_understanding(
    payload: EidonOrderDocumentIntakeRequestDTO,
    _entitlement: dict[str, Any] = Depends(require_module_entitlement("AI_COPILOT")),
    claims: dict[str, Any] = Depends(require_claims),
    db: Session = Depends(get_db_session),
) -> EidonOrderDocumentIntakeResponseDTO:
    return _run_tenant_document_understanding_surface(
        payload=payload,
        claims=claims,
        db=db,
        action_success="ai.tenant_document_understanding",
        action_deny="ai.tenant_document_understanding_action_boundary_deny",
        target="ai/tenant-copilot/document-understanding",
        surface_marker="canonical",
    )


def _run_tenant_document_understanding_surface(
    *,
    payload: EidonOrderDocumentIntakeRequestDTO,
    claims: dict[str, Any],
    db: Session,
    action_success: str,
    action_deny: str,
    target: str,
    surface_marker: str,
) -> EidonOrderDocumentIntakeResponseDTO:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    try:
        out = order_document_intake_service.ingest(tenant_id=tenant_id, payload=payload)
    except ValueError as exc:
        detail = str(exc)
        if detail == AI_ACTION_BOUNDARY_VIOLATION:
            write_audit(
                db,
                action=action_deny,
                actor=actor,
                tenant_id=tenant_id,
                target=target,
                metadata={
                    "tenant_action_boundary": detail,
                    "document_understanding_surface": surface_marker,
                    "document_understanding_traceability": "summary_only",
                },
            )
            db.commit()
        raise HTTPException(status_code=400, detail=detail) from exc

    write_audit(
        db,
        action=action_success,
        actor=actor,
        tenant_id=tenant_id,
        target=target,
        metadata={
            "extracted_fields": len(out.extracted_fields),
            "missing_required_fields": len(out.missing_required_fields),
            "ambiguous_fields": len(out.ambiguous_fields),
            "cmr_ready": out.cmr_readiness.ready,
            "adr_ready": out.adr_readiness.ready,
            "adr_applicable": out.adr_readiness.applicable,
            "template_fingerprint": out.template_fingerprint,
            "template_learning_candidate_eligible": out.template_learning_candidate.eligible,
            "authoritative_finalize_allowed": out.authoritative_finalize_allowed,
            "tenant_action_boundary": "advisory_only",
            "document_understanding_surface": surface_marker,
            "document_understanding_traceability": "summary_only",
        },
    )
    db.commit()
    return out


@router.post("/tenant-copilot/order-intake-feedback", response_model=EidonOrderIntakeFeedbackResponseDTO)
def tenant_copilot_order_intake_feedback(
    payload: EidonOrderIntakeFeedbackRequestDTO,
    _entitlement: dict[str, Any] = Depends(require_module_entitlement("AI_COPILOT")),
    claims: dict[str, Any] = Depends(require_claims),
    db: Session = Depends(get_db_session),
) -> EidonOrderIntakeFeedbackResponseDTO:
    return _run_tenant_order_feedback_surface(
        payload=payload,
        claims=claims,
        db=db,
        action_success="ai.tenant_order_intake_feedback_loop",
        action_guard_deny="ai.tenant_order_intake_feedback_guard_deny",
        action_boundary_deny="ai.tenant_order_intake_feedback_action_boundary_deny",
        target="ai/tenant-copilot/order-intake-feedback",
        surface_marker="compatibility",
    )


@router.post("/tenant-copilot/order-feedback", response_model=EidonOrderIntakeFeedbackResponseDTO)
def tenant_copilot_order_feedback(
    payload: EidonOrderIntakeFeedbackRequestDTO,
    _entitlement: dict[str, Any] = Depends(require_module_entitlement("AI_COPILOT")),
    claims: dict[str, Any] = Depends(require_claims),
    db: Session = Depends(get_db_session),
) -> EidonOrderIntakeFeedbackResponseDTO:
    return _run_tenant_order_feedback_surface(
        payload=payload,
        claims=claims,
        db=db,
        action_success="ai.tenant_order_feedback",
        action_guard_deny="ai.tenant_order_feedback_guard_deny",
        action_boundary_deny="ai.tenant_order_feedback_action_boundary_deny",
        target="ai/tenant-copilot/order-feedback",
        surface_marker="canonical",
    )


def _run_tenant_order_feedback_surface(
    *,
    payload: EidonOrderIntakeFeedbackRequestDTO,
    claims: dict[str, Any],
    db: Session,
    action_success: str,
    action_guard_deny: str,
    action_boundary_deny: str,
    target: str,
    surface_marker: str,
) -> EidonOrderIntakeFeedbackResponseDTO:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    feedback_reference_path_used = has_feedback_order_reference_path(payload)
    try:
        out = order_intake_feedback_service.apply_feedback(db=db, tenant_id=tenant_id, payload=payload)
    except ValueError as exc:
        detail = str(exc)
        if detail == OBJECT_REFERENCE_NOT_ACCESSIBLE:
            write_audit(
                db,
                action=action_guard_deny,
                actor=actor,
                tenant_id=tenant_id,
                target=target,
                metadata={
                    "retrieval_action_guard": detail,
                    "retrieval_execution": "deny",
                    "retrieval_object_type": "order",
                    "retrieval_traceability": "summary_only",
                    "order_feedback_surface": surface_marker,
                },
            )
            db.commit()
        if detail == AI_ACTION_BOUNDARY_VIOLATION:
            write_audit(
                db,
                action=action_boundary_deny,
                actor=actor,
                tenant_id=tenant_id,
                target=target,
                metadata={
                    "tenant_action_boundary": detail,
                    "order_feedback_surface": surface_marker,
                },
            )
            db.commit()
        status_code = 403 if detail == OBJECT_REFERENCE_NOT_ACCESSIBLE else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    write_audit(
        db,
        action=action_success,
        actor=actor,
        tenant_id=tenant_id,
        target=target,
        metadata={
            "confirmed_mappings": len(out.confirmed_mappings),
            "corrected_mappings": len(out.corrected_mappings),
            "unresolved_mappings": len(out.unresolved_mappings),
            "human_confirmation_recorded": out.human_confirmation_recorded,
            "global_pattern_submission_candidate_eligible": out.global_pattern_submission_candidate.eligible,
            "authoritative_finalize_allowed": out.authoritative_finalize_allowed,
            "retrieval_action_guard": "allow" if feedback_reference_path_used else "not_applicable",
            "retrieval_execution": "allow" if feedback_reference_path_used else "not_applicable",
            "retrieval_object_type": "order" if feedback_reference_path_used else "not_applicable",
            "retrieval_traceability": "summary_only" if feedback_reference_path_used else "not_applicable",
            "tenant_action_boundary": "advisory_only",
            "order_feedback_surface": surface_marker,
            "order_feedback_traceability": "summary_only",
        },
    )
    db.commit()
    return out


@router.post("/tenant-copilot/template-submissions/stage", response_model=EidonTemplateSubmissionStagingResponseDTO)
def tenant_copilot_template_submissions_stage(
    payload: EidonTemplateSubmissionStagingRequestDTO,
    _entitlement: dict[str, Any] = Depends(require_module_entitlement("AI_COPILOT")),
    claims: dict[str, Any] = Depends(require_claims),
    db: Session = Depends(get_db_session),
) -> EidonTemplateSubmissionStagingResponseDTO:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")
    try:
        out = order_template_submission_staging_service.stage(
            db=db,
            tenant_id=tenant_id,
            actor=actor,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit(
        db,
        action="ai.tenant_template_submission_staging",
        actor=actor,
        tenant_id=tenant_id,
        target="ai/tenant-copilot/template-submissions/stage",
        metadata={
            "template_fingerprint": out.staged_submission.template_fingerprint,
            "status": out.staged_submission.status,
            "review_required": out.staged_submission.review_required,
            "quality_score": out.staged_submission.quality_score,
            "authoritative_publish_allowed": out.authoritative_publish_allowed,
        },
    )
    db.commit()
    return out


@router.get("/superadmin-copilot/quality-events/summary", response_model=EidonQualitySummaryResponseDTO)
def superadmin_quality_events_summary(
    event_type: str = "ORDER_INTAKE_FEEDBACK_V1",
    limit: int = 50,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> EidonQualitySummaryResponseDTO:
    limit_norm = max(1, min(int(limit), 200))
    out = order_quality_analysis_service.summarize(
        db=db,
        event_type=event_type,
        limit=limit_norm,
    )
    write_audit(
        db,
        action="ai.superadmin_quality_events_summary",
        actor=str(claims.get("sub") or "unknown"),
        tenant_id=None,
        target="ai/superadmin-copilot/quality-events/summary",
        metadata={
            "event_type": out.event_type,
            "limit": out.limit,
            "rows_count": len(out.rows),
        },
    )
    db.commit()
    return out


@router.get("/superadmin-copilot/runtime-decision-surface", response_model=EidonRuntimeDecisionSurfaceResponseDTO)
def superadmin_runtime_decision_surface(
    limit: int = 50,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> EidonRuntimeDecisionSurfaceResponseDTO:
    limit_norm = max(1, min(int(limit), 200))
    out = order_runtime_decision_surface_service.summarize(
        db=db,
        limit=limit_norm,
    )
    write_audit(
        db,
        action="ai.superadmin_runtime_decision_surface",
        actor=str(claims.get("sub") or "unknown"),
        tenant_id=None,
        target="ai/superadmin-copilot/runtime-decision-surface",
        metadata={
            "limit": out.limit,
            "rows_count": len(out.rows),
        },
    )
    db.commit()
    return out


@router.get("/superadmin-copilot/template-submissions/queue", response_model=EidonTemplateReviewQueueResponseDTO)
def superadmin_template_submissions_queue(
    status: str | None = "STAGED_REVIEW_REQUIRED",
    limit: int = 50,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> EidonTemplateReviewQueueResponseDTO:
    out = order_template_review_service.list_queue(db=db, limit=limit, status=status)
    write_audit(
        db,
        action="ai.superadmin_template_submissions_queue",
        actor=str(claims.get("sub") or "unknown"),
        tenant_id=None,
        target="ai/superadmin-copilot/template-submissions/queue",
        metadata={
            "status_filter": status,
            "limit": limit,
            "items_count": len(out.items),
        },
    )
    db.commit()
    return out


@router.get("/superadmin-copilot/template-submissions/{submission_id}", response_model=EidonTemplateReviewReadResponseDTO)
def superadmin_template_submission_read(
    submission_id: str,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> EidonTemplateReviewReadResponseDTO:
    try:
        out = order_template_review_service.read_submission(db=db, submission_id=submission_id)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail == "submission_not_found" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    write_audit(
        db,
        action="ai.superadmin_template_submission_read",
        actor=str(claims.get("sub") or "unknown"),
        tenant_id=None,
        target=f"ai/superadmin-copilot/template-submissions/{submission_id}",
        metadata={"submission_id": submission_id},
    )
    db.commit()
    return out


@router.post("/superadmin-copilot/template-submissions/{submission_id}/approve", response_model=EidonTemplateReviewDecisionResponseDTO)
def superadmin_template_submission_approve(
    submission_id: str,
    payload: EidonTemplateReviewDecisionRequestDTO,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> EidonTemplateReviewDecisionResponseDTO:
    try:
        out = order_template_review_service.approve(
            db=db,
            submission_id=submission_id,
            actor=str(claims.get("sub") or "unknown"),
            review_note=payload.review_note,
            quality_score=payload.quality_score,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail == "submission_not_found" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    write_audit(
        db,
        action="ai.superadmin_template_submission_approve",
        actor=str(claims.get("sub") or "unknown"),
        tenant_id=None,
        target=f"ai/superadmin-copilot/template-submissions/{submission_id}/approve",
        metadata={
            "submission_id": submission_id,
            "quality_score": payload.quality_score,
            "status": out.submission.status,
            "reviewed_by": out.submission.reviewed_by,
            "reviewed_at": out.submission.reviewed_at,
        },
    )
    db.commit()
    return out


@router.post("/superadmin-copilot/template-submissions/{submission_id}/reject", response_model=EidonTemplateReviewDecisionResponseDTO)
def superadmin_template_submission_reject(
    submission_id: str,
    payload: EidonTemplateReviewDecisionRequestDTO,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> EidonTemplateReviewDecisionResponseDTO:
    try:
        out = order_template_review_service.reject(
            db=db,
            submission_id=submission_id,
            actor=str(claims.get("sub") or "unknown"),
            review_note=payload.review_note,
            quality_score=payload.quality_score,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail == "submission_not_found" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    write_audit(
        db,
        action="ai.superadmin_template_submission_reject",
        actor=str(claims.get("sub") or "unknown"),
        tenant_id=None,
        target=f"ai/superadmin-copilot/template-submissions/{submission_id}/reject",
        metadata={
            "submission_id": submission_id,
            "quality_score": payload.quality_score,
            "status": out.submission.status,
            "reviewed_by": out.submission.reviewed_by,
            "reviewed_at": out.submission.reviewed_at,
        },
    )
    db.commit()
    return out


@router.post("/superadmin-copilot/template-submissions/{submission_id}/publish", response_model=EidonTemplatePublishResponseDTO)
def superadmin_template_submission_publish(
    submission_id: str,
    payload: EidonTemplatePublishRequestDTO,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> EidonTemplatePublishResponseDTO:
    actor = str(claims.get("sub") or "unknown")
    try:
        out = order_template_publish_service.publish(
            db=db,
            submission_id=submission_id,
            actor=actor,
            payload=payload,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail == "submission_not_found" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    write_audit(
        db,
        action="ai.superadmin_template_submission_publish",
        actor=actor,
        tenant_id=None,
        target=f"ai/superadmin-copilot/template-submissions/{submission_id}/publish",
        metadata={
            "submission_id": submission_id,
            "artifact_id": out.artifact.id,
            "pattern_version": out.artifact.pattern_version,
            "template_fingerprint": out.artifact.template_fingerprint,
            "authoritative_publish_allowed": out.authoritative_publish_allowed,
            "publish_not_rollout": True,
        },
    )
    db.commit()
    return out


@router.post(
    "/superadmin-copilot/published-patterns/{artifact_id}/distribution-record",
    response_model=EidonPatternDistributionResponseDTO,
)
def superadmin_published_pattern_distribution_record(
    artifact_id: str,
    payload: EidonPatternDistributionRecordRequestDTO,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> EidonPatternDistributionResponseDTO:
    actor = str(claims.get("sub") or "unknown")
    try:
        out = order_pattern_distribution_service.record_distribution(
            db=db,
            artifact_id=artifact_id,
            actor=actor,
            payload=payload,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail == "publish_artifact_not_found" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    write_audit(
        db,
        action="ai.superadmin_published_pattern_distribution_record",
        actor=actor,
        tenant_id=None,
        target=f"ai/superadmin-copilot/published-patterns/{artifact_id}/distribution-record",
        metadata={
            "artifact_id": artifact_id,
            "distribution_record_id": out.record.id,
            "distribution_status": out.record.distribution_status,
            "template_fingerprint": out.record.template_fingerprint,
            "authoritative_publish_allowed": out.authoritative_publish_allowed,
            "distribution_not_rollout": True,
            "distribution_not_activation": True,
        },
    )
    db.commit()
    return out


@router.post(
    "/superadmin-copilot/distribution-records/{record_id}/rollout-governance",
    response_model=EidonPatternRolloutGovernanceResponseDTO,
)
def superadmin_distribution_record_rollout_governance(
    record_id: str,
    payload: EidonPatternRolloutGovernanceRequestDTO,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> EidonPatternRolloutGovernanceResponseDTO:
    actor = str(claims.get("sub") or "unknown")
    try:
        out = order_pattern_rollout_governance_service.record_rollout_governance(
            db=db,
            record_id=record_id,
            actor=actor,
            payload=payload,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail == "distribution_record_not_found" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    write_audit(
        db,
        action="ai.superadmin_distribution_record_rollout_governance",
        actor=actor,
        tenant_id=None,
        target=f"ai/superadmin-copilot/distribution-records/{record_id}/rollout-governance",
        metadata={
            "distribution_record_id": record_id,
            "governance_record_id": out.record.id,
            "governance_status": out.record.governance_status,
            "eligibility_decision": out.record.eligibility_decision,
            "template_fingerprint": out.record.template_fingerprint,
            "authoritative_publish_allowed": out.authoritative_publish_allowed,
            "governance_not_rollout": True,
            "governance_not_activation": True,
        },
    )
    db.commit()
    return out


@router.post(
    "/superadmin-copilot/rollout-governance-records/{record_id}/activation-record",
    response_model=EidonPatternActivationResponseDTO,
)
def superadmin_rollout_governance_record_activation_record(
    record_id: str,
    payload: EidonPatternActivationRequestDTO,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> EidonPatternActivationResponseDTO:
    actor = str(claims.get("sub") or "unknown")
    try:
        out = order_pattern_activation_service.record_activation(
            db=db,
            record_id=record_id,
            actor=actor,
            payload=payload,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail == "rollout_governance_record_not_found" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    write_audit(
        db,
        action="ai.superadmin_rollout_governance_record_activation_record",
        actor=actor,
        tenant_id=None,
        target=f"ai/superadmin-copilot/rollout-governance-records/{record_id}/activation-record",
        metadata={
            "rollout_governance_record_id": record_id,
            "activation_record_id": out.record.id,
            "activation_status": out.record.activation_status,
            "template_fingerprint": out.record.template_fingerprint,
            "authoritative_publish_allowed": out.authoritative_publish_allowed,
            "activation_not_runtime_enablement": True,
        },
    )
    db.commit()
    return out


@router.post(
    "/superadmin-copilot/activation-records/{record_id}/runtime-enablement-record",
    response_model=EidonRuntimeEnablementResponseDTO,
)
def superadmin_activation_record_runtime_enablement_record(
    record_id: str,
    payload: EidonRuntimeEnablementRequestDTO,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> EidonRuntimeEnablementResponseDTO:
    actor = str(claims.get("sub") or "unknown")
    try:
        out = order_runtime_enablement_service.record_runtime_enablement(
            db=db,
            record_id=record_id,
            actor=actor,
            payload=payload,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail == "activation_record_not_found" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    write_audit(
        db,
        action="ai.superadmin_activation_record_runtime_enablement_record",
        actor=actor,
        tenant_id=None,
        target=f"ai/superadmin-copilot/activation-records/{record_id}/runtime-enablement-record",
        metadata={
            "activation_record_id": record_id,
            "runtime_enablement_record_id": out.record.id,
            "runtime_enablement_status": out.record.runtime_enablement_status,
            "runtime_decision": out.record.runtime_decision,
            "template_fingerprint": out.record.template_fingerprint,
            "authoritative_publish_allowed": out.authoritative_publish_allowed,
            "runtime_enablement_not_actual_runtime_enablement": True,
        },
    )
    db.commit()
    return out


@router.post("/superadmin-copilot")
def superadmin_copilot(payload: dict[str, Any], claims: dict[str, Any] = Depends(require_superadmin)) -> dict[str, Any]:
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt_required")

    write_audit(
        action="ai.superadmin_copilot",
        actor=claims.get("sub", "unknown"),
        tenant_id=None,
        target="ai/superadmin",
        metadata={"prompt_len": len(prompt)},
    )

    return {
        "ok": True,
        "mode": "superadmin",
        "policy": "advisory_only",
        "message": "Anomaly and governance summary prepared.",
    }
