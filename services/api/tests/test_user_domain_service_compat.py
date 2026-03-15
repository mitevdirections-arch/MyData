from importlib import import_module


def test_user_domain_service_import_compatibility() -> None:
    mod = import_module("app.modules.profile.user_domain_service")

    assert hasattr(mod, "UserDomainService")
    assert hasattr(mod, "service")

    cls = getattr(mod, "UserDomainService")
    svc = getattr(mod, "service")

    assert isinstance(svc, cls)


def test_user_domain_service_public_entry_points_present() -> None:
    mod = import_module("app.modules.profile.user_domain_service")
    svc = getattr(mod, "service")

    expected = [
        "get_or_create_user_profile",
        "update_user_profile",
        "list_user_contacts",
        "upsert_user_contact",
        "delete_user_contact",
        "list_user_addresses",
        "upsert_user_address",
        "delete_user_address",
        "list_user_documents",
        "upsert_user_document",
        "delete_user_document",
        "list_user_next_of_kin",
        "upsert_user_next_of_kin",
        "delete_user_next_of_kin",
        "get_user_credential",
        "issue_user_credentials",
        "reset_user_password",
        "bootstrap_first_tenant_admin",
    ]

    missing = [name for name in expected if not callable(getattr(svc, name, None))]
    assert missing == []
