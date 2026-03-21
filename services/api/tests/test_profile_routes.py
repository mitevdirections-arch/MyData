def test_profile_routes_registered(registered_paths: set[str]) -> None:
    paths = registered_paths

    assert '/admin/company/verification-summary' in paths
    assert '/admin/company/verification/recheck' in paths

    assert '/profile/workspace' in paths
    assert '/profile/me/credentials/change-password' in paths
    assert '/profile/me/credentials/change-username' in paths
    assert '/profile/workspace/contacts' in paths
    assert '/profile/workspace/contacts/{contact_id}' in paths
    assert '/profile/workspace/addresses' in paths
    assert '/profile/workspace/addresses/{address_id}' in paths

    assert '/profile/admin/roles/{role_code}' in paths
    assert '/profile/admin/users/{user_id}/profile' in paths
    assert '/profile/admin/users/{user_id}/provision' in paths
    assert '/profile/admin/users/{user_id}/contacts' in paths
    assert '/profile/admin/users/{user_id}/contacts/{contact_id}' in paths
    assert '/profile/admin/users/{user_id}/addresses' in paths
    assert '/profile/admin/users/{user_id}/addresses/{address_id}' in paths
    assert '/profile/admin/users/{user_id}/next-of-kin' in paths
    assert '/profile/admin/users/{user_id}/next-of-kin/{kin_id}' in paths
    assert '/profile/admin/users/{user_id}/documents' in paths
    assert '/profile/admin/users/{user_id}/documents/{document_id}' in paths
    assert '/profile/admin/users/{user_id}/credentials' in paths
    assert '/profile/admin/users/{user_id}/credentials/issue' in paths
    assert '/profile/admin/users/{user_id}/credentials/invite' in paths
    assert '/profile/admin/users/{user_id}/credentials/reset-password' in paths
    assert '/profile/admin/users/{user_id}/credentials/lock' in paths
    assert '/profile/admin/users/{user_id}/credentials/unlock' in paths
    assert '/profile/admin/users/{user_id}/credentials/revoke-invite' in paths


def test_superadmin_meta_route_registered(registered_paths: set[str]) -> None:
    paths = registered_paths

    assert '/superadmin/meta/tenants-overview' in paths
