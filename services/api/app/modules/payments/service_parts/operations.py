from __future__ import annotations

from datetime import datetime
from typing import Any
import uuid

from sqlalchemy.orm import Session

from app.db.models import PaymentAllocation, PaymentInvoice
from app.modules.payments.service_constants import DEFAULT_TEMPLATE_POLICY


class PaymentsOperationsMixin:
    def _ensure_deferred_ready(
        self,
        db: Session,
        *,
        tenant_id: str,
        amount_minor: int,
        currency: str,
    ) -> TenantCreditAccount:
        row = self._account_row(db, tenant_id)
        if row is None:
            raise ValueError("deferred_account_required")

        if str(row.payment_mode or "").upper() != "DEFERRED":
            raise ValueError("deferred_mode_not_enabled")
        if str(row.status or "").upper() != "ACTIVE":
            raise ValueError("deferred_account_not_active")
        if bool(row.overdue_hold):
            raise ValueError("deferred_account_on_hold")

        cur = self._currency(currency, str(row.currency or "EUR"))
        if cur != str(row.currency or "EUR").upper():
            raise ValueError("deferred_currency_mismatch")

        exposure = self._exposure_minor(db, tenant_id)
        new_total = exposure + int(amount_minor)
        if new_total > int(row.credit_limit_minor or 0):
            raise ValueError("deferred_credit_limit_exceeded")

        return row

    def create_deferred_invoice_for_marketplace(
        self,
        db: Session,
        *,
        tenant_id: str,
        module_code: str,
        amount_minor: int,
        currency: str,
        actor: str,
        source_type: str,
        source_ref: str | None,
        description: str | None,
        terms_days: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tid = self._tenant_id(tenant_id)
        amt = self._to_minor(amount_minor)
        if amt <= 0:
            raise ValueError("amount_minor_required")

        cur = self._currency(currency)
        row = self._ensure_deferred_ready(db, tenant_id=tid, amount_minor=amt, currency=cur)

        td = max(1, min(int(terms_days if terms_days is not None else row.terms_days), 365))
        now = self._now()
        due_at = now + timedelta(days=td)

        policy = self.get_invoice_template_policy(db, tenant_id=tid).get("policy") or dict(DEFAULT_TEMPLATE_POLICY)
        serial = self._next_invoice_serial(db, tenant_id=tid)
        invoice_no = self._build_invoice_number(
            issue_at=now,
            serial=serial,
            numbering_mode=str(policy.get("numbering_mode") or "AUTO_EU"),
        )
        template_code = self._template_code(policy.get("template_code"), "EU_VAT_V1")

        doc = self._build_invoice_document(
            db,
            tenant_id=tid,
            invoice_no=invoice_no,
            template_code=template_code,
            issue_at=now,
            due_at=due_at,
            amount_minor=amt,
            currency=cur,
            description=self._clean(description, 1024) or f"Marketplace module {module_code}",
            module_code=module_code,
            source_type=source_type,
            source_ref=source_ref,
            policy=policy,
        )

        compliance = (doc.get("compliance") if isinstance(doc.get("compliance"), dict) else {})
        if str(policy.get("enforcement_mode") or "WARN").upper() == "STRICT" and not bool(compliance.get("valid", False)):
            raise ValueError("invoice_compliance_missing_fields")

        inv = PaymentInvoice(
            id=uuid.uuid4(),
            tenant_id=tid,
            source_type=self._clean(source_type, 32).upper() or "MARKETPLACE",
            source_ref=self._clean(source_ref, 128) or None,
            module_code=self._clean(module_code, 64).upper() or None,
            invoice_no=invoice_no,
            template_code=template_code,
            status="ISSUED",
            currency=cur,
            amount_minor=amt,
            description=self._clean(description, 1024) or None,
            issue_at=now,
            due_at=due_at,
            paid_at=None,
            canceled_at=None,
            metadata_json=(dict(metadata or {}) if isinstance(metadata, dict) else {}),
            compliance_json=doc,
            created_by=str(actor or "unknown"),
            updated_by=str(actor or "unknown"),
            created_at=now,
            updated_at=now,
        )
        db.add(inv)
        db.flush()

        account = self._account_to_dict(db, row, tid)
        return {
            "flow": "DEFERRED_INVOICE",
            "invoice": self._invoice_to_dict(inv),
            "account": account,
        }

    def _sync_tenant_overdue_hold(self, db: Session, tenant_id: str, *, actor: str) -> dict[str, Any] | None:
        row = self._account_row(db, tenant_id)
        if row is None:
            return None
        if str(row.payment_mode or "").upper() != "DEFERRED":
            if bool(row.overdue_hold):
                row.overdue_hold = False
                row.updated_by = str(actor or "system")
                row.updated_at = self._now()
                db.flush()
            return self._account_to_dict(db, row, tenant_id)

        overdue = self._overdue_count(db, tenant_id)
        should_hold = bool(row.auto_hold_on_overdue) and overdue > 0 and str(row.status or "").upper() == "ACTIVE"
        if bool(row.overdue_hold) != should_hold:
            row.overdue_hold = should_hold
            row.updated_by = str(actor or "system")
            row.updated_at = self._now()
            db.flush()
        return self._account_to_dict(db, row, tenant_id)

    def mark_invoice_paid(self, db: Session, *, invoice_id: str, actor: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        try:
            iid = uuid.UUID(str(invoice_id))
        except Exception as exc:  # noqa: BLE001
            raise ValueError("invoice_id_invalid") from exc

        row = db.query(PaymentInvoice).filter(PaymentInvoice.id == iid).first()
        if row is None:
            raise ValueError("invoice_not_found")
        if str(row.status or "").upper() in {"PAID", "CANCELED"}:
            raise ValueError("invoice_not_payable")

        amount_minor = self._to_minor(body.get("amount_minor") if "amount_minor" in body else row.amount_minor)
        if amount_minor != int(row.amount_minor):
            raise ValueError("partial_payment_not_supported")

        now = self._now()
        alloc = PaymentAllocation(
            id=uuid.uuid4(),
            invoice_id=row.id,
            tenant_id=row.tenant_id,
            amount_minor=amount_minor,
            method=self._clean(body.get("method") or "MANUAL", 32).upper() or "MANUAL",
            reference=self._clean(body.get("reference"), 255) or None,
            paid_by=str(actor or "unknown"),
            paid_at=now,
            metadata_json=(dict(body.get("metadata") or {}) if isinstance(body.get("metadata"), dict) else {}),
        )
        db.add(alloc)

        row.status = "PAID"
        row.paid_at = now
        row.updated_by = str(actor or "unknown")
        row.updated_at = now
        db.flush()

        account = self._sync_tenant_overdue_hold(db, row.tenant_id, actor=actor)
        return {
            "ok": True,
            "invoice": self._invoice_to_dict(row),
            "allocation": {
                "id": str(alloc.id),
                "amount_minor": int(alloc.amount_minor),
                "method": alloc.method,
                "reference": alloc.reference,
                "paid_by": alloc.paid_by,
                "paid_at": alloc.paid_at.isoformat() if alloc.paid_at else None,
            },
            "account": account,
        }

    def run_overdue_sync(
        self,
        db: Session,
        *,
        actor: str,
        tenant_id: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        now = self._now()
        q = db.query(PaymentInvoice).filter(PaymentInvoice.status == "ISSUED", PaymentInvoice.due_at < now)
        if tenant_id:
            q = q.filter(PaymentInvoice.tenant_id == self._tenant_id(tenant_id))

        rows = q.order_by(PaymentInvoice.due_at.asc()).limit(self._limit(limit, 500, 5000)).all()

        touched_tenants: set[str] = set()
        changed = 0
        for row in rows:
            row.status = "OVERDUE"
            row.updated_by = str(actor or "system")
            row.updated_at = now
            touched_tenants.add(str(row.tenant_id))
            changed += 1

        if tenant_id:
            touched_tenants.add(self._tenant_id(tenant_id))

        accounts_updated: list[dict[str, Any]] = []
        for tid in sorted(touched_tenants):
            out = self._sync_tenant_overdue_hold(db, tid, actor=actor)
            if out is not None:
                accounts_updated.append(out)

        return {
            "ok": True,
            "processed": len(rows),
            "marked_overdue": changed,
            "tenants_touched": len(touched_tenants),
            "accounts_updated": len(accounts_updated),
            "items": [self._invoice_to_dict(x) for x in rows],
        }


