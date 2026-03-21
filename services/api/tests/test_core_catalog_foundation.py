from __future__ import annotations

from app.modules.licensing.core_catalog import (
    canonical_plan_code,
    catalog_items,
    recommended_plan_for_seats,
    seat_upgrade_hint,
)
from app.modules.licensing.service import service as licensing_service


def test_core_catalog_aliases_and_recommendation_contract() -> None:
    assert canonical_plan_code("core_u3") == "CORE3"
    assert canonical_plan_code("COREENTERPRISE") == "CORE_ENTERPRISE"
    assert canonical_plan_code("CORE_ENT") == "CORE_ENTERPRISE"
    assert recommended_plan_for_seats(1) == "CORE3"
    assert recommended_plan_for_seats(4) == "CORE5"
    assert recommended_plan_for_seats(22) == "CORE34"
    assert recommended_plan_for_seats(999) == "CORE_ENTERPRISE"


def test_core_catalog_public_contract_uses_single_source_of_truth() -> None:
    public_codes = [x.plan_code for x in catalog_items(include_legacy=False, public_only=True)]
    assert public_codes == ["CORE3", "CORE5", "CORE8", "CORE13", "CORE21", "CORE34", "CORE_ENTERPRISE"]

    service_codes = [x["plan_code"] for x in licensing_service.core_plan_catalog(include_legacy=False, public_only=True)]
    assert service_codes == public_codes


def test_upgrade_hint_contract() -> None:
    hint = seat_upgrade_hint(current_plan_code="CORE3", target_active_users=4)
    assert hint["needs_upgrade"] is True
    assert hint["recommended_plan_code"] == "CORE5"
    assert hint["next_plan_code"] == "CORE5"
    assert (hint.get("marketplace_upgrade_hint") or {}).get("path") == "/marketplace/catalog"
