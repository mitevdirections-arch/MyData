from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import app.core.module_factory_contract as mfc
import app.modules.ai.contract_v1 as ai_contract_v1
import app.modules.ai.surface_contract as ai_contract
import app.modules.ai.retrieval_contract_v1 as ai_retrieval_contract_v1
import app.modules.ai.eidon_drafting_contract_v1 as ai_drafting_contract_v1
import app.modules.ai.eidon_template_learning_contract_v1 as ai_template_learning_contract_v1
import app.modules.orders.module_contract as orders_contract
import app.modules.support.surface_contract as support_contract
from app.core.module_factory_contract import (
    check_ai_contract_v1,
    check_ai_retrieval_contract_v1,
    check_eidon_drafting_contract_v1,
    check_eidon_template_learning_contract_v1,
    check_ai_plane_decomposition_contract,
    check_module_factory_contract,
    check_module_factory_coverage_contract,
    check_support_plane_decomposition_contract,
    module_contract_coverage_report_v1,
)


def test_module_factory_contract_check_passes_for_current_targets() -> None:
    root = Path(__file__).resolve().parents[1]
    issues = check_module_factory_contract(root)
    assert issues == []


def test_module_factory_contract_check_fails_when_marker_missing_field() -> None:
    root = Path(__file__).resolve().parents[1]
    old = orders_contract.MODULE_CONTRACT_V1.pop("module_code")
    try:
        issues = check_module_factory_contract(root)
        assert any(x.startswith("module_factory_marker_missing_field:orders:module_code") for x in issues)
    finally:
        orders_contract.MODULE_CONTRACT_V1["module_code"] = old


def test_module_factory_coverage_contract_check_passes_for_current_assessment() -> None:
    root = Path(__file__).resolve().parents[1]
    issues = check_module_factory_coverage_contract(root)
    assert issues == []


def test_module_factory_coverage_report_has_ready_and_not_ready_buckets() -> None:
    report = module_contract_coverage_report_v1()

    ready = {x["module_slug"] for x in report["reference_ready_modules"]}
    not_ready = {x["module_slug"]: x["reason"] for x in report["not_ready_modules"]}

    assert "orders" in ready
    for slug in (
        "marketplace",
        "support_tenant_runtime",
        "support_superadmin_control",
        "ai_tenant_runtime",
        "ai_superadmin_control",
    ):
        assert slug in not_ready
        assert str(not_ready[slug]).strip() != ""


def test_module_factory_coverage_contract_fails_when_not_ready_reason_missing() -> None:
    root = Path(__file__).resolve().parents[1]
    old = mfc._MODULE_COVERAGE_ASSESSMENTS_V1

    mutated = list(old)
    for idx, item in enumerate(mutated):
        if item.module_slug == "support_tenant_runtime":
            mutated[idx] = replace(item, reason="")
            break

    mfc._MODULE_COVERAGE_ASSESSMENTS_V1 = tuple(mutated)
    try:
        issues = check_module_factory_coverage_contract(root)
        assert any(x.startswith("module_factory_coverage_not_ready_reason_missing:support_tenant_runtime") for x in issues)
    finally:
        mfc._MODULE_COVERAGE_ASSESSMENTS_V1 = old


def test_support_plane_decomposition_contract_passes() -> None:
    root = Path(__file__).resolve().parents[1]
    issues = check_support_plane_decomposition_contract(root)
    assert issues == []


def test_support_plane_decomposition_contract_fails_when_tenant_plane_invalid() -> None:
    root = Path(__file__).resolve().parents[1]
    old = dict(support_contract.SUPPORT_SURFACE_CONTRACT_V1["tenant_runtime"])
    support_contract.SUPPORT_SURFACE_CONTRACT_V1["tenant_runtime"]["plane_ownership"] = "FOUNDATION"
    try:
        issues = check_support_plane_decomposition_contract(root)
        assert any(x.startswith("support_plane_contract_invalid_plane:tenant_runtime") for x in issues)
    finally:
        support_contract.SUPPORT_SURFACE_CONTRACT_V1["tenant_runtime"] = old


def test_ai_plane_decomposition_contract_passes() -> None:
    root = Path(__file__).resolve().parents[1]
    issues = check_ai_plane_decomposition_contract(root)
    assert issues == []


def test_ai_plane_decomposition_contract_fails_when_tenant_plane_invalid() -> None:
    root = Path(__file__).resolve().parents[1]
    old = dict(ai_contract.AI_SURFACE_CONTRACT_V1["tenant_runtime"])
    ai_contract.AI_SURFACE_CONTRACT_V1["tenant_runtime"]["plane_ownership"] = "FOUNDATION"
    try:
        issues = check_ai_plane_decomposition_contract(root)
        assert any(x.startswith("ai_plane_contract_invalid_plane:tenant_runtime") for x in issues)
    finally:
        ai_contract.AI_SURFACE_CONTRACT_V1["tenant_runtime"] = old


def test_ai_contract_v1_check_passes() -> None:
    root = Path(__file__).resolve().parents[1]
    issues = check_ai_contract_v1(root)
    assert issues == []


def test_ai_contract_v1_check_fails_when_truth_rule_disabled() -> None:
    root = Path(__file__).resolve().parents[1]
    old = ai_contract_v1.AI_CONTRACT_V1["ai_does_not_override_system_truth"]
    ai_contract_v1.AI_CONTRACT_V1["ai_does_not_override_system_truth"] = False
    try:
        issues = check_ai_contract_v1(root)
        assert any(x.startswith("ai_contract_v1_truth_override_rule_missing_or_false") for x in issues)
    finally:
        ai_contract_v1.AI_CONTRACT_V1["ai_does_not_override_system_truth"] = old


