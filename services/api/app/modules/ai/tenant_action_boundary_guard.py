from __future__ import annotations

from typing import Any


AI_ACTION_BOUNDARY_VIOLATION = "ai_action_boundary_violation"

_DENY_MARKERS: set[str] = {
    "finalize",
    "finalize_now",
    "execute_action",
    "action_execute",
    "apply_now",
    "auto_apply",
    "save_order",
    "commit",
    "issue_document",
    "issue_now",
    "activate",
    "activation",
    "enable_runtime",
    "runtime_enable",
    "go_live",
    "live_enable",
    "auto_finalize",
    "write_back",
}


class TenantActionBoundaryGuard:
    def _normalized(self, value: Any) -> str:
        return str(value or "").strip().lower()

    def _scan_for_denied_markers(self, value: Any) -> None:
        if isinstance(value, dict):
            for raw_key, raw_val in value.items():
                if self._normalized(raw_key) in _DENY_MARKERS:
                    raise ValueError(AI_ACTION_BOUNDARY_VIOLATION)
                self._scan_for_denied_markers(raw_val)
            return

        if isinstance(value, (list, tuple, set)):
            for item in value:
                self._scan_for_denied_markers(item)
            return

        if isinstance(value, str):
            if self._normalized(value) in _DENY_MARKERS:
                raise ValueError(AI_ACTION_BOUNDARY_VIOLATION)

    def enforce_advisory_only(self, payload: Any) -> Any:
        if hasattr(payload, "model_dump"):
            serialized = payload.model_dump(exclude_none=False)
        elif isinstance(payload, dict):
            serialized = dict(payload)
        else:
            raise ValueError(AI_ACTION_BOUNDARY_VIOLATION)

        if serialized.get("authoritative_finalize_allowed") is not False:
            raise ValueError(AI_ACTION_BOUNDARY_VIOLATION)

        self._scan_for_denied_markers(serialized)
        return payload


service = TenantActionBoundaryGuard()
