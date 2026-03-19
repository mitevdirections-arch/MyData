from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import time
from typing import Any

from sqlalchemy import and_, bindparam, select
from sqlalchemy.orm import Session

from app.core.perf_profile import record_segment
from app.core.permissions import dedupe_permissions, normalize_permission
from app.db.models import WorkspaceRole, WorkspaceUser, WorkspaceUserEffectivePermission, WorkspaceUserRole

ACTIVE_EMPLOYMENT_STATUS = "ACTIVE"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_permissions(raw_values: list[Any] | None) -> list[str]:
    out: list[str] = []
    for raw in list(raw_values or []):
        val = normalize_permission(raw)
        if val:
            out.append(val)
    return dedupe_permissions(out)


def _stable_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _fast_path_breakdown_enabled() -> bool:
    access_raw = str(os.getenv("MYDATA_PERF_ACCESS_BREAKDOWN", "0")).strip().lower()
    if access_raw in {"1", "true", "yes", "on"}:
        return True
    raw = str(os.getenv("MYDATA_PERF_AUTHZ_FAST_PATH_BREAKDOWN", "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _access_db_split_enabled() -> bool:
    raw = str(os.getenv("MYDATA_PERF_ACCESS_DB_SPLIT", "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _record_fast_path_breakdown(*, sql_ms: float, materialize_ms: float, shape_ms: float) -> None:
    record_segment("tenant_db_authz_sql_ms", max(0.0, float(sql_ms)))
    record_segment("tenant_db_authz_materialize_ms", max(0.0, float(materialize_ms)))
    record_segment("tenant_db_authz_shape_ms", max(0.0, float(shape_ms)))


_CANONICAL_EFFECTIVE_PERMISSIONS_STMT = (
    select(
        WorkspaceUser.employment_status,
        WorkspaceUser.direct_permissions_json,
        WorkspaceRole.permissions_json,
    )
    .select_from(WorkspaceUser)
    .outerjoin(
        WorkspaceUserRole,
        and_(
            WorkspaceUserRole.workspace_type == WorkspaceUser.workspace_type,
            WorkspaceUserRole.workspace_id == WorkspaceUser.workspace_id,
            WorkspaceUserRole.user_id == WorkspaceUser.user_id,
        ),
    )
    .outerjoin(
        WorkspaceRole,
        and_(
            WorkspaceRole.workspace_type == WorkspaceUserRole.workspace_type,
            WorkspaceRole.workspace_id == WorkspaceUserRole.workspace_id,
            WorkspaceRole.role_code == WorkspaceUserRole.role_code,
        ),
    )
    .where(
        WorkspaceUser.workspace_type == bindparam("workspace_type"),
        WorkspaceUser.workspace_id == bindparam("workspace_id"),
        WorkspaceUser.user_id == bindparam("user_id"),
    )
)


def resolve_effective_permissions_from_canonical(
    db: Session,
    *,
    workspace_type: str,
    workspace_id: str,
    user_id: str,
) -> dict[str, Any]:
    breakdown_enabled = _fast_path_breakdown_enabled()
    split_enabled = _access_db_split_enabled()
    sql_ms = 0.0
    materialize_ms = 0.0
    shape_ms = 0.0
    checkout_ms = 0.0
    exec_ms = 0.0

    if split_enabled:
        checkout_started = time.perf_counter()
        db.connection()
        checkout_ms = (time.perf_counter() - checkout_started) * 1000.0

    sql_started = time.perf_counter()
    rows = db.execute(
        _CANONICAL_EFFECTIVE_PERMISSIONS_STMT,
        {
            "workspace_type": workspace_type,
            "workspace_id": workspace_id,
            "user_id": user_id,
        },
    )
    rows = rows.all()
    exec_ms = (time.perf_counter() - sql_started) * 1000.0
    sql_ms = max(0.0, float(checkout_ms + exec_ms)) if split_enabled else exec_ms

    if not rows:
        if breakdown_enabled:
            _record_fast_path_breakdown(sql_ms=sql_ms, materialize_ms=materialize_ms, shape_ms=shape_ms)
            if split_enabled:
                record_segment("tenant_db_authz_db_checkout_ms", max(0.0, float(checkout_ms)))
                record_segment("tenant_db_authz_exec_ms", max(0.0, float(exec_ms)))
        return {
            "found": False,
            "workspace_type": workspace_type,
            "workspace_id": workspace_id,
            "user_id": user_id,
            "employment_status": None,
            "direct_permissions": [],
            "role_permissions": [],
            "effective_permissions": [],
            "source_hash_sha256": None,
        }

    materialize_started = time.perf_counter()
    employment_status_raw = (rows[0][0] if rows[0] else "") or ""
    direct_permissions_raw = list((rows[0][1] if rows[0] else None) or [])
    role_permissions_raw: list[str] = []
    for _status, _direct, role_perm_list in rows:
        role_permissions_raw.extend(list(role_perm_list or []))
    materialize_ms = (time.perf_counter() - materialize_started) * 1000.0

    shape_started = time.perf_counter()
    employment_status = str(employment_status_raw).strip().upper()
    direct_permissions = _normalize_permissions(direct_permissions_raw)
    role_permissions = _normalize_permissions(role_permissions_raw)

    if employment_status == ACTIVE_EMPLOYMENT_STATUS:
        effective_permissions = dedupe_permissions([*direct_permissions, *role_permissions])
    else:
        effective_permissions = []

    source_hash_sha256 = _stable_hash(
        {
            "workspace_type": workspace_type,
            "workspace_id": workspace_id,
            "user_id": user_id,
            "employment_status": employment_status,
            "direct_permissions": direct_permissions,
            "role_permissions": role_permissions,
            "effective_permissions": effective_permissions,
        }
    )
    shape_ms = (time.perf_counter() - shape_started) * 1000.0
    if breakdown_enabled:
        _record_fast_path_breakdown(sql_ms=sql_ms, materialize_ms=materialize_ms, shape_ms=shape_ms)
        if split_enabled:
            record_segment("tenant_db_authz_db_checkout_ms", max(0.0, float(checkout_ms)))
            record_segment("tenant_db_authz_exec_ms", max(0.0, float(exec_ms)))

    return {
        "found": True,
        "workspace_type": workspace_type,
        "workspace_id": workspace_id,
        "user_id": user_id,
        "employment_status": employment_status,
        "direct_permissions": direct_permissions,
        "role_permissions": role_permissions,
        "effective_permissions": effective_permissions,
        "source_hash_sha256": source_hash_sha256,
    }


def resolve_effective_permissions_from_fast_path(
    db: Session,
    *,
    workspace_type: str,
    workspace_id: str,
    user_id: str,
    required_source_version: int,
) -> dict[str, Any]:
    breakdown_enabled = _fast_path_breakdown_enabled()
    sql_ms = 0.0
    materialize_ms = 0.0
    shape_ms = 0.0

    sql_started = time.perf_counter()
    row = (
        db.query(
            WorkspaceUserEffectivePermission.employment_status,
            WorkspaceUserEffectivePermission.effective_permissions_json,
            WorkspaceUserEffectivePermission.source_version,
        )
        .filter(
            WorkspaceUserEffectivePermission.workspace_type == workspace_type,
            WorkspaceUserEffectivePermission.workspace_id == workspace_id,
            WorkspaceUserEffectivePermission.user_id == user_id,
        )
        .first()
    )
    sql_ms = (time.perf_counter() - sql_started) * 1000.0

    if row is None:
        if breakdown_enabled:
            _record_fast_path_breakdown(sql_ms=sql_ms, materialize_ms=materialize_ms, shape_ms=shape_ms)
        return {
            "found": False,
            "valid": False,
            "reason": "missing",
            "effective_permissions": [],
        }

    materialize_started = time.perf_counter()
    employment_status_raw = row[0] if isinstance(row, tuple) else getattr(row, "employment_status", "")
    raw_perms_obj = row[1] if isinstance(row, tuple) else getattr(row, "effective_permissions_json", None)
    source_version_raw = row[2] if isinstance(row, tuple) else getattr(row, "source_version", 0)
    row_version = int(source_version_raw or 0)
    employment_status = str(employment_status_raw or "").strip().upper()
    materialize_ms = (time.perf_counter() - materialize_started) * 1000.0

    if row_version != int(required_source_version):
        if breakdown_enabled:
            _record_fast_path_breakdown(sql_ms=sql_ms, materialize_ms=materialize_ms, shape_ms=shape_ms)
        return {
            "found": True,
            "valid": False,
            "reason": "stale_source_version",
            "effective_permissions": [],
            "source_version": row_version,
        }

    if employment_status != ACTIVE_EMPLOYMENT_STATUS:
        if breakdown_enabled:
            _record_fast_path_breakdown(sql_ms=sql_ms, materialize_ms=materialize_ms, shape_ms=shape_ms)
        return {
            "found": True,
            "valid": True,
            "reason": "inactive_employment",
            "employment_status": employment_status,
            "effective_permissions": [],
            "source_version": row_version,
        }

    if not isinstance(raw_perms_obj, list):
        if breakdown_enabled:
            _record_fast_path_breakdown(sql_ms=sql_ms, materialize_ms=materialize_ms, shape_ms=shape_ms)
        return {
            "found": True,
            "valid": False,
            "reason": "invalid_permissions_payload",
            "effective_permissions": [],
            "source_version": row_version,
        }

    shape_started = time.perf_counter()
    normalized_permissions = _normalize_permissions(raw_perms_obj)
    shape_ms = (time.perf_counter() - shape_started) * 1000.0
    if breakdown_enabled:
        _record_fast_path_breakdown(sql_ms=sql_ms, materialize_ms=materialize_ms, shape_ms=shape_ms)

    return {
        "found": True,
        "valid": True,
        "reason": "ok",
        "employment_status": employment_status,
        "effective_permissions": normalized_permissions,
        "source_version": row_version,
    }


def upsert_effective_permissions_snapshot(
    db: Session,
    *,
    workspace_type: str,
    workspace_id: str,
    user_id: str,
    actor: str,
    source_version: int,
) -> dict[str, Any]:
    canonical = resolve_effective_permissions_from_canonical(
        db,
        workspace_type=workspace_type,
        workspace_id=workspace_id,
        user_id=user_id,
    )

    row = (
        db.query(WorkspaceUserEffectivePermission)
        .filter(
            WorkspaceUserEffectivePermission.workspace_type == workspace_type,
            WorkspaceUserEffectivePermission.workspace_id == workspace_id,
            WorkspaceUserEffectivePermission.user_id == user_id,
        )
        .first()
    )

    if not bool(canonical.get("found")):
        if row is not None:
            db.delete(row)
            db.flush()
            return {
                "ok": True,
                "action": "deleted_missing_user",
                "workspace_type": workspace_type,
                "workspace_id": workspace_id,
                "user_id": user_id,
            }
        return {
            "ok": True,
            "action": "noop_missing_user",
            "workspace_type": workspace_type,
            "workspace_id": workspace_id,
            "user_id": user_id,
        }

    now = _now()
    if row is None:
        row = WorkspaceUserEffectivePermission(
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            user_id=user_id,
            employment_status=str(canonical.get("employment_status") or "INACTIVE"),
            effective_permissions_json=list(canonical.get("effective_permissions") or []),
            source_version=max(1, int(source_version)),
            source_hash_sha256=str(canonical.get("source_hash_sha256") or "") or None,
            computed_at=now,
            updated_by=str(actor or "unknown"),
            updated_at=now,
        )
        db.add(row)
        action = "created"
    else:
        row.employment_status = str(canonical.get("employment_status") or "INACTIVE")
        row.effective_permissions_json = list(canonical.get("effective_permissions") or [])
        row.source_version = max(1, int(source_version))
        row.source_hash_sha256 = str(canonical.get("source_hash_sha256") or "") or None
        row.computed_at = now
        row.updated_by = str(actor or "unknown")
        row.updated_at = now
        action = "updated"

    db.flush()

    return {
        "ok": True,
        "action": action,
        "workspace_type": workspace_type,
        "workspace_id": workspace_id,
        "user_id": user_id,
        "employment_status": row.employment_status,
        "effective_permissions": list(row.effective_permissions_json or []),
        "source_version": int(row.source_version),
        "source_hash_sha256": row.source_hash_sha256,
    }


def recompute_effective_permissions_for_role(
    db: Session,
    *,
    workspace_type: str,
    workspace_id: str,
    role_code: str,
    actor: str,
    source_version: int,
) -> dict[str, Any]:
    user_ids = [
        str(x[0])
        for x in (
            db.query(WorkspaceUserRole.user_id)
            .filter(
                WorkspaceUserRole.workspace_type == workspace_type,
                WorkspaceUserRole.workspace_id == workspace_id,
                WorkspaceUserRole.role_code == role_code,
            )
            .distinct()
            .all()
        )
        if str(x[0] or "").strip()
    ]

    touched = 0
    for uid in user_ids:
        upsert_effective_permissions_snapshot(
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            user_id=uid,
            actor=actor,
            source_version=source_version,
        )
        touched += 1

    return {
        "ok": True,
        "workspace_type": workspace_type,
        "workspace_id": workspace_id,
        "role_code": role_code,
        "users_touched": touched,
    }


def rebuild_effective_permissions_for_workspace(
    db: Session,
    *,
    workspace_type: str,
    workspace_id: str,
    actor: str,
    source_version: int,
) -> dict[str, Any]:
    user_ids = [
        str(x[0])
        for x in (
            db.query(WorkspaceUser.user_id)
            .filter(
                WorkspaceUser.workspace_type == workspace_type,
                WorkspaceUser.workspace_id == workspace_id,
            )
            .all()
        )
        if str(x[0] or "").strip()
    ]

    upserted = 0
    for uid in user_ids:
        upsert_effective_permissions_snapshot(
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            user_id=uid,
            actor=actor,
            source_version=source_version,
        )
        upserted += 1

    if user_ids:
        deleted_orphans = int(
            db.query(WorkspaceUserEffectivePermission)
            .filter(
                WorkspaceUserEffectivePermission.workspace_type == workspace_type,
                WorkspaceUserEffectivePermission.workspace_id == workspace_id,
                WorkspaceUserEffectivePermission.user_id.notin_(user_ids),
            )
            .delete(synchronize_session=False)
        )
    else:
        deleted_orphans = int(
            db.query(WorkspaceUserEffectivePermission)
            .filter(
                WorkspaceUserEffectivePermission.workspace_type == workspace_type,
                WorkspaceUserEffectivePermission.workspace_id == workspace_id,
            )
            .delete(synchronize_session=False)
        )

    db.flush()

    return {
        "ok": True,
        "workspace_type": workspace_type,
        "workspace_id": workspace_id,
        "users_total": len(user_ids),
        "upserted": upserted,
        "deleted_orphans": deleted_orphans,
    }


def drift_check_effective_permissions_for_workspace(
    db: Session,
    *,
    workspace_type: str,
    workspace_id: str,
    required_source_version: int,
) -> dict[str, Any]:
    user_ids = [
        str(x[0])
        for x in (
            db.query(WorkspaceUser.user_id)
            .filter(
                WorkspaceUser.workspace_type == workspace_type,
                WorkspaceUser.workspace_id == workspace_id,
            )
            .all()
        )
        if str(x[0] or "").strip()
    ]

    mismatches: list[dict[str, Any]] = []
    for uid in user_ids:
        canonical = resolve_effective_permissions_from_canonical(
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            user_id=uid,
        )
        fast = resolve_effective_permissions_from_fast_path(
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            user_id=uid,
            required_source_version=required_source_version,
        )

        expected = list(canonical.get("effective_permissions") or []) if str(canonical.get("employment_status") or "").upper() == ACTIVE_EMPLOYMENT_STATUS else []

        if not bool(fast.get("found")):
            mismatches.append({"user_id": uid, "reason": "missing_fast_path_row"})
            continue
        if not bool(fast.get("valid")):
            mismatches.append({"user_id": uid, "reason": f"invalid_fast_path:{fast.get('reason')}"})
            continue

        got = list(fast.get("effective_permissions") or [])
        if set(got) != set(expected):
            mismatches.append({"user_id": uid, "reason": "permissions_mismatch", "expected": expected, "got": got})

    fast_user_ids = {
        str(x[0])
        for x in (
            db.query(WorkspaceUserEffectivePermission.user_id)
            .filter(
                WorkspaceUserEffectivePermission.workspace_type == workspace_type,
                WorkspaceUserEffectivePermission.workspace_id == workspace_id,
            )
            .all()
        )
        if str(x[0] or "").strip()
    }
    orphan_ids = sorted(fast_user_ids - set(user_ids))
    for orphan in orphan_ids:
        mismatches.append({"user_id": orphan, "reason": "orphan_fast_path_row"})

    return {
        "ok": len(mismatches) == 0,
        "workspace_type": workspace_type,
        "workspace_id": workspace_id,
        "users_checked": len(user_ids),
        "orphan_rows": len(orphan_ids),
        "mismatches": mismatches,
    }
