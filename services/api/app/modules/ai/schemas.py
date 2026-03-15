from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.modules.orders.schemas import (
    OrderAdrDetailsDTO,
    OrderCreateRequestDTO,
    OrderGoodsDTO,
    OrderPartyDTO,
    OrderPlaceOfDeliveryDTO,
    OrderReferencesDTO,
    OrderTakingOverDTO,
)


class EidonExistingOrderDraftContextDTO(OrderCreateRequestDTO):
    id: str | None = None
    tenant_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class EidonOrderDraftAssistRequestDTO(BaseModel):
    order_draft_input: OrderCreateRequestDTO | None = None
    existing_order_draft_context: EidonExistingOrderDraftContextDTO | None = None
    focus_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_has_context(self) -> "EidonOrderDraftAssistRequestDTO":
        if self.order_draft_input is None and self.existing_order_draft_context is None:
            raise ValueError("order_draft_context_required")
        return self


class EidonReadinessDTO(BaseModel):
    ready: bool
    applicable: bool = True
    required_fields: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)


class EidonSuggestedFieldValueDTO(BaseModel):
    field_path: str
    suggested_value: str | int | float | bool
    rationale: str


class EidonSourceTraceabilityDTO(BaseModel):
    field_path: str
    source_class: str
    source_ref: str


class EidonRetrievalTraceabilityDTO(BaseModel):
    retrieval_class: str
    retrieval_marker: str
    guard_outcome: str


class EidonOrderRetrievalSummaryDTO(BaseModel):
    object_type: str
    object_id: str
    template_fingerprint: str | None = None
    retrieval_traceability: EidonRetrievalTraceabilityDTO
    tenant_visible: bool


class EidonOrderReferenceRetrievalRequestDTO(BaseModel):
    order_id: str


class EidonOrderReferenceRetrievalResponseDTO(BaseModel):
    ok: bool
    tenant_id: str
    capability: str
    result: EidonOrderRetrievalSummaryDTO
    authoritative_finalize_allowed: bool
    warnings: list[str] = Field(default_factory=list)
    source_traceability: EidonRetrievalTraceabilityDTO | None = None
    no_authoritative_finalize_rule: str
    system_truth_rule: str


class EidonOrderDraftAssistResponseDTO(BaseModel):
    ok: bool
    tenant_id: str
    capability: str
    missing_required_fields: list[str] = Field(default_factory=list)
    ambiguous_fields: list[str] = Field(default_factory=list)
    cmr_readiness: EidonReadinessDTO
    adr_readiness: EidonReadinessDTO
    suggested_field_values: list[EidonSuggestedFieldValueDTO] = Field(default_factory=list)
    human_confirmation_required_items: list[str] = Field(default_factory=list)
    source_traceability: list[EidonSourceTraceabilityDTO] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    authoritative_finalize_allowed: bool
    no_authoritative_finalize_rule: str
    system_truth_rule: str


class EidonDocumentMetadataDTO(BaseModel):
    document_type: str | None = None
    document_id: str | None = None
    source_channel: str | None = None
    locale: str | None = None
    file_name: str | None = None


class EidonOrderDocumentIntakeRequestDTO(BaseModel):
    extracted_text: str = Field(min_length=1, max_length=200000)
    document_metadata: EidonDocumentMetadataDTO | None = None
    layout_hints: dict[str, str] = Field(default_factory=dict)
    field_hints: dict[str, str | int | float | bool] = Field(default_factory=dict)


class EidonExtractedFieldDTO(BaseModel):
    field_path: str
    value: str | int | float | bool
    confidence: float = Field(ge=0.0, le=1.0)
    source_ref: str


class EidonTemplateLearningCandidateDTO(BaseModel):
    eligible: bool
    pattern_version: str
    template_fingerprint: str
    extracted_field_paths: list[str] = Field(default_factory=list)
    de_identified_pattern_features: dict[str, str | int | float | bool] = Field(default_factory=dict)
    learn_globally_act_locally_rule: str
    raw_tenant_document_included: bool


class EidonOrderDraftCandidateDTO(BaseModel):
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
    payload: object | None = None


