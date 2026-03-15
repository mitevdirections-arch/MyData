from __future__ import annotations

from dataclasses import asdict, dataclass
import importlib
from pathlib import Path
from typing import Any

from fastapi.routing import APIRoute

from app.core.policy_matrix import ROUTE_POLICY, is_protected_route_path
from app.core.route_ownership import ROUTE_PLANE_FOUNDATION, ROUTE_PLANE_OPERATIONAL, resolve_route_plane


@dataclass(frozen=True)
class ModuleFactoryTarget:
    module_slug: str
    module_import: str
    module_dir: str
    module_name: str
    module_code: str
    plane_ownership: str
    authz_mode: str
    marketplace_facing: bool
    route_prefixes: tuple[str, ...]
    sensitivity: str
    required_tests: tuple[str, ...]
    required_gate_expectations: tuple[str, ...]


@dataclass(frozen=True)
class ModuleCoverageAssessment:
    module_slug: str
    module_dir: str
    status: str
    business_runtime: bool
    marketplace_facing: bool
    plane_ownership: str
    reason: str
    protected_route_prefixes: tuple[str, ...] = ()
    public_route_prefixes: tuple[str, ...] = ()


MODULE_COVERAGE_REFERENCE_READY = "REFERENCE_READY"
MODULE_COVERAGE_NOT_READY = "NOT_READY"

_ALLOWED_SENSITIVITY = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
_ALLOWED_COVERAGE_STATUS = {MODULE_COVERAGE_REFERENCE_READY, MODULE_COVERAGE_NOT_READY}
_ALLOWED_COVERAGE_PLANES = {ROUTE_PLANE_FOUNDATION, ROUTE_PLANE_OPERATIONAL, "MIXED"}


_MODULE_FACTORY_TARGETS_V1: tuple[ModuleFactoryTarget, ...] = (
    ModuleFactoryTarget(
        module_slug="orders",
        module_import="app.modules.orders.module_contract",
        module_dir="app/modules/orders",
        module_name="Orders",
        module_code="MODULE_ORDERS",
        plane_ownership=ROUTE_PLANE_OPERATIONAL,
        authz_mode="DB_TRUTH",
        marketplace_facing=True,
        route_prefixes=("/orders",),
        sensitivity="MEDIUM",
        required_tests=(
            "tests/test_orders_routes.py",
            "tests/test_orders_contract.py",
        ),
        required_gate_expectations=(
            "authz_contract",
            "route_ownership_contract",
            "module_factory_contract",
            "module_factory_coverage_contract",
            "support_plane_decomposition_contract",
            "ai_plane_decomposition_contract",
        ),
    ),
)


_MODULE_COVERAGE_ASSESSMENTS_V1: tuple[ModuleCoverageAssessment, ...] = (
    ModuleCoverageAssessment(
        module_slug="orders",
        module_dir="app/modules/orders",
        status=MODULE_COVERAGE_REFERENCE_READY,
        business_runtime=True,
        marketplace_facing=True,
        plane_ownership=ROUTE_PLANE_OPERATIONAL,
        reason="reference_module_with_typed_contract_and_operational_plane",
        protected_route_prefixes=("/orders",),
    ),
    ModuleCoverageAssessment(
        module_slug="marketplace",
        module_dir="app/modules/marketplace",
        status=MODULE_COVERAGE_NOT_READY,
        business_runtime=False,
        marketplace_facing=True,
        plane_ownership=ROUTE_PLANE_FOUNDATION,
        reason="foundation_controlled_facade_not_business_runtime_module",
        protected_route_prefixes=("/marketplace",),
    ),
    ModuleCoverageAssessment(
        module_slug="support_tenant_runtime",
        module_dir="app/modules/support",
        status=MODULE_COVERAGE_NOT_READY,
        business_runtime=True,
        marketplace_facing=False,
        plane_ownership=ROUTE_PLANE_OPERATIONAL,
        reason="decomposed_operational_support_surface_not_reference_ready_yet",
        protected_route_prefixes=("/support/tenant",),
        public_route_prefixes=("/support/public",),
    ),
    ModuleCoverageAssessment(
        module_slug="support_superadmin_control",
        module_dir="app/modules/support",
        status=MODULE_COVERAGE_NOT_READY,
        business_runtime=False,
        marketplace_facing=False,
        plane_ownership=ROUTE_PLANE_FOUNDATION,
        reason="decomposed_foundation_control_surface_not_reference_ready_yet",
        protected_route_prefixes=("/support/superadmin",),
    ),
    ModuleCoverageAssessment(
        module_slug="ai_tenant_runtime",
        module_dir="app/modules/ai",
        status=MODULE_COVERAGE_NOT_READY,
        business_runtime=True,
        marketplace_facing=False,
        plane_ownership=ROUTE_PLANE_OPERATIONAL,
        reason="decomposed_operational_ai_surface_not_reference_ready_yet",
        protected_route_prefixes=("/ai/tenant-copilot",),
    ),
    ModuleCoverageAssessment(
        module_slug="ai_superadmin_control",
        module_dir="app/modules/ai",
        status=MODULE_COVERAGE_NOT_READY,
        business_runtime=False,
        marketplace_facing=False,
        plane_ownership=ROUTE_PLANE_FOUNDATION,
        reason="decomposed_foundation_ai_control_surface_not_reference_ready_yet",
        protected_route_prefixes=("/ai/superadmin-copilot",),
    ),
)


