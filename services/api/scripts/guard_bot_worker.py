from __future__ import annotations

import argparse
import time

from app.core.settings import get_settings
from app.db.session import get_session_factory
from app.modules.guard.service import service


def run_once(*, actor: str, tenant_id: str | None, mode: str, limit: int) -> dict:
    db = get_session_factory()()
    try:
        return service.bot_sweep_once(
            db,
            actor=actor,
            tenant_id=tenant_id,
            limit=limit,
            mode=mode,
        )
    finally:
        db.close()


def _parse_args() -> argparse.Namespace:
    s = get_settings()
    p = argparse.ArgumentParser(description="Guard bot sweep worker")
    p.add_argument("--once", action="store_true", help="Run one sweep and exit")
    p.add_argument("--tenant-id", default=None, help="Optional single tenant sweep")
    p.add_argument("--mode", default=s.guard_bot_default_mode, help="Sweep mode label (e.g. SCHEDULED/MANUAL)")
    p.add_argument("--limit", type=int, default=int(s.guard_bot_sweep_limit), help="Max tenants per run")
    p.add_argument("--interval-seconds", type=int, default=int(s.guard_bot_sweep_interval_seconds), help="Loop interval")
    p.add_argument("--actor", default="guard-bot-worker", help="Actor label for audit/check notes")
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    def _do_run() -> dict:
        out = run_once(
            actor=str(args.actor),
            tenant_id=(str(args.tenant_id).strip() if args.tenant_id else None),
            mode=str(args.mode).strip().upper() or "SCHEDULED",
            limit=max(1, min(int(args.limit), 1000)),
        )
        print(
            f"guard_bot_run={out.get('run_id')} checked={out.get('checked_tenants')} "
            f"allow={out.get('allow_tenants')} restrict={out.get('restrict_tenants')}"
        )
        return out

    if args.once:
        _do_run()
        return 0

    interval = max(30, int(args.interval_seconds))
    print(f"guard_bot_worker=started interval_seconds={interval} mode={str(args.mode).strip().upper()}")
    while True:
        try:
            _do_run()
        except Exception as exc:  # noqa: BLE001
            print(f"guard_bot_worker_error={exc}")
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
