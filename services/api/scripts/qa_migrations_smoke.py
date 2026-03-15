from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit

from alembic.config import Config
from alembic.script import ScriptDirectory

try:
    import psycopg
    from psycopg import sql
except Exception:  # noqa: BLE001
    psycopg = None
    sql = None


DEFAULT_EXPECT_TABLES = [
    "tenants",
    "licenses",
    "workspace_users",
    "workspace_user_credentials",
    "workspace_user_effective_permissions",
    "marketplace_modules",
    "payment_invoices",
    "orders",
    "guard_heartbeats",
    "eidon_pattern_publish_artifacts",
    "eidon_pattern_distribution_records",
    "eidon_pattern_rollout_governance_records",
    "eidon_pattern_activation_records",
    "eidon_ai_quality_events",
]


def _detect_admin_database(url: str) -> str:
    scheme = str(urlsplit(url).scheme or "").lower()
    if "cockroach" in scheme:
        return "defaultdb"
    return "postgres"


def _db_name_from_url(url: str) -> str:
    path = str(urlsplit(url).path or "").lstrip("/")
    return path.split("/", 1)[0] if path else ""


def _url_with_database(url: str, db_name: str) -> str:
    split = urlsplit(url)
    base = SplitResult(split.scheme, split.netloc, f"/{db_name}", split.query, split.fragment)
    return urlunsplit(base)


def _to_psycopg_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        raise RuntimeError("database_url_required")

    for token in ("<user>", "<pass>", "<db>"):
        if token in raw:
            raise RuntimeError("database_url_contains_placeholders")

    split = urlsplit(raw)
    scheme = str(split.scheme or "").lower()

    # psycopg accepts postgresql:// / postgres:// URLs, but not SQLAlchemy driver-style schemes.
    if scheme in {"cockroachdb+psycopg", "cockroachdb", "postgresql+psycopg", "postgres"}:
        split = SplitResult("postgresql", split.netloc, split.path, split.query, split.fragment)
        return urlunsplit(split)

    return raw


def _temp_db_name(prefix: str) -> str:
    safe_prefix = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in str(prefix or "mig").lower())
    safe_prefix = safe_prefix[:24].strip("_") or "mig"
    return f"{safe_prefix}_{secrets.token_hex(6)}"


