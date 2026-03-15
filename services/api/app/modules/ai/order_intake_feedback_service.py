from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.modules.ai.eidon_orders_response_contract_v1 import (
    EIDON_ORDERS_RESPONSE_SURFACE_FEEDBACK,
    enforce_orders_response_contract_or_fail,
)
from app.modules.ai.order_retrieval_execution_service import (
    service as order_retrieval_execution_service,
)
from app.modules.ai.order_quality_event_service import service as order_quality_event_service
from app.modules.ai.tenant_action_boundary_guard import (
    service as tenant_action_boundary_guard,
)
from app.modules.ai.tenant_retrieval_action_guard import (
    get_order_reference_from_feedback_payload,
    has_feedback_order_reference_path,
)
from app.modules.ai.schemas import (
    EidonFeedbackConfidenceAdjustmentDTO,
    EidonFeedbackConfirmedMappingDTO,
    EidonFeedbackCorrectedMappingDTO,
    EidonFeedbackUnresolvedMappingDTO,
    EidonGlobalPatternSubmissionCandidateDTO,
    EidonOrderIntakeFeedbackRequestDTO,
    EidonOrderIntakeFeedbackResponseDTO,
    EidonOrderRetrievalSummaryDTO,
    EidonSourceTraceabilityDTO,
    EidonTenantLocalLearningCandidateDTO,
)

_PARTY_FIELDS: tuple[str, ...] = (
    "legal_name",
    "vat_number",
    "registration_number",
    "contact_name",
    "contact_email",
    "contact_phone",
)
_ADDRESS_FIELDS: tuple[str, ...] = (
    "address_line_1",
    "address_line_2",
    "city",
    "postal_code",
    "country_code",
)

_ALLOWED_FEEDBACK_FIELDS: set[str] = {
    "order_no",
    "status",
    "transport_mode",
    "direction",
    "instructions_formalities",
    "is_dangerous_goods",
    "customer_name",
    "pickup_location",
    "delivery_location",
    "cargo_description",
    "reference_no",
    "scheduled_pickup_at",
    "scheduled_delivery_at",
    "taking_over.place",
    "taking_over.date",
    "place_of_delivery.place",
    "goods.goods_description",
    "goods.packages_count",
    "goods.packing_method",
    "goods.marks_numbers",
    "goods.gross_weight_kg",
    "goods.volume_m3",
    "references.customer_reference",
    "references.booking_reference",
    "references.contract_reference",
    "references.external_reference",
    "adr.un_number",
    "adr.adr_class",
    "adr.packing_group",
    "adr.proper_shipping_name",
    "adr.adr_notes",
}

for _party_prefix in ("shipper", "consignee", "carrier"):
    for _field in _PARTY_FIELDS:
        _ALLOWED_FEEDBACK_FIELDS.add(f"{_party_prefix}.{_field}")
    for _field in _ADDRESS_FIELDS:
        _ALLOWED_FEEDBACK_FIELDS.add(f"{_party_prefix}.address.{_field}")

for _location_prefix in ("taking_over", "place_of_delivery"):
    for _field in _ADDRESS_FIELDS:
        _ALLOWED_FEEDBACK_FIELDS.add(f"{_location_prefix}.address.{_field}")


