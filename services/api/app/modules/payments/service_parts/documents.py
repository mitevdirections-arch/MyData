from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import PaymentInvoice, PaymentInvoiceSequence, WorkspaceOrganizationProfile
from app.modules.payments.service_constants import (
    DEFAULT_TEMPLATE_POLICY,
    PLATFORM_WORKSPACE_ID,
    WORKSPACE_TENANT,
)


class PaymentsDocumentsMixin:
    def _as_party(self, org: WorkspaceOrganizationProfile | None, *, fallback_name: str | None = None, fallback_vat: str | None = None, fallback_country: str | None = None) -> dict[str, Any]:
        return {
            "legal_name": self._clean((org.legal_name if org is not None else fallback_name), 255) or None,
            "vat_number": self._clean((org.vat_number if org is not None else fallback_vat), 64) or None,
            "registration_number": self._clean((org.registration_number if org is not None else None), 64) or None,
            "address": {
                "country_code": self._clean((org.address_country_code if org is not None else fallback_country), 8).upper() or None,
                "line1": self._clean((org.address_line1 if org is not None else None), 255) or None,
                "line2": self._clean((org.address_line2 if org is not None else None), 255) or None,
                "city": self._clean((org.address_city if org is not None else None), 128) or None,
                "postal_code": self._clean((org.address_postal_code if org is not None else None), 32) or None,
            },
            "contact": {
                "email": self._clean((org.contact_email if org is not None else None), 255) or None,
                "phone": self._clean((org.contact_phone if org is not None else None), 64) or None,
            },
            "bank": {
                "account_holder": self._clean((org.bank_account_holder if org is not None else None), 255) or None,
                "iban": self._clean((org.bank_iban if org is not None else None), 64) or None,
                "swift": self._clean((org.bank_swift if org is not None else None), 32) or None,
                "bank_name": self._clean((org.bank_name if org is not None else None), 255) or None,
                "currency": self._clean((org.bank_currency if org is not None else None), 16).upper() or None,
            },
        }

    def _next_invoice_serial(self, db: Session, *, tenant_id: str) -> int:
        row = db.query(PaymentInvoiceSequence).filter(PaymentInvoiceSequence.tenant_id == tenant_id).first()
        if row is None:
            row = PaymentInvoiceSequence(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                next_serial=2,
                updated_at=self._now(),
            )
            db.add(row)
            db.flush()
            return 1

        serial = max(1, int(row.next_serial or 1))
        row.next_serial = serial + 1
        row.updated_at = self._now()
        db.flush()
        return serial

    def _build_invoice_number(self, *, issue_at: datetime, serial: int, numbering_mode: str) -> str:
        mode = self._numbering_mode(numbering_mode, "AUTO_EU")
        if mode == "BG_NUMERIC10":
            if serial > 9_999_999_999:
                raise ValueError("invoice_sequence_exhausted")
            return f"{serial:010d}"
        return f"INV-{issue_at:%Y%m}-{serial:06d}"

    def _calc_vat_minor(self, *, amount_minor: int, vat_rate_percent: int) -> int:
        base = Decimal(str(max(0, amount_minor)))
        rate = Decimal(str(max(0, vat_rate_percent)))
        out = (base * rate / Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return int(out)

    def _build_invoice_document(
        self,
        db: Session,
        *,
        tenant_id: str,
        invoice_no: str,
        template_code: str,
        issue_at: datetime,
        due_at: datetime,
        amount_minor: int,
        currency: str,
        description: str,
        module_code: str | None,
        source_type: str,
        source_ref: str | None,
        policy: dict[str, Any],
    ) -> dict[str, Any]:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()

        seller_org = (
            db.query(WorkspaceOrganizationProfile)
            .filter(
                WorkspaceOrganizationProfile.workspace_type == WORKSPACE_PLATFORM,
                WorkspaceOrganizationProfile.workspace_id == PLATFORM_WORKSPACE_ID,
            )
            .first()
        )
        buyer_org = (
            db.query(WorkspaceOrganizationProfile)
            .filter(
                WorkspaceOrganizationProfile.workspace_type == WORKSPACE_TENANT,
                WorkspaceOrganizationProfile.workspace_id == tenant_id,
            )
            .first()
        )

        seller = self._as_party(seller_org, fallback_name="MyData Platform", fallback_vat=None, fallback_country="EU")
        buyer = self._as_party(
            buyer_org,
            fallback_name=(tenant.name if tenant is not None else tenant_id),
            fallback_vat=(tenant.vat_number if tenant is not None else None),
            fallback_country=self._tenant_country_code(db, tenant_id=tenant_id),
        )

        vat_mode = self._vat_mode(policy.get("vat_mode"), "STANDARD")
        vat_rate_percent = int(policy.get("vat_rate_percent") or 0)
        if vat_mode != "STANDARD":
            vat_rate_percent = 0

        taxable_amount_minor = max(0, int(amount_minor))
        tax_amount_minor = self._calc_vat_minor(amount_minor=taxable_amount_minor, vat_rate_percent=vat_rate_percent) if vat_mode == "STANDARD" else 0
        payable_amount_minor = taxable_amount_minor + tax_amount_minor

        exemption_reason = self._clean(policy.get("exemption_reason"), 512) or None
        reverse_charge_note = self._clean(policy.get("reverse_charge_note"), 512) or None
        if vat_mode in {"EXEMPT", "OUT_OF_SCOPE"} and exemption_reason is None:
            exemption_reason = "VAT treatment per configured policy"
        if vat_mode == "REVERSE_CHARGE" and reverse_charge_note is None:
            reverse_charge_note = "Reverse charge"
            if exemption_reason is None:
                exemption_reason = "VAT due by recipient (reverse charge)"

        template = self._template_code(template_code, "EU_VAT_V1")
        country_code = self._clean(policy.get("country_code"), 8).upper() or self._tenant_country_code(db, tenant_id=tenant_id)

        issue_date = issue_at.astimezone(timezone.utc).date().isoformat()
        due_date = due_at.astimezone(timezone.utc).date().isoformat()

        document: dict[str, Any] = {
            "template": {"template_code": template, "template_version": "v1", "country_code": country_code},
            "invoice": {
                "number": invoice_no,
                "number_numeric": bool(str(invoice_no or "").isdigit()),
                "number_digits_valid": bool(str(invoice_no or "").isdigit() and len(str(invoice_no)) <= 10),
                "issue_date": issue_date,
                "supply_date": issue_date,
                "due_date": due_date,
                "currency": self._currency(currency, "EUR"),
                "type": "INVOICE",
            },
            "seller": seller,
            "buyer": buyer,
            "lines": [{
                "line_no": 1,
                "description": self._clean(description, 1024) or f"Marketplace module {module_code or 'N/A'}",
                "quantity": 1,
                "unit_code": "SERVICE",
                "unit_price_minor": taxable_amount_minor,
                "taxable_amount_minor": taxable_amount_minor,
                "vat_rate_percent": vat_rate_percent,
                "tax_amount_minor": tax_amount_minor,
                "total_amount_minor": payable_amount_minor,
            }],
            "tax": {
                "vat_mode": vat_mode,
                "vat_rate_percent": vat_rate_percent,
                "exemption_reason": exemption_reason,
                "reverse_charge_note": reverse_charge_note,
            },
            "totals": {
                "taxable_amount_minor": taxable_amount_minor,
                "tax_amount_minor": tax_amount_minor,
                "payable_amount_minor": payable_amount_minor,
            },
            "payment": {"method": "BANK_TRANSFER", "due_date": due_date, "bank": seller.get("bank") or {}},
            "references": {
                "tenant_id": tenant_id,
                "module_code": module_code,
                "source_type": source_type,
                "source_ref": source_ref,
            },
        }

        required_fields = self._required_fields_for_policy(policy)
        missing_fields = self._validate_required_fields(document, required_fields)
        legal_basis = ["EU VAT Directive 2006/112/EC Art. 226"]
        if template == "BG_VAT_V1":
            legal_basis.append("Bulgarian VAT Act (ZDDS) Art. 114")

        document["compliance"] = {
            "valid": len(missing_fields) == 0,
            "missing_fields": missing_fields,
            "required_fields": required_fields,
            "jurisdiction": ("BG" if template == "BG_VAT_V1" else "EU"),
            "enforcement_mode": self._enforcement_mode(policy.get("enforcement_mode"), "WARN"),
            "legal_basis": legal_basis,
            "checked_at": self._now().isoformat(),
        }
        return document

    def preview_invoice_document(self, db: Session, *, tenant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        tid = self._tenant_id(tenant_id)
        current = self.get_invoice_template_policy(db, tenant_id=tid)
        base_policy = dict(current.get("policy") or DEFAULT_TEMPLATE_POLICY)
        override = payload.get("policy") if isinstance(payload.get("policy"), dict) else {}
        policy = self._normalize_template_policy(dict(override or {}), base=base_policy)

        issue_at = self._now()
        try:
            serial = max(1, int(payload.get("preview_serial") or 1))
        except Exception as exc:  # noqa: BLE001
            raise ValueError("preview_serial_invalid") from exc

        invoice_no = self._build_invoice_number(
            issue_at=issue_at,
            serial=serial,
            numbering_mode=str(policy.get("numbering_mode") or "AUTO_EU"),
        )

        amount_minor = self._to_minor(payload.get("amount_minor") if "amount_minor" in payload else 0)
        currency = self._currency(payload.get("currency"), "EUR")
        description = self._clean(payload.get("description"), 1024) or "Invoice preview"
        module_code = self._clean(payload.get("module_code"), 64) or None

        doc = self._build_invoice_document(
            db,
            tenant_id=tid,
            invoice_no=invoice_no,
            template_code=self._template_code(policy.get("template_code"), "EU_VAT_V1"),
            issue_at=issue_at,
            due_at=issue_at + timedelta(days=30),
            amount_minor=amount_minor,
            currency=currency,
            description=description,
            module_code=module_code,
            source_type="PREVIEW",
            source_ref=None,
            policy=policy,
        )

        return {"ok": True, "tenant_id": tid, "policy": policy, "invoice_no": invoice_no, "document": doc}

    def _invoice_to_dict(self, row: PaymentInvoice) -> dict[str, Any]:
        compliance = row.compliance_json if isinstance(row.compliance_json, dict) else {}
        comp_meta = compliance.get("compliance") if isinstance(compliance.get("compliance"), dict) else {}
        return {
            "id": str(row.id),
            "tenant_id": row.tenant_id,
            "source_type": row.source_type,
            "source_ref": row.source_ref,
            "module_code": row.module_code,
            "invoice_no": row.invoice_no,
            "template_code": row.template_code,
            "status": row.status,
            "currency": row.currency,
            "amount_minor": int(row.amount_minor),
            "description": row.description,
            "issue_at": row.issue_at.isoformat() if row.issue_at else None,
            "due_at": row.due_at.isoformat() if row.due_at else None,
            "paid_at": row.paid_at.isoformat() if row.paid_at else None,
            "canceled_at": row.canceled_at.isoformat() if row.canceled_at else None,
            "metadata": row.metadata_json or {},
            "compliance": {
                "valid": bool(comp_meta.get("valid", False)),
                "missing_fields": list(comp_meta.get("missing_fields") or []),
                "enforcement_mode": comp_meta.get("enforcement_mode"),
                "jurisdiction": comp_meta.get("jurisdiction"),
            },
            "updated_by": row.updated_by,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def list_invoices(
        self,
        db: Session,
        *,
        tenant_id: str | None = None,
        status: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        q = db.query(PaymentInvoice)
        if tenant_id:
            q = q.filter(PaymentInvoice.tenant_id == self._tenant_id(tenant_id))
        if status:
            st = self._clean(status, 16).upper()
            if st not in ALLOWED_INVOICE_STATUS:
                raise ValueError("invoice_status_invalid")
            q = q.filter(PaymentInvoice.status == st)

        rows = q.order_by(PaymentInvoice.created_at.desc()).limit(self._limit(limit, 500, 5000)).all()
        return [self._invoice_to_dict(x) for x in rows]

    def get_invoice_document(self, db: Session, *, invoice_id: str, tenant_id: str | None = None) -> dict[str, Any]:
        try:
            iid = uuid.UUID(str(invoice_id))
        except Exception as exc:  # noqa: BLE001
            raise ValueError("invoice_id_invalid") from exc

        q = db.query(PaymentInvoice).filter(PaymentInvoice.id == iid)
        if tenant_id:
            q = q.filter(PaymentInvoice.tenant_id == self._tenant_id(tenant_id))
        row = q.first()
        if row is None:
            raise ValueError("invoice_not_found")

        document = row.compliance_json if isinstance(row.compliance_json, dict) else {}
        if not document:
            base_policy = self.get_invoice_template_policy(db, tenant_id=row.tenant_id).get("policy") or DEFAULT_TEMPLATE_POLICY
            # Historical invoices without stored document must be rebuilt using their
            # own template_code, not the tenant's current template policy.
            policy = self._normalize_template_policy(
                {"template_code": row.template_code},
                base=dict(base_policy),
            )
            document = self._build_invoice_document(
                db,
                tenant_id=row.tenant_id,
                invoice_no=row.invoice_no,
                template_code=row.template_code,
                issue_at=row.issue_at,
                due_at=row.due_at,
                amount_minor=int(row.amount_minor),
                currency=row.currency,
                description=row.description or f"Invoice {row.invoice_no}",
                module_code=row.module_code,
                source_type=row.source_type,
                source_ref=row.source_ref,
                policy=policy,
            )

        return {
            "ok": True,
            "invoice": self._invoice_to_dict(row),
            "document": document,
        }

