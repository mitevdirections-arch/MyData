from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import subprocess
import sys
sys.dont_write_bytecode = True
from typing import Callable, Mapping

from app.core.settings import Settings
from app.core.startup_security import collect_startup_security_issues
from app.core.module_factory_contract import check_module_factory_contract, check_module_factory_coverage_contract, check_support_plane_decomposition_contract, check_ai_plane_decomposition_contract, check_ai_contract_v1, check_ai_retrieval_contract_v1, check_eidon_drafting_contract_v1, check_eidon_template_learning_contract_v1


REQUIRED_ENV_KEYS = {
    "AUTH_DEV_TOKEN_ENABLED",
    "API_DOCS_ENABLED_IN_PROD",
    "CORS_ALLOW_ORIGINS",
    "CORS_ALLOW_CREDENTIALS",
    "SECURITY_ENFORCE_PROD_CHECKS",
    "SECRET_ROTATION_MAX_AGE_DAYS",
    "JWT_SECRET_ROTATED_AT",
    "JWT_SECRET_VERSION",
    "STORAGE_GRANT_SECRET_VERSION",
    "GUARD_BOT_SIGNING_MASTER_SECRET_VERSION",
    "STORAGE_GRANT_SECRET_ROTATED_AT",
    "GUARD_BOT_SIGNING_MASTER_SECRET_ROTATED_AT",
    "GUARD_BOT_CREDENTIAL_AUTO_ROTATE_DAYS",
    "GUARD_BOT_CREDENTIAL_ROTATION_BATCH_SIZE",
    "SECURITY_KEY_ROTATION_WORKER_ENABLED",
    "SECURITY_ALERTS_ENABLED",
    "SECURITY_ALERTS_DELIVERY_MODE",
    "SECURITY_ALERT_MIN_SEVERITY",
    "SUPERADMIN_STEP_UP_ENABLED",
    "SUPERADMIN_STEP_UP_TOTP_SECRET",
    "SUPERADMIN_STEP_UP_PERIOD_SECONDS",
    "SUPERADMIN_STEP_UP_WINDOW_STEPS",
    "CORE_ENTITLEMENT_CACHE_TTL_SECONDS",
    "CORE_ENTITLEMENT_CACHE_MAX_ENTRIES",
    "PROD_GATE_BUG_SCAN_ENABLED",
    "PROD_GATE_MIGRATIONS_SMOKE_ENABLED",
    "AUTHZ_TENANT_DB_FAST_PATH_ENABLED",
    "AUTHZ_TENANT_DB_FAST_PATH_SHADOW_COMPARE_ENABLED",
    "AUTHZ_TENANT_DB_FAST_PATH_SOURCE_VERSION",
}

TEXT_EXTS = {".py", ".toml", ".ini", ".md", ".yml", ".yaml", ".txt", ".env", ".example"}
SKIP_DIRS = {".venv", ".pytest_cache", "__pycache__", "mydata_api.egg-info"}
SAFE_SECRET_MARKERS = {"change-me", "example", "<", ">"}


ASSIGNMENT_SECRET_RE = re.compile(
    r"(?i)\b(jwt_secret|storage_grant_secret|guard_bot_signing_master_secret|storage_secret_key|s3_secret_key)\s*=\s*[\"']([^\"']{8,})[\"']"
)
INLINE_DSN_WITH_CREDS_RE = re.compile(
    r"(?i)\b(cockroachdb\+psycopg|cockroachdb|postgresql|postgres|mysql|mariadb)://[^/\s:\"']+:[^@\s\"']+@"
)

EXTERNAL_EIDATA_PATH_RE = re.compile(
    r"(?i)(?:[a-z]:[\\/][^\r\n]*?[\\/]eidata[\\/]|[\\/]eidata[\\/])"
)


def iter_files(root: Path):
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        if any(x in SKIP_DIRS for x in p.parts):
            continue
        if p.name in {".env", ".env.example", "alembic.ini"}:
            yield p
            continue
        if p.suffix.lower() in TEXT_EXTS:
            yield p


