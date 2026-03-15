from importlib import import_module

from fastapi import APIRouter


def test_profile_router_import_compatibility() -> None:
    mod = import_module("app.modules.profile.router")

    assert hasattr(mod, "router")
    assert hasattr(mod, "super_router")

    assert isinstance(getattr(mod, "router"), APIRouter)
    assert isinstance(getattr(mod, "super_router"), APIRouter)


def test_profile_router_public_entry_points_present() -> None:
    mod = import_module("app.modules.profile.router")

    expected = [
        "router",
        "super_router",
        "user_next_of_kin_router",
        "create_user_next_of_kin",
        "update_user_next_of_kin",
        "delete_user_next_of_kin",
        "list_user_next_of_kin",
    ]

    missing = [name for name in expected if not hasattr(mod, name)]
    assert missing == []


def test_profile_router_contract_paths_registered(registered_paths: set[str]) -> None:
    expected = [
        "/profile/me",
        "/profile/workspace",
        "/profile/workspace/contacts",
        "/profile/workspace/contacts/{contact_id}",
        "/profile/workspace/addresses",
        "/profile/workspace/addresses/{address_id}",
        "/profile/admin/roles",
        "/profile/admin/roles/{role_code}",
        "/profile/admin/users",
        "/profile/admin/users/{user_id}",
        "/profile/admin/users/{user_id}/roles",
        "/profile/admin/users/{user_id}/profile",
        "/profile/admin/users/{user_id}/contacts",
        "/profile/admin/users/{user_id}/contacts/{contact_id}",
        "/profile/admin/users/{user_id}/addresses",
        "/profile/admin/users/{user_id}/addresses/{address_id}",
        "/profile/admin/users/{user_id}/next-of-kin",
        "/profile/admin/users/{user_id}/next-of-kin/{kin_id}",
        "/profile/admin/users/{user_id}/documents",
        "/profile/admin/users/{user_id}/documents/{document_id}",
        "/profile/admin/users/{user_id}/credentials",
        "/profile/admin/users/{user_id}/credentials/issue",
        "/profile/admin/users/{user_id}/credentials/reset-password",
        "/superadmin/meta/tenants-overview",
    ]

    missing = [path for path in expected if path not in registered_paths]
    assert missing == []
