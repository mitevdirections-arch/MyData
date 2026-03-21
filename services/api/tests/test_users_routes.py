def test_users_routes_registered(registered_paths: set[str]) -> None:
    paths = registered_paths

    assert '/users/me' in paths
    assert '/users/admin/roles' in paths
    assert '/users/admin/roles/{role_code}' in paths
    assert '/users/admin/users' in paths
    assert '/users/admin/users/{user_id}' in paths
    assert '/users/admin/users/{user_id}/roles' in paths
    assert '/users/admin/users/{user_id}/provision' in paths
    assert '/users/admin/users/{user_id}/profile' in paths
    assert '/users/admin/users/{user_id}/contacts' in paths
    assert '/users/admin/users/{user_id}/contacts/{contact_id}' in paths
    assert '/users/admin/users/{user_id}/addresses' in paths
    assert '/users/admin/users/{user_id}/addresses/{address_id}' in paths
    assert '/users/admin/users/{user_id}/next-of-kin' in paths
    assert '/users/admin/users/{user_id}/next-of-kin/{kin_id}' in paths
    assert '/users/admin/users/{user_id}/documents' in paths
    assert '/users/admin/users/{user_id}/documents/{document_id}' in paths
    assert '/users/admin/users/{user_id}/credentials' in paths
    assert '/users/admin/users/{user_id}/credentials/issue' in paths
    assert '/users/admin/users/{user_id}/credentials/invite' in paths
    assert '/users/admin/users/{user_id}/credentials/reset-password' in paths
    assert '/users/admin/users/{user_id}/credentials/lock' in paths
    assert '/users/admin/users/{user_id}/credentials/unlock' in paths
    assert '/users/admin/users/{user_id}/credentials/revoke-invite' in paths