def check_no_bom(root: Path) -> list[str]:
    bad: list[str] = []
    for p in iter_files(root):
        try:
            raw = p.read_bytes()
        except Exception:
            continue
        if raw.startswith(b"\xef\xbb\xbf"):
            bad.append(str(p))
    return bad


def _is_safe_secret_value(v: str) -> bool:
    raw = str(v or "").strip().lower()
    if not raw:
        return True
    return any(marker in raw for marker in SAFE_SECRET_MARKERS)


def check_no_hardcoded_code_secrets(root: Path) -> list[str]:
    issues: list[str] = []
    scan_roots = [root / "app", root / "scripts"]

    for base in scan_roots:
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if any(x in SKIP_DIRS for x in p.parts):
                continue
            rel = p.relative_to(root).as_posix()
            for ln, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
                s = line.strip()
                if not s or s.startswith("#"):
                    continue

                m = ASSIGNMENT_SECRET_RE.search(s)
                if m:
                    secret_value = m.group(2)
                    if not _is_safe_secret_value(secret_value):
                        issues.append(f"hardcoded_secret_assignment:{rel}:{ln}")
                        if len(issues) >= 50:
                            return issues + ["hardcoded_secret_assignment:truncated"]

                if INLINE_DSN_WITH_CREDS_RE.search(s):
                    issues.append(f"hardcoded_dsn_credentials:{rel}:{ln}")
                    if len(issues) >= 50:
                        return issues + ["hardcoded_dsn_credentials:truncated"]

    return issues


def check_no_external_project_refs(root: Path) -> list[str]:
    issues: list[str] = []
    for p in iter_files(root):
        rel = _rel(root, p)
        if rel.startswith('.venv/'):
            continue
        try:
            lines = p.read_text(encoding='utf-8', errors='ignore').splitlines()
        except Exception:  # noqa: BLE001
            continue

        for ln, line in enumerate(lines, start=1):
            if EXTERNAL_EIDATA_PATH_RE.search(line):
                issues.append(f"external_project_reference_eidata:{rel}:{ln}")
                if len(issues) >= 50:
                    return issues + ["external_project_reference_eidata:truncated"]

    return issues


def check_env_example(path: Path) -> list[str]:
    if not path.exists():
        return [".env.example_not_found"]

    keys: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k = s.split("=", 1)[0].strip()
        if k:
            keys.add(k)

    missing = sorted(REQUIRED_ENV_KEYS - keys)
    return [f".env.example_missing:{x}" for x in missing]



def _rel(root: Path, p: Path) -> str:
    try:
        return p.relative_to(root).as_posix()
    except Exception:  # noqa: BLE001
        return str(p)


def _sample_paths(root: Path, items: list[Path], *, max_items: int = 5) -> str:
    if not items:
        return ""
    return ",".join(_rel(root, p) for p in items[:max_items])


def check_workspace_hygiene(root: Path) -> list[str]:
    issues: list[str] = []

    forbidden_paths = [
        root / ".env",
        root / ".pytest_cache",
        root / "mydata_api.egg-info",
    ]
    for p in forbidden_paths:
        if p.exists():
            issues.append(f"workspace_hygiene_forbidden_path:{_rel(root, p)}")

    pycache_dirs = [p for p in root.rglob("__pycache__") if p.is_dir() and ".venv" not in p.parts]
    pyc_files = [p for p in root.rglob("*.pyc") if ".venv" not in p.parts]

    artifacts_json: list[Path] = []
    artifacts_dir = root / "artifacts"
    if artifacts_dir.exists() and artifacts_dir.is_dir():
        artifacts_json = [p for p in artifacts_dir.glob("*.json") if p.is_file()]

    if pycache_dirs:
        sample = _sample_paths(root, pycache_dirs)
        issues.append(
            f"workspace_hygiene_pycache_dirs:{len(pycache_dirs)}" + (f":{sample}" if sample else "")
        )
    if pyc_files:
        sample = _sample_paths(root, pyc_files)
        issues.append(
            f"workspace_hygiene_pyc_files:{len(pyc_files)}" + (f":{sample}" if sample else "")
        )
    if artifacts_json:
        sample = _sample_paths(root, artifacts_json)
        issues.append(
            f"workspace_hygiene_artifacts_json:{len(artifacts_json)}" + (f":{sample}" if sample else "")
        )

    return issues

