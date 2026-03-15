from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.modules.ai.eidon_orders_response_contract_v1 import (
    EIDON_ORDERS_RESPONSE_SURFACE_COPILOT,
    enforce_orders_response_contract_or_fail,
)
from app.modules.ai.eidon_capability_exposure_contract_v1 import is_copilot_routable_capability_or_fail
from app.modules.ai.eidon_capability_registry_contract_v1 import (
    EIDON_CAPABILITY_AI_ORDERS_DOCUMENT_UNDERSTANDING,
    EIDON_CAPABILITY_AI_ORDERS_DRAFTING,
    EIDON_CAPABILITY_AI_ORDERS_FEEDBACK,
    EIDON_CAPABILITY_AI_ORDERS_RETRIEVE_REFERENCE,
)
from app.modules.ai.eidon_orders_intent_contract_v1 import (
    EIDON_ORDERS_COPILOT_SUPPORTED_INTENTS,
    EIDON_ORDERS_COPILOT_UNSUPPORTED_INTENT_CODE,
    resolve_orders_copilot_capability_code_or_fail,
)
from app.modules.ai.order_document_intake_service import service as order_document_intake_service
from app.modules.ai.order_draft_assist_service import service as order_draft_assist_service
from app.modules.ai.order_intake_feedback_service import service as order_intake_feedback_service
from app.modules.ai.order_retrieval_execution_service import service as order_retrieval_execution_service
from app.modules.ai.schemas import (
    EidonOrderDocumentIntakeRequestDTO,
    EidonOrderDraftAssistRequestDTO,
    EidonOrderIntakeFeedbackRequestDTO,
    EidonOrdersCopilotResponseDTO,
)

UNSUPPORTED_ORDERS_COPILOT_INTENT = EIDON_ORDERS_COPILOT_UNSUPPORTED_INTENT_CODE
ORDERS_COPILOT_AUTHORITATIVE_FINALIZE_VIOLATION = "orders_copilot_authoritative_finalize_violation"
ORDERS_COPILOT_NON_ROUTABLE_CAPABILITY = "orders_copilot_non_routable_capability"
DEFAULT_NO_ACTION_EXECUTION_RULE = "eidon_advisory_only_no_action_execution"
SUPPORTED_ORDERS_COPILOT_INTENTS: tuple[str, ...] = EIDON_ORDERS_COPILOT_SUPPORTED_INTENTS


class EidonOrdersCopilotOrchestrationService:
    def _normalized(self, value: Any) -> str:
        return str(value or "").strip()

    def _to_dump(self, value: Any) -> Any:
        if value is None:
            return None
        if hasattr(value, "model_dump"):
            return value.model_dump(exclude_none=True)
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, (list, tuple, set)):
            out: list[Any] = []
            for item in value:
                out.append(self._to_dump(item))
            return out
        return value

    def _extract_warnings(self, result: Any) -> list[str]:
        raw = getattr(result, "warnings", [])
        if not isinstance(raw, list):
            return []
        out: list[str] = []
        for item in raw:
            text = self._normalized(item)
            if text:
                out.append(text)
        return out

    def _extract_source_traceability(self, result: Any) -> Any:
        if hasattr(result, "retrieval_traceability"):
            return self._to_dump(getattr(result, "retrieval_traceability"))
        if hasattr(result, "source_traceability"):
            return self._to_dump(getattr(result, "source_traceability"))
        return None

    def _extract_authoritative_finalize_allowed(self, result: Any) -> bool:
        value = getattr(result, "authoritative_finalize_allowed", False)
        return bool(value)

    def orchestrate(
        self,
        *,
        db: Session,
        tenant_id: str,
        intent: str,
        payload: dict[str, Any] | None,
    ) -> EidonOrdersCopilotResponseDTO:
        tenant_norm = self._normalized(tenant_id)
        if not tenant_norm:
            raise ValueError("missing_tenant_context")

        intent_norm = self._normalized(intent)
        capability_code = resolve_orders_copilot_capability_code_or_fail(intent_norm)
        if not is_copilot_routable_capability_or_fail(capability_code):
            raise ValueError(ORDERS_COPILOT_NON_ROUTABLE_CAPABILITY)

        payload_norm: dict[str, Any] = dict(payload or {})

        if capability_code == EIDON_CAPABILITY_AI_ORDERS_RETRIEVE_REFERENCE:
            order_reference_id = self._normalized(payload_norm.get("order_id"))
            result = order_retrieval_execution_service.retrieve_order_reference(
                db=db,
                tenant_id=tenant_norm,
                order_reference_id=order_reference_id,
                template_fingerprint=None,
            )
        elif capability_code == EIDON_CAPABILITY_AI_ORDERS_DOCUMENT_UNDERSTANDING:
            request = EidonOrderDocumentIntakeRequestDTO.model_validate(payload_norm)
            result = order_document_intake_service.ingest(
                tenant_id=tenant_norm,
                payload=request,
            )
        elif capability_code == EIDON_CAPABILITY_AI_ORDERS_DRAFTING:
            request = EidonOrderDraftAssistRequestDTO.model_validate(payload_norm)
            result = order_draft_assist_service.assist(
                db=db,
                tenant_id=tenant_norm,
                payload=request,
            )
        elif capability_code == EIDON_CAPABILITY_AI_ORDERS_FEEDBACK:
            request = EidonOrderIntakeFeedbackRequestDTO.model_validate(payload_norm)
            result = order_intake_feedback_service.apply_feedback(
                db=db,
                tenant_id=tenant_norm,
                payload=request,
            )
        else:
            raise ValueError(UNSUPPORTED_ORDERS_COPILOT_INTENT)

        if self._extract_authoritative_finalize_allowed(result):
            raise ValueError(ORDERS_COPILOT_AUTHORITATIVE_FINALIZE_VIOLATION)

        out = EidonOrdersCopilotResponseDTO(
            ok=True,
            tenant_id=tenant_norm,
            capability="EIDON_ORDERS_COPILOT_ORCHESTRATION_V1",
            intent=intent_norm,
            result=self._to_dump(result) or {},
            authoritative_finalize_allowed=False,
            warnings=self._extract_warnings(result),
            source_traceability=self._extract_source_traceability(result),
            no_authoritative_finalize_rule="eidon_prepare_only_no_authoritative_finalize",
            no_action_execution_rule=DEFAULT_NO_ACTION_EXECUTION_RULE,
            system_truth_rule="ai_does_not_override_system_truth",
        )
        enforce_orders_response_contract_or_fail(
            surface_code=EIDON_ORDERS_RESPONSE_SURFACE_COPILOT,
            response=out,
        )
        return out


service = EidonOrdersCopilotOrchestrationService()
