def test_partners_routes_registered(registered_paths: set[str]) -> None:
    paths = registered_paths
    assert "/partners" in paths
    assert "/partners/{partner_id}" in paths
    assert "/partners/{partner_id}/archive" in paths
    assert "/partners/{partner_id}/roles" in paths
    assert "/partners/{partner_id}/blacklist" in paths
    assert "/partners/{partner_id}/watchlist" in paths
    assert "/partners/{partner_id}/ratings" in paths
    assert "/partners/{partner_id}/rating-summary" in paths
    assert "/partners/{partner_id}/global-signal" in paths
