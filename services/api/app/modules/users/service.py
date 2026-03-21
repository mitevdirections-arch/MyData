from __future__ import annotations

from app.modules.profile.service_parts.shared import ProfileSharedMixin
from app.modules.users.service_parts import (
    UsersAddressesMixin,
    UsersContactsMixin,
    UsersCredentialsMixin,
    UsersDocumentsMixin,
    UsersMembershipMixin,
    UsersNextOfKinMixin,
    UsersProfileMixin,
    UsersSharedMixin,
)


class UsersService(
    UsersSharedMixin,
    ProfileSharedMixin,
    UsersMembershipMixin,
    UsersProfileMixin,
    UsersContactsMixin,
    UsersAddressesMixin,
    UsersDocumentsMixin,
    UsersNextOfKinMixin,
    UsersCredentialsMixin,
):
    """Canonical users-domain service boundary."""


service = UsersService()