class EidonOrderDocumentIntakeResponseDTO(BaseModel):
    ok: bool
    tenant_id: str
    capability: str
    draft_order_candidate: EidonOrderDraftCandidateDTO
    extracted_fields: list[EidonExtractedFieldDTO] = Field(default_factory=list)
    missing_required_fields: list[str] = Field(default_factory=list)
    ambiguous_fields: list[str] = Field(default_factory=list)
    cmr_readiness: EidonReadinessDTO
    adr_readiness: EidonReadinessDTO
    human_confirmation_required_items: list[str] = Field(default_factory=list)
    source_traceability: list[EidonSourceTraceabilityDTO] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    template_fingerprint: str
    template_learning_candidate: EidonTemplateLearningCandidateDTO
    authoritative_finalize_allowed: bool
    no_authoritative_finalize_rule: str
    system_truth_rule: str


class EidonOrderIntakeFeedbackConfirmationMetadataDTO(BaseModel):
    confirmation_channel: str | None = None
    confirmed_by: str | None = None
    confirmation_note: str | None = None
    confirmed_at: str | None = None


class EidonFeedbackConfirmedMappingDTO(BaseModel):
    field_path: str
    value: str | int | float | bool


class EidonFeedbackCorrectedMappingDTO(BaseModel):
    field_path: str
    previous_value: str | int | float | bool | None = None
    corrected_value: str | int | float | bool


class EidonFeedbackUnresolvedMappingDTO(BaseModel):
    field_path: str
    reason: str


class EidonFeedbackConfidenceAdjustmentDTO(BaseModel):
    field_path: str
    from_confidence: float = Field(ge=0.0, le=1.0)
    to_confidence: float = Field(ge=0.0, le=1.0)
    rationale: str


class EidonTenantLocalLearningCandidateDTO(BaseModel):
    eligible: bool
    pattern_version: str
    template_fingerprint: str
    confirmed_field_paths: list[str] = Field(default_factory=list)
    corrected_field_paths: list[str] = Field(default_factory=list)
    unresolved_field_paths: list[str] = Field(default_factory=list)
    de_identified_pattern_features: dict[str, str | int | float | bool] = Field(default_factory=dict)
    human_confirmation_recorded: bool
    raw_tenant_document_included: bool
    tenant_scope_rule: str


class EidonGlobalPatternSubmissionCandidateDTO(BaseModel):
    eligible: bool
    pattern_version: str
    template_fingerprint: str
    de_identified_pattern_features: dict[str, str | int | float | bool] = Field(default_factory=dict)
    learn_globally_act_locally_rule: str
    raw_tenant_document_included: bool
    submission_blocked_reason: str


class EidonOrderIntakeFeedbackRequestDTO(BaseModel):
    original_template_fingerprint: str = Field(min_length=1)
    original_template_learning_candidate: EidonTemplateLearningCandidateDTO | None = None
    proposed_draft_order_candidate: EidonOrderDraftCandidateDTO
    user_confirmed_fields: list[str] = Field(default_factory=list)
    user_corrected_fields: dict[str, str | int | float | bool] = Field(default_factory=dict)
    unresolved_fields: list[str] = Field(default_factory=list)
    confirmation_metadata: EidonOrderIntakeFeedbackConfirmationMetadataDTO | None = None

    @model_validator(mode="after")
    def _validate_feedback_signal(self) -> "EidonOrderIntakeFeedbackRequestDTO":
        if (
            len(self.user_confirmed_fields) == 0
            and len(self.user_corrected_fields) == 0
            and len(self.unresolved_fields) == 0
        ):
            raise ValueError("feedback_signal_required")
        return self


class EidonOrderIntakeFeedbackResponseDTO(BaseModel):
    ok: bool
    tenant_id: str
    capability: str
    tenant_local_learning_candidate: EidonTenantLocalLearningCandidateDTO
    confirmed_mappings: list[EidonFeedbackConfirmedMappingDTO] = Field(default_factory=list)
    corrected_mappings: list[EidonFeedbackCorrectedMappingDTO] = Field(default_factory=list)
    unresolved_mappings: list[EidonFeedbackUnresolvedMappingDTO] = Field(default_factory=list)
    confidence_adjustments: list[EidonFeedbackConfidenceAdjustmentDTO] = Field(default_factory=list)
    source_traceability: list[EidonSourceTraceabilityDTO] = Field(default_factory=list)
    human_confirmation_recorded: bool
    global_pattern_submission_candidate: EidonGlobalPatternSubmissionCandidateDTO
    warnings: list[str] = Field(default_factory=list)
    authoritative_finalize_allowed: bool
    no_authoritative_finalize_rule: str
    system_truth_rule: str