class EidonOrderIntakeFeedbackService:
    def _retrieve_feedback_order_reference(
        self,
        *,
        db: Session,
        tenant_id: str,
        payload: EidonOrderIntakeFeedbackRequestDTO,
    ) -> EidonOrderRetrievalSummaryDTO | None:
        if not has_feedback_order_reference_path(payload):
            return None
        order_reference_id = get_order_reference_from_feedback_payload(payload)
        return order_retrieval_execution_service.retrieve_order_reference(
            db=db,
            tenant_id=tenant_id,
            order_reference_id=order_reference_id,
            template_fingerprint=payload.original_template_fingerprint,
        )

    def _path_value(self, model: Any, field_path: str) -> Any:
        node: Any = model
        for seg in str(field_path).split("."):
            if node is None:
                return None
            if isinstance(node, dict):
                node = node.get(seg)
                continue
            if hasattr(node, seg):
                node = getattr(node, seg)
                continue
            return None
        return node

    def _is_supported_field(self, field_path: str) -> bool:
        return str(field_path or "").strip() in _ALLOWED_FEEDBACK_FIELDS

    def _source_ref(self, metadata: Any) -> str:
        if metadata is None:
            return "tenant_feedback:channel=UNKNOWN"
        channel = str(metadata.confirmation_channel or "UNKNOWN")
        return f"tenant_feedback:channel={channel}"

    def apply_feedback(self, *, db: Session, tenant_id: str, payload: EidonOrderIntakeFeedbackRequestDTO) -> EidonOrderIntakeFeedbackResponseDTO:
        retrieval_summary = self._retrieve_feedback_order_reference(
            db=db,
            tenant_id=tenant_id,
            payload=payload,
        )
        draft = payload.proposed_draft_order_candidate
        warnings: list[str] = []

        confirmed_mappings: list[EidonFeedbackConfirmedMappingDTO] = []
        corrected_mappings: list[EidonFeedbackCorrectedMappingDTO] = []
        unresolved_mappings: list[EidonFeedbackUnresolvedMappingDTO] = []
        confidence_adjustments: list[EidonFeedbackConfidenceAdjustmentDTO] = []
        source_traceability: list[EidonSourceTraceabilityDTO] = []

        source_ref = self._source_ref(payload.confirmation_metadata)
        if retrieval_summary is not None:
            source_traceability.append(
                EidonSourceTraceabilityDTO(
                    field_path="retrieval_context.order",
                    source_class=retrieval_summary.retrieval_traceability.retrieval_class,
                    source_ref=retrieval_summary.retrieval_traceability.retrieval_marker,
                )
            )

        confirmed_paths_seen: set[str] = set()
        for raw_path in payload.user_confirmed_fields:
            field_path = str(raw_path or "").strip()
            if not field_path or field_path in confirmed_paths_seen:
                continue
            confirmed_paths_seen.add(field_path)

            if not self._is_supported_field(field_path):
                warnings.append(f"unsupported_feedback_field:{field_path}")
                continue

            value = self._path_value(draft, field_path)
            if value is None:
                warnings.append(f"confirmed_field_missing_in_candidate:{field_path}")
                continue

            confirmed_mappings.append(
                EidonFeedbackConfirmedMappingDTO(
                    field_path=field_path,
                    value=value,
                )
            )
            confidence_adjustments.append(
                EidonFeedbackConfidenceAdjustmentDTO(
                    field_path=field_path,
                    from_confidence=0.70,
                    to_confidence=0.95,
                    rationale="user_confirmed_field",
                )
            )
            source_traceability.append(
                EidonSourceTraceabilityDTO(
                    field_path=field_path,
                    source_class="tenant_user_feedback",
                    source_ref=source_ref,
                )
            )

        corrected_paths_seen: set[str] = set()
        for raw_path, corrected_value in (payload.user_corrected_fields or {}).items():
            field_path = str(raw_path or "").strip()
            if not field_path or field_path in corrected_paths_seen:
                continue
            corrected_paths_seen.add(field_path)

            if not self._is_supported_field(field_path):
                warnings.append(f"unsupported_feedback_field:{field_path}")
                continue

            previous_value = self._path_value(draft, field_path)
            corrected_mappings.append(
                EidonFeedbackCorrectedMappingDTO(
                    field_path=field_path,
                    previous_value=previous_value,
                    corrected_value=corrected_value,
                )
            )
            confidence_adjustments.append(
                EidonFeedbackConfidenceAdjustmentDTO(
                    field_path=field_path,
                    from_confidence=0.70,
                    to_confidence=0.98,
                    rationale="user_corrected_field",
                )
            )
            source_traceability.append(
                EidonSourceTraceabilityDTO(
                    field_path=field_path,
                    source_class="tenant_user_feedback",
                    source_ref=source_ref,
                )
            )

            if previous_value == corrected_value:
                warnings.append(f"corrected_field_same_as_previous:{field_path}")

        unresolved_paths_seen: set[str] = set()
        for raw_path in payload.unresolved_fields:
            field_path = str(raw_path or "").strip()
            if not field_path or field_path in unresolved_paths_seen:
                continue
            unresolved_paths_seen.add(field_path)

            if not self._is_supported_field(field_path):
                warnings.append(f"unsupported_feedback_field:{field_path}")
                continue

            unresolved_mappings.append(
                EidonFeedbackUnresolvedMappingDTO(
                    field_path=field_path,
                    reason="user_marked_unresolved",
                )
            )
            confidence_adjustments.append(
                EidonFeedbackConfidenceAdjustmentDTO(
                    field_path=field_path,
                    from_confidence=0.70,
                    to_confidence=0.25,
                    rationale="user_marked_unresolved",
                )
            )
            source_traceability.append(
                EidonSourceTraceabilityDTO(
                    field_path=field_path,
                    source_class="tenant_user_feedback",
                    source_ref=source_ref,
                )
            )

        human_confirmation_recorded = True

        de_identified_features: dict[str, str | int | float | bool] = {
            "confirmed_count": len(confirmed_mappings),
            "corrected_count": len(corrected_mappings),
            "unresolved_count": len(unresolved_mappings),
            "warnings_count": len(warnings),
            "has_original_template_learning_candidate": payload.original_template_learning_candidate is not None,
            "human_confirmation_recorded": human_confirmation_recorded,
        }

        local_candidate = EidonTenantLocalLearningCandidateDTO(
            eligible=(len(confirmed_mappings) + len(corrected_mappings) + len(unresolved_mappings)) > 0,
            pattern_version="v1-feedback",
            template_fingerprint=payload.original_template_fingerprint,
            confirmed_field_paths=[x.field_path for x in confirmed_mappings],
            corrected_field_paths=[x.field_path for x in corrected_mappings],
            unresolved_field_paths=[x.field_path for x in unresolved_mappings],
            de_identified_pattern_features=de_identified_features,
            human_confirmation_recorded=human_confirmation_recorded,
            raw_tenant_document_included=False,
            tenant_scope_rule="tenant_local_learning_only",
        )

        global_candidate = EidonGlobalPatternSubmissionCandidateDTO(
            eligible=(len(corrected_mappings) + len(confirmed_mappings)) >= 2,
            pattern_version="v1-feedback",
            template_fingerprint=payload.original_template_fingerprint,
            de_identified_pattern_features=de_identified_features,
            learn_globally_act_locally_rule="learn_globally_from_patterns_act_locally_within_tenant_boundaries",
            raw_tenant_document_included=False,
            submission_blocked_reason="global_submission_engine_not_enabled_in_this_cycle",
        )

        try:
            order_quality_event_service.write_order_intake_feedback_event(
                db=db,
                tenant_id=tenant_id,
                template_fingerprint=payload.original_template_fingerprint,
                confirmed_count=len(confirmed_mappings),
                corrected_count=len(corrected_mappings),
                unresolved_count=len(unresolved_mappings),
                human_confirmation_recorded=human_confirmation_recorded,
                confidence_adjustments=confidence_adjustments,
            )
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ValueError("quality_event_persistence_failed") from exc

        out = EidonOrderIntakeFeedbackResponseDTO(
            ok=True,
            tenant_id=str(tenant_id),
            capability="EIDON_ORDER_INTAKE_FEEDBACK_LOOP_V1",
            tenant_local_learning_candidate=local_candidate,
            confirmed_mappings=confirmed_mappings,
            corrected_mappings=corrected_mappings,
            unresolved_mappings=unresolved_mappings,
            confidence_adjustments=confidence_adjustments,
            source_traceability=source_traceability,
            human_confirmation_recorded=human_confirmation_recorded,
            global_pattern_submission_candidate=global_candidate,
            warnings=warnings,
            authoritative_finalize_allowed=False,
            no_authoritative_finalize_rule="eidon_prepare_only_no_authoritative_finalize",
            system_truth_rule="ai_does_not_override_system_truth",
        )
        tenant_action_boundary_guard.enforce_advisory_only(out)
        enforce_orders_response_contract_or_fail(
            surface_code=EIDON_ORDERS_RESPONSE_SURFACE_FEEDBACK,
            response=out,
        )
        return out


service = EidonOrderIntakeFeedbackService()
