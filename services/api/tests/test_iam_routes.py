def test_iam_routes_registered(registered_paths: set[str]) -> None:
    paths = registered_paths

    assert '/iam/permission-registry' in paths
    assert '/iam/role-templates' in paths
    assert '/iam/me/access' in paths
    assert '/iam/me/access/check' in paths
    assert '/iam/admin/rls-context' in paths


def test_licensing_entitlement_v2_route_registered(registered_paths: set[str]) -> None:
    paths = registered_paths
    assert '/licenses/entitlement-v2' in paths
    assert '/licenses/admin/issue-core' in paths
