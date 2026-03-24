from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.settings import Settings, get_settings
from app.core.startup_security import collect_startup_security_issues
import app.core.policy_matrix as pm
import app.core.route_ownership as roc
import app.modules.ai.retrieval_contract_v1 as ai_retrieval_contract_v1
import app.modules.ai.eidon_drafting_contract_v1 as ai_drafting_contract_v1
import app.modules.ai.eidon_template_learning_contract_v1 as ai_template_learning_contract_v1
from app.main import app
from scripts.prod_gate import (
    check_ai_contract_v1,
    check_ai_retrieval_contract_v1,
    check_eidon_drafting_contract_v1,
    check_eidon_template_learning_contract_v1,
    check_ai_plane_decomposition_contract,
    check_authz_contract,
    check_bug_finder_smoke,
    check_code_default_contract,
    check_migrations_smoke,
    check_module_factory_contract,
    check_module_factory_coverage_contract,
    check_no_external_project_refs,
    check_no_hardcoded_code_secrets,
    check_route_ownership_contract,
    check_support_plane_decomposition_contract,
    check_workspace_hygiene,
)
def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_dev_token_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_DEV_TOKEN_ENABLED", "false")
    get_settings.cache_clear()
    try:
        client = TestClient(app)
        r = client.post('/auth/dev-token', json={"sub": "tester@local", "roles": ["SUPERADMIN"], "tenant_id": "t1"})
        assert r.status_code == 404
    finally:
        get_settings.cache_clear()


