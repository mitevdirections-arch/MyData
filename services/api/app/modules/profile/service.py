from __future__ import annotations

from app.modules.profile.service_constants import (
    CORE_PLAN_SEATS,
    DEFAULT_PLATFORM_ROLES,
    DEFAULT_TENANT_ROLES,
    PERM_RE,
    PLATFORM_WORKSPACE_ID,
    ROLE_CODE_RE,
    UNLIMITED_CORE_PLANS,
    WORKSPACE_PLATFORM,
    WORKSPACE_TENANT,
)
from app.modules.profile.service_parts import (
    ProfileAdminProfileMixin,
    ProfileOrganizationMixin,
    ProfileOverviewMixin,
    ProfileRoleUserMixin,
    ProfileSharedMixin,
)


class ProfileService(
    ProfileSharedMixin,
    ProfileAdminProfileMixin,
    ProfileOrganizationMixin,
    ProfileRoleUserMixin,
    ProfileOverviewMixin,
):
    """Compatibility facade preserving the original public service contract."""


service = ProfileService()
