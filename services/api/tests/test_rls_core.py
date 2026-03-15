from app.core.rls import RLSScopeViolationError, rls_context_from_claims, validate_tenant_write_scope


class _TenantObj:
    def __init__(self, tenant_id: str | None) -> None:
        self.tenant_id = tenant_id


class _WorkspaceObj:
    def __init__(self, workspace_type: str, workspace_id: str | None) -> None:
        self.workspace_type = workspace_type
        self.workspace_id = workspace_id


def test_rls_context_tenant_user() -> None:
    ctx = rls_context_from_claims({'sub': 'u@t', 'roles': ['TENANT_ADMIN'], 'tenant_id': 't-1'})
    assert ctx['mode'] == 'TENANT_SCOPED'
    assert ctx['tenant_id'] == 't-1'


def test_rls_context_superadmin_global() -> None:
    ctx = rls_context_from_claims({'sub': 'sa@x', 'roles': ['SUPERADMIN'], 'tenant_id': 'platform'})
    assert ctx['mode'] == 'SUPERADMIN_GLOBAL'
    assert ctx['tenant_id'] is None


def test_rls_context_superadmin_support_scope() -> None:
    ctx = rls_context_from_claims({'sub': 'sa@x', 'roles': ['SUPERADMIN'], 'tenant_id': 'platform', 'support_tenant_id': 't-9', 'support_session_id': 'abc'})
    assert ctx['mode'] == 'TENANT_SCOPED'
    assert ctx['tenant_id'] == 't-9'


def test_rls_write_scope_allows_same_tenant() -> None:
    validate_tenant_write_scope(
        rls_enabled=True,
        rls_bypass=False,
        rls_tenant_id='t-1',
        objects=[_TenantObj('t-1'), _WorkspaceObj('TENANT', 't-1')],
    )


def test_rls_write_scope_blocks_cross_tenant() -> None:
    try:
        validate_tenant_write_scope(
            rls_enabled=True,
            rls_bypass=False,
            rls_tenant_id='t-1',
            objects=[_TenantObj('t-2')],
        )
        assert False, 'expected RLSScopeViolationError'
    except RLSScopeViolationError as exc:
        assert str(exc) == 'rls_tenant_scope_violation'


def test_rls_write_scope_blocks_platform_workspace_for_tenant_scope() -> None:
    try:
        validate_tenant_write_scope(
            rls_enabled=True,
            rls_bypass=False,
            rls_tenant_id='t-1',
            objects=[_WorkspaceObj('PLATFORM', 'platform')],
        )
        assert False, 'expected RLSScopeViolationError'
    except RLSScopeViolationError as exc:
        assert str(exc) == 'rls_platform_workspace_write_forbidden'