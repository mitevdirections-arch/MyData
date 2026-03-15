from __future__ import annotations

import pytest

from app.modules.ai.tenant_action_boundary_guard import (
    AI_ACTION_BOUNDARY_VIOLATION,
    service as tenant_action_boundary_guard,
)


def test_tenant_action_boundary_guard_allows_advisory_only_payload() -> None:
    payload = {
        "ok": True,
        "authoritative_finalize_allowed": False,
        "human_confirmation_required_items": [
            "order_submission_or_state_transition",
            "authoritative_business_document_finalize",
        ],
        "nested": {
            "mode": "advisory_only",
            "flags": ["preview", "suggestion"],
        },
    }

    out = tenant_action_boundary_guard.enforce_advisory_only(payload)
    assert out is payload
    assert out["authoritative_finalize_allowed"] is False


def test_tenant_action_boundary_guard_denies_authoritative_finalize_true() -> None:
    payload = {
        "ok": True,
        "authoritative_finalize_allowed": True,
    }

    with pytest.raises(ValueError) as err:
        tenant_action_boundary_guard.enforce_advisory_only(payload)

    assert str(err.value) == AI_ACTION_BOUNDARY_VIOLATION


def test_tenant_action_boundary_guard_denies_nested_action_markers() -> None:
    payload = {
        "ok": True,
        "authoritative_finalize_allowed": False,
        "meta": {
            "safe": "advisory_only",
            "nested": [
                {
                    "step": "preview",
                    "mode": "execute_action",
                }
            ],
        },
    }

    with pytest.raises(ValueError) as err:
        tenant_action_boundary_guard.enforce_advisory_only(payload)

    assert str(err.value) == AI_ACTION_BOUNDARY_VIOLATION