def test_dev_token_requires_explicit_claims(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_DEV_TOKEN_ENABLED", "true")
    get_settings.cache_clear()
    try:
        client = TestClient(app)
        r = client.post('/auth/dev-token', json={})
        assert r.status_code == 400
        assert r.json().get("detail") == "sub_required"
    finally:
        get_settings.cache_clear()


def test_prod_guardrails_detect_insecure_defaults() -> None:
    s = Settings(
        app_env="prod",
        auth_dev_token_enabled=True,
        jwt_secret="change-me-dev-secret",
        storage_grant_secret="change-me-storage-grant-secret",
        guard_bot_signing_master_secret="change-me-guard-bot-signing-master-secret",
        superadmin_step_up_enabled=False,
        superadmin_step_up_totp_secret="",
        guard_bot_signature_required=False,
        cors_allow_origins="*",
        jwt_secret_rotated_at=None,
        storage_grant_secret_rotated_at=None,
        guard_bot_signing_master_secret_rotated_at=None,
        security_alerts_delivery_mode="WEBHOOK",
        security_alert_webhook_url="",
    )
    issues = collect_startup_security_issues(s)
    assert "auth_dev_token_enabled_must_be_false_in_prod" in issues
    assert "jwt_secret_default_in_prod" in issues
    assert "storage_grant_secret_default_in_prod" in issues
    assert "guard_bot_signing_master_secret_default_in_prod" in issues
    assert "superadmin_step_up_must_be_enabled_in_prod" in issues
    assert "superadmin_step_up_totp_secret_missing_in_prod" in issues
    assert "guard_bot_signature_required_must_be_true_in_prod" in issues
    assert "cors_allow_origins_wildcard_forbidden_in_prod" in issues
    assert "jwt_secret_rotated_at_missing_or_invalid_in_prod" in issues
    assert "storage_grant_secret_rotated_at_missing_or_invalid_in_prod" in issues
    assert "guard_bot_signing_master_secret_rotated_at_missing_or_invalid_in_prod" in issues
    assert "security_alert_webhook_url_required_for_webhook_mode_in_prod" in issues


def test_prod_guardrails_pass_for_hardened_profile() -> None:
    now = _iso_now()
    s = Settings(
        app_env="prod",
        auth_dev_token_enabled=False,
        jwt_secret="x" * 64,
        storage_grant_secret="y" * 64,
        guard_bot_signing_master_secret="z" * 64,
        superadmin_step_up_enabled=True,
        superadmin_step_up_totp_secret="JBSWY3DPEHPK3PXP",
        guard_bot_signature_required=True,
        cors_allow_origins="https://app.mydata.local",
        jwt_secret_rotated_at=now,
        storage_grant_secret_rotated_at=now,
        guard_bot_signing_master_secret_rotated_at=now,
        security_alerts_delivery_mode="LOG_ONLY",
    )
    issues = collect_startup_security_issues(s)
    assert issues == []


def test_code_default_contract_secure() -> None:
    assert check_code_default_contract() == []

def test_prod_guardrails_webhook_requires_https() -> None:
    now = _iso_now()
    s = Settings(
        app_env="prod",
        auth_dev_token_enabled=False,
        jwt_secret="x" * 64,
        storage_grant_secret="y" * 64,
        guard_bot_signing_master_secret="z" * 64,
        superadmin_step_up_enabled=True,
        superadmin_step_up_totp_secret="JBSWY3DPEHPK3PXP",
        guard_bot_signature_required=True,
        cors_allow_origins="https://app.mydata.local",
        jwt_secret_rotated_at=now,
        storage_grant_secret_rotated_at=now,
        guard_bot_signing_master_secret_rotated_at=now,
        security_alerts_delivery_mode="WEBHOOK",
        security_alert_webhook_url="http://alerts.internal.local/hook",
    )
    issues = collect_startup_security_issues(s)
    assert "security_alert_webhook_url_must_be_https_in_prod" in issues



def test_bug_scan_disabled_no_errors() -> None:
    root = Path(__file__).resolve().parents[1]
    issues = check_bug_finder_smoke(root, environ={})
    assert issues == []


def test_bug_scan_enabled_requires_api_base() -> None:
    root = Path(__file__).resolve().parents[1]
    env = {"PROD_GATE_BUG_SCAN_ENABLED": "true"}
    issues = check_bug_finder_smoke(root, environ=env)
    assert "prod_gate_bug_scan_api_base_required_when_enabled" in issues


def test_bug_scan_enabled_reports_suspects() -> None:
    root = Path(__file__).resolve().parents[1]
    env = {
        "PROD_GATE_BUG_SCAN_ENABLED": "true",
        "PROD_GATE_BUG_SCAN_API_BASE": "http://127.0.0.1:8100",
    }

    def fake_runner(_cmd: list[str]) -> tuple[int, str, str]:
        return 1, '{"ok": true, "summary": {"suspect_endpoints": 2}}', ""

    issues = check_bug_finder_smoke(root, environ=env, run_cmd=fake_runner)
    assert any(x.startswith("prod_gate_bug_scan_suspects_found") for x in issues)


def test_bug_scan_enabled_success_no_issues() -> None:
    root = Path(__file__).resolve().parents[1]
    env = {
        "PROD_GATE_BUG_SCAN_ENABLED": "true",
        "PROD_GATE_BUG_SCAN_API_BASE": "http://127.0.0.1:8100",
    }

    def fake_runner(_cmd: list[str]) -> tuple[int, str, str]:
        return 0, '{"ok": true}', ""

    issues = check_bug_finder_smoke(root, environ=env, run_cmd=fake_runner)
    assert issues == []


def test_no_hardcoded_code_secrets_detects_literal_secret(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "x.py").write_text('jwt_secret = "hardcodedsecret123"\n', encoding="utf-8")

    issues = check_no_hardcoded_code_secrets(tmp_path)
    assert any(x.startswith("hardcoded_secret_assignment:app/x.py:1") for x in issues)


def test_no_hardcoded_code_secrets_ignores_change_me_placeholder(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "x.py").write_text('jwt_secret = "change-me-dev-secret"\n', encoding="utf-8")

    issues = check_no_hardcoded_code_secrets(tmp_path)
    assert issues == []


def test_no_hardcoded_code_secrets_allows_official_vies_public_urls(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "x.py").write_text(
        'entity_verification_vies_wsdl_url = "https://ec.europa.eu/taxation_customs/vies/checkVatService.wsdl"\n'
        'entity_verification_vies_service_url = "https://ec.europa.eu/taxation_customs/vies/services/checkVatService"\n',
        encoding="utf-8",
    )

    issues = check_no_hardcoded_code_secrets(tmp_path)
    assert issues == []


def test_no_hardcoded_code_secrets_blocks_non_official_vies_public_url(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "x.py").write_text(
        'entity_verification_vies_service_url = "https://example.invalid/vies/service"\n',
        encoding="utf-8",
    )

    issues = check_no_hardcoded_code_secrets(tmp_path)
    assert any(x.startswith("non_official_public_service_url_assignment:app/x.py:1") for x in issues)


def test_external_project_refs_clean_tmp_path(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("Standalone MyData docs only.\n", encoding="utf-8")
    assert check_no_external_project_refs(tmp_path) == []


def test_external_project_refs_detect_foreign_workspace_path(tmp_path: Path) -> None:
    # Keep runtime semantics while avoiding repository-level absolute-path literals.
    path = "Use " + "C:" + "/Users/mitev/Desktop/ExternalLookup/bin/crdb-start-only.ps1 for startup\n"
    (tmp_path / "RUNBOOK.md").write_text(path, encoding="utf-8")
    issues = check_no_external_project_refs(tmp_path)
    assert any(x.startswith("external_project_reference_foreign_workspace:RUNBOOK.md:1") for x in issues)


def test_workspace_hygiene_clean_tmp_path(tmp_path: Path) -> None:
    assert check_workspace_hygiene(tmp_path) == []


def test_workspace_hygiene_detects_noise(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("DATABASE_URL=\n", encoding="utf-8")
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / "mydata_api.egg-info").mkdir()
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "a.json").write_text("{}", encoding="utf-8")
    (tmp_path / "app" / "__pycache__").mkdir(parents=True)
    (tmp_path / "app" / "__pycache__" / "x.cpython-313.pyc").write_bytes(b"\x00")

    issues = check_workspace_hygiene(tmp_path)

    assert any(x.startswith("workspace_hygiene_forbidden_path:.env") for x in issues)
    assert any(x.startswith("workspace_hygiene_forbidden_path:.pytest_cache") for x in issues)
    assert any(x.startswith("workspace_hygiene_forbidden_path:mydata_api.egg-info") for x in issues)
    assert any(x.startswith("workspace_hygiene_pycache_dirs:") for x in issues)
    assert any(x.startswith("workspace_hygiene_pyc_files:") for x in issues)
    assert any(x.startswith("workspace_hygiene_artifacts_json:") for x in issues)



def test_migrations_smoke_disabled_no_errors() -> None:
    root = Path(__file__).resolve().parents[1]
    issues = check_migrations_smoke(root, environ={})
    assert issues == []


def test_migrations_smoke_enabled_requires_database_url() -> None:
    root = Path(__file__).resolve().parents[1]
    env = {"PROD_GATE_MIGRATIONS_SMOKE_ENABLED": "true"}
    issues = check_migrations_smoke(root, environ=env)
    assert "prod_gate_migrations_smoke_database_url_required_when_enabled" in issues


def test_migrations_smoke_enabled_success_no_issues() -> None:
    root = Path(__file__).resolve().parents[1]
    env = {
        "PROD_GATE_MIGRATIONS_SMOKE_ENABLED": "true",
        "PROD_GATE_MIGRATIONS_SMOKE_DATABASE_URL": "postgresql://user:pass@127.0.0.1:26257/mydata",
    }

    def fake_runner(_cmd: list[str]) -> tuple[int, str, str]:
        return 0, '{"ok": true}', ""

    issues = check_migrations_smoke(root, environ=env, run_cmd=fake_runner)
    assert issues == []


def test_migrations_smoke_enabled_reports_failure() -> None:
    root = Path(__file__).resolve().parents[1]
    env = {
        "PROD_GATE_MIGRATIONS_SMOKE_ENABLED": "true",
        "PROD_GATE_MIGRATIONS_SMOKE_DATABASE_URL": "postgresql://user:pass@127.0.0.1:26257/mydata",
    }

    def fake_runner(_cmd: list[str]) -> tuple[int, str, str]:
        return 1, '{"ok": false, "error": "upgrade_failed"}', ""

    issues = check_migrations_smoke(root, environ=env, run_cmd=fake_runner)
    assert any(x.startswith("prod_gate_migrations_smoke_failed") for x in issues)


def test_authz_contract_check_passes_for_current_routes() -> None:
    root = Path(__file__).resolve().parents[1]
    issues = check_authz_contract(root)
    assert issues == []


def test_authz_contract_check_fails_when_mode_missing() -> None:
    root = Path(__file__).resolve().parents[1]
    key = ("GET", "/iam/admin/rls-context")
    old = pm.ROUTE_POLICY[key]
    pm.ROUTE_POLICY[key] = pm.RoutePolicy(
        permission_code=old.permission_code,
        step_up=old.step_up,
        authz_source=old.authz_source,
        authz_mode=None,
    )
    try:
        issues = check_authz_contract(root)
        assert any(x.startswith("authz_contract_missing_or_invalid_mode:") for x in issues)
    finally:
        pm.ROUTE_POLICY[key] = old



def test_route_ownership_contract_check_passes_for_current_routes() -> None:
    root = Path(__file__).resolve().parents[1]
    issues = check_route_ownership_contract(root)
    assert issues == []


def test_route_ownership_contract_check_fails_when_mapping_missing() -> None:
    root = Path(__file__).resolve().parents[1]
    key = ("GET", "/orders")
    old = roc.ROUTE_PLANE_OWNERSHIP.pop(key)
    try:
        issues = check_route_ownership_contract(root)
        assert any(x.startswith("route_ownership_contract_drift_missing:") for x in issues)
    finally:
        roc.ROUTE_PLANE_OWNERSHIP[key] = old

def test_module_factory_contract_check_passes_for_current_modules() -> None:
    root = Path(__file__).resolve().parents[1]
    issues = check_module_factory_contract(root)
    assert issues == []


def test_module_factory_contract_check_fails_when_required_gate_missing() -> None:
    root = Path(__file__).resolve().parents[1]
    import app.modules.orders.module_contract as orders_contract

    gates = list(orders_contract.MODULE_CONTRACT_V1.get("minimum_gate_expectations") or [])
    old = list(gates)
    if "module_factory_contract" in gates:
        gates.remove("module_factory_contract")
    orders_contract.MODULE_CONTRACT_V1["minimum_gate_expectations"] = gates

    try:
        issues = check_module_factory_contract(root)
        assert any(x.startswith("module_factory_marker_missing_gate:orders:module_factory_contract") for x in issues)
    finally:
        orders_contract.MODULE_CONTRACT_V1["minimum_gate_expectations"] = old

def test_module_factory_coverage_contract_check_passes_for_current_modules() -> None:
    root = Path(__file__).resolve().parents[1]
    issues = check_module_factory_coverage_contract(root)
    assert issues == []


def test_module_factory_coverage_contract_check_fails_when_required_module_missing() -> None:
    root = Path(__file__).resolve().parents[1]
    import app.core.module_factory_contract as mfc

    old = mfc._MODULE_COVERAGE_ASSESSMENTS_V1
    mfc._MODULE_COVERAGE_ASSESSMENTS_V1 = tuple(x for x in old if x.module_slug != "ai_superadmin_control")

    try:
        issues = check_module_factory_coverage_contract(root)
        assert any(x.startswith("module_factory_coverage_missing_module:ai_superadmin_control") for x in issues)
    finally:
        mfc._MODULE_COVERAGE_ASSESSMENTS_V1 = old

def test_support_plane_decomposition_contract_check_passes() -> None:
    root = Path(__file__).resolve().parents[1]
    issues = check_support_plane_decomposition_contract(root)
    assert issues == []


def test_support_plane_decomposition_contract_check_fails_when_surface_missing() -> None:
    root = Path(__file__).resolve().parents[1]
    import app.modules.support.surface_contract as support_contract

    old = dict(support_contract.SUPPORT_SURFACE_CONTRACT_V1)
    support_contract.SUPPORT_SURFACE_CONTRACT_V1.pop("superadmin_control", None)

    try:
        issues = check_support_plane_decomposition_contract(root)
        assert any(x.startswith("support_plane_contract_missing_surface:superadmin_control") for x in issues)
    finally:
        support_contract.SUPPORT_SURFACE_CONTRACT_V1 = old

def test_ai_plane_decomposition_contract_check_passes() -> None:
    root = Path(__file__).resolve().parents[1]
    issues = check_ai_plane_decomposition_contract(root)
    assert issues == []


def test_ai_plane_decomposition_contract_check_fails_when_surface_missing() -> None:
    root = Path(__file__).resolve().parents[1]
    import app.modules.ai.surface_contract as ai_contract

    old = dict(ai_contract.AI_SURFACE_CONTRACT_V1)
    ai_contract.AI_SURFACE_CONTRACT_V1.pop("superadmin_control", None)

    try:
        issues = check_ai_plane_decomposition_contract(root)
        assert any(x.startswith("ai_plane_contract_missing_surface:superadmin_control") for x in issues)
    finally:
        ai_contract.AI_SURFACE_CONTRACT_V1 = old

def test_ai_contract_v1_check_passes() -> None:
    root = Path(__file__).resolve().parents[1]
    issues = check_ai_contract_v1(root)
    assert issues == []


def test_ai_contract_v1_check_fails_when_contract_ref_missing() -> None:
    root = Path(__file__).resolve().parents[1]
    import app.modules.ai.surface_contract as ai_contract

    old = dict(ai_contract.AI_SURFACE_CONTRACT_V1["tenant_runtime"])
    ai_contract.AI_SURFACE_CONTRACT_V1["tenant_runtime"].pop("contract_ref", None)

    try:
        issues = check_ai_contract_v1(root)
        assert any(x.startswith("ai_contract_v1_surface_contract_ref_mismatch:tenant_runtime") for x in issues)
    finally:
        ai_contract.AI_SURFACE_CONTRACT_V1["tenant_runtime"] = old

def test_ai_retrieval_contract_v1_check_passes() -> None:
    root = Path(__file__).resolve().parents[1]
    issues = check_ai_retrieval_contract_v1(root)
    assert issues == []


def test_ai_retrieval_contract_v1_check_fails_when_surface_ref_missing() -> None:
    root = Path(__file__).resolve().parents[1]
    import app.modules.ai.surface_contract as ai_contract

    old = dict(ai_contract.AI_SURFACE_CONTRACT_V1["tenant_runtime"])
    ai_contract.AI_SURFACE_CONTRACT_V1["tenant_runtime"].pop("retrieval_contract_ref", None)

    try:
        issues = check_ai_retrieval_contract_v1(root)
        assert any(x.startswith("ai_retrieval_contract_v1_surface_contract_ref_mismatch:tenant_runtime") for x in issues)
    finally:
        ai_contract.AI_SURFACE_CONTRACT_V1["tenant_runtime"] = old


def test_ai_retrieval_contract_v1_check_fails_when_no_cross_tenant_rule_missing() -> None:
    root = Path(__file__).resolve().parents[1]
    old = ai_retrieval_contract_v1.AI_RETRIEVAL_CONTRACT_V1["surfaces"]["tenant_runtime"]["no_cross_tenant_rule"]
    ai_retrieval_contract_v1.AI_RETRIEVAL_CONTRACT_V1["surfaces"]["tenant_runtime"]["no_cross_tenant_rule"] = ""

    try:
        issues = check_ai_retrieval_contract_v1(root)
        assert any(
            x.startswith("ai_retrieval_contract_v1_invalid_field_empty:tenant_runtime:no_cross_tenant_rule")
            for x in issues
        )
    finally:
        ai_retrieval_contract_v1.AI_RETRIEVAL_CONTRACT_V1["surfaces"]["tenant_runtime"]["no_cross_tenant_rule"] = old

def test_eidon_drafting_contract_v1_check_passes() -> None:
    root = Path(__file__).resolve().parents[1]
    issues = check_eidon_drafting_contract_v1(root)
    assert issues == []


def test_eidon_drafting_contract_v1_check_fails_when_surface_ref_missing() -> None:
    root = Path(__file__).resolve().parents[1]
    import app.modules.ai.surface_contract as ai_contract

    old = dict(ai_contract.AI_SURFACE_CONTRACT_V1["tenant_runtime"])
    ai_contract.AI_SURFACE_CONTRACT_V1["tenant_runtime"].pop("drafting_contract_ref", None)

    try:
        issues = check_eidon_drafting_contract_v1(root)
        assert any(x.startswith("eidon_drafting_contract_v1_surface_contract_ref_mismatch:tenant_runtime") for x in issues)
    finally:
        ai_contract.AI_SURFACE_CONTRACT_V1["tenant_runtime"] = old


def test_eidon_drafting_contract_v1_check_fails_when_ambiguity_rule_missing() -> None:
    root = Path(__file__).resolve().parents[1]
    old = ai_drafting_contract_v1.EIDON_DRAFTING_CONTRACT_V1["surfaces"]["tenant_runtime"]["ambiguity_escalation_rule"]
    ai_drafting_contract_v1.EIDON_DRAFTING_CONTRACT_V1["surfaces"]["tenant_runtime"]["ambiguity_escalation_rule"] = ""

    try:
        issues = check_eidon_drafting_contract_v1(root)
        assert any(
            x.startswith("eidon_drafting_contract_v1_invalid_field_empty:tenant_runtime:ambiguity_escalation_rule")
            for x in issues
        )
    finally:
        ai_drafting_contract_v1.EIDON_DRAFTING_CONTRACT_V1["surfaces"]["tenant_runtime"]["ambiguity_escalation_rule"] = old

def test_eidon_template_learning_contract_v1_check_passes() -> None:
    root = Path(__file__).resolve().parents[1]
    issues = check_eidon_template_learning_contract_v1(root)
    assert issues == []


def test_eidon_template_learning_contract_v1_check_fails_when_surface_ref_missing() -> None:
    root = Path(__file__).resolve().parents[1]
    import app.modules.ai.surface_contract as ai_contract

    old = dict(ai_contract.AI_SURFACE_CONTRACT_V1["tenant_runtime"])
    ai_contract.AI_SURFACE_CONTRACT_V1["tenant_runtime"].pop("template_learning_contract_ref", None)

    try:
        issues = check_eidon_template_learning_contract_v1(root)
        assert any(x.startswith("eidon_template_learning_contract_v1_surface_contract_ref_mismatch:tenant_runtime") for x in issues)
    finally:
        ai_contract.AI_SURFACE_CONTRACT_V1["tenant_runtime"] = old


def test_eidon_template_learning_contract_v1_check_fails_when_human_confirm_required_missing() -> None:
    root = Path(__file__).resolve().parents[1]
    old = ai_template_learning_contract_v1.EIDON_TEMPLATE_LEARNING_CONTRACT_V1["surfaces"]["tenant_runtime"]["human_confirmed_learning_requirement"]
    ai_template_learning_contract_v1.EIDON_TEMPLATE_LEARNING_CONTRACT_V1["surfaces"]["tenant_runtime"]["human_confirmed_learning_requirement"] = ""

    try:
        issues = check_eidon_template_learning_contract_v1(root)
        assert any(
            x.startswith("eidon_template_learning_contract_v1_invalid_field_empty:tenant_runtime:human_confirmed_learning_requirement")
            for x in issues
        )
    finally:
        ai_template_learning_contract_v1.EIDON_TEMPLATE_LEARNING_CONTRACT_V1["surfaces"]["tenant_runtime"]["human_confirmed_learning_requirement"] = old
