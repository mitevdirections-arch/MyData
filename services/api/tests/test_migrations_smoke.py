import os

import pytest

from scripts.qa_migrations_smoke import run_smoke


def _truthy(v: str | None) -> bool:
    return str(v or "").strip().lower() in {"1", "true", "yes", "on"}


@pytest.mark.integration
def test_forward_only_migrations_clean_and_snapshot_upgrade() -> None:
    if not _truthy(os.getenv("MIGRATIONS_SMOKE_ENABLED")):
        pytest.skip("MIGRATIONS_SMOKE_ENABLED is not true")

    db_url = str(os.getenv("MIGRATIONS_SMOKE_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
    if not db_url:
        pytest.fail("MIGRATIONS_SMOKE_DATABASE_URL or DATABASE_URL is required")

    out = run_smoke(database_url=db_url)
    assert bool(out.get("ok")), out

    checks = out.get("checks") if isinstance(out, dict) else {}
    clean = (checks or {}).get("clean_upgrade") if isinstance(checks, dict) else {}
    snapshot = (checks or {}).get("snapshot_to_head_upgrade") if isinstance(checks, dict) else {}

    assert bool((clean or {}).get("ok")), out
    assert bool((snapshot or {}).get("ok")), out
