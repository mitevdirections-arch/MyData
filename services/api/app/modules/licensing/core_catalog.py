from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_CORE_PLAN_CODE = "CORE8"


@dataclass(frozen=True)
class CorePlanDefinition:
    plan_code: str
    seat_limit: int | None
    order: int
    next_upgrade_plan_code: str | None
    public_visible: bool
    marketplace_visible: bool
    self_service_eligible: bool
    legacy: bool = False


_CORE_PLAN_DEFS: tuple[CorePlanDefinition, ...] = (
    CorePlanDefinition(
        plan_code="CORE3",
        seat_limit=3,
        order=10,
        next_upgrade_plan_code="CORE5",
        public_visible=True,
        marketplace_visible=True,
        self_service_eligible=True,
    ),
    CorePlanDefinition(
        plan_code="CORE5",
        seat_limit=5,
        order=20,
        next_upgrade_plan_code="CORE8",
        public_visible=True,
        marketplace_visible=True,
        self_service_eligible=True,
    ),
    CorePlanDefinition(
        plan_code="CORE8",
        seat_limit=8,
        order=30,
        next_upgrade_plan_code="CORE13",
        public_visible=True,
        marketplace_visible=True,
        self_service_eligible=True,
    ),
    CorePlanDefinition(
        plan_code="CORE13",
        seat_limit=13,
        order=40,
        next_upgrade_plan_code="CORE21",
        public_visible=True,
        marketplace_visible=True,
        self_service_eligible=True,
    ),
    CorePlanDefinition(
        plan_code="CORE21",
        seat_limit=21,
        order=50,
        next_upgrade_plan_code="CORE34",
        public_visible=True,
        marketplace_visible=True,
        self_service_eligible=True,
    ),
    CorePlanDefinition(
        # Compatibility only; hidden from public/self-service catalogs.
        plan_code="CORE24",
        seat_limit=24,
        order=55,
        next_upgrade_plan_code="CORE34",
        public_visible=False,
        marketplace_visible=False,
        self_service_eligible=False,
        legacy=True,
    ),
    CorePlanDefinition(
        plan_code="CORE34",
        seat_limit=34,
        order=60,
        next_upgrade_plan_code="CORE_ENTERPRISE",
        public_visible=True,
        marketplace_visible=True,
        self_service_eligible=True,
    ),
    CorePlanDefinition(
        # Compatibility only; hidden from public/self-service catalogs.
        plan_code="CORE45",
        seat_limit=45,
        order=65,
        next_upgrade_plan_code="CORE_ENTERPRISE",
        public_visible=False,
        marketplace_visible=False,
        self_service_eligible=False,
        legacy=True,
    ),
    CorePlanDefinition(
        plan_code="CORE_ENTERPRISE",
        seat_limit=None,
        order=70,
        next_upgrade_plan_code=None,
        public_visible=True,
        marketplace_visible=True,
        self_service_eligible=False,
    ),
)

_ALIAS_TO_PLAN: dict[str, str] = {
    "CORE_U3": "CORE3",
    "CORE_U5": "CORE5",
    "CORE_U8": "CORE8",
    "CORE_U13": "CORE13",
    "CORE_U21": "CORE21",
    "CORE_U34": "CORE34",
    "CORE_U_ENTERPRISE": "CORE_ENTERPRISE",
    "COREENTERPRISE": "CORE_ENTERPRISE",
    "CORE_ENT": "CORE_ENTERPRISE",
}

_PLAN_BY_CODE: dict[str, CorePlanDefinition] = {item.plan_code: item for item in _CORE_PLAN_DEFS}


def canonical_plan_code(raw_code: str | None, *, default: str = DEFAULT_CORE_PLAN_CODE) -> str:
    code = str(raw_code or "").strip().upper()
    if not code:
        return default
    mapped = _ALIAS_TO_PLAN.get(code, code)
    if mapped in _PLAN_BY_CODE:
        return mapped
    return default


def is_supported_plan_code(raw_code: str | None) -> bool:
    code = canonical_plan_code(raw_code, default="")
    return bool(code) and code in _PLAN_BY_CODE


def plan_definition(raw_code: str | None) -> CorePlanDefinition | None:
    code = canonical_plan_code(raw_code, default="")
    return _PLAN_BY_CODE.get(code)


def seat_limit_for_plan(raw_code: str | None) -> int | None:
    item = plan_definition(raw_code)
    return item.seat_limit if item is not None else None


def next_upgrade_plan(raw_code: str | None) -> str | None:
    item = plan_definition(raw_code)
    return item.next_upgrade_plan_code if item is not None else None


def catalog_items(
    *,
    include_legacy: bool = False,
    public_only: bool = False,
    marketplace_only: bool = False,
) -> list[CorePlanDefinition]:
    out: list[CorePlanDefinition] = []
    for item in _CORE_PLAN_DEFS:
        if not include_legacy and item.legacy:
            continue
        if public_only and not item.public_visible:
            continue
        if marketplace_only and not item.marketplace_visible:
            continue
        out.append(item)
    return out


def recommended_plan_for_seats(seats: int) -> str:
    requested = max(1, int(seats))
    candidates = [x for x in catalog_items(include_legacy=False, public_only=True) if x.seat_limit is not None]
    for item in sorted(candidates, key=lambda x: x.order):
        if requested <= int(item.seat_limit):
            return item.plan_code
    return "CORE_ENTERPRISE"


def seat_upgrade_hint(*, current_plan_code: str | None, target_active_users: int) -> dict[str, Any]:
    current = plan_definition(current_plan_code)
    target = max(1, int(target_active_users))

    ordered = sorted(catalog_items(include_legacy=False, public_only=True), key=lambda x: x.order)
    recommended = next((item for item in ordered if item.seat_limit is None or target <= int(item.seat_limit)), ordered[-1])

    current_code = current.plan_code if current is not None else canonical_plan_code(current_plan_code)
    needs_upgrade = bool(
        current is not None
        and current.seat_limit is not None
        and target > int(current.seat_limit)
    )

    return {
        "current_plan_code": current_code or None,
        "target_active_users": target,
        "recommended_plan_code": recommended.plan_code,
        "recommended_seat_limit": recommended.seat_limit,
        "next_plan_code": next_upgrade_plan(current_code),
        "needs_upgrade": needs_upgrade,
        "marketplace_upgrade_hint": {
            "path": "/marketplace/catalog",
            "target_plan_code": recommended.plan_code,
        },
    }
