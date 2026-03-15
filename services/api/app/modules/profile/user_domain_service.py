from __future__ import annotations

from app.modules.profile.user_domain_service_parts import (
    UserDomainAddressesMixin,
    UserDomainContactsMixin,
    UserDomainCredentialsMixin,
    UserDomainDocumentsMixin,
    UserDomainNextOfKinMixin,
    UserDomainSharedMixin,
    UserDomainUsersMixin,
)


class UserDomainService(
    UserDomainSharedMixin,
    UserDomainUsersMixin,
    UserDomainContactsMixin,
    UserDomainAddressesMixin,
    UserDomainDocumentsMixin,
    UserDomainNextOfKinMixin,
    UserDomainCredentialsMixin,
):
    """Compatibility facade preserving the original public service contract."""


service = UserDomainService()
