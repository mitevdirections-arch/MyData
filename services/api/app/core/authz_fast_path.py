from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from sqlalchemy import and_
from sqlalchemy.orm import Session

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


def resolve_effective_permissions_from_canonical(
    db: Session,
    *,
    workspace_type: str,
    workspace_id: str,
    user_id: str,
) -> dict[str, Any]:
    rows = (
        db.query(
            WorkspaceUser.employment_status,
            WorkspaceUser.direct_permissions_json,
            WorkspaceRole.permissions_json,
        )
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
        .filter(
            WorkspaceUser.workspace_type == workspace_type,
            WorkspaceUser.workspace_id == workspace_id,
            WorkspaceUser.user_id == user_id,
        )
        .all()
    )

    if not rows:
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

    employment_status = str((rows[0][0] if rows[0] else "") or "").strip().upper()
    direct_permissions = _normalize_permissions(list((rows[0][1] if rows[0] else None) or []))

    role_permissions_raw: list[str] = []
    for _status, _direct, role_perm_list in rows:
        role_permissions_raw.extend(list(role_perm_list or []))
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
    row = (
        db.query(WorkspaceUserEffectivePermission)
        .filter(
            WorkspaceUserEffectivePermission.workspace_type == workspace_type,
            WorkspaceUserEffectivePermission.workspace_id == workspace_id,
            WorkspaceUserEffectivePermission.user_id == user_id,
        )
        .first()
    )

    if row is None:
        return {
            "found": False,
            "valid": False,
            "reason": "missing",
            "effective_permissions": [],
        }

    row_version = int(getattr(row, "source_version", 0) or 0)
    if row_version != int(required_source_version):
        return {
            "found": True,
            "valid": False,
            "reason": "stale_source_version",
            "effective_permissions": [],
            "source_version": row_version,
        }

    employment_status = str(getattr(row, "employment_status", "") or "").strip().upper()
    if employment_status != ACTIVE_EMPLOYMENT_STATUS:
        return {
            "found": True,
            "valid": True,
            "reason": "inactive_employment",
            "employment_status": employment_status,
            "effective_permissions": [],
            "source_version": row_version,
        }

    raw_perms = getattr(row, "effective_permissions_json", None)
    if not isinstance(raw_perms, list):
        return {
            "found": True,
            "valid": False,
            "reason": "invalid_permissions_payload",
            "effective_permissions": [],
            "source_version": row_version,
        }

    return {
        "found": True,
        "valid": True,
        "reason": "ok",
        "employment_status": employment_status,
        "effective_permissions": _normalize_permissions(raw_perms),
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