_REQUIRED_COVERAGE_MODULES_V1 = {
    "orders",
    "marketplace",
    "support_tenant_runtime",
    "support_superadmin_control",
    "ai_tenant_runtime",
    "ai_superadmin_control",
}


def module_factory_targets_v1() -> tuple[ModuleFactoryTarget, ...]:
    return _MODULE_FACTORY_TARGETS_V1


def module_contract_coverage_assessments_v1() -> tuple[ModuleCoverageAssessment, ...]:
    return _MODULE_COVERAGE_ASSESSMENTS_V1


def module_contract_coverage_report_v1() -> dict[str, Any]:
    ready: list[dict[str, Any]] = []
    not_ready: list[dict[str, Any]] = []

    for item in module_contract_coverage_assessments_v1():
        row = asdict(item)
        if item.status == MODULE_COVERAGE_REFERENCE_READY:
            ready.append(row)
        else:
            not_ready.append(row)

    return {
        "version": "v1",
        "reference_ready_modules": ready,
        "not_ready_modules": not_ready,
    }


def module_factory_contract_required_fields_v1() -> tuple[str, ...]:
    return (
        "module_name",
        "module_code",
        "plane_ownership",
        "authz_mode",
        "marketplace_facing",
        "typed_schemas",
        "readme",
        "router_service_boundaries",
        "sensitivity",
        "route_prefixes",
        "minimum_tests",
        "minimum_gate_expectations",
    )


def _path_matches_prefix(path: str, prefixes: tuple[str, ...]) -> bool:
    for prefix in prefixes:
        if path == prefix:
            return True
        if path.startswith(prefix + "/"):
            return True
    return False


def _rel(root: Path, p: Path) -> str:
    try:
        return p.relative_to(root).as_posix()
    except Exception:  # noqa: BLE001
        return str(p)


def _app_route_keys() -> set[tuple[str, str]]:
    from app.main import app

    out: set[tuple[str, str]] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        methods = sorted(set(route.methods or set()))
        for method in methods:
            if method in {"HEAD", "OPTIONS"}:
                continue
            out.add((method, route.path))
    return out


def _policy_keys_for_prefixes(prefixes: tuple[str, ...]) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    for method, path in sorted(ROUTE_POLICY.keys()):
        if _path_matches_prefix(path, prefixes):
            keys.append((method, path))
    return keys


def check_module_factory_contract(root: Path) -> list[str]:
    issues: list[str] = []
    required_fields = set(module_factory_contract_required_fields_v1())

    for target in module_factory_targets_v1():
        module_root = root / target.module_dir
        required_files = (
            module_root / "router.py",
            module_root / "service.py",
            module_root / "schemas.py",
            module_root / "README.md",
            module_root / "module_contract.py",
        )
        for req in required_files:
            if not req.exists():
                issues.append(f"module_factory_missing_file:{target.module_slug}:{_rel(root, req)}")

        try:
            marker_module = importlib.import_module(target.module_import)
            marker: Any = getattr(marker_module, "MODULE_CONTRACT_V1", None)
        except Exception as exc:  # noqa: BLE001
            issues.append(f"module_factory_marker_import_failed:{target.module_slug}:{str(exc)[:200]}")
            continue

        if not isinstance(marker, dict):
            issues.append(f"module_factory_marker_invalid:{target.module_slug}:not_dict")
            continue

        missing_fields = sorted(required_fields - set(marker.keys()))
        for field in missing_fields:
            issues.append(f"module_factory_marker_missing_field:{target.module_slug}:{field}")

        if missing_fields:
            continue

        if str(marker.get("module_name") or "") != target.module_name:
            issues.append(f"module_factory_marker_mismatch:{target.module_slug}:module_name")
        if str(marker.get("module_code") or "") != target.module_code:
            issues.append(f"module_factory_marker_mismatch:{target.module_slug}:module_code")
        if str(marker.get("plane_ownership") or "") != target.plane_ownership:
            issues.append(f"module_factory_marker_mismatch:{target.module_slug}:plane_ownership")

        mode = str(marker.get("authz_mode") or "").strip().upper()
        if mode != target.authz_mode:
            issues.append(f"module_factory_marker_mismatch:{target.module_slug}:authz_mode")

        if bool(marker.get("marketplace_facing")) != bool(target.marketplace_facing):
            issues.append(f"module_factory_marker_mismatch:{target.module_slug}:marketplace_facing")

        if bool(marker.get("typed_schemas")) is not True:
            issues.append(f"module_factory_marker_required_true:{target.module_slug}:typed_schemas")
        if bool(marker.get("readme")) is not True:
            issues.append(f"module_factory_marker_required_true:{target.module_slug}:readme")
        if bool(marker.get("router_service_boundaries")) is not True:
            issues.append(f"module_factory_marker_required_true:{target.module_slug}:router_service_boundaries")

        sensitivity = str(marker.get("sensitivity") or "").strip().upper()
        if sensitivity not in _ALLOWED_SENSITIVITY:
            issues.append(f"module_factory_marker_invalid_sensitivity:{target.module_slug}:{sensitivity or 'EMPTY'}")
        if sensitivity != target.sensitivity:
            issues.append(f"module_factory_marker_mismatch:{target.module_slug}:sensitivity")

        marker_prefixes = tuple(str(x) for x in (marker.get("route_prefixes") or []))
        for pref in target.route_prefixes:
            if pref not in marker_prefixes:
                issues.append(f"module_factory_marker_missing_prefix:{target.module_slug}:{pref}")

        marker_tests = set(str(x) for x in (marker.get("minimum_tests") or []))
        for req_test in target.required_tests:
            if req_test not in marker_tests:
                issues.append(f"module_factory_marker_missing_test:{target.module_slug}:{req_test}")
            elif not (root / req_test).exists():
                issues.append(f"module_factory_test_file_missing:{target.module_slug}:{req_test}")

        marker_gates = set(str(x) for x in (marker.get("minimum_gate_expectations") or []))
        for req_gate in target.required_gate_expectations:
            if req_gate not in marker_gates:
                issues.append(f"module_factory_marker_missing_gate:{target.module_slug}:{req_gate}")

        covered = 0
        for (method, path), policy in ROUTE_POLICY.items():
            if not _path_matches_prefix(path, target.route_prefixes):
                continue
            if not is_protected_route_path(path):
                continue

            covered += 1
            owner = resolve_route_plane(method, path)
            if owner != target.plane_ownership:
                issues.append(
                    f"module_factory_route_owner_mismatch:{target.module_slug}:{method}:{path}:{owner or 'EMPTY'}"
                )

            policy_mode = str(getattr(policy, "authz_mode", "") or "").strip().upper()
            if policy_mode != target.authz_mode:
                issues.append(
                    f"module_factory_route_authz_mode_mismatch:{target.module_slug}:{method}:{path}:{policy_mode or 'EMPTY'}"
                )

        if covered == 0:
            issues.append(f"module_factory_no_protected_routes:{target.module_slug}")

    return issues