def _run_alembic_upgrade(root: Path, *, database_url: str, target: str) -> tuple[int, str, str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = str(database_url)
    env["PYTHONPATH"] = "."
    cmd = [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", str(target)]
    proc = subprocess.run(
        cmd,
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return int(proc.returncode), str(proc.stdout or ""), str(proc.stderr or "")


def _assert_tables_exist(database_url: str, expected: list[str]) -> list[str]:
    if psycopg is None:
        raise RuntimeError("psycopg_not_available")

    conn_url = _to_psycopg_url(database_url)
    with psycopg.connect(conn_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                """
            )
            existing = {str(row[0]) for row in cur.fetchall()}

    return [t for t in expected if t not in existing]


def _create_database(admin_url: str, db_name: str) -> None:
    if psycopg is None or sql is None:
        raise RuntimeError("psycopg_not_available")

    conn_url = _to_psycopg_url(admin_url)
    with psycopg.connect(conn_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))


def _drop_database(admin_url: str, db_name: str) -> None:
    if psycopg is None or sql is None:
        return

    try:
        conn_url = _to_psycopg_url(admin_url)
        with psycopg.connect(conn_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} CASCADE").format(sql.Identifier(db_name)))
    except Exception:  # noqa: BLE001
        # Cleanup must never mask the real smoke failure.
        return


def _resolve_snapshot_revision(root: Path) -> str:
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    if not head:
        raise RuntimeError("alembic_head_not_found")

    rev = script.get_revision(head)
    if rev is None:
        raise RuntimeError("alembic_head_revision_missing")

    down = rev.down_revision
    if isinstance(down, tuple):
        down = down[0] if down else None
    if not down:
        raise RuntimeError("snapshot_revision_not_found")
    return str(down)


def _flat(out: str, err: str, *, max_len: int = 600) -> str:
    raw = (str(out or "").strip() or str(err or "").strip()).replace("\r", " ").replace("\n", " | ").strip()
    if len(raw) <= max_len:
        return raw
    return raw[:max_len] + "..."


def _run_clean_upgrade(root: Path, *, admin_url: str, base_url: str, expected_tables: list[str]) -> dict[str, Any]:
    db_name = _temp_db_name("mig_clean")
    db_url = _url_with_database(base_url, db_name)
    result: dict[str, Any] = {
        "ok": False,
        "database": db_name,
        "target": "head",
        "missing_tables": [],
    }

    created = False
    try:
        _create_database(admin_url, db_name)
        created = True

        rc, out, err = _run_alembic_upgrade(root, database_url=db_url, target="head")
        result["alembic_rc"] = rc
        if rc != 0:
            result["error"] = _flat(out, err)
            return result

        missing = _assert_tables_exist(db_url, expected_tables)
        result["missing_tables"] = missing
        result["ok"] = len(missing) == 0
        return result
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"clean_upgrade_runtime:{exc}"
        return result
    finally:
        if created:
            _drop_database(admin_url, db_name)


def _run_snapshot_upgrade(
    root: Path,
    *,
    admin_url: str,
    base_url: str,
    snapshot_revision: str,
    expected_tables: list[str],
) -> dict[str, Any]:
    db_name = _temp_db_name("mig_snapshot")
    db_url = _url_with_database(base_url, db_name)
    result: dict[str, Any] = {
        "ok": False,
        "database": db_name,
        "snapshot_revision": snapshot_revision,
        "missing_tables": [],
    }

    created = False
    try:
        _create_database(admin_url, db_name)
        created = True

        rc1, out1, err1 = _run_alembic_upgrade(root, database_url=db_url, target=snapshot_revision)
        result["snapshot_upgrade_rc"] = rc1
        if rc1 != 0:
            result["error"] = _flat(out1, err1)
            return result

        rc2, out2, err2 = _run_alembic_upgrade(root, database_url=db_url, target="head")
        result["head_upgrade_rc"] = rc2
        if rc2 != 0:
            result["error"] = _flat(out2, err2)
            return result

        missing = _assert_tables_exist(db_url, expected_tables)
        result["missing_tables"] = missing
        result["ok"] = len(missing) == 0
        return result
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"snapshot_upgrade_runtime:{exc}"
        return result
    finally:
        if created:
            _drop_database(admin_url, db_name)


def run_smoke(
    *,
    database_url: str,
    admin_database: str | None = None,
    snapshot_revision: str | None = None,
    expected_tables: list[str] | None = None,
) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    db_url = str(database_url or "").strip()
    if not db_url:
        return {"ok": False, "error": "database_url_required"}

    if psycopg is None:
        return {"ok": False, "error": "psycopg_not_available"}

    try:
        _ = _to_psycopg_url(db_url)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}

    expected = [str(x).strip() for x in (expected_tables or DEFAULT_EXPECT_TABLES) if str(x).strip()]
    if not expected:
        expected = list(DEFAULT_EXPECT_TABLES)

    source_db = _db_name_from_url(db_url)
    if not source_db:
        return {"ok": False, "error": "database_name_missing_in_url"}

    admin_db = str(admin_database or "").strip() or _detect_admin_database(db_url)
    admin_url = _url_with_database(db_url, admin_db)

    snap = str(snapshot_revision or "").strip()
    if not snap:
        try:
            snap = _resolve_snapshot_revision(root)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"snapshot_revision_resolve_failed:{exc}"}

    clean = _run_clean_upgrade(root, admin_url=admin_url, base_url=db_url, expected_tables=expected)
    snapshot = _run_snapshot_upgrade(
        root,
        admin_url=admin_url,
        base_url=db_url,
        snapshot_revision=snap,
        expected_tables=expected,
    )

    ok = bool(clean.get("ok")) and bool(snapshot.get("ok"))
    return {
        "ok": ok,
        "policy": "forward_only",
        "checks": {
            "clean_upgrade": clean,
            "snapshot_to_head_upgrade": snapshot,
        },
        "expected_tables": expected,
        "snapshot_revision": snap,
        "admin_database": admin_db,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Forward-only migration smoke: clean upgrade + snapshot->head upgrade")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""), help="Target DB URL (with database name)")
    parser.add_argument("--admin-database", default=os.getenv("MIGRATIONS_SMOKE_ADMIN_DATABASE", ""), help="Admin DB name (optional)")
    parser.add_argument("--snapshot-revision", default=os.getenv("MIGRATIONS_SMOKE_SNAPSHOT_REVISION", ""), help="Optional snapshot revision (default: head down_revision)")
    parser.add_argument(
        "--expect-table",
        action="append",
        default=[],
        help="Expected table (repeatable). If omitted, defaults are used.",
    )
    parser.add_argument("--strict", action="store_true", help="Exit 1 on failure")
    args = parser.parse_args()

    expect_tables = [str(x).strip() for x in (args.expect_table or []) if str(x).strip()]
    out = run_smoke(
        database_url=str(args.database_url),
        admin_database=str(args.admin_database or "").strip() or None,
        snapshot_revision=str(args.snapshot_revision or "").strip() or None,
        expected_tables=expect_tables or None,
    )
    print(json.dumps(out, ensure_ascii=True))
    if bool(args.strict) and not bool(out.get("ok")):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


