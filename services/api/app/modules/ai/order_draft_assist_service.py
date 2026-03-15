from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.modules.ai.order_retrieval_execution_service import (
    service as order_retrieval_execution_service,
)
from app.modules.ai.tenant_retrieval_action_guard import (
    get_order_reference_from_existing_draft_context,
    has_existing_draft_context_path,
)
from app.modules.ai.schemas import (
    EidonOrderRetrievalSummaryDTO,
    EidonOrderDraftAssistRequestDTO,
    EidonOrderDraftAssistResponseDTO,
    EidonReadinessDTO,
    EidonSourceTraceabilityDTO,
    EidonSuggestedFieldValueDTO,
)
from app.modules.orders.schemas import OrderCreateRequestDTO


_CMR_REQUIRED_FIELDS: tuple[str, ...] = (
    "shipper.legal_name",
    "shipper.address.address_line_1",
    "shipper.address.city",
    "shipper.address.postal_code",
    "shipper.address.country_code",
    "consignee.legal_name",
    "consignee.address.address_line_1",
    "consignee.address.city",
    "consignee.address.postal_code",
    "consignee.address.country_code",
    "carrier.legal_name",
    "carrier.address.address_line_1",
    "carrier.address.city",
    "carrier.address.postal_code",
    "carrier.address.country_code",
    "taking_over.place",
    "taking_over.date",
    "place_of_delivery.place",
    "goods.goods_description",
    "goods.packages_count",
    "goods.packing_method",
    "goods.marks_numbers",
    "goods.gross_weight_kg",
    "goods.volume_m3",
)

_ADR_REQUIRED_FIELDS: tuple[str, ...] = (
    "adr.un_number",
    "adr.adr_class",
    "adr.packing_group",
    "adr.proper_shipping_name",
)

_PLACEHOLDER_VALUES = {
    "?",
    "??",
    "N/A",
    "NA",
    "NONE",
    "UNKNOWN",
    "UNSPECIFIED",
    "TBD",
    "TO_BE_DEFINED",
}