def check_support_plane_decomposition_contract(root: Path) -> list[str]:
    issues: list[str] = []

    support_dir = root / "app/modules/support"
    marker_path = support_dir / "surface_contract.py"
    if not marker_path.exists():
        return [f"support_plane_contract_missing_file:{_rel(root, marker_path)}"]

    try:
        marker_module = importlib.import_module("app.modules.support.surface_contract")
        marker: Any = getattr(marker_module, "SUPPORT_SURFACE_CONTRACT_V1", None)
    except Exception as exc:  # noqa: BLE001
        return [f"support_plane_contract_import_failed:{str(exc)[:200]}"]

    if not isinstance(marker, dict):
        return ["support_plane_contract_invalid:not_dict"]

    required_surfaces = {"tenant_runtime", "superadmin_control"}
    for key in sorted(required_surfaces - set(marker.keys())):
        issues.append(f"support_plane_contract_missing_surface:{key}")

    tenant = marker.get("tenant_runtime") if isinstance(marker.get("tenant_runtime"), dict) else None
    superadmin = marker.get("superadmin_control") if isinstance(marker.get("superadmin_control"), dict) else None

    if tenant is None:
        issues.append("support_plane_contract_invalid_surface:tenant_runtime")
    if superadmin is None:
        issues.append("support_plane_contract_invalid_surface:superadmin_control")

    if tenant is None or superadmin is None:
        return issues

    tenant_plane = str(tenant.get("plane_ownership") or "").strip().upper()
    super_plane = str(superadmin.get("plane_ownership") or "").strip().upper()

    if tenant_plane != ROUTE_PLANE_OPERATIONAL:
        issues.append(f"support_plane_contract_invalid_plane:tenant_runtime:{tenant_plane or 'EMPTY'}")
    if super_plane != ROUTE_PLANE_FOUNDATION:
        issues.append(f"support_plane_contract_invalid_plane:superadmin_control:{super_plane or 'EMPTY'}")

    tenant_protected_prefixes = tuple(str(x) for x in (tenant.get("protected_route_prefixes") or []))
    tenant_public_prefixes = tuple(str(x) for x in (tenant.get("public_route_prefixes") or []))
    super_protected_prefixes = tuple(str(x) for x in (superadmin.get("protected_route_prefixes") or []))

    if not tenant_protected_prefixes:
        issues.append("support_plane_contract_missing_prefixes:tenant_runtime:protected")
    if not tenant_public_prefixes:
        issues.append("support_plane_contract_missing_prefixes:tenant_runtime:public")
    if not super_protected_prefixes:
        issues.append("support_plane_contract_missing_prefixes:superadmin_control:protected")

    tenant_policy_keys = _policy_keys_for_prefixes(tenant_protected_prefixes)
    if not tenant_policy_keys:
        issues.append("support_plane_contract_no_policy_routes:tenant_runtime")
    for method, path in tenant_policy_keys:
        owner = resolve_route_plane(method, path)
        if owner != ROUTE_PLANE_OPERATIONAL:
            issues.append(f"support_plane_contract_owner_mismatch:tenant_runtime:{method}:{path}:{owner or 'EMPTY'}")

    super_policy_keys = _policy_keys_for_prefixes(super_protected_prefixes)
    if not super_policy_keys:
        issues.append("support_plane_contract_no_policy_routes:superadmin_control")
    for method, path in super_policy_keys:
        owner = resolve_route_plane(method, path)
        if owner != ROUTE_PLANE_FOUNDATION:
            issues.append(f"support_plane_contract_owner_mismatch:superadmin_control:{method}:{path}:{owner or 'EMPTY'}")

    app_keys = _app_route_keys()
    tenant_public_routes = [(m, p) for (m, p) in sorted(app_keys) if _path_matches_prefix(p, tenant_public_prefixes)]
    if not tenant_public_routes:
        issues.append("support_plane_contract_no_public_routes:tenant_runtime")

    for method, path in tenant_public_routes:
        if (method, path) in ROUTE_POLICY:
            owner = resolve_route_plane(method, path)
            if owner != ROUTE_PLANE_OPERATIONAL:
                issues.append(f"support_plane_contract_public_owner_mismatch:{method}:{path}:{owner or 'EMPTY'}")

    return issues