def test_ai_retrieval_contract_v1_check_passes() -> None:
    root = Path(__file__).resolve().parents[1]
    issues = check_ai_retrieval_contract_v1(root)
    assert issues == []


def test_ai_retrieval_contract_v1_check_fails_when_surface_ref_missing() -> None:
    root = Path(__file__).resolve().parents[1]
    old = dict(ai_contract.AI_SURFACE_CONTRACT_V1["tenant_runtime"])
    ai_contract.AI_SURFACE_CONTRACT_V1["tenant_runtime"].pop("retrieval_contract_ref", None)
    try:
        issues = check_ai_retrieval_contract_v1(root)
        assert any(x.startswith("ai_retrieval_contract_v1_surface_contract_ref_mismatch:tenant_runtime") for x in issues)
    finally:
        ai_contract.AI_SURFACE_CONTRACT_V1["tenant_runtime"] = old


def test_ai_retrieval_contract_v1_check_fails_when_direct_access_rule_missing() -> None:
    root = Path(__file__).resolve().parents[1]
    old = ai_retrieval_contract_v1.AI_RETRIEVAL_CONTRACT_V1["surfaces"]["tenant_runtime"]["cannot_exceed_requesting_user_direct_access_rule"]
    ai_retrieval_contract_v1.AI_RETRIEVAL_CONTRACT_V1["surfaces"]["tenant_runtime"]["cannot_exceed_requesting_user_direct_access_rule"] = ""
    try:
        issues = check_ai_retrieval_contract_v1(root)
        assert any(
            x.startswith(
                "ai_retrieval_contract_v1_invalid_field_empty:tenant_runtime:cannot_exceed_requesting_user_direct_access_rule"
            )
            for x in issues
        )
    finally:
        ai_retrieval_contract_v1.AI_RETRIEVAL_CONTRACT_V1["surfaces"]["tenant_runtime"]["cannot_exceed_requesting_user_direct_access_rule"] = old

def test_eidon_drafting_contract_v1_check_passes() -> None:
    root = Path(__file__).resolve().parents[1]
    issues = check_eidon_drafting_contract_v1(root)
    assert issues == []


def test_eidon_drafting_contract_v1_check_fails_when_surface_ref_missing() -> None:
    root = Path(__file__).resolve().parents[1]
    old = dict(ai_contract.AI_SURFACE_CONTRACT_V1["tenant_runtime"])
    ai_contract.AI_SURFACE_CONTRACT_V1["tenant_runtime"].pop("drafting_contract_ref", None)
    try:
        issues = check_eidon_drafting_contract_v1(root)
        assert any(x.startswith("eidon_drafting_contract_v1_surface_contract_ref_mismatch:tenant_runtime") for x in issues)
    finally:
        ai_contract.AI_SURFACE_CONTRACT_V1["tenant_runtime"] = old


def test_eidon_drafting_contract_v1_check_fails_when_finalize_rule_missing() -> None:
    root = Path(__file__).resolve().parents[1]
    old = ai_drafting_contract_v1.EIDON_DRAFTING_CONTRACT_V1["surfaces"]["tenant_runtime"]["prepare_only_no_authoritative_finalize_rule"]
    ai_drafting_contract_v1.EIDON_DRAFTING_CONTRACT_V1["surfaces"]["tenant_runtime"]["prepare_only_no_authoritative_finalize_rule"] = ""
    try:
        issues = check_eidon_drafting_contract_v1(root)
        assert any(
            x.startswith(
                "eidon_drafting_contract_v1_invalid_field_empty:tenant_runtime:prepare_only_no_authoritative_finalize_rule"
            )
            for x in issues
        )
    finally:
        ai_drafting_contract_v1.EIDON_DRAFTING_CONTRACT_V1["surfaces"]["tenant_runtime"]["prepare_only_no_authoritative_finalize_rule"] = old

def test_eidon_template_learning_contract_v1_check_passes() -> None:
    root = Path(__file__).resolve().parents[1]
    issues = check_eidon_template_learning_contract_v1(root)
    assert issues == []


def test_eidon_template_learning_contract_v1_check_fails_when_surface_ref_missing() -> None:
    root = Path(__file__).resolve().parents[1]
    old = dict(ai_contract.AI_SURFACE_CONTRACT_V1["tenant_runtime"])
    ai_contract.AI_SURFACE_CONTRACT_V1["tenant_runtime"].pop("template_learning_contract_ref", None)
    try:
        issues = check_eidon_template_learning_contract_v1(root)
        assert any(x.startswith("eidon_template_learning_contract_v1_surface_contract_ref_mismatch:tenant_runtime") for x in issues)
    finally:
        ai_contract.AI_SURFACE_CONTRACT_V1["tenant_runtime"] = old


def test_eidon_template_learning_contract_v1_check_fails_when_local_rule_missing() -> None:
    root = Path(__file__).resolve().parents[1]
    old = ai_template_learning_contract_v1.EIDON_TEMPLATE_LEARNING_CONTRACT_V1["surfaces"]["tenant_runtime"]["learn_globally_act_locally_rule"]
    ai_template_learning_contract_v1.EIDON_TEMPLATE_LEARNING_CONTRACT_V1["surfaces"]["tenant_runtime"]["learn_globally_act_locally_rule"] = ""
    try:
        issues = check_eidon_template_learning_contract_v1(root)
        assert any(
            x.startswith(
                "eidon_template_learning_contract_v1_invalid_field_empty:tenant_runtime:learn_globally_act_locally_rule"
            )
            for x in issues
        )
    finally:
        ai_template_learning_contract_v1.EIDON_TEMPLATE_LEARNING_CONTRACT_V1["surfaces"]["tenant_runtime"]["learn_globally_act_locally_rule"] = old