from __future__ import annotations

import app.modules.ai.order_retrieval_execution_service as retrieval_service_mod
import app.modules.ai.tenant_retrieval_action_guard as guard_mod


class _FakeQuery:
    def __init__(self, scalar_value: object | None) -> None:
        self._scalar_value = scalar_value

    def filter(self, *_args, **_kwargs) -> "_FakeQuery":
        return self

    def scalar(self) -> object | None:
        return self._scalar_value


class _ReadOnlyDB:
    def __init__(self, *, scalar_value: object | None) -> None:
        self.scalar_value = scalar_value
        self.query_calls = 0
        self.add_calls = 0
        self.flush_calls = 0
        self.commit_calls = 0

    def query(self, *_args, **_kwargs) -> _FakeQuery:
        self.query_calls += 1
        return _FakeQuery(self.scalar_value)

    def add(self, *_args, **_kwargs) -> None:
        self.add_calls += 1
        raise AssertionError("retrieval_execution_must_be_read_only")

    def flush(self) -> None:
        self.flush_calls += 1
        raise AssertionError("retrieval_execution_must_be_read_only")

    def commit(self) -> None:
        self.commit_calls += 1
        raise AssertionError("retrieval_execution_must_be_read_only")


def test_order_retrieval_execution_allow_returns_minimal_summary(monkeypatch) -> None:
    db = _ReadOnlyDB(scalar_value="ord-visible-001")
    monkeypatch.setattr(
        retrieval_service_mod.tenant_retrieval_action_guard,
        "validate_order_reference_access",
        lambda **_kwargs: guard_mod.TenantRetrievalActionGuardResult(allowed=True, code="allow"),
    )

    out = retrieval_service_mod.service.retrieve_order_reference(
        db=db,  # type: ignore[arg-type]
        tenant_id="tenant-ai-001",
        order_reference_id="ord-visible-001",
        template_fingerprint=None,
    )

    assert out.object_type == "order"
    assert out.object_id == "ord-visible-001"
    assert out.template_fingerprint is None
    assert out.tenant_visible is True
    assert out.retrieval_traceability.guard_outcome == "allow"
    assert out.retrieval_traceability.retrieval_marker == "summary_only_guarded_reference_lookup"

    dumped = out.model_dump()
    dump_text = str(dumped).lower()
    assert "payload" not in dump_text
    assert "source_traceability" not in dump_text
    assert db.add_calls == 0
    assert db.flush_calls == 0
    assert db.commit_calls == 0
    assert db.query_calls == 1


def test_order_retrieval_execution_hidden_object_safe_deny_missing_vs_inaccessible(monkeypatch) -> None:
    db = _ReadOnlyDB(scalar_value="ord-visible-001")

    def _guard_stub(**kwargs):
        ref = str(kwargs.get("order_reference_id") or "").strip()
        if not ref:
            raise ValueError(guard_mod.OBJECT_REFERENCE_NOT_ACCESSIBLE)
        if ref == "ord-hidden-001":
            raise ValueError(guard_mod.OBJECT_REFERENCE_NOT_ACCESSIBLE)
        return guard_mod.TenantRetrievalActionGuardResult(allowed=True, code="allow")

    monkeypatch.setattr(
        retrieval_service_mod.tenant_retrieval_action_guard,
        "validate_order_reference_access",
        _guard_stub,
    )

    missing_err: str | None = None
    hidden_err: str | None = None

    try:
        retrieval_service_mod.service.retrieve_order_reference(
            db=db,  # type: ignore[arg-type]
            tenant_id="tenant-ai-001",
            order_reference_id=None,
        )
    except ValueError as exc:
        missing_err = str(exc)

    try:
        retrieval_service_mod.service.retrieve_order_reference(
            db=db,  # type: ignore[arg-type]
            tenant_id="tenant-ai-001",
            order_reference_id="ord-hidden-001",
        )
    except ValueError as exc:
        hidden_err = str(exc)

    assert missing_err == guard_mod.OBJECT_REFERENCE_NOT_ACCESSIBLE
    assert hidden_err == guard_mod.OBJECT_REFERENCE_NOT_ACCESSIBLE
    assert db.add_calls == 0
    assert db.flush_calls == 0
    assert db.commit_calls == 0
