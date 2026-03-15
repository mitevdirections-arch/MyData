def test_security_ops_routes_registered(registered_paths: set[str]) -> None:
    paths = registered_paths

    assert '/superadmin/security/posture' in paths
    assert '/superadmin/security/keys/lifecycle' in paths
    assert '/superadmin/security/events' in paths
    assert '/superadmin/security/kill-switch/tenant/{tenant_id}' in paths

    assert '/superadmin/security/alerts/test-incident' in paths
    assert '/superadmin/security/alerts/queue' in paths
    assert '/superadmin/security/alerts/dispatch-once' in paths
    assert '/superadmin/security/alerts/{alert_id}/requeue' in paths
    assert '/superadmin/security/alerts/{alert_id}/fail-now' in paths