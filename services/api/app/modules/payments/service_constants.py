from __future__ import annotations

from typing import Any

ALLOWED_PAYMENT_MODE = {"PREPAID", "DEFERRED"}
ALLOWED_ACCOUNT_STATUS = {"ACTIVE", "SUSPENDED"}
ALLOWED_CURRENCIES = {"EUR", "USD", "BGN"}
OPEN_INVOICE_STATUSES = {"ISSUED", "OVERDUE"}
ALLOWED_INVOICE_STATUS = {"ISSUED", "PAID", "OVERDUE", "CANCELED"}

ALLOWED_TEMPLATE_CODES = {"EU_VAT_V1", "BG_VAT_V1"}
ALLOWED_NUMBERING_MODE = {"AUTO_EU", "BG_NUMERIC10"}
ALLOWED_VAT_MODE = {"STANDARD", "EXEMPT", "REVERSE_CHARGE", "OUT_OF_SCOPE"}
ALLOWED_ENFORCEMENT_MODE = {"WARN", "STRICT"}

WORKSPACE_TENANT = "TENANT"
WORKSPACE_PLATFORM = "PLATFORM"
PLATFORM_WORKSPACE_ID = "platform"

DEFAULT_TEMPLATE_POLICY: dict[str, Any] = {
    "version": "v1",
    "template_code": "EU_VAT_V1",
    "numbering_mode": "AUTO_EU",
    "vat_mode": "STANDARD",
    "vat_rate_percent": 20,
    "enforcement_mode": "WARN",
    "country_code": "EU",
}

EU_REQUIRED_BASE = [
    "invoice.number",
    "invoice.issue_date",
    "invoice.currency",
    "seller.legal_name",
    "seller.address.line1",
    "seller.address.country_code",
    "seller.vat_number",
    "buyer.legal_name",
    "buyer.address.line1",
    "buyer.address.country_code",
    "lines[0].description",
    "lines[0].quantity",
    "lines[0].unit_price_minor",
    "totals.taxable_amount_minor",
    "totals.tax_amount_minor",
    "totals.payable_amount_minor",
    "payment.due_date",
]

BG_EXTRA_REQUIRED = [
    "invoice.number_numeric",
    "invoice.number_digits_valid",
]

__all__ = [
    "ALLOWED_PAYMENT_MODE",
    "ALLOWED_ACCOUNT_STATUS",
    "ALLOWED_CURRENCIES",
    "OPEN_INVOICE_STATUSES",
    "ALLOWED_INVOICE_STATUS",
    "ALLOWED_TEMPLATE_CODES",
    "ALLOWED_NUMBERING_MODE",
    "ALLOWED_VAT_MODE",
    "ALLOWED_ENFORCEMENT_MODE",
    "WORKSPACE_TENANT",
    "WORKSPACE_PLATFORM",
    "PLATFORM_WORKSPACE_ID",
    "DEFAULT_TEMPLATE_POLICY",
    "EU_REQUIRED_BASE",
    "BG_EXTRA_REQUIRED",
]
