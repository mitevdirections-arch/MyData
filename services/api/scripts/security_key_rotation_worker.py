from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime, timedelta, timezone
import json
from typing import Any

from app.core.settings import get_settings
from app.db.models import GuardBotCredential
from app.db.session import get_session_factory
from app.modules.guard.service import service as guard_service


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_due(row: GuardBotCredential, *, cutoff: datetime) -> bool:
    pivot = row.rotated_at or row.created_at
    if pivot is None:
        return True
    if pivot.tzinfo is None:
        pivot = pivot.replace(tzinfo=timezone.utc)
    return pivot <= cutoff


def run_once(*, tenant_id: str | None, rotate_days: int, limit: int, dry_run: bool, actor: str) -> dict[str, Any]:
    db = get_session_factory()()
    now = _now()
    cutoff = now.replace(microsecond=0)
    cutoff = cutoff - timedelta(days=max(1, int(rotate_days)))

    processed = 0
    rotated = 0
    skipped = 0
    errors = 0
    items: list[dict[str, Any]] = []

    try:
        q = db.query(GuardBotCredential).filter(GuardBotCredential.status == "ACTIVE")
        if tenant_id:
            q = q.filter(GuardBotCredential.tenant_id == str(tenant_id).strip())
        rows = q.order_by(GuardBotCredential.last_seen_at.asc(), GuardBotCredential.created_at.asc()).limit(max(1, min(int(limit), 5000))).all()

        for row in rows:
            processed += 1
            if not _is_due(row, cutoff=cutoff):
                skipped += 1
                continue

            if dry_run:
                items.append(
                    {
                        "tenant_id": row.tenant_id,
                        "bot_id": row.bot_id,
                        "action": "would_rotate",
                        "key_version": int(row.key_version),
                        "rotated_at": row.rotated_at.isoformat() if row.rotated_at else None,
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                    }
                )
                continue

            try:
                out = guard_service.rotate_bot_credential(db, tenant_id=row.tenant_id, bot_id=row.bot_id, actor=actor)
                items.append(
                    {
                        "tenant_id": row.tenant_id,
                        "bot_id": row.bot_id,
                        "action": "rotated",
                        "key_version": int((out or {}).get("key_version") or row.key_version),
                        "rotated_at": (out or {}).get("rotated_at"),
                    }
                )
                rotated += 1
            except Exception as exc:  # noqa: BLE001
                errors += 1
                items.append(
                    {
                        "tenant_id": row.tenant_id,
                        "bot_id": row.bot_id,
                        "action": "error",
                        "error": str(exc),
                    }
                )

        if not dry_run:
            db.commit()

        return {
            "ok": errors == 0,
            "dry_run": dry_run,
            "cutoff": cutoff.isoformat(),
            "processed": processed,
            "rotated": rotated,
            "skipped": skipped,
            "errors": errors,
            "items": items,
        }
    finally:
        db.close()


def main() -> int:
    s = get_settings()

    parser = ArgumentParser(description="Rotate stale guard bot credentials")
    parser.add_argument("--tenant-id", default=None)
    parser.add_argument("--rotate-days", type=int, default=max(1, int(s.guard_bot_credential_auto_rotate_days)))
    parser.add_argument("--limit", type=int, default=max(1, int(s.guard_bot_credential_rotation_batch_size)))
    parser.add_argument("--actor", default="security-rotation-worker")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    enabled = bool(s.security_key_rotation_worker_enabled)
    if not enabled and not args.dry_run:
        out = {
            "ok": False,
            "detail": "security_key_rotation_worker_disabled",
            "hint": "Set SECURITY_KEY_ROTATION_WORKER_ENABLED=true or use --dry-run",
        }
        print(json.dumps(out, ensure_ascii=False))
        return 2

    out = run_once(
        tenant_id=(str(args.tenant_id).strip() or None),
        rotate_days=max(1, int(args.rotate_days)),
        limit=max(1, int(args.limit)),
        dry_run=bool(args.dry_run),
        actor=str(args.actor or "security-rotation-worker")[:255],
    )

    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(
            "security_rotation_worker"
            f" dry_run={out.get('dry_run')}"
            f" processed={out.get('processed')}"
            f" rotated={out.get('rotated')}"
            f" skipped={out.get('skipped')}"
            f" errors={out.get('errors')}"
        )

    return 0 if bool(out.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())