def check_ai_plane_decomposition_contract(root: Path) -> list[str]:
    issues: list[str] = []

    ai_dir = root / "app/modules/ai"
    marker_path = ai_dir / "surface_contract.py"
    if not marker_path.exists():
        return [f"ai_plane_contract_missing_file:{_rel(root, marker_path)}"]

    try:
        marker_module = importlib.import_module("app.modules.ai.surface_contract")
        marker: Any = getattr(marker_module, "AI_SURFACE_CONTRACT_V1", None)
    except Exception as exc:  # noqa: BLE001
        return [f"ai_plane_contract_import_failed:{str(exc)[:200]}"]

    if not isinstance(marker, dict):
        return ["ai_plane_contract_invalid:not_dict"]

    required_surfaces = {"tenant_runtime", "superadmin_control"}
    for key in sorted(required_surfaces - set(marker.keys())):
        issues.append(f"ai_plane_contract_missing_surface:{key}")

    tenant = marker.get("tenant_runtime") if isinstance(marker.get("tenant_runtime"), dict) else None
    superadmin = marker.get("superadmin_control") if isinstance(marker.get("superadmin_control"), dict) else None

    if tenant is None:
        issues.append("ai_plane_contract_invalid_surface:tenant_runtime")
    if superadmin is None:
        issues.append("ai_plane_contract_invalid_surface:superadmin_control")

    if tenant is None or superadmin is None:
        return issues

    tenant_plane = str(tenant.get("plane_ownership") or "").strip().upper()
    super_plane = str(superadmin.get("plane_ownership") or "").strip().upper()

    if tenant_plane != ROUTE_PLANE_OPERATIONAL:
        issues.append(f"ai_plane_contract_invalid_plane:tenant_runtime:{tenant_plane or 'EMPTY'}")
    if super_plane != ROUTE_PLANE_FOUNDATION:
        issues.append(f"ai_plane_contract_invalid_plane:superadmin_control:{super_plane or 'EMPTY'}")

    tenant_protected_prefixes = tuple(str(x) for x in (tenant.get("protected_route_prefixes") or []))
    super_protected_prefixes = tuple(str(x) for x in (superadmin.get("protected_route_prefixes") or []))

    if not tenant_protected_prefixes:
        issues.append("ai_plane_contract_missing_prefixes:tenant_runtime:protected")
    if not super_protected_prefixes:
        issues.append("ai_plane_contract_missing_prefixes:superadmin_control:protected")

    tenant_policy_keys = _policy_keys_for_prefixes(tenant_protected_prefixes)
    if not tenant_policy_keys:
        issues.append("ai_plane_contract_no_policy_routes:tenant_runtime")
    for method, path in tenant_policy_keys:
        owner = resolve_route_plane(method, path)
        if owner != ROUTE_PLANE_OPERATIONAL:
            issues.append(f"ai_plane_contract_owner_mismatch:tenant_runtime:{method}:{path}:{owner or 'EMPTY'}")

    super_policy_keys = _policy_keys_for_prefixes(super_protected_prefixes)
    if not super_policy_keys:
        issues.append("ai_plane_contract_no_policy_routes:superadmin_control")
    for method, path in super_policy_keys:
        owner = resolve_route_plane(method, path)
        if owner != ROUTE_PLANE_FOUNDATION:
            issues.append(f"ai_plane_contract_owner_mismatch:superadmin_control:{method}:{path}:{owner or 'EMPTY'}")
    return issues