class EidonOrderDraftAssistService:
    def _retrieve_existing_order_reference(
        self,
        *,
        db: Session,
        tenant_id: str,
        payload: EidonOrderDraftAssistRequestDTO,
    ) -> EidonOrderRetrievalSummaryDTO | None:
        if not has_existing_draft_context_path(payload):
            return None
        order_reference_id = get_order_reference_from_existing_draft_context(payload)
        return order_retrieval_execution_service.retrieve_order_reference(
            db=db,
            tenant_id=tenant_id,
            order_reference_id=order_reference_id,
            template_fingerprint=None,
        )

    def _resolve_draft(self, payload: EidonOrderDraftAssistRequestDTO) -> tuple[OrderCreateRequestDTO, str]:
        if payload.order_draft_input is not None:
            return payload.order_draft_input, "order_draft_input"

        if payload.existing_order_draft_context is not None:
            draft = OrderCreateRequestDTO.model_validate(payload.existing_order_draft_context.model_dump(exclude_none=True))
            return draft, "existing_order_draft_context"

        raise ValueError("order_draft_context_required")

    def _path_value(self, model: Any, field_path: str) -> Any:
        node: Any = model
        for seg in str(field_path).split("."):
            if node is None:
                return None
            if hasattr(node, seg):
                node = getattr(node, seg)
                continue
            if isinstance(node, dict):
                node = node.get(seg)
                continue
            return None
        return node

    def _is_missing(self, value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return str(value).strip() == ""
        if isinstance(value, (list, tuple, set, dict)):
            return len(value) == 0
        return False

    def _is_ambiguous(self, value: Any) -> bool:
        if not isinstance(value, str):
            return False
        raw = value.strip()
        if raw == "":
            return False
        upper = raw.upper().replace(" ", "_")
        if upper in _PLACEHOLDER_VALUES:
            return True
        return "?" in raw

    def _focus_enabled(self, field_path: str, focus: set[str]) -> bool:
        if not focus:
            return True
        for target in focus:
            if field_path == target:
                return True
            if field_path.startswith(target + "."):
                return True
            if target.startswith(field_path + "."):
                return True
        return False

    def _append_suggestion(
        self,
        *,
        suggestions: list[EidonSuggestedFieldValueDTO],
        traces: list[EidonSourceTraceabilityDTO],
        field_path: str,
        suggested_value: str | int | float | bool,
        rationale: str,
        focus: set[str],
    ) -> None:
        if not self._focus_enabled(field_path, focus):
            return
        suggestions.append(
            EidonSuggestedFieldValueDTO(
                field_path=field_path,
                suggested_value=suggested_value,
                rationale=rationale,
            )
        )
        traces.append(
            EidonSourceTraceabilityDTO(
                field_path=field_path,
                source_class="local_pattern_heuristic",
                source_ref=rationale,
            )
        )

    def assist(self, *, db: Session, tenant_id: str, payload: EidonOrderDraftAssistRequestDTO) -> EidonOrderDraftAssistResponseDTO:
        retrieval_summary = self._retrieve_existing_order_reference(
            db=db,
            tenant_id=tenant_id,
            payload=payload,
        )
        draft, context_source = self._resolve_draft(payload)
        focus = {str(x).strip() for x in (payload.focus_fields or []) if str(x).strip()}

        missing_required_fields = [
            field_path for field_path in _CMR_REQUIRED_FIELDS if self._is_missing(self._path_value(draft, field_path))
        ]

        ambiguous_fields: list[str] = []
        ambiguous_scan = list(_CMR_REQUIRED_FIELDS) + list(_ADR_REQUIRED_FIELDS)
        for field_path in ambiguous_scan:
            if not self._focus_enabled(field_path, focus):
                continue
            value = self._path_value(draft, field_path)
            if self._is_missing(value):
                continue
            if self._is_ambiguous(value):
                ambiguous_fields.append(field_path)

        is_dangerous_goods = bool(draft.is_dangerous_goods)
        adr_missing_fields: list[str] = []
        if is_dangerous_goods:
            adr_missing_fields = [
                field_path for field_path in _ADR_REQUIRED_FIELDS if self._is_missing(self._path_value(draft, field_path))
            ]

        suggestions: list[EidonSuggestedFieldValueDTO] = []
        traces: list[EidonSourceTraceabilityDTO] = [
            EidonSourceTraceabilityDTO(
                field_path="request_context",
                source_class=context_source,
                source_ref="tenant_local_payload",
            )
        ]
        if retrieval_summary is not None:
            traces.append(
                EidonSourceTraceabilityDTO(
                    field_path="retrieval_context.order",
                    source_class=retrieval_summary.retrieval_traceability.retrieval_class,
                    source_ref=retrieval_summary.retrieval_traceability.retrieval_marker,
                )
            )

        goods_desc = self._path_value(draft, "goods.goods_description")
        reference_no = self._path_value(draft, "reference_no")
        shipper_country = self._path_value(draft, "shipper.address.country_code")
        consignee_country = self._path_value(draft, "consignee.address.country_code")

        if self._is_missing(draft.transport_mode):
            self._append_suggestion(
                suggestions=suggestions,
                traces=traces,
                field_path="transport_mode",
                suggested_value="ROAD",
                rationale="default_transport_mode_for_draft",
                focus=focus,
            )

        if self._is_missing(draft.direction):
            self._append_suggestion(
                suggestions=suggestions,
                traces=traces,
                field_path="direction",
                suggested_value="OUTBOUND",
                rationale="default_direction_for_draft",
                focus=focus,
            )

        if self._is_missing(self._path_value(draft, "goods.packing_method")) and not self._is_missing(
            self._path_value(draft, "goods.packages_count")
        ):
            self._append_suggestion(
                suggestions=suggestions,
                traces=traces,
                field_path="goods.packing_method",
                suggested_value="PALLETS",
                rationale="packages_count_present_implies_packing_method_candidate",
                focus=focus,
            )

        if self._is_missing(self._path_value(draft, "goods.marks_numbers")) and not self._is_missing(reference_no):
            self._append_suggestion(
                suggestions=suggestions,
                traces=traces,
                field_path="goods.marks_numbers",
                suggested_value=str(reference_no),
                rationale="reuse_reference_no_for_marks_numbers",
                focus=focus,
            )

        if self._is_missing(draft.cargo_description) and not self._is_missing(goods_desc):
            self._append_suggestion(
                suggestions=suggestions,
                traces=traces,
                field_path="cargo_description",
                suggested_value=str(goods_desc),
                rationale="goods_description_can_seed_cargo_description",
                focus=focus,
            )

        if self._is_missing(self._path_value(draft, "taking_over.address.country_code")) and not self._is_missing(shipper_country):
            self._append_suggestion(
                suggestions=suggestions,
                traces=traces,
                field_path="taking_over.address.country_code",
                suggested_value=str(shipper_country),
                rationale="shipper_country_can_seed_taking_over_country",
                focus=focus,
            )

        if self._is_missing(self._path_value(draft, "place_of_delivery.address.country_code")) and not self._is_missing(consignee_country):
            self._append_suggestion(
                suggestions=suggestions,
                traces=traces,
                field_path="place_of_delivery.address.country_code",
                suggested_value=str(consignee_country),
                rationale="consignee_country_can_seed_delivery_country",
                focus=focus,
            )

        warnings: list[str] = []
        if missing_required_fields:
            warnings.append("missing_required_fields_detected")
        if ambiguous_fields:
            warnings.append("ambiguous_fields_require_human_clarification")
        if is_dangerous_goods and adr_missing_fields:
            warnings.append("adr_required_fields_missing")

        cmr_readiness = EidonReadinessDTO(
            ready=len(missing_required_fields) == 0,
            applicable=True,
            required_fields=list(_CMR_REQUIRED_FIELDS),
            missing_fields=missing_required_fields,
        )
        adr_readiness = EidonReadinessDTO(
            ready=(not is_dangerous_goods) or (len(adr_missing_fields) == 0),
            applicable=is_dangerous_goods,
            required_fields=list(_ADR_REQUIRED_FIELDS),
            missing_fields=adr_missing_fields,
        )

        human_confirmation_required_items = [
            "order_submission_or_state_transition",
            "authoritative_business_document_finalize",
            "any_financial_or_legally_binding_action",
        ]
        if ambiguous_fields:
            human_confirmation_required_items.extend([f"field_clarification:{x}" for x in ambiguous_fields])

        return EidonOrderDraftAssistResponseDTO(
            ok=True,
            tenant_id=str(tenant_id),
            capability="EIDON_ORDER_DRAFT_ASSIST_V1",
            missing_required_fields=missing_required_fields,
            ambiguous_fields=ambiguous_fields,
            cmr_readiness=cmr_readiness,
            adr_readiness=adr_readiness,
            suggested_field_values=suggestions,
            human_confirmation_required_items=human_confirmation_required_items,
            source_traceability=traces,
            warnings=warnings,
            authoritative_finalize_allowed=False,
            no_authoritative_finalize_rule="eidon_prepare_only_no_authoritative_finalize",
            system_truth_rule="ai_does_not_override_system_truth",
        )


service = EidonOrderDraftAssistService()
