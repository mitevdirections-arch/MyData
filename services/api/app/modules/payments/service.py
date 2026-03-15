from __future__ import annotations

from app.modules.payments.service_constants import (
    ALLOWED_ACCOUNT_STATUS,
    ALLOWED_CURRENCIES,
    ALLOWED_ENFORCEMENT_MODE,
    ALLOWED_INVOICE_STATUS,
    ALLOWED_NUMBERING_MODE,
    ALLOWED_PAYMENT_MODE,
    ALLOWED_TEMPLATE_CODES,
    ALLOWED_VAT_MODE,
    BG_EXTRA_REQUIRED,
    DEFAULT_TEMPLATE_POLICY,
    EU_REQUIRED_BASE,
    OPEN_INVOICE_STATUSES,
    PLATFORM_WORKSPACE_ID,
    WORKSPACE_PLATFORM,
    WORKSPACE_TENANT,
)
from app.modules.payments.service_parts import (
    PaymentsDocumentsMixin,
    PaymentsOperationsMixin,
    PaymentsSharedMixin,
    PaymentsTemplatesMixin,
)


class PaymentsService(
    PaymentsSharedMixin,
    PaymentsTemplatesMixin,
    PaymentsDocumentsMixin,
    PaymentsOperationsMixin,
):
    """Compatibility facade preserving the original public payments service contract."""


service = PaymentsService()
