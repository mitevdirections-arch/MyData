from __future__ import annotations

from datetime import datetime, timezone
import re
import uuid

from sqlalchemy import case, distinct, func
from sqlalchemy.orm import Session

from app.db.models import (
    GlobalCompany,
    GlobalCompanyReputation,
    PartnerOrderRating,
    TenantPartner,
    TenantPartnerAddress,
    TenantPartnerBankAccount,
    TenantPartnerContact,
    TenantPartnerDocument,
    TenantPartnerRatingSummary,
    TenantPartnerRole,
)
from app.modules.partners.schemas import (
    GlobalCompanySignalDTO,
    PartnerAddressDTO,
    PartnerBankAccountDTO,
    PartnerContactDTO,
    PartnerCreateRequestDTO,
    PartnerDetailDTO,
    PartnerDocumentDTO,
    PartnerRatingCreateRequestDTO,
    PartnerRoleCode,
    PartnerSummaryDTO,
    PartnerUpdateRequestDTO,
    TenantPartnerRatingSummaryDTO,
)

ALLOWED_PARTNER_STATUS = {"ACTIVE", "INACTIVE", "SUSPENDED", "ARCHIVED"}
ALLOWED_ROLE_CODES = {x.value for x in PartnerRoleCode}
NAME_NORMALIZE_RE = re.compile(r"[^A-Z0-9]+")


