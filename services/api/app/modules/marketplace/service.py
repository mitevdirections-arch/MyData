from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import uuid

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models import License, LicenseIssueRequest, MarketplaceModule, MarketplaceOffer, Tenant
from app.modules.licensing.service import service as licensing_service
from app.modules.payments.service import service as payments_service

ALLOWED_CURRENCIES = {"EUR", "USD", "BGN"}
ALLOWED_BILLING = {"MONTH", "YEAR", "ONCE"}
ALLOWED_OFFER_TYPES = {"DISCOUNT", "TRIAL", "CUSTOM", "BUNDLE"}
ALLOWED_OFFER_STATUS = {"DRAFT", "ACTIVE", "PAUSED", "ARCHIVED"}


class MarketplaceService:
    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _clean(self, value: Any, n: int) -> str:
        return str(value or "").strip()[:n]

    def _module_code(self, value: Any) -> str:
        code = self._clean(value, 64).upper()
        if not code:
            raise ValueError("module_code_required")
        return code

    def _currency(self, value: Any, default: str = "EUR") -> str:
        out = self._clean(value or default, 8).upper()
        if out not in ALLOWED_CURRENCIES:
            raise ValueError("currency_invalid")
        return out

    def _billing(self, value: Any, default: str = "MONTH") -> str:
        out = self._clean(value or default, 16).upper()
        if out not in ALLOWED_BILLING:
            raise ValueError("billing_period_invalid")
        return out

    def _offer_type(self, value: Any, default: str = "DISCOUNT") -> str:
        out = self._clean(value or default, 32).upper()
        if out not in ALLOWED_OFFER_TYPES:
            raise ValueError("offer_type_invalid")
        return out

    def _offer_status(self, value: Any, default: str = "ACTIVE") -> str:
        out = self._clean(value or default, 16).upper()
        if out not in ALLOWED_OFFER_STATUS:
            raise ValueError("offer_status_invalid")
        return out

    def _limit(self, value: int | None, default: int, hard_max: int) -> int:
        raw = int(value if value is not None else default)
        return max(1, min(raw, hard_max))

    def _days(self, value: Any, default: int = 30) -> int:
        if value in (None, ""):
            return default
        return max(1, min(int(value), 3650))

    def _parse_dt(self, value: Any, field: str) -> datetime | None:
        if value in (None, ""):
            return None
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field}_invalid_iso") from exc
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def ensure_default_modules(self, db: Session) -> None:
        if int(db.query(MarketplaceModule).count() or 0) > 0:
            return
        now = self._now()
        seed = [
            ("MODULE_ORDERS", "Orders", "OPERATIONS", 4900),
            ("MODULE_FLEET", "Fleet", "OPERATIONS", 5900),
            ("MODULE_WAREHOUSE", "Warehouse", "LOGISTICS", 6900),
            ("MODULE_INVOICING", "Invoicing", "FINANCE", 3900),
            ("MODULE_PAYMENTS", "Payments", "FINANCE", 4500),
        ]
        for code, name, mclass, price in seed:
            db.add(
                MarketplaceModule(
                    module_code=code,
                    name=name,
                    module_class=mclass,
                    description=f"{name} module",
                    default_license_type="MODULE_PAID",
                    base_price_minor=price,
                    currency="EUR",
                    billing_period="MONTH",
                    is_active=True,
                    metadata_json={},
                    created_at=now,
                    updated_at=now,
                )
            )
        db.flush()

    def _offer_live(self, row: MarketplaceOffer, now: datetime) -> bool:
        if row.status != "ACTIVE":
            return False
        if row.starts_at is not None and row.starts_at > now:
            return False
        if row.ends_at is not None and row.ends_at < now:
            return False
        return True

    def _offer_to_dict(self, row: MarketplaceOffer, now: datetime) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "code": row.code,
            "title": row.title,
            "description": row.description,
            "module_code": row.module_code,
            "offer_type": row.offer_type,
            "status": row.status,
            "discount_percent": row.discount_percent,
            "trial_days": row.trial_days,
            "price_override_minor": row.price_override_minor,
            "currency": row.currency,
            "starts_at": row.starts_at.isoformat() if row.starts_at else None,
            "ends_at": row.ends_at.isoformat() if row.ends_at else None,
            "auto_apply": bool(row.auto_apply),
            "metadata": row.metadata_json or {},
            "is_active_now": self._offer_live(row, now),
            "updated_by": row.updated_by,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def _pricing_for_offer(self, *, module: MarketplaceModule, offer: MarketplaceOffer | None) -> dict[str, Any]:
        base_minor = max(0, int(module.base_price_minor or 0))
        amount_minor = base_minor
        currency = self._currency(getattr(module, "currency", "EUR"), "EUR")
        rule = "BASE_PRICE"

        if offer is not None:
            if offer.price_override_minor is not None:
                amount_minor = max(0, int(offer.price_override_minor))
                rule = "OFFER_PRICE_OVERRIDE"
            elif offer.discount_percent is not None:
                pct = max(0, min(int(offer.discount_percent), 100))
                amount_minor = max(0, int(round(base_minor * (100 - pct) / 100.0)))
                rule = f"OFFER_DISCOUNT_{pct}"
            if offer.currency:
                currency = self._currency(offer.currency, currency)

        return {
            "base_amount_minor": base_minor,
            "amount_minor": amount_minor,
            "currency": currency,
            "rule": rule,
        }
    def list_active_offers(self, db: Session, *, module_code: str | None, limit: int = 300) -> list[dict[str, Any]]:
        now = self._now()
        q = db.query(MarketplaceOffer).filter(
            MarketplaceOffer.status == "ACTIVE",
            or_(MarketplaceOffer.starts_at.is_(None), MarketplaceOffer.starts_at <= now),
            or_(MarketplaceOffer.ends_at.is_(None), MarketplaceOffer.ends_at >= now),
        )
        if module_code:
            code = self._module_code(module_code)
            q = q.filter(or_(MarketplaceOffer.module_code.is_(None), MarketplaceOffer.module_code == code))
        rows = q.order_by(MarketplaceOffer.updated_at.desc()).limit(self._limit(limit, 300, 2000)).all()
        return [self._offer_to_dict(x, now) for x in rows]

    def list_catalog(
        self,
        db: Session,
        *,
        tenant_id: str | None,
        module_class: str | None,
        include_inactive: bool,
        limit: int = 300,
    ) -> list[dict[str, Any]]:
        self.ensure_default_modules(db)
        now = self._now()
        q = db.query(MarketplaceModule)
        if not include_inactive:
            q = q.filter(MarketplaceModule.is_active.is_(True))
        if module_class:
            q = q.filter(MarketplaceModule.module_class == self._clean(module_class, 64).upper())

        modules = q.order_by(MarketplaceModule.module_code.asc()).limit(self._limit(limit, 300, 5000)).all()
        offers = self.list_active_offers(db, module_code=None, limit=2000)

        shared_offers: list[dict[str, Any]] = []
        offers_by_module: dict[str, list[dict[str, Any]]] = {}
        for offer in offers:
            code = str(offer.get("module_code") or "").strip().upper()
            if not code:
                shared_offers.append(offer)
                continue
            offers_by_module.setdefault(code, []).append(offer)

        entitlement_by_module: dict[str, dict[str, Any]] = {}
        if tenant_id:
            tid = str(tenant_id).strip()
            startup = (
                db.query(License)
                .filter(
                    License.tenant_id == tid,
                    License.license_type == "STARTUP",
                    License.status == "ACTIVE",
                    License.valid_from <= now,
                    License.valid_to >= now,
                )
                .order_by(License.valid_to.desc())
                .first()
            )

            if startup is not None:
                base_ent = {
                    "allowed": True,
                    "reason": "startup_full_access",
                    "source": {
                        "license_type": startup.license_type,
                        "license_id": str(startup.id),
                    },
                    "valid_to": (startup.valid_to.isoformat() if getattr(startup, "valid_to", None) else None),
                }
                for row in modules:
                    entitlement_by_module[row.module_code] = {
                        "allowed": True,
                        "module_code": row.module_code,
                        "reason": base_ent["reason"],
                        "source": base_ent["source"],
                        "valid_to": base_ent["valid_to"],
                    }
            else:
                module_codes = [str(x.module_code).strip().upper() for x in modules if str(x.module_code or "").strip()]
                lic_rows: list[License] = []
                if module_codes:
                    lic_rows = (
                        db.query(License)
                        .filter(
                            License.tenant_id == tid,
                            License.module_code.in_(module_codes),
                            License.status == "ACTIVE",
                            License.valid_from <= now,
                            License.valid_to >= now,
                            License.license_type != "CORE",
                            License.license_type != "STARTUP",
                        )
                        .order_by(License.valid_to.desc())
                        .all()
                    )

                best_by_code: dict[str, License] = {}
                for lic in lic_rows:
                    code = str(lic.module_code or "").strip().upper()
                    if code and code not in best_by_code:
                        best_by_code[code] = lic

                for row in modules:
                    code = str(row.module_code or "").strip().upper()
                    lic = best_by_code.get(code)
                    if lic is None:
                        entitlement_by_module[row.module_code] = {
                            "allowed": False,
                            "module_code": row.module_code,
                            "reason": "module_license_required",
                            "source": None,
                            "valid_to": None,
                        }
                    else:
                        entitlement_by_module[row.module_code] = {
                            "allowed": True,
                            "module_code": row.module_code,
                            "reason": "module_license_active",
                            "source": {
                                "license_type": lic.license_type,
                                "license_id": str(lic.id),
                            },
                            "valid_to": (lic.valid_to.isoformat() if getattr(lic, "valid_to", None) else None),
                        }

        out: list[dict[str, Any]] = []
        for row in modules:
            module_code = str(row.module_code or "").strip().upper()
            linked = list(shared_offers)
            linked.extend(offers_by_module.get(module_code, []))

            base_price_minor = 0
            try:
                base_price_minor = max(0, int(getattr(row, "base_price_minor", 0) or 0))
            except Exception:  # noqa: BLE001
                base_price_minor = 0
            metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
            updated_at = row.updated_at.isoformat() if getattr(row, "updated_at", None) else None

            item = {
                "module_code": row.module_code,
                "name": row.name,
                "module_class": row.module_class,
                "description": row.description,
                "default_license_type": row.default_license_type,
                "base_price_minor": base_price_minor,
                "currency": self._clean(getattr(row, "currency", None), 8).upper() or "EUR",
                "billing_period": self._clean(getattr(row, "billing_period", None), 16).upper() or "MONTH",
                "is_active": bool(row.is_active),
                "metadata": metadata,
                "updated_at": updated_at,
                "offers": linked,
            }
            if tenant_id:
                item["entitlement"] = entitlement_by_module.get(
                    row.module_code,
                    {
                        "allowed": False,
                        "module_code": row.module_code,
                        "reason": "module_license_required",
                        "source": None,
                        "valid_to": None,
                    },
                )
            out.append(item)
        return out

    def upsert_module(self, db: Session, *, actor: str, payload: dict[str, Any], module_code: str | None = None) -> dict[str, Any]:
        code = self._module_code(module_code or payload.get("module_code"))
        now = self._now()
        row = db.query(MarketplaceModule).filter(MarketplaceModule.module_code == code).first()

        if row is None:
            row = MarketplaceModule(
                module_code=code,
                name=self._clean(payload.get("name") or code, 160),
                module_class=self._clean(payload.get("module_class") or "GENERAL", 64).upper() or "GENERAL",
                description=self._clean(payload.get("description"), 4000) or None,
                default_license_type=self._clean(payload.get("default_license_type") or "MODULE_PAID", 32).upper(),
                base_price_minor=max(0, int(payload.get("base_price_minor") or 0)),
                currency=self._currency(payload.get("currency"), "EUR"),
                billing_period=self._billing(payload.get("billing_period"), "MONTH"),
                is_active=bool(payload.get("is_active", True)),
                metadata_json=(dict(payload.get("metadata") or {}) if isinstance(payload.get("metadata"), dict) else {}),
                created_at=now,
                updated_at=now,
            )
            db.add(row)
        else:
            if "name" in payload:
                row.name = self._clean(payload.get("name"), 160) or row.name
            if "module_class" in payload:
                row.module_class = self._clean(payload.get("module_class"), 64).upper() or row.module_class
            if "description" in payload:
                row.description = self._clean(payload.get("description"), 4000) or None
            if "default_license_type" in payload:
                row.default_license_type = self._clean(payload.get("default_license_type"), 32).upper() or row.default_license_type
            if "base_price_minor" in payload:
                row.base_price_minor = max(0, int(payload.get("base_price_minor") or 0))
            if "currency" in payload:
                row.currency = self._currency(payload.get("currency"))
            if "billing_period" in payload:
                row.billing_period = self._billing(payload.get("billing_period"))
            if "is_active" in payload:
                row.is_active = bool(payload.get("is_active"))
            if "metadata" in payload and isinstance(payload.get("metadata"), dict):
                row.metadata_json = dict(payload.get("metadata") or {})
            row.updated_at = now

        db.flush()
        return {
            "module_code": row.module_code,
            "name": row.name,
            "module_class": row.module_class,
            "description": row.description,
            "default_license_type": row.default_license_type,
            "base_price_minor": int(row.base_price_minor),
            "currency": row.currency,
            "billing_period": row.billing_period,
            "is_active": bool(row.is_active),
            "metadata": row.metadata_json or {},
            "updated_by": str(actor or "unknown"),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def list_offers(
        self,
        db: Session,
        *,
        status: str | None,
        module_code: str | None,
        include_expired: bool,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        now = self._now()
        q = db.query(MarketplaceOffer)
        if status:
            q = q.filter(MarketplaceOffer.status == self._offer_status(status))
        if module_code:
            q = q.filter(MarketplaceOffer.module_code == self._module_code(module_code))
        if not include_expired:
            q = q.filter(or_(MarketplaceOffer.ends_at.is_(None), MarketplaceOffer.ends_at >= now))

        rows = q.order_by(MarketplaceOffer.updated_at.desc()).limit(self._limit(limit, 500, 5000)).all()
        return [self._offer_to_dict(x, now) for x in rows]

    def upsert_offer(self, db: Session, *, actor: str, payload: dict[str, Any], offer_id: str | None = None) -> dict[str, Any]:
        now = self._now()
        row: MarketplaceOffer | None = None

        if offer_id:
            try:
                oid = uuid.UUID(str(offer_id))
            except Exception as exc:  # noqa: BLE001
                raise ValueError("offer_id_invalid") from exc
            row = db.query(MarketplaceOffer).filter(MarketplaceOffer.id == oid).first()
            if row is None:
                raise ValueError("offer_not_found")

        code = self._clean(payload.get("code") if "code" in payload else (row.code if row else ""), 64).upper()
        if not code:
            raise ValueError("offer_code_required")

        title = self._clean(payload.get("title") if "title" in payload else (row.title if row else ""), 180)
        if len(title) < 3:
            raise ValueError("offer_title_too_short")

        module_code_raw = payload.get("module_code") if "module_code" in payload else (row.module_code if row else None)
        module_code = None if module_code_raw in (None, "") else self._module_code(module_code_raw)
        if module_code is not None:
            module = db.query(MarketplaceModule).filter(MarketplaceModule.module_code == module_code).first()
            if module is None:
                raise ValueError("module_not_found")

        offer_type = self._offer_type(payload.get("offer_type") if "offer_type" in payload else (row.offer_type if row else "DISCOUNT"))
        status = self._offer_status(payload.get("status") if "status" in payload else (row.status if row else "ACTIVE"))
        description = self._clean(payload.get("description") if "description" in payload else (row.description if row else ""), 5000) or None

        discount_percent = payload.get("discount_percent") if "discount_percent" in payload else (row.discount_percent if row else None)
        trial_days = payload.get("trial_days") if "trial_days" in payload else (row.trial_days if row else None)
        price_override_minor = payload.get("price_override_minor") if "price_override_minor" in payload else (row.price_override_minor if row else None)

        if discount_percent is not None:
            discount_percent = max(0, min(int(discount_percent), 100))
        if trial_days is not None:
            trial_days = self._days(trial_days)
        if price_override_minor is not None:
            price_override_minor = max(0, int(price_override_minor))

        currency_raw = payload.get("currency") if "currency" in payload else (row.currency if row else None)
        currency = None if currency_raw in (None, "") else self._currency(currency_raw)

        starts_at = self._parse_dt(payload.get("starts_at") if "starts_at" in payload else (row.starts_at if row else None), "starts_at")
        ends_at = self._parse_dt(payload.get("ends_at") if "ends_at" in payload else (row.ends_at if row else None), "ends_at")
        if starts_at and ends_at and ends_at < starts_at:
            raise ValueError("offer_window_invalid")

        auto_apply = bool(payload.get("auto_apply") if "auto_apply" in payload else (row.auto_apply if row else False))
        metadata_json = (dict(payload.get("metadata") or {}) if isinstance(payload.get("metadata"), dict) else (row.metadata_json if row else {}))

        if row is None:
            existing = db.query(MarketplaceOffer).filter(MarketplaceOffer.code == code).first()
            if existing is not None:
                raise ValueError("offer_code_exists")
            row = MarketplaceOffer(
                id=uuid.uuid4(),
                code=code,
                title=title,
                description=description,
                module_code=module_code,
                offer_type=offer_type,
                status=status,
                discount_percent=discount_percent,
                trial_days=trial_days,
                price_override_minor=price_override_minor,
                currency=currency,
                starts_at=starts_at,
                ends_at=ends_at,
                auto_apply=auto_apply,
                metadata_json=metadata_json,
                created_by=str(actor or "unknown"),
                updated_by=str(actor or "unknown"),
                created_at=now,
                updated_at=now,
            )
            db.add(row)
        else:
            existing = db.query(MarketplaceOffer).filter(MarketplaceOffer.code == code, MarketplaceOffer.id != row.id).first()
            if existing is not None:
                raise ValueError("offer_code_exists")
            row.code = code
            row.title = title
            row.description = description
            row.module_code = module_code
            row.offer_type = offer_type
            row.status = status
            row.discount_percent = discount_percent
            row.trial_days = trial_days
            row.price_override_minor = price_override_minor
            row.currency = currency
            row.starts_at = starts_at
            row.ends_at = ends_at
            row.auto_apply = auto_apply
            row.metadata_json = metadata_json
            row.updated_by = str(actor or "unknown")
            row.updated_at = now

        db.flush()
        return self._offer_to_dict(row, now)

    def _request_to_dict(self, row: LicenseIssueRequest) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "tenant_id": row.tenant_id,
            "request_type": row.request_type,
            "status": row.status,
            "payload": row.payload_json or {},
            "result": row.result_json or {},
            "requested_by": row.requested_by,
            "requested_at": row.requested_at.isoformat() if row.requested_at else None,
            "approved_by": row.approved_by,
            "approved_at": row.approved_at.isoformat() if row.approved_at else None,
            "decision_note": row.decision_note,
            "processed_at": row.processed_at.isoformat() if row.processed_at else None,
        }

    def _issue_paid(self, db: Session, *, tenant_id: str, module_code: str, days: int, actor: str) -> dict[str, Any]:
        core = licensing_service.get_active_core(db, tenant_id)
        if core is None:
            raise ValueError("core_required")

        active = licensing_service.get_active_module_license(db, tenant_id, module_code)
        if active is not None:
            raise ValueError("module_already_licensed")

        now = self._now()
        lid = uuid.uuid4()
        preview = licensing_service.preview_visual_code(
            db,
            tenant_id=tenant_id,
            license_type="MODULE_PAID",
            module_code=module_code,
            vat_number=None,
            issued_at=now,
            internal_mark=str(lid),
        )

        row = License(
            id=lid,
            tenant_id=tenant_id,
            license_type="MODULE_PAID",
            module_code=module_code,
            license_visual_code=str(preview.get("code") or "").strip().upper() or None,
            status="ACTIVE",
            valid_from=now,
            valid_to=now + timedelta(days=self._days(days)),
        )
        db.add(row)
        db.flush()
        return {
            "license_id": str(row.id),
            "tenant_id": row.tenant_id,
            "license_type": row.license_type,
            "module_code": row.module_code,
            "license_visual_code": row.license_visual_code,
            "valid_from": row.valid_from.isoformat(),
            "valid_to": row.valid_to.isoformat(),
            "issued_by": str(actor or "unknown"),
        }
    def request_purchase(self, db: Session, *, tenant_id: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:
        if db.query(Tenant.id).filter(Tenant.id == tenant_id).first() is None:
            raise ValueError("tenant_not_found")

        module_code = self._module_code(payload.get("module_code"))
        module = db.query(MarketplaceModule).filter(MarketplaceModule.module_code == module_code).first()
        if module is None:
            raise ValueError("module_not_found")
        if not bool(module.is_active):
            raise ValueError("module_inactive")

        core = licensing_service.get_active_core(db, tenant_id)
        if core is None:
            raise ValueError("core_required")

        entitlement = licensing_service.resolve_module_entitlement(db, tenant_id=tenant_id, module_code=module_code)
        if bool(entitlement.get("allowed")):
            return {"ok": True, "flow": "ALREADY_ENTITLED", "tenant_id": tenant_id, "module_code": module_code, "entitlement": entitlement}

        mode = str((licensing_service.get_issuance_policy(db, tenant_id=tenant_id) or {}).get("mode") or "SEMI").upper()
        offer_code = self._clean(payload.get("offer_code"), 64).upper() or None
        valid_days = self._days(payload.get("valid_days"), 30)

        offer = None
        if offer_code:
            offer = db.query(MarketplaceOffer).filter(MarketplaceOffer.code == offer_code).first()
            if offer is None:
                raise ValueError("offer_not_found")
            if offer.module_code and offer.module_code != module_code:
                raise ValueError("offer_module_mismatch")
            if not self._offer_live(offer, self._now()):
                raise ValueError("offer_not_active")
            if offer.trial_days:
                valid_days = self._days(offer.trial_days, valid_days)

        pricing = self._pricing_for_offer(module=module, offer=offer)
        payment_profile = payments_service.resolve_tenant_payment_profile(db, tenant_id=tenant_id)

        if mode == "AUTO":
            payment: dict[str, Any]
            if str(payment_profile.get("payment_mode") or "PREPAID").upper() == "DEFERRED":
                payment = payments_service.create_deferred_invoice_for_marketplace(
                    db,
                    tenant_id=tenant_id,
                    module_code=module_code,
                    amount_minor=int(pricing.get("amount_minor") or 0),
                    currency=str(pricing.get("currency") or "EUR"),
                    actor="marketplace-auto",
                    source_type="MARKETPLACE_AUTO",
                    source_ref=None,
                    description=f"Marketplace module {module_code}",
                    metadata={
                        "offer_code": offer_code,
                        "pricing_rule": pricing.get("rule"),
                    },
                )
            else:
                payment = {
                    "flow": "PREPAID_NOT_ENFORCED",
                    "pricing": pricing,
                    "profile": payment_profile,
                }

            issued = self._issue_paid(db, tenant_id=tenant_id, module_code=module_code, days=valid_days, actor="marketplace-auto")
            return {
                "ok": True,
                "flow": "ISSUED",
                "mode": mode,
                "tenant_id": tenant_id,
                "module_code": module_code,
                "offer": (self._offer_to_dict(offer, self._now()) if offer else None),
                "pricing": pricing,
                "payment": payment,
                "issued": issued,
            }

        existing = (
            db.query(LicenseIssueRequest)
            .filter(
                LicenseIssueRequest.tenant_id == tenant_id,
                LicenseIssueRequest.request_type == "MARKETPLACE_MODULE",
                LicenseIssueRequest.status == "PENDING",
            )
            .order_by(LicenseIssueRequest.requested_at.desc())
            .all()
        )
        for row in existing:
            p = row.payload_json or {}
            if str(p.get("module_code") or "").strip().upper() == module_code:
                return {
                    "ok": True,
                    "flow": "PENDING_APPROVAL",
                    "mode": mode,
                    "tenant_id": tenant_id,
                    "module_code": module_code,
                    "request": self._request_to_dict(row),
                }

        req = LicenseIssueRequest(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            request_type="MARKETPLACE_MODULE",
            status="PENDING",
            payload_json={
                "module_code": module_code,
                "offer_code": offer_code,
                "requested_valid_days": valid_days,
                "requested_amount_minor": int(pricing.get("amount_minor") or 0),
                "requested_currency": str(pricing.get("currency") or "EUR"),
                "pricing_rule": pricing.get("rule"),
                "payment_mode": str(payment_profile.get("payment_mode") or "PREPAID").upper(),
                "note": self._clean(payload.get("note"), 1024) or None,
            },
            result_json={},
            requested_by=str(actor or "unknown"),
            requested_at=self._now(),
        )
        db.add(req)
        db.flush()

        return {
            "ok": True,
            "flow": "PENDING_APPROVAL",
            "mode": mode,
            "tenant_id": tenant_id,
            "module_code": module_code,
            "pricing": pricing,
            "payment_profile": payment_profile,
            "request": self._request_to_dict(req),
        }

    def list_tenant_requests(self, db: Session, *, tenant_id: str, status: str | None, limit: int = 300) -> list[dict[str, Any]]:
        q = db.query(LicenseIssueRequest).filter(
            LicenseIssueRequest.tenant_id == tenant_id,
            LicenseIssueRequest.request_type == "MARKETPLACE_MODULE",
        )
        if status:
            q = q.filter(LicenseIssueRequest.status == self._clean(status, 32).upper())
        rows = q.order_by(LicenseIssueRequest.requested_at.desc()).limit(self._limit(limit, 300, 5000)).all()
        return [self._request_to_dict(x) for x in rows]

    def list_super_requests(self, db: Session, *, tenant_id: str | None, status: str | None, limit: int = 500) -> list[dict[str, Any]]:
        q = db.query(LicenseIssueRequest).filter(LicenseIssueRequest.request_type == "MARKETPLACE_MODULE")
        if tenant_id:
            q = q.filter(LicenseIssueRequest.tenant_id == self._clean(tenant_id, 64))
        if status:
            q = q.filter(LicenseIssueRequest.status == self._clean(status, 32).upper())
        rows = q.order_by(LicenseIssueRequest.requested_at.desc()).limit(self._limit(limit, 500, 5000)).all()
        return [self._request_to_dict(x) for x in rows]

    def _pending_request(self, db: Session, request_id: str) -> LicenseIssueRequest:
        try:
            rid = uuid.UUID(str(request_id))
        except Exception as exc:  # noqa: BLE001
            raise ValueError("request_id_invalid") from exc

        row = db.query(LicenseIssueRequest).filter(LicenseIssueRequest.id == rid, LicenseIssueRequest.request_type == "MARKETPLACE_MODULE").first()
        if row is None:
            raise ValueError("marketplace_request_not_found")
        if row.status != "PENDING":
            raise ValueError("marketplace_request_not_pending")
        return row
    def approve_request(self, db: Session, *, request_id: str, actor: str, note: str | None, valid_days: int | None) -> dict[str, Any]:
        row = self._pending_request(db, request_id)
        payload = row.payload_json or {}
        module_code = self._module_code(payload.get("module_code"))
        days = self._days(valid_days if valid_days is not None else payload.get("requested_valid_days"), 30)

        payment_mode = str(payload.get("payment_mode") or "PREPAID").upper()
        amount_minor = int(payload.get("requested_amount_minor") or 0)
        currency = str(payload.get("requested_currency") or "EUR").upper()

        payment: dict[str, Any]
        if payment_mode == "DEFERRED":
            payment = payments_service.create_deferred_invoice_for_marketplace(
                db,
                tenant_id=row.tenant_id,
                module_code=module_code,
                amount_minor=amount_minor,
                currency=currency,
                actor=actor,
                source_type="MARKETPLACE_APPROVED",
                source_ref=str(row.id),
                description=f"Marketplace module {module_code}",
                metadata={
                    "offer_code": payload.get("offer_code"),
                    "pricing_rule": payload.get("pricing_rule"),
                    "approved_request_id": str(row.id),
                },
            )
        else:
            payment = {
                "flow": "PREPAID_NOT_ENFORCED",
                "pricing": {
                    "amount_minor": amount_minor,
                    "currency": currency,
                    "rule": payload.get("pricing_rule") or "BASE_PRICE",
                },
            }

        issued = self._issue_paid(db, tenant_id=row.tenant_id, module_code=module_code, days=days, actor=actor)
        now = self._now()

        row.status = "APPROVED"
        row.approved_by = str(actor or "unknown")
        row.approved_at = now
        row.decision_note = self._clean(note, 1024) or None
        row.result_json = {"issued": issued, "payment": payment}
        row.processed_at = now
        db.flush()

        return {"ok": True, "request": self._request_to_dict(row), "issued": issued, "payment": payment}

    def reject_request(self, db: Session, *, request_id: str, actor: str, note: str | None) -> dict[str, Any]:
        row = self._pending_request(db, request_id)
        now = self._now()

        row.status = "REJECTED"
        row.approved_by = str(actor or "unknown")
        row.approved_at = now
        row.decision_note = self._clean(note, 1024) or "rejected_by_admin"
        row.result_json = {"rejected": True}
        row.processed_at = now
        db.flush()

        return {"ok": True, "request": self._request_to_dict(row)}


service = MarketplaceService()