class EidonTemplateSubmissionStagingRequestDTO(BaseModel):
    source_capability: str = "EIDON_ORDER_INTAKE_FEEDBACK_LOOP_V1"
    source_template_fingerprint: str = Field(min_length=1)
    global_pattern_submission_candidate: EidonGlobalPatternSubmissionCandidateDTO
    tenant_source_traceability: list[EidonSourceTraceabilityDTO] = Field(default_factory=list)
    human_confirmation_recorded: bool = True
    submission_shape_version: str = "v1"


class EidonStagedTemplateSubmissionRecordDTO(BaseModel):
    id: str
    tenant_id: str
    source_capability: str
    submission_shape_version: str
    pattern_version: str
    template_fingerprint: str
    status: str
    review_required: bool
    quality_score: int | None = None
    authoritative_publish_allowed: bool
    rollback_capable: bool
    rollback_from_submission_id: str | None = None
    raw_tenant_document_included: bool
    source_traceability: list[EidonSourceTraceabilityDTO] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: str


class EidonTemplateSubmissionStagingResponseDTO(BaseModel):
    ok: bool
    tenant_id: str
    capability: str
    staged_submission: EidonStagedTemplateSubmissionRecordDTO
    global_pattern_submission_candidate: EidonGlobalPatternSubmissionCandidateDTO
    warnings: list[str] = Field(default_factory=list)
    authoritative_publish_allowed: bool
    no_authoritative_publish_rule: str
    no_raw_document_rule: str
    system_truth_rule: str


class EidonTemplateReviewQueueItemDTO(BaseModel):
    id: str
    tenant_id: str
    source_capability: str
    submission_shape_version: str
    pattern_version: str
    template_fingerprint: str
    status: str
    review_required: bool
    quality_score: int | None = None
    submitted_by: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    created_at: str
    updated_at: str
    raw_tenant_document_included: bool


class EidonTemplateReviewQueueResponseDTO(BaseModel):
    ok: bool
    items: list[EidonTemplateReviewQueueItemDTO] = Field(default_factory=list)


class EidonTemplateReviewRecordDTO(EidonTemplateReviewQueueItemDTO):
    review_note: str | None = None
    authoritative_publish_allowed: bool
    rollback_capable: bool
    rollback_from_submission_id: str | None = None
    source_traceability: list[EidonSourceTraceabilityDTO] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class EidonTemplateReviewReadResponseDTO(BaseModel):
    ok: bool
    submission: EidonTemplateReviewRecordDTO


class EidonTemplateReviewDecisionRequestDTO(BaseModel):
    review_note: str | None = None
    quality_score: int | None = Field(default=None, ge=0, le=100)


class EidonTemplateReviewDecisionResponseDTO(BaseModel):
    ok: bool
    decision: str
    submission: EidonTemplateReviewRecordDTO


class EidonTemplatePublishRequestDTO(BaseModel):
    publish_note: str | None = None
    publish_shape_version: str = "v1"
    rollback_from_submission_id: str | None = None


class EidonPublishedPatternArtifactRecordDTO(BaseModel):
    id: str
    source_submission_id: str
    tenant_id: str
    source_capability: str
    submission_shape_version: str
    source_submission_status: str
    pattern_version: str
    template_fingerprint: str
    quality_score: int
    de_identified_pattern_features: dict[str, str | int | float | bool] = Field(default_factory=dict)
    authoritative_publish_allowed: bool
    rollback_capable: bool
    rollback_from_submission_id: str | None = None
    published_by: str
    published_at: str
    created_at: str
    warnings: list[str] = Field(default_factory=list)


class EidonTemplatePublishResponseDTO(BaseModel):
    ok: bool
    decision: str
    artifact: EidonPublishedPatternArtifactRecordDTO
    authoritative_publish_allowed: bool
    no_authoritative_publish_rule: str
    no_raw_document_rule: str
    no_rollout_rule: str
    system_truth_rule: str


class EidonPatternDistributionRecordRequestDTO(BaseModel):
    distribution_note: str | None = None
    distribution_meta: dict[str, Any] | None = None
    rollback_from_distribution_record_id: str | None = None


class EidonPatternDistributionRecordDTO(BaseModel):
    id: str
    publish_artifact_id: str
    tenant_id: str
    template_fingerprint: str
    pattern_version: str
    distribution_status: str
    distribution_note: str | None = None
    distribution_meta: dict[str, Any] = Field(default_factory=dict)
    rollback_from_distribution_record_id: str | None = None
    recorded_by: str
    recorded_at: str
    authoritative_publish_allowed: bool


