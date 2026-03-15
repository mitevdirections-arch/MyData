from app.core.permissions import (
    dedupe_permissions,
    effective_permissions_from_claims,
    is_permission_allowed,
    list_permission_registry,
    permission_matches,
)


def test_permission_match_wildcard() -> None:
    assert permission_matches('*', 'SECURITY.READ') is True
    assert permission_matches('SECURITY.*', 'SECURITY.READ') is True
    assert permission_matches('SECURITY.*', 'SECURITY.WRITE') is True
    assert permission_matches('SECURITY.READ', 'SECURITY.READ') is True
    assert permission_matches('SECURITY.READ', 'SECURITY.WRITE') is False


def test_permission_allow_dedupe() -> None:
    effective = dedupe_permissions(['security.read', 'SECURITY.READ', 'SECURITY.*'])
    assert 'SECURITY.READ' in effective
    assert is_permission_allowed('SECURITY.WRITE', effective) is True
    assert is_permission_allowed('TENANTS.WRITE', effective) is False


def test_permission_registry_workspace_filter() -> None:
    tenant_items = list_permission_registry(workspace_type='TENANT')
    platform_items = list_permission_registry(workspace_type='PLATFORM')
    assert len(tenant_items) > 0
    assert len(platform_items) > 0
    assert any(x.get('permission_code') == 'TENANTS.WRITE' for x in platform_items)


def test_effective_permissions_from_claims_role_fallback() -> None:
    claims = {'roles': ['support_agent'], 'perms': ['profile.read']}
    effective = effective_permissions_from_claims(claims)
    assert 'PROFILE.READ' in effective
    assert 'SUPPORT.READ' in effective
    assert 'SUPPORT.WRITE' in effective


def test_effective_permissions_from_claims_superadmin_wildcard() -> None:
    claims = {'roles': ['SUPERADMIN'], 'perms': []}
    effective = effective_permissions_from_claims(claims)
    assert is_permission_allowed('TENANTS.WRITE', effective) is True
    assert is_permission_allowed('IAM.WRITE', effective) is True