def check_ai_contract_v1(root: Path) -> list[str]:
    issues: list[str] = []

    ai_dir = root / "app/modules/ai"
    contract_path = ai_dir / "contract_v1.py"
    surface_path = ai_dir / "surface_contract.py"

    if not contract_path.exists():
        issues.append(f"ai_contract_v1_missing_file:{_rel(root, contract_path)}")
    if not surface_path.exists():
        issues.append(f"ai_contract_v1_missing_surface_file:{_rel(root, surface_path)}")
    if issues:
        return issues

    try:
        contract_module = importlib.import_module("app.modules.ai.contract_v1")
        contract: Any = getattr(contract_module, "AI_CONTRACT_V1", None)
    except Exception as exc:  # noqa: BLE001
        return [f"ai_contract_v1_import_failed:{str(exc)[:200]}"]

    try:
        surface_module = importlib.import_module("app.modules.ai.surface_contract")
        surfaces_marker: Any = getattr(surface_module, "AI_SURFACE_CONTRACT_V1", None)
    except Exception as exc:  # noqa: BLE001
        return [f"ai_contract_v1_surface_import_failed:{str(exc)[:200]}"]

    if not isinstance(contract, dict):
        return ["ai_contract_v1_invalid:not_dict"]
    if not isinstance(surfaces_marker, dict):
        return ["ai_contract_v1_surface_invalid:not_dict"]

    if str(contract.get("contract_code") or "").strip() != "AI_CONTRACT_V1":
        issues.append("ai_contract_v1_contract_code_invalid")
    if str(contract.get("version") or "").strip() != "v1":
        issues.append("ai_contract_v1_version_invalid")
    if bool(contract.get("ai_does_not_override_system_truth")) is not True:
        issues.append("ai_contract_v1_truth_override_rule_missing_or_false")

    contract_surfaces = contract.get("surfaces") if isinstance(contract.get("surfaces"), dict) else None
    if contract_surfaces is None:
        return issues + ["ai_contract_v1_surfaces_invalid:not_dict"]

    required_surfaces = ("tenant_runtime", "superadmin_control")
    required_fields = (
        "allowed_context_scope",
        "forbidden_context_scope",
        "allowed_suggestion_types",
        "forbidden_action_classes",
        "human_confirmation_required_actions",
        "auditability_requirement",
        "tenant_isolation_requirement",
        "superadmin_only_capabilities",
    )

    for surface in required_surfaces:
        payload = contract_surfaces.get(surface)
        marker_surface = surfaces_marker.get(surface) if isinstance(surfaces_marker.get(surface), dict) else None

        if not isinstance(payload, dict):
            issues.append(f"ai_contract_v1_missing_surface:{surface}")
            continue
        if marker_surface is None:
            issues.append(f"ai_contract_v1_missing_surface_marker:{surface}")
            continue

        for field in required_fields:
            if field not in payload:
                issues.append(f"ai_contract_v1_missing_field:{surface}:{field}")
                continue

            val = payload.get(field)
            if field.endswith("_scope") or field.endswith("_types") or field.endswith("_classes") or field.endswith("_actions") or field == "superadmin_only_capabilities":
                if not isinstance(val, list):
                    issues.append(f"ai_contract_v1_invalid_field_type:{surface}:{field}:list_required")
                elif field != "superadmin_only_capabilities" and len(val) == 0:
                    issues.append(f"ai_contract_v1_invalid_field_empty:{surface}:{field}")
            else:
                if not str(val or "").strip():
                    issues.append(f"ai_contract_v1_invalid_field_empty:{surface}:{field}")

        ref = str(marker_surface.get("contract_ref") or "").strip()
        expected_ref = f"AI_CONTRACT_V1:{surface}"
        if ref != expected_ref:
            issues.append(f"ai_contract_v1_surface_contract_ref_mismatch:{surface}:{ref or 'EMPTY'}")

        if surface == "tenant_runtime" and list(payload.get("superadmin_only_capabilities") or []):
            issues.append("ai_contract_v1_tenant_superadmin_capabilities_must_be_empty")
        if surface == "superadmin_control" and len(list(payload.get("superadmin_only_capabilities") or [])) == 0:
            issues.append("ai_contract_v1_superadmin_capabilities_required")

    return issues