def check_code_default_contract() -> list[str]:
    fields = Settings.model_fields
    issues: list[str] = []

    def default_of(name: str):
        return fields[name].default

    if bool(default_of("auth_dev_token_enabled")):
        issues.append("code_default_auth_dev_token_enabled_must_be_false")

    if str(default_of("jwt_secret") or "").strip():
        issues.append("code_default_jwt_secret_must_be_empty")
    if str(default_of("storage_grant_secret") or "").strip():
        issues.append("code_default_storage_grant_secret_must_be_empty")
    if str(default_of("guard_bot_signing_master_secret") or "").strip():
        issues.append("code_default_guard_bot_signing_master_secret_must_be_empty")

    cors = str(default_of("cors_allow_origins") or "").lower()
    if "localhost" in cors or "127.0.0.1" in cors:
        issues.append("code_default_cors_allow_origins_contains_localhost")

    for key in ("storage_endpoint", "storage_access_key", "storage_secret_key"):
        if str(default_of(key) or "").strip():
            issues.append(f"code_default_{key}_must_be_empty")

    return issues


def check_prod_profile_contract() -> list[str]:
    now = datetime.now(timezone.utc).isoformat()
    hardened = Settings(
        app_env="prod",
        auth_dev_token_enabled=False,
        jwt_secret="x" * 64,
        storage_grant_secret="y" * 64,
        guard_bot_signing_master_secret="z" * 64,
        guard_bot_signature_required=True,
        cors_allow_origins="https://app.mydata.local",
        jwt_secret_rotated_at=now,
        storage_grant_secret_rotated_at=now,
        guard_bot_signing_master_secret_rotated_at=now,
        superadmin_step_up_enabled=True,
        superadmin_step_up_totp_secret="JBSWY3DPEHPK3PXP",
        superadmin_step_up_period_seconds=30,
        superadmin_step_up_window_steps=1,
        security_alerts_delivery_mode="LOG_ONLY",
    )
    issues = collect_startup_security_issues(hardened)
    if issues:
        return ["prod_profile_contract_failed:" + ";".join(issues)]
    return []


