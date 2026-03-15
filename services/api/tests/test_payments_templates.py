from datetime import datetime, timezone

from app.modules.payments.service import service


def test_required_fields_bg_include_numeric_checks() -> None:
    fields = service._required_fields_for_policy({"template_code": "BG_VAT_V1", "vat_mode": "STANDARD"})
    assert "invoice.number_numeric" in fields
    assert "invoice.number_digits_valid" in fields
    assert "tax.vat_rate_percent" in fields


def test_required_fields_eu_exclude_bg_numeric_checks() -> None:
    fields = service._required_fields_for_policy({"template_code": "EU_VAT_V1", "vat_mode": "STANDARD"})
    assert "invoice.number_numeric" not in fields
    assert "invoice.number_digits_valid" not in fields
    assert "tax.vat_rate_percent" in fields


def test_invoice_numbering_modes() -> None:
    ts = datetime(2026, 3, 7, 12, 0, 0, tzinfo=timezone.utc)

    bg = service._build_invoice_number(issue_at=ts, serial=42, numbering_mode="BG_NUMERIC10")
    eu = service._build_invoice_number(issue_at=ts, serial=42, numbering_mode="AUTO_EU")

    assert bg == "0000000042"
    assert eu == "INV-202603-000042"