class PartnersService:
    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _clean(self, value: object, size: int) -> str:
        return str(value or "").strip()[:size]

    def _clean_opt(self, value: object, size: int) -> str | None:
        out = self._clean(value, size)
        return out if out else None

    def _country(self, value: object) -> str:
        out = self._clean(value, 8).upper()
        if not out:
            raise ValueError("country_code_required")
        return out

    def _status(self, value: object | None, *, default: str = "ACTIVE") -> str:
        out = self._clean(value or default, 32).upper()
        if out not in ALLOWED_PARTNER_STATUS:
            raise ValueError("partner_status_invalid")
        return out

    def _parse_uuid(self, value: object | None, field: str) -> uuid.UUID | None:
        if value in (None, ""):
            return None
        try:
            return uuid.UUID(str(value))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"{field}_invalid") from exc

    def _normalize_roles(self, roles: list[PartnerRoleCode | str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in list(roles or []):
            code = self._clean(raw, 64).upper()
            if not code:
                continue
            if code not in ALLOWED_ROLE_CODES:
                raise ValueError("partner_role_invalid")
            if code in seen:
                continue
            seen.add(code)
            out.append(code)
        return out

    def _normalized_name(self, display_name: str, legal_name: str | None) -> str:
        src = str(legal_name or display_name or "").upper()
        return NAME_NORMALIZE_RE.sub("", src).strip()[:255]

    def _partner_row(self, db: Session, *, company_id: str, partner_id: str, include_archived: bool = False) -> TenantPartner:
        pid = self._parse_uuid(partner_id, "partner_id")
        row = db.query(TenantPartner).filter(TenantPartner.id == pid, TenantPartner.company_id == company_id).first()
        if row is None:
            raise ValueError("partner_not_found")
        if not include_archived and row.archived_at is not None:
            raise ValueError("partner_not_found")
        return row

    def _to_summary(self, row: TenantPartner) -> PartnerSummaryDTO:
        return PartnerSummaryDTO(
            id=str(row.id),
            company_id=str(row.company_id),
            global_company_id=(str(row.global_company_id) if row.global_company_id else None),
            partner_code=row.partner_code,
            display_name=row.display_name,
            legal_name=row.legal_name,
            country_code=row.country_code,
            vat_number=row.vat_number,
            registration_number=row.registration_number,
            website_url=row.website_url,
            main_email=row.main_email,
            main_phone=row.main_phone,
            status=row.status,
            is_blacklisted=bool(row.is_blacklisted),
            is_watchlisted=bool(row.is_watchlisted),
            blacklist_reason=row.blacklist_reason,
            created_at=(row.created_at.isoformat() if row.created_at else None),
            updated_at=(row.updated_at.isoformat() if row.updated_at else None),
            archived_at=(row.archived_at.isoformat() if row.archived_at else None),
        )

    def _to_tenant_summary(self, row: TenantPartnerRatingSummary) -> TenantPartnerRatingSummaryDTO:
        return TenantPartnerRatingSummaryDTO(
            partner_id=str(row.partner_id),
            rating_count=int(row.rating_count),
            avg_execution_quality=row.avg_execution_quality,
            avg_communication_docs=row.avg_communication_docs,
            avg_payment_discipline=row.avg_payment_discipline,
            avg_overall_score=row.avg_overall_score,
            last_rating_at=(row.last_rating_at.isoformat() if row.last_rating_at else None),
            payment_issue_count=int(row.payment_issue_count),
            updated_at=(row.updated_at.isoformat() if row.updated_at else None),
        )

    def _dedupe_or_create_global(
        self,
        db: Session,
        *,
        country_code: str,
        display_name: str,
        legal_name: str | None,
        vat_number: str | None,
        registration_number: str | None,
        website_url: str | None,
        main_email: str | None,
        main_phone: str | None,
    ) -> GlobalCompany | None:
        country = self._country(country_code)
        vat = self._clean_opt(vat_number, 64)
        reg = self._clean_opt(registration_number, 64)
        canonical = self._clean(legal_name or display_name, 255)
        normalized_name = self._normalized_name(display_name, legal_name)
        if not canonical or not normalized_name:
            return None

        rows: list[GlobalCompany]
        if vat:
            rows = db.query(GlobalCompany).filter(GlobalCompany.country_code == country, GlobalCompany.vat_number == vat).all()
        elif reg:
            rows = db.query(GlobalCompany).filter(GlobalCompany.country_code == country, GlobalCompany.registration_number == reg).all()
        else:
            rows = db.query(GlobalCompany).filter(GlobalCompany.country_code == country, GlobalCompany.normalized_name == normalized_name).all()

        if len(rows) == 1:
            return rows[0]

        row = GlobalCompany(
            canonical_name=canonical,
            legal_name=self._clean_opt(legal_name, 255),
            country_code=country,
            vat_number=vat,
            registration_number=reg,
            website_url=self._clean_opt(website_url, 512),
            main_email=self._clean_opt(main_email, 255),
            main_phone=self._clean_opt(main_phone, 64),
            normalized_name=normalized_name,
            status="ACTIVE",
            created_at=self._now(),
            updated_at=self._now(),
        )
        db.add(row)
        db.flush()
        return row

    def _replace_roles(self, db: Session, *, partner_id: uuid.UUID, roles: list[PartnerRoleCode | str]) -> None:
        db.query(TenantPartnerRole).filter(TenantPartnerRole.partner_id == partner_id).delete(synchronize_session=False)
        for code in self._normalize_roles(roles):
            db.add(TenantPartnerRole(partner_id=partner_id, role_code=code))

    def _replace_addresses(self, db: Session, *, company_id: str, partner_id: uuid.UUID, rows: list[PartnerAddressDTO]) -> None:
        db.query(TenantPartnerAddress).filter(TenantPartnerAddress.partner_id == partner_id).delete(synchronize_session=False)
        now = self._now()
        for idx, x in enumerate(list(rows or [])):
            db.add(
                TenantPartnerAddress(
                    company_id=company_id,
                    partner_id=partner_id,
                    address_type=self._clean(x.address_type or "HQ", 32).upper(),
                    label=self._clean_opt(x.label, 128),
                    country_code=self._clean_opt(x.country_code, 8),
                    line1=self._clean_opt(x.line1, 255),
                    line2=self._clean_opt(x.line2, 255),
                    city=self._clean_opt(x.city, 128),
                    postal_code=self._clean_opt(x.postal_code, 32),
                    is_primary=bool(x.is_primary),
                    sort_order=int(x.sort_order if x.sort_order is not None else idx),
                    created_at=now,
                    updated_at=now,
                )
            )

    def _replace_banks(self, db: Session, *, company_id: str, partner_id: uuid.UUID, rows: list[PartnerBankAccountDTO]) -> None:
        db.query(TenantPartnerBankAccount).filter(TenantPartnerBankAccount.partner_id == partner_id).delete(synchronize_session=False)
        now = self._now()
        for x in list(rows or []):
            db.add(
                TenantPartnerBankAccount(
                    company_id=company_id,
                    partner_id=partner_id,
                    account_holder=self._clean_opt(x.account_holder, 255),
                    iban=self._clean_opt(x.iban, 64),
                    swift=self._clean_opt(x.swift, 32),
                    bank_name=self._clean_opt(x.bank_name, 255),
                    bank_country_code=self._clean_opt(x.bank_country_code, 8),
                    currency=self._clean_opt(x.currency, 16),
                    is_primary=bool(x.is_primary),
                    note=self._clean_opt(x.note, 1024),
                    created_at=now,
                    updated_at=now,
                )
            )

    def _replace_contacts(self, db: Session, *, company_id: str, partner_id: uuid.UUID, rows: list[PartnerContactDTO]) -> None:
        db.query(TenantPartnerContact).filter(TenantPartnerContact.partner_id == partner_id).delete(synchronize_session=False)
        now = self._now()
        for idx, x in enumerate(list(rows or [])):
            db.add(
                TenantPartnerContact(
                    company_id=company_id,
                    partner_id=partner_id,
                    contact_name=self._clean(x.contact_name, 255),
                    contact_role=self._clean_opt(x.contact_role, 128),
                    email=self._clean_opt(x.email, 255),
                    phone=self._clean_opt(x.phone, 64),
                    is_primary=bool(x.is_primary),
                    sort_order=int(x.sort_order if x.sort_order is not None else idx),
                    note=self._clean_opt(x.note, 1024),
                    created_at=now,
                    updated_at=now,
                )
            )

    def _replace_documents(self, db: Session, *, company_id: str, partner_id: uuid.UUID, rows: list[PartnerDocumentDTO]) -> None:
        db.query(TenantPartnerDocument).filter(TenantPartnerDocument.partner_id == partner_id).delete(synchronize_session=False)
        now = self._now()
        for x in list(rows or []):
            db.add(
                TenantPartnerDocument(
                    company_id=company_id,
                    partner_id=partner_id,
                    doc_type=self._clean(x.doc_type, 64),
                    file_name=self._clean(x.file_name, 255),
                    content_type=self._clean_opt(x.content_type, 128),
                    size_bytes=(int(x.size_bytes) if x.size_bytes is not None else None),
                    storage_key=self._clean(x.storage_key, 512),
                    uploaded_by_user_id=self._clean_opt(x.uploaded_by_user_id, 255),
                    note=self._clean_opt(x.note, 1024),
                    created_at=now,
                )
            )

    def _load_roles(self, db: Session, *, partner_id: uuid.UUID) -> list[PartnerRoleCode]:
        rows = db.query(TenantPartnerRole).filter(TenantPartnerRole.partner_id == partner_id).order_by(TenantPartnerRole.role_code.asc()).all()
        out: list[PartnerRoleCode] = []
        for row in rows:
            try:
                out.append(PartnerRoleCode(str(row.role_code)))
            except Exception:  # noqa: BLE001
                continue
        return out

    def _load_addresses(self, db: Session, *, partner_id: uuid.UUID) -> list[PartnerAddressDTO]:
        rows = (
            db.query(TenantPartnerAddress)
            .filter(TenantPartnerAddress.partner_id == partner_id)
            .order_by(TenantPartnerAddress.is_primary.desc(), TenantPartnerAddress.sort_order.asc())
            .all()
        )
        return [
            PartnerAddressDTO(
                id=str(x.id),
                address_type=x.address_type,
                label=x.label,
                country_code=x.country_code,
                line1=x.line1,
                line2=x.line2,
                city=x.city,
                postal_code=x.postal_code,
                is_primary=bool(x.is_primary),
                sort_order=int(x.sort_order),
                created_at=(x.created_at.isoformat() if x.created_at else None),
                updated_at=(x.updated_at.isoformat() if x.updated_at else None),
                archived_at=(x.archived_at.isoformat() if x.archived_at else None),
            )
            for x in rows
        ]

    def _load_banks(self, db: Session, *, partner_id: uuid.UUID) -> list[PartnerBankAccountDTO]:
        rows = (
            db.query(TenantPartnerBankAccount)
            .filter(TenantPartnerBankAccount.partner_id == partner_id)
            .order_by(TenantPartnerBankAccount.is_primary.desc(), TenantPartnerBankAccount.created_at.desc())
            .all()
        )
        return [
            PartnerBankAccountDTO(
                id=str(x.id),
                account_holder=x.account_holder,
                iban=x.iban,
                swift=x.swift,
                bank_name=x.bank_name,
                bank_country_code=x.bank_country_code,
                currency=x.currency,
                is_primary=bool(x.is_primary),
                note=x.note,
                created_at=(x.created_at.isoformat() if x.created_at else None),
                updated_at=(x.updated_at.isoformat() if x.updated_at else None),
                archived_at=(x.archived_at.isoformat() if x.archived_at else None),
            )
            for x in rows
        ]

    def _load_contacts(self, db: Session, *, partner_id: uuid.UUID) -> list[PartnerContactDTO]:
        rows = (
            db.query(TenantPartnerContact)
            .filter(TenantPartnerContact.partner_id == partner_id)
            .order_by(TenantPartnerContact.is_primary.desc(), TenantPartnerContact.sort_order.asc())
            .all()
        )
        return [
            PartnerContactDTO(
                id=str(x.id),
                contact_name=x.contact_name,
                contact_role=x.contact_role,
                email=x.email,
                phone=x.phone,
                is_primary=bool(x.is_primary),
                sort_order=int(x.sort_order),
                note=x.note,
                created_at=(x.created_at.isoformat() if x.created_at else None),
                updated_at=(x.updated_at.isoformat() if x.updated_at else None),
                archived_at=(x.archived_at.isoformat() if x.archived_at else None),
            )
            for x in rows
        ]

    def _load_documents(self, db: Session, *, partner_id: uuid.UUID) -> list[PartnerDocumentDTO]:
        rows = db.query(TenantPartnerDocument).filter(TenantPartnerDocument.partner_id == partner_id).order_by(TenantPartnerDocument.created_at.desc()).all()
        return [
            PartnerDocumentDTO(
                id=str(x.id),
                doc_type=x.doc_type,
                file_name=x.file_name,
                content_type=x.content_type,
                size_bytes=x.size_bytes,
                storage_key=x.storage_key,
                uploaded_by_user_id=x.uploaded_by_user_id,
                note=x.note,
                created_at=(x.created_at.isoformat() if x.created_at else None),
                archived_at=(x.archived_at.isoformat() if x.archived_at else None),
            )
            for x in rows
        ]

    def _overall_score(self, row: PartnerOrderRating) -> float:
        if row.payment_expected:
            return float(row.execution_quality_stars + row.communication_docs_stars + int(row.payment_discipline_stars or 0)) / 3.0
        return float(row.execution_quality_stars + row.communication_docs_stars) / 2.0

    def _recompute_tenant_summary(self, db: Session, *, company_id: str, partner_id: uuid.UUID) -> TenantPartnerRatingSummary | None:
        tenant_aggregate = (
            db.query(
                func.count(PartnerOrderRating.id),
                func.sum(case((PartnerOrderRating.payment_expected.is_(True), 1), else_=0)),
                func.avg(PartnerOrderRating.execution_quality_stars),
                func.avg(PartnerOrderRating.communication_docs_stars),
                func.avg(
                    case(
                        (PartnerOrderRating.payment_expected.is_(True), PartnerOrderRating.payment_discipline_stars),
                        else_=None,
                    )
                ),
                func.avg(
                    case(
                        (
                            PartnerOrderRating.payment_expected.is_(True),
                            (
                                PartnerOrderRating.execution_quality_stars
                                + PartnerOrderRating.communication_docs_stars
                                + PartnerOrderRating.payment_discipline_stars
                            ),
                        ),
                        else_=None,
                    )
                ),
                func.avg(
                    case(
                        (
                            PartnerOrderRating.payment_expected.is_(False),
                            (PartnerOrderRating.execution_quality_stars + PartnerOrderRating.communication_docs_stars),
                        ),
                        else_=None,
                    )
                ),
                func.max(PartnerOrderRating.created_at),
                func.sum(
                    case(
                        (
                            (PartnerOrderRating.payment_expected.is_(True))
                            & (PartnerOrderRating.payment_discipline_stars <= 2),
                            1,
                        ),
                        else_=0,
                    )
                ),
            )
            .filter(
                PartnerOrderRating.company_id == company_id,
                PartnerOrderRating.partner_id == partner_id,
            )
            .one()
        )
        rating_count = int(tenant_aggregate[0] or 0)
        summary = db.query(TenantPartnerRatingSummary).filter(TenantPartnerRatingSummary.partner_id == partner_id).first()
        if rating_count <= 0:
            if summary is not None:
                db.delete(summary)
            return None

        now = self._now()
        payment_count = int(tenant_aggregate[1] or 0)
        non_payment_count = max(0, rating_count - payment_count)
        overall_sum = 0.0
        if payment_count > 0 and tenant_aggregate[5] is not None:
            overall_sum += (float(tenant_aggregate[5]) / 3.0) * payment_count
        if non_payment_count > 0 and tenant_aggregate[6] is not None:
            overall_sum += (float(tenant_aggregate[6]) / 2.0) * non_payment_count
        avg_overall_score = (overall_sum / float(rating_count)) if rating_count > 0 else None
        payload = {
            "rating_count": rating_count,
            "avg_execution_quality": (float(tenant_aggregate[2]) if tenant_aggregate[2] is not None else None),
            "avg_communication_docs": (float(tenant_aggregate[3]) if tenant_aggregate[3] is not None else None),
            "avg_payment_discipline": (float(tenant_aggregate[4]) if tenant_aggregate[4] is not None else None),
            "avg_overall_score": avg_overall_score,
            "last_rating_at": tenant_aggregate[7],
            "payment_issue_count": int(tenant_aggregate[8] or 0),
            "updated_at": now,
        }
        if summary is None:
            summary = TenantPartnerRatingSummary(partner_id=partner_id, **payload)
            db.add(summary)
        else:
            for key, value in payload.items():
                setattr(summary, key, value)
        db.flush()
        return summary

    def _recompute_global_summary(self, db: Session, *, global_company_id: uuid.UUID | None) -> GlobalCompanyReputation | None:
        if global_company_id is None:
            return None
        partner_aggregate = (
            db.query(
                func.count(TenantPartner.id),
                func.count(distinct(TenantPartner.company_id)),
                func.sum(case((TenantPartner.is_blacklisted.is_(True), 1), else_=0)),
            )
            .filter(TenantPartner.global_company_id == global_company_id)
            .one()
        )
        rating_aggregate = (
            db.query(
                func.count(PartnerOrderRating.id),
                func.sum(case((PartnerOrderRating.payment_expected.is_(True), 1), else_=0)),
                func.avg(PartnerOrderRating.execution_quality_stars),
                func.avg(PartnerOrderRating.communication_docs_stars),
                func.avg(
                    case(
                        (PartnerOrderRating.payment_expected.is_(True), PartnerOrderRating.payment_discipline_stars),
                        else_=None,
                    )
                ),
                func.avg(
                    case(
                        (
                            PartnerOrderRating.payment_expected.is_(True),
                            (
                                PartnerOrderRating.execution_quality_stars
                                + PartnerOrderRating.communication_docs_stars
                                + PartnerOrderRating.payment_discipline_stars
                            ),
                        ),
                        else_=None,
                    )
                ),
                func.avg(
                    case(
                        (
                            PartnerOrderRating.payment_expected.is_(False),
                            (PartnerOrderRating.execution_quality_stars + PartnerOrderRating.communication_docs_stars),
                        ),
                        else_=None,
                    )
                ),
                func.sum(
                    case(
                        (
                            (PartnerOrderRating.payment_expected.is_(True))
                            & (PartnerOrderRating.payment_discipline_stars <= 2),
                            1,
                        ),
                        else_=0,
                    )
                ),
                func.sum(
                    case(
                        (
                            (PartnerOrderRating.execution_quality_stars <= 2)
                            | (PartnerOrderRating.communication_docs_stars <= 2),
                            1,
                        ),
                        else_=0,
                    )
                ),
            )
            .join(TenantPartner, TenantPartner.id == PartnerOrderRating.partner_id)
            .filter(TenantPartner.global_company_id == global_company_id)
            .one()
        )
        total_ratings = int(rating_aggregate[0] or 0)
        payment_count = int(rating_aggregate[1] or 0)
        non_payment_count = max(0, total_ratings - payment_count)
        overall_sum = 0.0
        if payment_count > 0 and rating_aggregate[5] is not None:
            overall_sum += (float(rating_aggregate[5]) / 3.0) * payment_count
        if non_payment_count > 0 and rating_aggregate[6] is not None:
            overall_sum += (float(rating_aggregate[6]) / 2.0) * non_payment_count
        global_overall_score = (overall_sum / float(total_ratings)) if total_ratings > 0 else None
        now = self._now()
        payload = {
            "total_tenants": int(partner_aggregate[1] or 0),
            "total_completed_orders_rated": total_ratings,
            "avg_execution_quality": (float(rating_aggregate[2]) if rating_aggregate[2] is not None else None),
            "avg_communication_docs": (float(rating_aggregate[3]) if rating_aggregate[3] is not None else None),
            "avg_payment_discipline": (float(rating_aggregate[4]) if rating_aggregate[4] is not None else None),
            "global_overall_score": global_overall_score,
            "risk_payment_count": int(rating_aggregate[7] or 0),
            "risk_quality_count": int(rating_aggregate[8] or 0),
            "blacklist_signal_count": int(partner_aggregate[2] or 0),
            "updated_at": now,
        }
        row = db.query(GlobalCompanyReputation).filter(GlobalCompanyReputation.global_company_id == global_company_id).first()
        if row is None:
            row = GlobalCompanyReputation(global_company_id=global_company_id, **payload)
            db.add(row)
        else:
            for key, value in payload.items():
                setattr(row, key, value)
        db.flush()
        return row

    def _global_signal(self, db: Session, *, global_company_id: uuid.UUID | None) -> GlobalCompanySignalDTO | None:
        if global_company_id is None:
            return None
        company = db.query(GlobalCompany).filter(GlobalCompany.id == global_company_id).first()
        if company is None:
            return None
        rep = db.query(GlobalCompanyReputation).filter(GlobalCompanyReputation.global_company_id == global_company_id).first()
        return GlobalCompanySignalDTO(
            global_company_id=str(company.id),
            canonical_name=company.canonical_name,
            legal_name=company.legal_name,
            country_code=company.country_code,
            vat_number=company.vat_number,
            registration_number=company.registration_number,
            status=company.status,
            total_tenants=(int(rep.total_tenants) if rep is not None else 0),
            total_completed_orders_rated=(int(rep.total_completed_orders_rated) if rep is not None else 0),
            avg_execution_quality=(rep.avg_execution_quality if rep is not None else None),
            avg_communication_docs=(rep.avg_communication_docs if rep is not None else None),
            avg_payment_discipline=(rep.avg_payment_discipline if rep is not None else None),
            global_overall_score=(rep.global_overall_score if rep is not None else None),
            risk_payment_count=(int(rep.risk_payment_count) if rep is not None else 0),
            risk_quality_count=(int(rep.risk_quality_count) if rep is not None else 0),
            blacklist_signal_count=(int(rep.blacklist_signal_count) if rep is not None else 0),
            updated_at=(rep.updated_at.isoformat() if rep is not None and rep.updated_at else None),
        )

    def _to_detail(self, db: Session, row: TenantPartner) -> PartnerDetailDTO:
        summary = self._to_summary(row)
        tenant_summary_row = db.query(TenantPartnerRatingSummary).filter(TenantPartnerRatingSummary.partner_id == row.id).first()
        return PartnerDetailDTO(
            **summary.model_dump(),
            internal_note=row.internal_note,
            roles=self._load_roles(db, partner_id=row.id),
            addresses=self._load_addresses(db, partner_id=row.id),
            bank_accounts=self._load_banks(db, partner_id=row.id),
            contacts=self._load_contacts(db, partner_id=row.id),
            documents=self._load_documents(db, partner_id=row.id),
            rating_summary=(self._to_tenant_summary(tenant_summary_row) if tenant_summary_row is not None else None),
        )

    def create_partner(self, db: Session, *, company_id: str, payload: PartnerCreateRequestDTO) -> PartnerDetailDTO:
        partner_code = self._clean(payload.partner_code, 64).upper() if payload.partner_code else f"PARTNER-{str(uuid.uuid4())[:8].upper()}"
        if db.query(TenantPartner.id).filter(TenantPartner.company_id == company_id, TenantPartner.partner_code == partner_code).first() is not None:
            raise ValueError("partner_code_exists")
        display_name = self._clean(payload.display_name, 255)
        if not display_name:
            raise ValueError("display_name_required")
        global_company = self._dedupe_or_create_global(
            db,
            country_code=payload.country_code,
            display_name=display_name,
            legal_name=payload.legal_name,
            vat_number=payload.vat_number,
            registration_number=payload.registration_number,
            website_url=payload.website_url,
            main_email=payload.main_email,
            main_phone=payload.main_phone,
        )
        now = self._now()
        row = TenantPartner(
            company_id=company_id,
            global_company_id=(global_company.id if global_company is not None else None),
            partner_code=partner_code,
            display_name=display_name,
            legal_name=self._clean_opt(payload.legal_name, 255),
            country_code=self._country(payload.country_code),
            vat_number=self._clean_opt(payload.vat_number, 64),
            registration_number=self._clean_opt(payload.registration_number, 64),
            website_url=self._clean_opt(payload.website_url, 512),
            main_email=self._clean_opt(payload.main_email, 255),
            main_phone=self._clean_opt(payload.main_phone, 64),
            status=self._status(payload.status),
            is_blacklisted=bool(payload.is_blacklisted),
            is_watchlisted=bool(payload.is_watchlisted),
            blacklist_reason=self._clean_opt(payload.blacklist_reason, 1024),
            internal_note=self._clean_opt(payload.internal_note, 4000),
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        db.flush()
        self._replace_roles(db, partner_id=row.id, roles=payload.roles)
        self._replace_addresses(db, company_id=company_id, partner_id=row.id, rows=payload.addresses)
        self._replace_banks(db, company_id=company_id, partner_id=row.id, rows=payload.bank_accounts)
        self._replace_contacts(db, company_id=company_id, partner_id=row.id, rows=payload.contacts)
        self._replace_documents(db, company_id=company_id, partner_id=row.id, rows=payload.documents)
        self._recompute_global_summary(db, global_company_id=row.global_company_id)
        return self._to_detail(db, row)

    def list_partners(self, db: Session, *, company_id: str, status: str | None = None, include_archived: bool = False, limit: int = 200) -> list[PartnerSummaryDTO]:
        q = db.query(TenantPartner).filter(TenantPartner.company_id == company_id)
        if not include_archived:
            q = q.filter(TenantPartner.archived_at.is_(None))
        if status:
            q = q.filter(TenantPartner.status == self._status(status))
        rows = q.order_by(TenantPartner.updated_at.desc()).limit(max(1, min(int(limit), 1000))).all()
        return [self._to_summary(x) for x in rows]

    def get_partner(self, db: Session, *, company_id: str, partner_id: str, include_archived: bool = False) -> PartnerDetailDTO:
        return self._to_detail(db, self._partner_row(db, company_id=company_id, partner_id=partner_id, include_archived=include_archived))

    def update_partner(self, db: Session, *, company_id: str, partner_id: str, payload: PartnerUpdateRequestDTO) -> PartnerDetailDTO:
        row = self._partner_row(db, company_id=company_id, partner_id=partner_id)
        old_global_company_id = row.global_company_id
        changed = payload.model_dump(exclude_unset=True)
        if "display_name" in changed:
            row.display_name = self._clean(payload.display_name, 255)
            if not row.display_name:
                raise ValueError("display_name_required")
        if "legal_name" in changed:
            row.legal_name = self._clean_opt(payload.legal_name, 255)
        if "country_code" in changed:
            row.country_code = self._country(payload.country_code)
        if "vat_number" in changed:
            row.vat_number = self._clean_opt(payload.vat_number, 64)
        if "registration_number" in changed:
            row.registration_number = self._clean_opt(payload.registration_number, 64)
        if "website_url" in changed:
            row.website_url = self._clean_opt(payload.website_url, 512)
        if "main_email" in changed:
            row.main_email = self._clean_opt(payload.main_email, 255)
        if "main_phone" in changed:
            row.main_phone = self._clean_opt(payload.main_phone, 64)
        if "status" in changed:
            row.status = self._status(payload.status)
        if "internal_note" in changed:
            row.internal_note = self._clean_opt(payload.internal_note, 4000)

        if any(k in changed for k in {"display_name", "legal_name", "country_code", "vat_number", "registration_number", "website_url", "main_email", "main_phone"}):
            global_company = self._dedupe_or_create_global(
                db,
                country_code=row.country_code,
                display_name=row.display_name,
                legal_name=row.legal_name,
                vat_number=row.vat_number,
                registration_number=row.registration_number,
                website_url=row.website_url,
                main_email=row.main_email,
                main_phone=row.main_phone,
            )
            row.global_company_id = (global_company.id if global_company is not None else None)

        if payload.addresses is not None:
            self._replace_addresses(db, company_id=company_id, partner_id=row.id, rows=payload.addresses)
        if payload.bank_accounts is not None:
            self._replace_banks(db, company_id=company_id, partner_id=row.id, rows=payload.bank_accounts)
        if payload.contacts is not None:
            self._replace_contacts(db, company_id=company_id, partner_id=row.id, rows=payload.contacts)
        if payload.documents is not None:
            self._replace_documents(db, company_id=company_id, partner_id=row.id, rows=payload.documents)

        row.updated_at = self._now()
        db.flush()
        if old_global_company_id != row.global_company_id:
            self._recompute_global_summary(db, global_company_id=old_global_company_id)
        self._recompute_global_summary(db, global_company_id=row.global_company_id)
        return self._to_detail(db, row)

    def set_roles(self, db: Session, *, company_id: str, partner_id: str, roles: list[PartnerRoleCode | str]) -> PartnerDetailDTO:
        row = self._partner_row(db, company_id=company_id, partner_id=partner_id)
        self._replace_roles(db, partner_id=row.id, roles=roles)
        row.updated_at = self._now()
        db.flush()
        return self._to_detail(db, row)

    def archive_partner(self, db: Session, *, company_id: str, partner_id: str) -> PartnerDetailDTO:
        row = self._partner_row(db, company_id=company_id, partner_id=partner_id)
        now = self._now()
        row.status = "ARCHIVED"
        row.archived_at = now
        row.updated_at = now
        db.flush()
        self._recompute_global_summary(db, global_company_id=row.global_company_id)
        return self._to_detail(db, row)

    def set_blacklist(self, db: Session, *, company_id: str, partner_id: str, is_blacklisted: bool, blacklist_reason: str | None) -> PartnerDetailDTO:
        row = self._partner_row(db, company_id=company_id, partner_id=partner_id)
        row.is_blacklisted = bool(is_blacklisted)
        row.blacklist_reason = self._clean_opt(blacklist_reason, 1024)
        row.updated_at = self._now()
        db.flush()
        self._recompute_global_summary(db, global_company_id=row.global_company_id)
        return self._to_detail(db, row)

    def set_watchlist(self, db: Session, *, company_id: str, partner_id: str, is_watchlisted: bool) -> PartnerDetailDTO:
        row = self._partner_row(db, company_id=company_id, partner_id=partner_id)
        row.is_watchlisted = bool(is_watchlisted)
        row.updated_at = self._now()
        db.flush()
        return self._to_detail(db, row)

    def create_rating(self, db: Session, *, company_id: str, partner_id: str, actor: str, payload: PartnerRatingCreateRequestDTO) -> tuple[str, TenantPartnerRatingSummaryDTO, GlobalCompanySignalDTO | None]:
        row = self._partner_row(db, company_id=company_id, partner_id=partner_id)
        if payload.payment_expected and payload.payment_discipline_stars is None:
            raise ValueError("payment_discipline_required_when_payment_expected")
        if (not payload.payment_expected) and payload.payment_discipline_stars is not None:
            raise ValueError("payment_discipline_not_allowed_when_payment_not_expected")

        rating = PartnerOrderRating(
            company_id=company_id,
            partner_id=row.id,
            order_id=self._parse_uuid(payload.order_id, "order_id"),
            rated_by_user_id=self._clean(actor, 255) or "unknown",
            execution_quality_stars=int(payload.execution_quality_stars),
            communication_docs_stars=int(payload.communication_docs_stars),
            payment_discipline_stars=(int(payload.payment_discipline_stars) if payload.payment_discipline_stars is not None else None),
            payment_expected=bool(payload.payment_expected),
            short_comment=self._clean_opt(payload.short_comment, 2000),
            issue_flags_json=(dict(payload.issue_flags_json or {}) if isinstance(payload.issue_flags_json, dict) else {}),
            created_at=self._now(),
            updated_at=self._now(),
        )
        db.add(rating)
        db.flush()
        summary = self._recompute_tenant_summary(db, company_id=company_id, partner_id=row.id)
        if summary is None:
            raise ValueError("rating_summary_recompute_failed")
        self._recompute_global_summary(db, global_company_id=row.global_company_id)
        return str(rating.id), self._to_tenant_summary(summary), self._global_signal(db, global_company_id=row.global_company_id)

    def get_rating_summary(self, db: Session, *, company_id: str, partner_id: str) -> TenantPartnerRatingSummaryDTO | None:
        row = self._partner_row(db, company_id=company_id, partner_id=partner_id)
        summary = db.query(TenantPartnerRatingSummary).filter(TenantPartnerRatingSummary.partner_id == row.id).first()
        return self._to_tenant_summary(summary) if summary is not None else None

    def get_global_signal(self, db: Session, *, company_id: str, partner_id: str) -> GlobalCompanySignalDTO | None:
        row = self._partner_row(db, company_id=company_id, partner_id=partner_id)
        return self._global_signal(db, global_company_id=row.global_company_id)


service = PartnersService()