def _truthy(v: str | None) -> bool:
    raw = str(v or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _safe_int(v: str | None, default: int, lo: int, hi: int) -> int:
    try:
        n = int(str(v or "").strip())
    except Exception:  # noqa: BLE001
        return default
    return max(lo, min(n, hi))


def _safe_float(v: str | None, default: float, lo: float, hi: float) -> float:
    try:
        n = float(str(v or "").strip())
    except Exception:  # noqa: BLE001
        return default
    return max(lo, min(n, hi))


def _run_cmd_real(cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return int(proc.returncode), str(proc.stdout or ""), str(proc.stderr or "")


def _flat_detail(out: str, err: str, *, max_len: int = 500) -> str:
    raw = (out.strip() or err.strip()).replace("\r", " ").replace("\n", " | ").strip()
    if len(raw) <= max_len:
        return raw
    return raw[:max_len] + "..."


def check_bug_finder_smoke(
    root: Path,
    *,
    environ: Mapping[str, str] | None = None,
    run_cmd: Callable[[list[str]], tuple[int, str, str]] | None = None,
) -> list[str]:
    env = environ or os.environ
    if not _truthy(env.get("PROD_GATE_BUG_SCAN_ENABLED")):
        return []

    api_base = str(env.get("PROD_GATE_BUG_SCAN_API_BASE") or "").strip()
    if not api_base:
        return ["prod_gate_bug_scan_api_base_required_when_enabled"]

    bug_finder = root / "scripts" / "bug_finder.py"
    if not bug_finder.exists():
        return ["prod_gate_bug_scan_script_missing"]

    cmd = [
        sys.executable,
        str(bug_finder),
        "--api-base",
        api_base,
        "--iterations",
        str(_safe_int(env.get("PROD_GATE_BUG_SCAN_ITERATIONS"), 2, 1, 50)),
        "--workers",
        str(_safe_int(env.get("PROD_GATE_BUG_SCAN_WORKERS"), 8, 1, 128)),
        "--timeout-seconds",
        str(_safe_float(env.get("PROD_GATE_BUG_SCAN_TIMEOUT_SECONDS"), 5.0, 0.5, 120.0)),
        "--slow-ms-threshold",
        str(_safe_float(env.get("PROD_GATE_BUG_SCAN_SLOW_MS"), 1500.0, 1.0, 60000.0)),
        "--max-endpoints",
        str(_safe_int(env.get("PROD_GATE_BUG_SCAN_MAX_ENDPOINTS"), 200, 1, 5000)),
    ]

    token = str(env.get("PROD_GATE_BUG_SCAN_TOKEN") or "").strip()
    if token:
        cmd.extend(["--token", token])

    include_prefixes = str(env.get("PROD_GATE_BUG_SCAN_INCLUDE_PREFIXES") or "").strip()
    if include_prefixes:
        cmd.extend(["--include-prefixes", include_prefixes])

    exclude_prefixes = str(env.get("PROD_GATE_BUG_SCAN_EXCLUDE_PREFIXES") or "").strip()
    if exclude_prefixes:
        cmd.extend(["--exclude-prefixes", exclude_prefixes])

    if _truthy(env.get("PROD_GATE_BUG_SCAN_INCLUDE_PROTECTED_WITHOUT_TOKEN")):
        cmd.append("--include-protected-without-token")

    runner = run_cmd or _run_cmd_real
    rc, out, err = runner(cmd)

    if rc == 0:
        return []

    detail = _flat_detail(out, err)
    if rc == 1:
        return [f"prod_gate_bug_scan_suspects_found:{detail}" if detail else "prod_gate_bug_scan_suspects_found"]
    return [f"prod_gate_bug_scan_failed:{detail}" if detail else "prod_gate_bug_scan_failed"]



def check_payments_e2e_smoke(
    root: Path,
    *,
    environ: Mapping[str, str] | None = None,
    run_cmd: Callable[[list[str]], tuple[int, str, str]] | None = None,
) -> list[str]:
    env = environ or os.environ
    if not _truthy(env.get("PROD_GATE_PAYMENTS_E2E_ENABLED")):
        return []

    api_base = str(env.get("PROD_GATE_PAYMENTS_E2E_API_BASE") or "").strip()
    if not api_base:
        return ["prod_gate_payments_e2e_api_base_required_when_enabled"]

    script = root / "scripts" / "qa_payments_e2e.py"
    if not script.exists():
        return ["prod_gate_payments_e2e_script_missing"]

    tenant_prefix = str(env.get("PROD_GATE_PAYMENTS_E2E_TENANT_PREFIX") or "tenant-pay-e2e").strip() or "tenant-pay-e2e"
    cmd = [
        sys.executable,
        str(script),
        "--api-base",
        api_base,
        "--tenant-id",
        tenant_prefix,
        "--strict",
    ]

    runner = run_cmd or _run_cmd_real
    rc, out, err = runner(cmd)

    if rc == 0:
        return []

    detail = _flat_detail(out, err)
    return [f"prod_gate_payments_e2e_failed:{detail}" if detail else "prod_gate_payments_e2e_failed"]



def check_authz_contract(root: Path) -> list[str]:
    issues: list[str] = []

    try:
        from app.main import app
        from app.core.policy_matrix import (
            AUTHZ_MODE_DB_TRUTH,
            AUTHZ_MODE_FAST_PATH,
            AUTHZ_MODE_TOKEN_CLAIMS,
            ROUTE_POLICY,
            is_protected_route_path,
            protected_routes_without_explicit_authz_mode,
        )
    except Exception as exc:  # noqa: BLE001
        return [f"authz_contract_check_failed:{str(exc)[:200]}"]

    allowed_modes = {AUTHZ_MODE_DB_TRUTH, AUTHZ_MODE_TOKEN_CLAIMS, AUTHZ_MODE_FAST_PATH}

    for route in app.routes:
        path = getattr(route, "path", None)
        methods = set(getattr(route, "methods", set()) or set())
        if not path:
            continue
        if "HEAD" in methods and "GET" in methods:
            methods.remove("HEAD")

        for method in sorted(methods):
            if not is_protected_route_path(path):
                continue
            key = (str(method).upper(), str(path))
            rule = ROUTE_POLICY.get(key)
            if rule is None:
                issues.append(f"authz_contract_missing_policy:{key[0]}:{key[1]}")
                if len(issues) >= 100:
                    return issues + ["authz_contract_missing_policy:truncated"]
                continue

            mode = str(getattr(rule, "authz_mode", "") or "").strip().upper()
            if mode not in allowed_modes:
                issues.append(f"authz_contract_missing_or_invalid_mode:{key[0]}:{key[1]}:{mode or 'EMPTY'}")
                if len(issues) >= 100:
                    return issues + ["authz_contract_missing_or_invalid_mode:truncated"]

    matrix_missing = protected_routes_without_explicit_authz_mode()
    for item in matrix_missing:
        issues.append(f"authz_contract_matrix_missing_mode:{item}")
        if len(issues) >= 100:
            return issues + ["authz_contract_matrix_missing_mode:truncated"]

    return issues



def check_route_ownership_contract(root: Path) -> list[str]:
    issues: list[str] = []

    try:
        from app.main import app
        from app.core.policy_matrix import ROUTE_POLICY, is_protected_route_path
        from app.core.route_ownership import (
            ALLOWED_ROUTE_PLANES,
            ROUTE_PLANE_FOUNDATION,
            ROUTE_PLANE_OPERATIONAL,
            ROUTE_PLANE_OWNERSHIP,
            route_keys_without_explicit_plane_ownership,
            route_plane_ownership_drift,
            resolve_route_plane,
        )
    except Exception as exc:  # noqa: BLE001
        return [f"route_ownership_contract_check_failed:{str(exc)[:200]}"]

    drift = route_plane_ownership_drift()
    for item in list(drift.get("missing") or []):
        issues.append(f"route_ownership_contract_drift_missing:{item}")
        if len(issues) >= 100:
            return issues + ["route_ownership_contract_drift_missing:truncated"]

    for item in list(drift.get("extra") or []):
        issues.append(f"route_ownership_contract_drift_extra:{item}")
        if len(issues) >= 100:
            return issues + ["route_ownership_contract_drift_extra:truncated"]

    for item in route_keys_without_explicit_plane_ownership():
        issues.append(f"route_ownership_contract_missing:{item}")
        if len(issues) >= 100:
            return issues + ["route_ownership_contract_missing:truncated"]

    for route in app.routes:
        path = getattr(route, "path", None)
        methods = set(getattr(route, "methods", set()) or set())
        if not path:
            continue
        if "HEAD" in methods and "GET" in methods:
            methods.remove("HEAD")

        for method in sorted(methods):
            if not is_protected_route_path(path):
                continue
            key = (str(method).upper(), str(path))
            if key not in ROUTE_POLICY:
                # authz_contract handles policy coverage; keep ownership gate scoped.
                continue

            plane = resolve_route_plane(key[0], key[1])
            if plane is None:
                issues.append(f"route_ownership_contract_missing:{key[0]}:{key[1]}")
                if len(issues) >= 100:
                    return issues + ["route_ownership_contract_missing:truncated"]
                continue

            if plane not in ALLOWED_ROUTE_PLANES:
                issues.append(f"route_ownership_contract_invalid:{key[0]}:{key[1]}:{plane}")
                if len(issues) >= 100:
                    return issues + ["route_ownership_contract_invalid:truncated"]

    for method, path in sorted(ROUTE_POLICY.keys()):
        plane = resolve_route_plane(method, path)
        if path == "/orders" or path.startswith("/orders/"):
            if plane != ROUTE_PLANE_OPERATIONAL:
                issues.append(f"route_ownership_orders_not_operational:{method}:{path}:{plane or 'EMPTY'}")
                if len(issues) >= 100:
                    return issues + ["route_ownership_orders_not_operational:truncated"]

        if path == "/marketplace" or path.startswith("/marketplace/"):
            if plane != ROUTE_PLANE_FOUNDATION:
                issues.append(f"route_ownership_marketplace_not_foundation:{method}:{path}:{plane or 'EMPTY'}")
                if len(issues) >= 100:
                    return issues + ["route_ownership_marketplace_not_foundation:truncated"]

    return issues

def check_migrations_smoke(
    root: Path,
    *,
    environ: Mapping[str, str] | None = None,
    run_cmd: Callable[[list[str]], tuple[int, str, str]] | None = None,
) -> list[str]:
    env = environ or os.environ
    if not _truthy(env.get("PROD_GATE_MIGRATIONS_SMOKE_ENABLED")):
        return []

    db_url = str(env.get("PROD_GATE_MIGRATIONS_SMOKE_DATABASE_URL") or env.get("DATABASE_URL") or "").strip()
    if not db_url:
        return ["prod_gate_migrations_smoke_database_url_required_when_enabled"]

    script = root / "scripts" / "qa_migrations_smoke.py"
    if not script.exists():
        return ["prod_gate_migrations_smoke_script_missing"]

    cmd = [
        sys.executable,
        str(script),
        "--database-url",
        db_url,
        "--strict",
    ]

    admin_db = str(env.get("PROD_GATE_MIGRATIONS_SMOKE_ADMIN_DATABASE") or "").strip()
    if admin_db:
        cmd.extend(["--admin-database", admin_db])

    snapshot_revision = str(env.get("PROD_GATE_MIGRATIONS_SMOKE_SNAPSHOT_REVISION") or "").strip()
    if snapshot_revision:
        cmd.extend(["--snapshot-revision", snapshot_revision])

    expect_tables = str(env.get("PROD_GATE_MIGRATIONS_SMOKE_EXPECT_TABLES") or "").strip()
    if expect_tables:
        for table in [x.strip() for x in expect_tables.split(",") if x.strip()]:
            cmd.extend(["--expect-table", table])

    runner = run_cmd or _run_cmd_real
    rc, out, err = runner(cmd)

    if rc == 0:
        return []

    detail = _flat_detail(out, err)
    return [f"prod_gate_migrations_smoke_failed:{detail}" if detail else "prod_gate_migrations_smoke_failed"]
def main() -> int:
    root = Path(__file__).resolve().parents[1]

    errors: list[str] = []
    errors.extend(check_no_bom(root))
    errors.extend(check_no_hardcoded_code_secrets(root))
    errors.extend(check_no_external_project_refs(root))
    errors.extend(check_env_example(root / ".env.example"))
    errors.extend(check_workspace_hygiene(root))
    errors.extend(check_code_default_contract())
    errors.extend(check_prod_profile_contract())
    errors.extend(check_authz_contract(root))
    errors.extend(check_route_ownership_contract(root))
    errors.extend(check_module_factory_contract(root))
    errors.extend(check_module_factory_coverage_contract(root))
    errors.extend(check_support_plane_decomposition_contract(root))
    errors.extend(check_ai_plane_decomposition_contract(root))
    errors.extend(check_ai_contract_v1(root))
    errors.extend(check_ai_retrieval_contract_v1(root))
    errors.extend(check_eidon_drafting_contract_v1(root))
    errors.extend(check_eidon_template_learning_contract_v1(root))
    errors.extend(check_bug_finder_smoke(root))
    errors.extend(check_payments_e2e_smoke(root))
    errors.extend(check_migrations_smoke(root))

    if errors:
        print("prod_gate=failed")
        for err in errors:
            print(("- " + str(err)).encode("ascii", errors="backslashreplace").decode("ascii"))
        return 1

    print("prod_gate=ok")
    print("checks=no_bom,no_hardcoded_code_secrets,no_external_project_refs,.env.example_keys,workspace_hygiene,code_default_contract,prod_profile_contract,authz_contract,route_ownership_contract,module_factory_contract,module_factory_coverage_contract,support_plane_decomposition_contract,ai_plane_decomposition_contract,ai_contract_v1,ai_retrieval_contract_v1,eidon_drafting_contract_v1,eidon_template_learning_contract_v1,bug_scan_optional,payments_e2e_optional,migrations_smoke_optional")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())




