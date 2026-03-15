from importlib import import_module


def test_profile_service_import_compatibility() -> None:
    mod = import_module("app.modules.profile.service")

    assert hasattr(mod, "ProfileService")
    assert hasattr(mod, "service")

    cls = getattr(mod, "ProfileService")
    svc = getattr(mod, "service")

    assert isinstance(svc, cls)


def test_profile_service_constant_exports() -> None:
    mod = import_module("app.modules.profile.service")

    expected = ["WORKSPACE_TENANT", "WORKSPACE_PLATFORM", "PLATFORM_WORKSPACE_ID"]
    missing = [name for name in expected if not hasattr(mod, name)]
    assert missing == []


def test_profile_service_public_entry_points_present() -> None:
    mod = import_module("app.modules.profile.service")
    svc = getattr(mod, "service")

    expected = [
        "resolve_workspace",
        "_ensure_workspace_exists",
        "get_or_create_admin_profile",
        "update_admin_profile",
        "get_or_create_organization_profile",
        "update_organization_profile",
        "list_contact_points",
        "upsert_contact_point",
        "delete_contact_point",
        "list_addresses",
        "upsert_address",
        "delete_address",
        "list_roles",
        "upsert_role",
        "list_workspace_users",
        "upsert_workspace_user",
        "get_workspace_user",
        "set_workspace_user_roles",
        "superadmin_platform_overview",
    ]

    missing = [name for name in expected if not callable(getattr(svc, name, None))]
    assert missing == []