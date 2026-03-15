def test_orders_routes_registered(registered_paths: set[str]) -> None:
    paths = registered_paths

    assert '/orders' in paths
    assert '/orders/{order_id}' in paths