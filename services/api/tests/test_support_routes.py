def test_support_routes_registered(registered_paths: set[str]) -> None:
    paths = registered_paths

    assert '/support/tenant/requests' in paths
    assert '/support/tenant/requests/{request_id}/open-door' in paths
    assert '/support/tenant/requests/{request_id}/close' in paths
    assert '/support/tenant/requests/{request_id}/messages' in paths
    assert '/support/tenant/requests/{request_id}/chat-bot' in paths

    assert '/support/superadmin/requests' in paths
    assert '/support/superadmin/requests/{request_id}/start-session' in paths
    assert '/support/superadmin/sessions' in paths
    assert '/support/superadmin/sessions/{session_id}/end' in paths
    assert '/support/superadmin/sessions/{session_id}/issue-token' in paths
    assert '/support/superadmin/requests/{request_id}/messages' in paths
    assert '/support/superadmin/faq' in paths
    assert '/support/superadmin/faq/{entry_id}' in paths

    assert '/support/public/faq' in paths