def check_ai_retrieval_contract_v1(root: Path) -> list[str]:
    issues: list[str] = []

    ai_dir = root / "app/modules/ai"
    contract_path = ai_dir / "retrieval_contract_v1.py"
    surface_path = ai_dir / "surface_contract.py"

    if not contract_path.exists():
        issues.append(f"ai_retrieval_contract_v1_missing_file:{_rel(root, contract_path)}")
    if not surface_path.exists():
        issues.append(f"ai_retrieval_contract_v1_missing_surface_file:{_rel(root, surface_path)}")
    if issues:
        return issues

    try:
        contract_module = importlib.import_module("app.modules.ai.retrieval_contract_v1")
        contract: Any = getattr(contract_module, "AI_RETRIEVAL_CONTRACT_V1", None)
    except Exception as exc:  # noqa: BLE001
        return [f"ai_retrieval_contract_v1_import_failed:{str(exc)[:200]}"]

    try:
        surface_module = importlib.import_module("app.modules.ai.surface_contract")
        surfaces_marker: Any = getattr(surface_module, "AI_SURFACE_CONTRACT_V1", None)
    except Exception as exc:  # noqa: BLE001
        return [f"ai_retrieval_contract_v1_surface_import_failed:{str(exc)[:200]}"]

    if not isinstance(contract, dict):
        return ["ai_retrieval_contract_v1_invalid:not_dict"]
    if not isinstance(surfaces_marker, dict):
        return ["ai_retrieval_contract_v1_surface_invalid:not_dict"]

    if str(contract.get("contract_code") or "").strip() != "AI_RETRIEVAL_CONTRACT_V1":
        issues.append("ai_retrieval_contract_v1_contract_code_invalid")
    if str(contract.get("version") or "").strip() != "v1":
        issues.append("ai_retrieval_contract_v1_version_invalid")

    contract_surfaces = contract.get("surfaces") if isinstance(contract.get("surfaces"), dict) else None
    if contract_surfaces is None:
        return issues + ["ai_retrieval_contract_v1_surfaces_invalid:not_dict"]

    tenant_payload = contract_surfaces.get("tenant_runtime")
    if not isinstance(tenant_payload, dict):
        return issues + ["ai_retrieval_contract_v1_missing_surface:tenant_runtime"]

    tenant_marker = surfaces_marker.get("tenant_runtime") if isinstance(surfaces_marker.get("tenant_runtime"), dict) else None
    if tenant_marker is None:
        return issues + ["ai_retrieval_contract_v1_missing_surface_marker:tenant_runtime"]

    required_fields = (
        "allowed_retrieval_scope",
        "forbidden_retrieval_scope",
        "tenant_boundary_rule",
        "permission_filtered_visibility_rule",
        "no_cross_tenant_rule",
        "no_hidden_object_inference_rule",
        "allowed_source_classes",
        "forbidden_source_classes",
        "result_traceability_auditability_requirement",
        "cannot_exceed_requesting_user_direct_access_rule",
    )

    for field in required_fields:
        if field not in tenant_payload:
            issues.append(f"ai_retrieval_contract_v1_missing_field:tenant_runtime:{field}")
            continue

        val = tenant_payload.get(field)
        if field.endswith("_scope") or field.endswith("_classes"):
            if not isinstance(val, list):
                issues.append(f"ai_retrieval_contract_v1_invalid_field_type:tenant_runtime:{field}:list_required")
            elif len(val) == 0:
                issues.append(f"ai_retrieval_contract_v1_invalid_field_empty:tenant_runtime:{field}")
        else:
            if not str(val or "").strip():
                issues.append(f"ai_retrieval_contract_v1_invalid_field_empty:tenant_runtime:{field}")

    ref = str(tenant_marker.get("retrieval_contract_ref") or "").strip()
    expected_ref = "AI_RETRIEVAL_CONTRACT_V1:tenant_runtime"
    if ref != expected_ref:
        issues.append(f"ai_retrieval_contract_v1_surface_contract_ref_mismatch:tenant_runtime:{ref or 'EMPTY'}")

    return issues
