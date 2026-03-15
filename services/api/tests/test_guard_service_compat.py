from importlib import import_module


def test_guard_service_import_compatibility() -> None:
    mod = import_module("app.modules.guard.service")

    assert hasattr(mod, "GuardService")
    assert hasattr(mod, "service")
    assert hasattr(mod, "VALID_HEARTBEAT_EVENTS")

    cls = getattr(mod, "GuardService")
    svc = getattr(mod, "service")

    assert isinstance(svc, cls)


def test_guard_service_public_entry_points_present() -> None:
    mod = import_module("app.modules.guard.service")
    svc = getattr(mod, "service")

    expected = [
        "get_behavior_policy",
        "ingest",
        "verify_leases_vs_heartbeats",
        "issue_bot_credential",
        "rotate_bot_credential",
        "revoke_bot_credential",
        "list_bot_credentials",
        "verify_bot_signature",
        "verify_license_snapshot",
        "list_locked_bot_credentials",
        "unlock_bot_credential",
        "bot_check_tenant",
        "bot_sweep_once",
        "list_bot_checks",
        "record_security_flag",
        "tenant_status",
        "lease_device",
        "get_lease",
    ]

    missing = [name for name in expected if not callable(getattr(svc, name, None))]
    assert missing == []
