from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.modules.ai.eidon_orders_response_contract_v1 import (
    EIDON_ORDERS_RESPONSE_SURFACE_DOCUMENT_UNDERSTANDING,
    enforce_orders_response_contract_or_fail,
)
from app.modules.ai.schemas import (
    EidonExtractedFieldDTO,
    EidonOrderDraftCandidateDTO,
    EidonOrderDocumentIntakeRequestDTO,
    EidonOrderDocumentIntakeResponseDTO,
    EidonReadinessDTO,
    EidonSourceTraceabilityDTO,
    EidonTemplateLearningCandidateDTO,
)
from app.modules.ai.tenant_action_boundary_guard import (
    service as tenant_action_boundary_guard,
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

_TEXT_PATTERNS: dict[str, tuple[str, ...]] = {
    "shipper.legal_name": (r"(?im)^\s*shipper\s*:\s*(.+?)\s*$",),
    "consignee.legal_name": (r"(?im)^\s*consignee\s*:\s*(.+?)\s*$",),
    "carrier.legal_name": (r"(?im)^\s*carrier\s*:\s*(.+?)\s*$",),
    "taking_over.place": (
        r"(?im)^\s*(taking\s*over\s*place|pickup\s*place|place\s*of\s*taking\s*over)\s*:\s*(.+?)\s*$",
    ),
    "taking_over.date": (
        r"(?im)^\s*(taking\s*over\s*date|pickup\s*date|date\s*of\s*taking\s*over)\s*:\s*(.+?)\s*$",
    ),
    "place_of_delivery.place": (r"(?im)^\s*(delivery\s*place|place\s*of\s*delivery)\s*:\s*(.+?)\s*$",),
    "goods.goods_description": (r"(?im)^\s*(goods|cargo\s*description)\s*:\s*(.+?)\s*$",),
    "goods.packages_count": (r"(?im)^\s*(packages|package\s*count)\s*:\s*(.+?)\s*$",),
    "goods.packing_method": (r"(?im)^\s*(packing|packing\s*method)\s*:\s*(.+?)\s*$",),
    "goods.marks_numbers": (r"(?im)^\s*(marks|marks\s*numbers)\s*:\s*(.+?)\s*$",),
    "goods.gross_weight_kg": (r"(?im)^\s*(gross\s*weight|gross\s*weight\s*kg|weight\s*kg)\s*:\s*(.+?)\s*$",),
    "goods.volume_m3": (r"(?im)^\s*(volume|volume\s*m3)\s*:\s*(.+?)\s*$",),
    "is_dangerous_goods": (r"(?im)^\s*(dangerous\s*goods|adr)\s*:\s*(.+?)\s*$",),
    "adr.un_number": (r"(?im)^\s*(un\s*number|un\s*no)\s*:\s*(.+?)\s*$",),
    "adr.adr_class": (r"(?im)^\s*(adr\s*class)\s*:\s*(.+?)\s*$",),
    "adr.packing_group": (r"(?im)^\s*(packing\s*group)\s*:\s*(.+?)\s*$",),
    "adr.proper_shipping_name": (r"(?im)^\s*(proper\s*shipping\s*name)\s*:\s*(.+?)\s*$",),
    "adr.adr_notes": (r"(?im)^\s*(adr\s*notes)\s*:\s*(.+?)\s*$",),
    "order_no": (r"(?im)^\s*(order\s*no|order\s*number)\s*:\s*(.+?)\s*$",),
    "reference_no": (r"(?im)^\s*(reference\s*no|customer\s*reference)\s*:\s*(.+?)\s*$",),
    "transport_mode": (r"(?im)^\s*(transport\s*mode)\s*:\s*(.+?)\s*$",),
    "direction": (r"(?im)^\s*(direction)\s*:\s*(.+?)\s*$",),
}

_ALLOWED_FIELD_HINTS = set(_CMR_REQUIRED_FIELDS) | set(_ADR_REQUIRED_FIELDS) | {
    "order_no",
    "reference_no",
    "transport_mode",
    "direction",
    "is_dangerous_goods",
    "adr.adr_notes",
}

_FORBIDDEN_DOCUMENT_OUTPUT_KEYS: set[str] = {
    "extracted_text",
    "raw_document_blob",
    "raw_document_payload",
    "document_blob",
}


class EidonOrderDocumentIntakeService:
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

    def _normalize_bool(self, value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        raw = str(value or "").strip().lower()
        if raw in {"1", "true", "yes", "y", "on", "да"}:
            return True
        if raw in {"0", "false", "no", "n", "off", "не"}:
            return False
        return None

    def _normalize_int(self, value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        raw = str(value or "").strip()
        m = re.search(r"-?\d+", raw)
        if not m:
            return None
        try:
            return int(m.group(0))
        except Exception:  # noqa: BLE001
            return None

    def _normalize_float(self, value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        raw = str(value or "").strip().replace(",", ".")
        m = re.search(r"-?\d+(?:\.\d+)?", raw)
        if not m:
            return None
        try:
            return float(m.group(0))
        except Exception:  # noqa: BLE001
            return None

    def _normalize_value(self, field_path: str, value: Any) -> str | int | float | bool | None:
        if self._is_missing(value):
            return None

        if field_path in {"goods.packages_count"}:
            return self._normalize_int(value)
        if field_path in {"goods.gross_weight_kg", "goods.volume_m3"}:
            return self._normalize_float(value)
        if field_path in {"is_dangerous_goods"}:
            return self._normalize_bool(value)

        return str(value).strip()

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

    def _set_nested(self, target: dict[str, Any], field_path: str, value: Any) -> None:
        node = target
        segments = str(field_path).split(".")
        for seg in segments[:-1]:
            nxt = node.get(seg)
            if not isinstance(nxt, dict):
                nxt = {}
                node[seg] = nxt
            node = nxt
        node[segments[-1]] = value

    def _collect_forbidden_output_keys(self, value: Any, out: set[str]) -> None:
        if isinstance(value, dict):
            for raw_key, raw_val in value.items():
                key_norm = str(raw_key or "").strip().lower()
                if key_norm in _FORBIDDEN_DOCUMENT_OUTPUT_KEYS:
                    out.add(key_norm)
                self._collect_forbidden_output_keys(raw_val, out)
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                self._collect_forbidden_output_keys(item, out)

    def _enforce_no_raw_output(self, output: EidonOrderDocumentIntakeResponseDTO) -> None:
        if bool(output.template_learning_candidate.raw_tenant_document_included):
            raise ValueError("document_understanding_raw_output_violation")
        serialized = output.model_dump(exclude_none=True)
        violations: set[str] = set()
        self._collect_forbidden_output_keys(serialized, violations)
        if violations:
            raise ValueError("document_understanding_raw_output_violation")

    def _extract_from_text(self, extracted_text: str) -> list[tuple[str, str | int | float | bool, float, str]]:
        out: list[tuple[str, str | int | float | bool, float, str]] = []

        for field_path, patterns in _TEXT_PATTERNS.items():
            for pattern in patterns:
                m = re.search(pattern, extracted_text)
                if not m:
                    continue

                raw = m.group(m.lastindex or 1)
                if m.lastindex and m.lastindex > 1:
                    raw = m.group(m.lastindex)

                normalized = self._normalize_value(field_path, raw)
                if normalized is None:
                    continue

                out.append((field_path, normalized, 0.72, "normalized_input:text_pattern"))
                break

        return out

    def _round_bucket(self, value: int, step: int) -> int:
        if value <= 0:
            return 0
        return int((value // step) * step)

    def ingest(self, *, tenant_id: str, payload: EidonOrderDocumentIntakeRequestDTO) -> EidonOrderDocumentIntakeResponseDTO:
        extracted_values: dict[str, str | int | float | bool] = {}
        extracted_meta: dict[str, tuple[float, str, int]] = {}
        ambiguous: set[str] = set()
        warnings: list[str] = []

        def register_value(
            *,
            field_path: str,
            value: str | int | float | bool,
            confidence: float,
            source_ref: str,
            source_priority: int,
        ) -> None:
            normalized = self._normalize_value(field_path, value)
            if normalized is None:
                return

            existing = extracted_values.get(field_path)
            if existing is not None and existing != normalized:
                ambiguous.add(field_path)

            if existing is None:
                extracted_values[field_path] = normalized
                extracted_meta[field_path] = (confidence, source_ref, source_priority)
                return

            _, _, current_priority = extracted_meta[field_path]
            if source_priority >= current_priority:
                extracted_values[field_path] = normalized
                extracted_meta[field_path] = (confidence, source_ref, source_priority)

        for field_path, value, confidence, source_ref in self._extract_from_text(payload.extracted_text):
            register_value(
                field_path=field_path,
                value=value,
                confidence=confidence,
                source_ref=source_ref,
                source_priority=1,
            )

        for key, value in (payload.field_hints or {}).items():
            field_path = str(key or "").strip()
            if not field_path:
                continue
            if field_path not in _ALLOWED_FIELD_HINTS:
                warnings.append(f"unsupported_field_hint:{field_path}")
                continue
            register_value(
                field_path=field_path,
                value=value,
                confidence=0.94,
                source_ref="normalized_input:field_hint",
                source_priority=2,
            )

        draft_payload: dict[str, Any] = {}
        for field_path, value in extracted_values.items():
            self._set_nested(draft_payload, field_path, value)

        draft_candidate = OrderCreateRequestDTO.model_validate(draft_payload)
        draft_candidate_out = EidonOrderDraftCandidateDTO.model_validate(draft_candidate.model_dump())

        missing_required_fields = [
            field_path
            for field_path in _CMR_REQUIRED_FIELDS
            if self._is_missing(self._path_value(draft_candidate, field_path))
        ]

        for field_path in list(_CMR_REQUIRED_FIELDS) + list(_ADR_REQUIRED_FIELDS):
            value = self._path_value(draft_candidate, field_path)
            if self._is_missing(value):
                continue
            if self._is_ambiguous(value):
                ambiguous.add(field_path)

        is_dangerous_goods = bool(self._path_value(draft_candidate, "is_dangerous_goods"))
        adr_missing_fields: list[str] = []
        if is_dangerous_goods:
            adr_missing_fields = [
                field_path
                for field_path in _ADR_REQUIRED_FIELDS
                if self._is_missing(self._path_value(draft_candidate, field_path))
            ]

        if missing_required_fields:
            warnings.append("missing_required_fields_detected")
        if ambiguous:
            warnings.append("ambiguous_fields_require_human_clarification")
        if is_dangerous_goods and adr_missing_fields:
            warnings.append("adr_required_fields_missing")
        if not extracted_values:
            warnings.append("no_fields_extracted_from_input")

        extracted_fields = [
            EidonExtractedFieldDTO(
                field_path=field_path,
                value=extracted_values[field_path],
                confidence=extracted_meta[field_path][0],
                source_ref=extracted_meta[field_path][1],
            )
            for field_path in sorted(extracted_values.keys())
        ]

        source_traceability = [
            EidonSourceTraceabilityDTO(
                field_path=x.field_path,
                source_class="normalized_document_input",
                source_ref=x.source_ref,
            )
            for x in extracted_fields
        ]

        metadata = payload.document_metadata
        lines = payload.extracted_text.count("\n") + 1
        chars = len(payload.extracted_text)
        features = {
            "document_type": str((metadata.document_type if metadata else None) or "UNKNOWN"),
            "source_channel": str((metadata.source_channel if metadata else None) or "UNKNOWN"),
            "locale": str((metadata.locale if metadata else None) or "UNKNOWN"),
            "line_count_bucket": self._round_bucket(lines, 5),
            "char_count_bucket": self._round_bucket(chars, 250),
            "layout_hints_count": len(payload.layout_hints or {}),
            "field_hints_count": len(payload.field_hints or {}),
            "is_dangerous_goods": is_dangerous_goods,
            "extracted_field_paths": sorted(extracted_values.keys()),
        }
        fingerprint_seed = json.dumps(features, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        template_fingerprint = hashlib.sha256(fingerprint_seed.encode("utf-8")).hexdigest()[:24]

        cmr_required_count = len(_CMR_REQUIRED_FIELDS)
        cmr_missing_count = len(missing_required_fields)
        cmr_coverage_percent = round(((cmr_required_count - cmr_missing_count) / max(1, cmr_required_count)) * 100.0, 2)

        template_learning_candidate = EidonTemplateLearningCandidateDTO(
            eligible=len(extracted_values) >= 5,
            pattern_version="v1",
            template_fingerprint=template_fingerprint,
            extracted_field_paths=sorted(extracted_values.keys()),
            de_identified_pattern_features={
                "document_type": str(features["document_type"]),
                "source_channel": str(features["source_channel"]),
                "locale": str(features["locale"]),
                "line_count_bucket": int(features["line_count_bucket"]),
                "char_count_bucket": int(features["char_count_bucket"]),
                "layout_hints_count": int(features["layout_hints_count"]),
                "field_hints_count": int(features["field_hints_count"]),
                "is_dangerous_goods": bool(features["is_dangerous_goods"]),
                "cmr_coverage_percent": float(cmr_coverage_percent),
            },
            learn_globally_act_locally_rule="learn_globally_from_patterns_act_locally_within_tenant_boundaries",
            raw_tenant_document_included=False,
        )

        cmr_readiness = EidonReadinessDTO(
            ready=cmr_missing_count == 0,
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
        if ambiguous:
            human_confirmation_required_items.extend(f"field_clarification:{x}" for x in sorted(ambiguous))

        out = EidonOrderDocumentIntakeResponseDTO(
            ok=True,
            tenant_id=str(tenant_id),
            capability="EIDON_ORDER_DOCUMENT_INTAKE_V1",
            draft_order_candidate=draft_candidate_out,
            extracted_fields=extracted_fields,
            missing_required_fields=missing_required_fields,
            ambiguous_fields=sorted(ambiguous),
            cmr_readiness=cmr_readiness,
            adr_readiness=adr_readiness,
            human_confirmation_required_items=human_confirmation_required_items,
            source_traceability=source_traceability,
            warnings=warnings,
            template_fingerprint=template_fingerprint,
            template_learning_candidate=template_learning_candidate,
            authoritative_finalize_allowed=False,
            no_authoritative_finalize_rule="eidon_prepare_only_no_authoritative_finalize",
            system_truth_rule="ai_does_not_override_system_truth",
        )
        self._enforce_no_raw_output(out)
        tenant_action_boundary_guard.enforce_advisory_only(out)
        enforce_orders_response_contract_or_fail(
            surface_code=EIDON_ORDERS_RESPONSE_SURFACE_DOCUMENT_UNDERSTANDING,
            response=out,
        )
        return out


service = EidonOrderDocumentIntakeService()