class EidonPatternDistributionResponseDTO(BaseModel):
    ok: bool
    decision: str
    record: EidonPatternDistributionRecordDTO
    authoritative_publish_allowed: bool
    no_authoritative_publish_rule: str
    no_rollout_rule: str
    no_activation_rule: str
    no_tenant_runtime_mutation_rule: str
    system_truth_rule: str


class EidonPatternRolloutGovernanceRequestDTO(BaseModel):
    eligibility_decision: str
    governance_note: str | None = None
    governance_meta: dict[str, Any] | None = None


class EidonPatternRolloutGovernanceRecordDTO(BaseModel):
    id: str
    distribution_record_id: str
    tenant_id: str
    template_fingerprint: str
    pattern_version: str
    governance_status: str
    eligibility_decision: str
    governance_note: str | None = None
    governance_meta: dict[str, Any] = Field(default_factory=dict)
    rollback_from_governance_record_id: str | None = None
    recorded_by: str
    recorded_at: str
    authoritative_publish_allowed: bool


class EidonPatternRolloutGovernanceResponseDTO(BaseModel):
    ok: bool
    decision: str
    record: EidonPatternRolloutGovernanceRecordDTO
    authoritative_publish_allowed: bool
    no_authoritative_publish_rule: str
    no_rollout_rule: str
    no_activation_rule: str
    no_tenant_runtime_mutation_rule: str
    system_truth_rule: str


class EidonPatternActivationRequestDTO(BaseModel):
    activation_note: str | None = None
    activation_meta: dict[str, Any] | None = None


class EidonPatternActivationRecordDTO(BaseModel):
    id: str
    rollout_governance_record_id: str
    tenant_id: str
    template_fingerprint: str
    pattern_version: str
    activation_status: str
    activation_note: str | None = None
    activation_meta: dict[str, Any] = Field(default_factory=dict)
    rollback_from_activation_record_id: str | None = None
    recorded_by: str
    recorded_at: str
    authoritative_publish_allowed: bool


class EidonPatternActivationResponseDTO(BaseModel):
    ok: bool
    decision: str
    record: EidonPatternActivationRecordDTO
    authoritative_publish_allowed: bool
    no_authoritative_publish_rule: str
    no_runtime_enablement_rule: str
    no_activation_worker_rule: str
    no_tenant_runtime_mutation_rule: str
    system_truth_rule: str


class EidonRuntimeEnablementRequestDTO(BaseModel):
    runtime_decision: str
    runtime_note: str | None = None
    runtime_meta: dict[str, Any] | None = None


class EidonRuntimeEnablementRecordDTO(BaseModel):
    id: str
    activation_record_id: str
    tenant_id: str
    template_fingerprint: str
    pattern_version: str
    runtime_enablement_status: str
    runtime_decision: str
    runtime_note: str | None = None
    runtime_meta: dict[str, Any] = Field(default_factory=dict)
    rollback_from_runtime_enablement_record_id: str | None = None
    recorded_by: str
    recorded_at: str
    authoritative_publish_allowed: bool


class EidonRuntimeEnablementResponseDTO(BaseModel):
    ok: bool
    decision: str
    record: EidonRuntimeEnablementRecordDTO
    authoritative_publish_allowed: bool
    no_authoritative_publish_rule: str
    no_actual_runtime_enablement_rule: str
    no_runtime_worker_rule: str
    no_tenant_runtime_mutation_rule: str
    system_truth_rule: str


class EidonQualitySummaryRowDTO(BaseModel):
    template_fingerprint: str
    event_count: int
    total_confirmed_count: int
    total_corrected_count: int
    total_unresolved_count: int
    human_confirmation_true_count: int
    correction_rate: float | None = None
    last_event_at: str | None = None


class EidonQualitySummaryResponseDTO(BaseModel):
    ok: bool
    event_type: str
    limit: int
    rows: list[EidonQualitySummaryRowDTO] = Field(default_factory=list)
    generated_at: str


class EidonRuntimeDecisionSurfaceRowDTO(BaseModel):
    template_fingerprint: str
    pattern_version: str
    publish_recorded: bool
    distribution_recorded: bool
    rollout_governance_recorded: bool
    rollout_eligibility_decision: str | None = None
    activation_recorded: bool
    runtime_enablement_recorded: bool
    runtime_decision: str | None = None
    last_governance_event_at: str | None = None


class EidonRuntimeDecisionSurfaceResponseDTO(BaseModel):
    ok: bool
    limit: int
    rows: list[EidonRuntimeDecisionSurfaceRowDTO] = Field(default_factory=list)
    generated_at: str
