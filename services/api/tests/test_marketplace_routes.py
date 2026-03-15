def test_marketplace_routes_registered(registered_paths: set[str]) -> None:
    paths = registered_paths

    assert '/marketplace/catalog' in paths
    assert '/marketplace/offers/active' in paths
    assert '/marketplace/purchase-requests' in paths

    assert '/marketplace/admin/catalog' in paths
    assert '/marketplace/admin/catalog/{module_code}' in paths
    assert '/marketplace/admin/offers' in paths
    assert '/marketplace/admin/offers/{offer_id}' in paths
    assert '/marketplace/admin/purchase-requests' in paths
    assert '/marketplace/admin/purchase-requests/{request_id}/approve' in paths
    assert '/marketplace/admin/purchase-requests/{request_id}/reject' in paths