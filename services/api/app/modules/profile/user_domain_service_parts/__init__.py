from .shared import UserDomainSharedMixin
from .users import UserDomainUsersMixin
from .contacts import UserDomainContactsMixin
from .addresses import UserDomainAddressesMixin
from .documents import UserDomainDocumentsMixin
from .next_of_kin import UserDomainNextOfKinMixin
from .credentials import UserDomainCredentialsMixin

__all__ = [
    "UserDomainSharedMixin",
    "UserDomainUsersMixin",
    "UserDomainContactsMixin",
    "UserDomainAddressesMixin",
    "UserDomainDocumentsMixin",
    "UserDomainNextOfKinMixin",
    "UserDomainCredentialsMixin",
]