def check_eidon_drafting_contract_v1(root: Path) -> list[str]:
    issues: list[str] = []

    ai_dir = root / "app/modules/ai"
    contract_path = ai_dir / "eidon_drafting_contract_v1.py"
    surface_path = ai_dir / "surface_contract.py"

    if not contract_path.exists():
        issues.append(f"eidon_drafting_contract_v1_missing_file:{_rel(root, contract_path)}")
    if not surface_path.exists():
        issues.append(f"eidon_drafting_contract_v1_missing_surface_file:{_rel(root, surface_path)}")
    if issues:
        return issues

    try:
        contract_module = importlib.import_module("app.modules.ai.eidon_drafting_contract_v1")
        contract: Any = getattr(contract_module, "EIDON_DRAFTING_CONTRACT_V1", None)
    except Exception as exc:  # noqa: BLE001
        return [f"eidon_drafting_contract_v1_import_failed:{str(exc)[:200]}"]

    try:
        surface_module = importlib.import_module("app.modules.ai.surface_contract")
        surfaces_marker: Any = getattr(surface_module, "AI_SURFACE_CONTRACT_V1", None)
    except Exception as exc:  # noqa: BLE001
        return [f"eidon_drafting_contract_v1_surface_import_failed:{str(exc)[:200]}"]

    if not isinstance(contract, dict):
        return ["eidon_drafting_contract_v1_invalid:not_dict"]
    if not isinstance(surfaces_marker, dict):
        return ["eidon_drafting_contract_v1_surface_invalid:not_dict"]

    if str(contract.get("contract_code") or "").strip() != "EIDON_DRAFTING_CONTRACT_V1":
        issues.append("eidon_drafting_contract_v1_contract_code_invalid")
    if str(contract.get("version") or "").strip() != "v1":
        issues.append("eidon_drafting_contract_v1_version_invalid")

    contract_surfaces = contract.get("surfaces") if isinstance(contract.get("surfaces"), dict) else None
    if contract_surfaces is None:
        return issues + ["eidon_drafting_contract_v1_surfaces_invalid:not_dict"]

    tenant_payload = contract_surfaces.get("tenant_runtime")
    if not isinstance(tenant_payload, dict):
        return issues + ["eidon_drafting_contract_v1_missing_surface:tenant_runtime"]

    tenant_marker = surfaces_marker.get("tenant_runtime") if isinstance(surfaces_marker.get("tenant_runtime"), dict) else None
    if tenant_marker is None:
        return issues + ["eidon_drafting_contract_v1_missing_surface_marker:tenant_runtime"]

    required_fields = (
        "allowed_drafting_targets",
        "forbidden_drafting_targets",
        "draft_only_vs_commit_prohibited_boundary",
        "required_human_confirmation_classes",
        "allowed_field_suggestion_scope",
        "forbidden_auto_fill_scope",
        "source_traceability_requirement",
        "ambiguity_escalation_rule",
        "prepare_only_no_authoritative_finalize_rule",
    )

    for field in required_fields:
        if field not in tenant_payload:
            issues.append(f"eidon_drafting_contract_v1_missing_field:tenant_runtime:{field}")
            continue

        val = tenant_payload.get(field)
        if field.endswith("_targets") or field.endswith("_classes") or field.endswith("_scope"):
            if not isinstance(val, list):
                issues.append(f"eidon_drafting_contract_v1_invalid_field_type:tenant_runtime:{field}:list_required")
            elif len(val) == 0:
                issues.append(f"eidon_drafting_contract_v1_invalid_field_empty:tenant_runtime:{field}")
        else:
            if not str(val or "").strip():
                issues.append(f"eidon_drafting_contract_v1_invalid_field_empty:tenant_runtime:{field}")

    ref = str(tenant_marker.get("drafting_contract_ref") or "").strip()
    expected_ref = "EIDON_DRAFTING_CONTRACT_V1:tenant_runtime"
    if ref != expected_ref:
        issues.append(f"eidon_drafting_contract_v1_surface_contract_ref_mismatch:tenant_runtime:{ref or 'EMPTY'}")

    return issues
def check_eidon_template_learning_contract_v1(root: Path) -> list[str]:
    issues: list[str] = []

    ai_dir = root / "app/modules/ai"
    contract_path = ai_dir / "eidon_template_learning_contract_v1.py"
    surface_path = ai_dir / "surface_contract.py"

    if not contract_path.exists():
        issues.append(f"eidon_template_learning_contract_v1_missing_file:{_rel(root, contract_path)}")
    if not surface_path.exists():
        issues.append(f"eidon_template_learning_contract_v1_missing_surface_file:{_rel(root, surface_path)}")
    if issues:
        return issues

    try:
        contract_module = importlib.import_module("app.modules.ai.eidon_template_learning_contract_v1")
        contract: Any = getattr(contract_module, "EIDON_TEMPLATE_LEARNING_CONTRACT_V1", None)
    except Exception as exc:  # noqa: BLE001
        return [f"eidon_template_learning_contract_v1_import_failed:{str(exc)[:200]}"]

    try:
        surface_module = importlib.import_module("app.modules.ai.surface_contract")
        surfaces_marker: Any = getattr(surface_module, "AI_SURFACE_CONTRACT_V1", None)
    except Exception as exc:  # noqa: BLE001
        return [f"eidon_template_learning_contract_v1_surface_import_failed:{str(exc)[:200]}"]

    if not isinstance(contract, dict):
        return ["eidon_template_learning_contract_v1_invalid:not_dict"]
    if not isinstance(surfaces_marker, dict):
        return ["eidon_template_learning_contract_v1_surface_invalid:not_dict"]

    if str(contract.get("contract_code") or "").strip() != "EIDON_TEMPLATE_LEARNING_CONTRACT_V1":
        issues.append("eidon_template_learning_contract_v1_contract_code_invalid")
    if str(contract.get("version") or "").strip() != "v1":
        issues.append("eidon_template_learning_contract_v1_version_invalid")

    contract_surfaces = contract.get("surfaces") if isinstance(contract.get("surfaces"), dict) else None
    if contract_surfaces is None:
        return issues + ["eidon_template_learning_contract_v1_surfaces_invalid:not_dict"]

    tenant_payload = contract_surfaces.get("tenant_runtime")
    if not isinstance(tenant_payload, dict):
        return issues + ["eidon_template_learning_contract_v1_missing_surface:tenant_runtime"]

    tenant_marker = surfaces_marker.get("tenant_runtime") if isinstance(surfaces_marker.get("tenant_runtime"), dict) else None
    if tenant_marker is None:
        return issues + ["eidon_template_learning_contract_v1_missing_surface_marker:tenant_runtime"]

    required_fields = (
        "allowed_global_learning_artifacts",
        "forbidden_learning_artifacts",
        "de_identified_pattern_only_rule",
        "no_raw_tenant_document_sharing_rule",
        "no_cross_tenant_business_data_rule",
        "tenant_local_override_rule",
        "human_confirmed_learning_requirement",
        "quality_scoring_rollback_requirement",
        "versioned_pattern_update_rule",
        "learn_globally_act_locally_rule",
    )

    for field in required_fields:
        if field not in tenant_payload:
            issues.append(f"eidon_template_learning_contract_v1_missing_field:tenant_runtime:{field}")
            continue

        val = tenant_payload.get(field)
        if field.endswith("_artifacts"):
            if not isinstance(val, list):
                issues.append(f"eidon_template_learning_contract_v1_invalid_field_type:tenant_runtime:{field}:list_required")
            elif len(val) == 0:
                issues.append(f"eidon_template_learning_contract_v1_invalid_field_empty:tenant_runtime:{field}")
        else:
            if not str(val or "").strip():
                issues.append(f"eidon_template_learning_contract_v1_invalid_field_empty:tenant_runtime:{field}")

    ref = str(tenant_marker.get("template_learning_contract_ref") or "").strip()
    expected_ref = "EIDON_TEMPLATE_LEARNING_CONTRACT_V1:tenant_runtime"
    if ref != expected_ref:
        issues.append(f"eidon_template_learning_contract_v1_surface_contract_ref_mismatch:tenant_runtime:{ref or 'EMPTY'}")

    return issues
