def test_payments_routes_registered(registered_paths: set[str]) -> None:
    paths = registered_paths

    assert '/admin/payments/credit-account' in paths
    assert '/admin/payments/invoice-template' in paths
    assert '/admin/payments/invoice-template/preview' in paths
    assert '/admin/payments/invoices' in paths
    assert '/admin/payments/invoices/{invoice_id}/document' in paths

    assert '/superadmin/payments/credit-accounts' in paths
    assert '/superadmin/payments/credit-accounts/{tenant_id}' in paths
    assert '/superadmin/payments/invoice-template/{tenant_id}' in paths
    assert '/superadmin/payments/invoices' in paths
    assert '/superadmin/payments/invoices/{invoice_id}/document' in paths
    assert '/superadmin/payments/invoices/{invoice_id}/mark-paid' in paths
    assert '/superadmin/payments/overdue/run-once' in paths