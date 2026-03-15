from importlib import import_module


def test_payments_service_import_compatibility() -> None:
    mod = import_module("app.modules.payments.service")

    assert hasattr(mod, "PaymentsService")
    assert hasattr(mod, "service")
    assert hasattr(mod, "DEFAULT_TEMPLATE_POLICY")

    cls = getattr(mod, "PaymentsService")
    svc = getattr(mod, "service")
    assert isinstance(svc, cls)


def test_payments_service_public_entry_points_present() -> None:
    mod = import_module("app.modules.payments.service")
    svc = getattr(mod, "service")

    expected = [
        "resolve_tenant_payment_profile",
        "upsert_credit_account",
        "list_credit_accounts",
        "list_invoice_templates",
        "get_invoice_template_policy",
        "set_invoice_template_policy",
        "preview_invoice_document",
        "list_invoices",
        "get_invoice_document",
        "create_deferred_invoice_for_marketplace",
        "mark_invoice_paid",
        "run_overdue_sync",
    ]

    missing = [name for name in expected if not callable(getattr(svc, name, None))]
    assert missing == []