def check_module_factory_coverage_contract(root: Path) -> list[str]:
    issues: list[str] = []

    target_slugs = {x.module_slug for x in module_factory_targets_v1()}
    seen: set[str] = set()
    ready: set[str] = set()

    app_keys = _app_route_keys()

    for item in module_contract_coverage_assessments_v1():
        if item.module_slug in seen:
            issues.append(f"module_factory_coverage_duplicate_module:{item.module_slug}")
            continue
        seen.add(item.module_slug)

        module_dir = root / item.module_dir
        if not module_dir.exists():
            issues.append(f"module_factory_coverage_module_dir_missing:{item.module_slug}:{_rel(root, module_dir)}")

        status = str(item.status or "").strip().upper()
        if status not in _ALLOWED_COVERAGE_STATUS:
            issues.append(f"module_factory_coverage_invalid_status:{item.module_slug}:{status or 'EMPTY'}")
            continue

        plane = str(item.plane_ownership or "").strip().upper()
        if plane not in _ALLOWED_COVERAGE_PLANES:
            issues.append(f"module_factory_coverage_invalid_plane:{item.module_slug}:{plane or 'EMPTY'}")

        marker_exists = (module_dir / "module_contract.py").exists()

        if status == MODULE_COVERAGE_REFERENCE_READY:
            ready.add(item.module_slug)
            if not item.business_runtime:
                issues.append(f"module_factory_coverage_reference_not_business_runtime:{item.module_slug}")
            if not marker_exists:
                issues.append(f"module_factory_coverage_reference_marker_missing:{item.module_slug}")
        else:
            if not str(item.reason or "").strip():
                issues.append(f"module_factory_coverage_not_ready_reason_missing:{item.module_slug}")
            if marker_exists and item.module_slug != "orders":
                issues.append(f"module_factory_coverage_not_ready_marker_present:{item.module_slug}")

        protected = _policy_keys_for_prefixes(tuple(item.protected_route_prefixes or ()))
        if item.protected_route_prefixes and not protected:
            issues.append(f"module_factory_coverage_no_protected_routes:{item.module_slug}")

        if plane in {ROUTE_PLANE_FOUNDATION, ROUTE_PLANE_OPERATIONAL}:
            for method, path in protected:
                owner = resolve_route_plane(method, path)
                if owner != plane:
                    issues.append(f"module_factory_coverage_owner_mismatch:{item.module_slug}:{method}:{path}:{owner or 'EMPTY'}")
        elif plane == "MIXED" and protected:
            owners = {resolve_route_plane(method, path) for method, path in protected}
            owners.discard(None)
            if len(owners) < 2:
                issues.append(f"module_factory_coverage_mixed_not_observed:{item.module_slug}")

        public_routes = [(m, p) for (m, p) in app_keys if _path_matches_prefix(p, tuple(item.public_route_prefixes or ()))]
        if item.public_route_prefixes and not public_routes:
            issues.append(f"module_factory_coverage_no_public_routes:{item.module_slug}")

    for module_slug in sorted(_REQUIRED_COVERAGE_MODULES_V1 - seen):
        issues.append(f"module_factory_coverage_missing_module:{module_slug}")

    if ready != target_slugs:
        issues.append(
            "module_factory_coverage_ready_target_mismatch:"
            + f"ready={','.join(sorted(ready)) or 'EMPTY'}"
            + f":targets={','.join(sorted(target_slugs)) or 'EMPTY'}"
        )

    issues.extend(check_support_plane_decomposition_contract(root))
    issues.extend(check_ai_plane_decomposition_contract(root))
    issues.extend(check_ai_contract_v1(root))
    issues.extend(check_ai_retrieval_contract_v1(root))
    issues.extend(check_eidon_drafting_contract_v1(root))
    issues.extend(check_eidon_template_learning_contract_v1(root))

    return issues
