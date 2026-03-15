from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import PaymentInvoice, Tenant, TenantCreditAccount
from app.modules.payments.service_constants import (
    ALLOWED_ACCOUNT_STATUS,
    ALLOWED_CURRENCIES,
    ALLOWED_PAYMENT_MODE,
    OPEN_INVOICE_STATUSES,
)


class PaymentsSharedMixin:
    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _clean(self, value: Any, n: int) -> str:
        return str(value or "").strip()[:n]

    def _tenant_id(self, value: Any) -> str:
        out = self._clean(value, 64)
        if not out:
            raise ValueError("tenant_id_required")
        return out

    def _mode(self, value: Any) -> str:
        out = self._clean(value, 16).upper() or "PREPAID"
        if out not in ALLOWED_PAYMENT_MODE:
            raise ValueError("payment_mode_invalid")
        return out

    def _status(self, value: Any) -> str:
        out = self._clean(value, 16).upper() or "ACTIVE"
        if out not in ALLOWED_ACCOUNT_STATUS:
            raise ValueError("credit_account_status_invalid")
        return out

    def _currency(self, value: Any, default: str = "EUR") -> str:
        out = self._clean(value or default, 8).upper()
        if out not in ALLOWED_CURRENCIES:
            raise ValueError("currency_invalid")
        return out

    def _limit(self, value: Any, default: int, hard_max: int) -> int:
        try:
            raw = int(value if value is not None else default)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("integer_required") from exc
        return max(1, min(raw, hard_max))

    def _to_minor(self, value: Any) -> int:
        try:
            out = int(value)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("amount_minor_invalid") from exc
        return max(0, out)

    def _tenant_exists(self, db: Session, tenant_id: str) -> bool:
        return db.query(Tenant.id).filter(Tenant.id == tenant_id).first() is not None

    def _account_row(self, db: Session, tenant_id: str) -> TenantCreditAccount | None:
        return db.query(TenantCreditAccount).filter(TenantCreditAccount.tenant_id == tenant_id).first()

    def _ensure_account_row(self, db: Session, *, tenant_id: str, actor: str) -> TenantCreditAccount:
        row = self._account_row(db, tenant_id)
        if row is not None:
            return row

        now = self._now()
        row = TenantCreditAccount(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            payment_mode="PREPAID",
            status="ACTIVE",
            credit_limit_minor=0,
            currency="EUR",
            terms_days=30,
            grace_days=3,
            auto_hold_on_overdue=True,
            overdue_hold=False,
            metadata_json={},
            updated_by=str(actor or "system"),
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        db.flush()
        return row

    def _exposure_minor(self, db: Session, tenant_id: str) -> int:
        # Cockroach may return DECIMAL for SUM(INT), so avoid COALESCE type mismatch.
        val = (
            db.query(func.sum(PaymentInvoice.amount_minor))
            .filter(PaymentInvoice.tenant_id == tenant_id, PaymentInvoice.status.in_(OPEN_INVOICE_STATUSES))
            .scalar()
        )
        return int(val or 0)

    def _overdue_count(self, db: Session, tenant_id: str) -> int:
        return int(db.query(PaymentInvoice).filter(PaymentInvoice.tenant_id == tenant_id, PaymentInvoice.status == "OVERDUE").count())

    def _account_to_dict(self, db: Session, row: TenantCreditAccount | None, tenant_id: str) -> dict[str, Any]:
        if row is None:
            return {
                "tenant_id": tenant_id,
                "payment_mode": "PREPAID",
                "status": "ACTIVE",
                "credit_limit_minor": 0,
                "currency": "EUR",
                "terms_days": 30,
                "grace_days": 3,
                "auto_hold_on_overdue": True,
                "overdue_hold": False,
                "metadata": {},
                "current_exposure_minor": 0,
                "available_credit_minor": 0,
                "can_deferred_charge": False,
                "updated_by": None,
                "updated_at": None,
            }

        exposure = self._exposure_minor(db, tenant_id)
        available = max(0, int(row.credit_limit_minor or 0) - exposure)
        can_charge = (
            str(row.payment_mode or "").upper() == "DEFERRED"
            and str(row.status or "").upper() == "ACTIVE"
            and not bool(row.overdue_hold)
            and available > 0
        )

        return {
            "tenant_id": row.tenant_id,
            "payment_mode": str(row.payment_mode or "PREPAID").upper(),
            "status": str(row.status or "ACTIVE").upper(),
            "credit_limit_minor": int(row.credit_limit_minor or 0),
            "currency": str(row.currency or "EUR").upper(),
            "terms_days": int(row.terms_days or 30),
            "grace_days": int(row.grace_days or 3),
            "auto_hold_on_overdue": bool(row.auto_hold_on_overdue),
            "overdue_hold": bool(row.overdue_hold),
            "metadata": row.metadata_json or {},
            "current_exposure_minor": exposure,
            "available_credit_minor": available,
            "can_deferred_charge": bool(can_charge),
            "updated_by": row.updated_by,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def resolve_tenant_payment_profile(self, db: Session, *, tenant_id: str) -> dict[str, Any]:
        tid = self._tenant_id(tenant_id)
        row = self._account_row(db, tid)
        return self._account_to_dict(db, row, tid)

    def upsert_credit_account(self, db: Session, *, tenant_id: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:
        tid = self._tenant_id(tenant_id)
        if not self._tenant_exists(db, tid):
            raise ValueError("tenant_not_found")

        now = self._now()
        row = self._account_row(db, tid)
        if row is None:
            row = TenantCreditAccount(
                id=uuid.uuid4(),
                tenant_id=tid,
                payment_mode="PREPAID",
                status="ACTIVE",
                credit_limit_minor=0,
                currency="EUR",
                terms_days=30,
                grace_days=3,
                auto_hold_on_overdue=True,
                overdue_hold=False,
                metadata_json={},
                updated_by=str(actor or "unknown"),
                created_at=now,
                updated_at=now,
            )
            db.add(row)

        if "payment_mode" in payload:
            row.payment_mode = self._mode(payload.get("payment_mode"))
        if "status" in payload:
            row.status = self._status(payload.get("status"))
        if "credit_limit_minor" in payload:
            row.credit_limit_minor = self._to_minor(payload.get("credit_limit_minor"))
        if "currency" in payload:
            row.currency = self._currency(payload.get("currency"))
        if "terms_days" in payload:
            row.terms_days = max(1, min(int(payload.get("terms_days") or 30), 365))
        if "grace_days" in payload:
            row.grace_days = max(0, min(int(payload.get("grace_days") or 3), 90))
        if "auto_hold_on_overdue" in payload:
            row.auto_hold_on_overdue = bool(payload.get("auto_hold_on_overdue"))
        if "overdue_hold" in payload:
            row.overdue_hold = bool(payload.get("overdue_hold"))
        if "metadata" in payload and isinstance(payload.get("metadata"), dict):
            row.metadata_json = dict(payload.get("metadata") or {})

        if str(row.payment_mode or "").upper() != "DEFERRED":
            row.overdue_hold = False

        row.updated_by = str(actor or "unknown")
        row.updated_at = now
        db.flush()
        return self._account_to_dict(db, row, tid)

    def list_credit_accounts(
        self,
        db: Session,
        *,
        tenant_id: str | None = None,
        payment_mode: str | None = None,
        status: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        q = db.query(TenantCreditAccount)
        if tenant_id:
            q = q.filter(TenantCreditAccount.tenant_id == self._tenant_id(tenant_id))
        if payment_mode:
            q = q.filter(TenantCreditAccount.payment_mode == self._mode(payment_mode))
        if status:
            q = q.filter(TenantCreditAccount.status == self._status(status))

        rows = q.order_by(TenantCreditAccount.updated_at.desc()).limit(self._limit(limit, 500, 5000)).all()
        return [self._account_to_dict(db, row, row.tenant_id) for row in rows]

