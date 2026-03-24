from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def registered_paths() -> set[str]:
    return {
        route.path
        for route in app.routes
        if isinstance(route, APIRoute)
    }


# Contract tests below validate endpoint/domain behavior, not device-lease state.
# Keep policy path active while providing deterministic request context.
_DEVICE_POLICY_CONTRACT_MODULES = {
    "test_ai_document_understanding_api.py",
    "test_ai_order_document_intake.py",
    "test_ai_order_draft_assist.py",
    "test_ai_order_drafting_api.py",
    "test_ai_order_feedback_api.py",
    "test_ai_order_intake_feedback.py",
    "test_ai_order_reference_retrieval_api.py",
    "test_ai_orders_copilot_api.py",
    "test_ai_template_submission_staging.py",
    "test_ai_tenant_retrieval_action_guard.py",
    "test_orders_contract.py",
    "test_partners_contract.py",
    "test_perf_request_authz_cache.py",
}


@pytest.fixture(autouse=True)
def _device_policy_contract_shim(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    module_name = Path(str(request.fspath)).name
    if module_name not in _DEVICE_POLICY_CONTRACT_MODULES:
        return

    if module_name == "test_perf_request_authz_cache.py":
        import app.core.policy_matrix as policy_matrix

        monkeypatch.setattr(policy_matrix, "_device_policy_enabled", lambda: False)
        return

    import app.modules.guard.service as guard_service_module

    def _ok_active(*_args, **_kwargs):
        return {
            "ok": True,
            "state": "ACTIVE",
            "non_blocking": True,
        }

    orig_request = TestClient.request

    def _request_with_default_device(self, method, url, **kwargs):  # noqa: ANN001
        headers = dict(kwargs.get("headers") or {})
        headers.setdefault("X-Device-ID", "test-device-001")
        kwargs["headers"] = headers
        return orig_request(self, method, url, **kwargs)

    monkeypatch.setattr(guard_service_module.service, "assert_request_device_active", _ok_active)
    monkeypatch.setattr(TestClient, "request", _request_with_default_device)
