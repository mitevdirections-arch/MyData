from __future__ import annotations

import pytest

from app.modules.licensing.service import LicensingPolicyError, LicensingService


def test_upgrade_hint_returns_next_plan_and_marketplace_target() -> None:
    svc = LicensingService()

    out = svc.evaluate_upgrade_need(current_plan_code="CORE_U3", target_active_users=4)

    assert out["current_plan_code"] == "CORE3"
    assert out["upgrade_required"] is True
    assert out["next_plan_code"] == "CORE5"
    assert out["recommended_plan_code"] == "CORE5"
    hint = out.get("marketplace_upgrade_hint") or {}
    assert hint.get("path") == "/marketplace/catalog"
    assert hint.get("target_plan_code") == "CORE5"


def test_core_u3_blocks_fourth_active_user_with_machine_readable_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = LicensingService()

    monkeypatch.setattr(
        svc,
        "resolve_core_entitlement",
        lambda *_args, **_kwargs: {
            "has_core": True,
            "plan_code": "CORE3",
            "seat_limit": 3,
            "core_valid_to": "2099-01-01T00:00:00Z",
        },
    )
    monkeypatch.setattr(svc, "count_active_tenant_users", lambda *_args, **_kwargs: 3)

    with pytest.raises(LicensingPolicyError) as exc:
        svc.assert_workspace_user_seat_available(
            None,  # db is stubbed via monkeypatches
            tenant_id="tenant-01",
            user_id="user-04",
        )

    detail = exc.value.to_detail()
    assert detail["code"] == "CORE_SEAT_LIMIT_EXCEEDED"
    assert detail["current_plan_code"] == "CORE3"
    assert int(detail["seat_limit"]) == 3
    assert int(detail["active_user_count"]) == 3
    assert int(detail["attempted_user_count"]) == 4
    assert detail["next_plan_code"] == "CORE5"
    assert detail["recommended_plan_code"] == "CORE5"
    assert (detail.get("marketplace_upgrade_hint") or {}).get("target_plan_code") == "CORE5"


def test_owner_admin_is_counted_in_active_seat_roster(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = LicensingService()

    monkeypatch.setattr(
        svc,
        "resolve_core_entitlement",
        lambda *_args, **_kwargs: {
            "has_core": True,
            "plan_code": "CORE3",
            "seat_limit": 3,
            "core_valid_to": None,
        },
    )
    # Represents roster where owner/admin + two users are already ACTIVE.
    monkeypatch.setattr(svc, "count_active_tenant_users", lambda *_args, **_kwargs: 3)

    with pytest.raises(LicensingPolicyError) as exc:
        svc.assert_workspace_user_seat_available(
            None,
            tenant_id="tenant-owner",
            user_id="user-new",
        )

    detail = exc.value.to_detail()
    assert detail["code"] == "CORE_SEAT_LIMIT_EXCEEDED"
    assert int(detail["active_user_count"]) == 3
    assert int(detail["attempted_user_count"]) == 4


def test_downgrade_denial_returns_exact_users_to_remove() -> None:
    svc = LicensingService()

    with pytest.raises(LicensingPolicyError) as exc:
        svc.assert_downgrade_allowed(
            current_plan_code="CORE13",
            target_plan_code="CORE5",
            current_active_users=7,
        )

    detail = exc.value.to_detail()
    assert detail["code"] == "CORE_DOWNGRADE_REQUIRES_USER_REDUCTION"
    assert detail["current_plan_code"] == "CORE13"
    assert detail["target_plan_code"] == "CORE5"
    assert int(detail["current_active_users"]) == 7
    assert int(detail["target_seat_limit"]) == 5
    assert int(detail["users_to_remove_from_active_roster"]) == 2
