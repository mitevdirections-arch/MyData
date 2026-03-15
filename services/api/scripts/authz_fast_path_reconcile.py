from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any

from app.core.authz_fast_path import (
    rebuild_effective_permissions_for_workspace,
    drift_check_effective_permissions_for_workspace,
)
from app.core.settings import get_settings
from app.db.session import get_session_factory


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Rebuild and drift-check tenant DB authz fast path")
    p.add_argument("--workspace-type", default="TENANT", help="Workspace type (TENANT or PLATFORM)")
    p.add_argument("--workspace-id", required=True, help="Workspace ID")
    p.add_argument("--actor", default="system-authz-fast-path", help="Audit actor for rebuild updates")
    p.add_argument("--source-version", type=int, default=0, help="Expected source version (0 = use settings default)")
    p.add_argument("--rebuild", action="store_true", help="Rebuild fast-path snapshots for this workspace")
    p.add_argument("--drift-check", action="store_true", help="Run drift-check against canonical authz truth")
    p.add_argument("--repair", action="store_true", help="If drift exists, rebuild and check again")
    p.add_argument("--strict", action="store_true", help="Exit non-zero when drift mismatches are found")
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    workspace_type = str(args.workspace_type or "TENANT").strip().upper() or "TENANT"
    workspace_id = str(args.workspace_id or "").strip()
    if not workspace_id:
        print(json.dumps({"ok": False, "detail": "workspace_id_required"}, ensure_ascii=False))
        return 2

    run_rebuild = bool(args.rebuild)
    run_drift = bool(args.drift_check)
    if not run_rebuild and not run_drift:
        run_rebuild = True
        run_drift = True

    source_version = int(args.source_version)
    if source_version <= 0:
        source_version = max(1, int(get_settings().authz_tenant_db_fast_path_source_version))

    out: dict[str, Any] = {
        "ok": True,
        "workspace_type": workspace_type,
        "workspace_id": workspace_id,
        "source_version": source_version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "steps": [],
    }

    db = get_session_factory()()
    try:
        if run_rebuild:
            rebuilt = rebuild_effective_permissions_for_workspace(
                db,
                workspace_type=workspace_type,
                workspace_id=workspace_id,
                actor=str(args.actor or "system-authz-fast-path"),
                source_version=source_version,
            )
            out["steps"].append({"step": "rebuild", **rebuilt})

        drift = None
        if run_drift:
            drift = drift_check_effective_permissions_for_workspace(
                db,
                workspace_type=workspace_type,
                workspace_id=workspace_id,
                required_source_version=source_version,
            )
            out["steps"].append({"step": "drift_check", **drift})

        if bool(args.repair) and isinstance(drift, dict) and not bool(drift.get("ok")):
            repaired = rebuild_effective_permissions_for_workspace(
                db,
                workspace_type=workspace_type,
                workspace_id=workspace_id,
                actor=str(args.actor or "system-authz-fast-path"),
                source_version=source_version,
            )
            out["steps"].append({"step": "repair_rebuild", **repaired})

            drift_after = drift_check_effective_permissions_for_workspace(
                db,
                workspace_type=workspace_type,
                workspace_id=workspace_id,
                required_source_version=source_version,
            )
            out["steps"].append({"step": "drift_check_after_repair", **drift_after})
            drift = drift_after

        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        print(
            json.dumps(
                {
                    "ok": False,
                    "workspace_type": workspace_type,
                    "workspace_id": workspace_id,
                    "detail": "authz_fast_path_reconcile_failed",
                    "error": str(exc),
                },
                ensure_ascii=False,
            )
        )
        return 1
    finally:
        db.close()

    print(json.dumps(out, ensure_ascii=False))

    if bool(args.strict):
        for step in list(out.get("steps") or []):
            if str(step.get("step") or "") in {"drift_check", "drift_check_after_repair"} and not bool(step.get("ok")):
                return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
