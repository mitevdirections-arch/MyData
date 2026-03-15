from __future__ import annotations

from datetime import datetime, timezone
import uuid
import re
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.authz_fast_path import (
    recompute_effective_permissions_for_role,
    upsert_effective_permissions_snapshot,
)
from app.core.settings import get_settings

from app.db.models import (
    AdminProfile,
    DeviceLease,
    License,
    Tenant,
    WorkspaceAddress,
    WorkspaceContactPoint,
    WorkspaceOrganizationProfile,
    WorkspaceRole,
    WorkspaceUser,
    WorkspaceUserRole,
)
from app.modules.profile.service_constants import (
    CORE_PLAN_SEATS,
    DEFAULT_PLATFORM_ROLES,
    DEFAULT_TENANT_ROLES,
    PERM_RE,
    PLATFORM_WORKSPACE_ID,
    ROLE_CODE_RE,
    UNLIMITED_CORE_PLANS,
    WORKSPACE_PLATFORM,
    WORKSPACE_TENANT,
)

class ProfileOrganizationMixin:
    def _clean_sort_order(self, value: Any, default: int = 0) -> int:
        try:
            out = int(value)
        except Exception:  # noqa: BLE001
            return default
        if out < 0:
            return 0
        if out > 100000:
            return 100000
        return out

    def _parse_uuid(self, value: Any, field_name: str) -> uuid.UUID:
        try:
            return uuid.UUID(str(value or "").strip())
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"{field_name}_invalid") from exc

    def _contact_to_dict(self, row: WorkspaceContactPoint) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "workspace_type": row.workspace_type,
            "workspace_id": row.workspace_id,
            "contact_kind": row.contact_kind,
            "label": row.label,
            "email": row.email,
            "phone": row.phone,
            "website_url": row.website_url,
            "is_primary": bool(row.is_primary),
            "is_public": bool(row.is_public),
            "sort_order": int(row.sort_order or 0),
            "metadata": row.metadata_json or {},
            "updated_by": row.updated_by,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def _address_to_dict(self, row: WorkspaceAddress) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "workspace_type": row.workspace_type,
            "workspace_id": row.workspace_id,
            "address_kind": row.address_kind,
            "label": row.label,
            "country_code": row.country_code,
            "line1": row.line1,
            "line2": row.line2,
            "city": row.city,
            "postal_code": row.postal_code,
            "is_primary": bool(row.is_primary),
            "is_public": bool(row.is_public),
            "sort_order": int(row.sort_order or 0),
            "metadata": row.metadata_json or {},
            "updated_by": row.updated_by,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def _list_contact_rows(self, db: Session, *, workspace_type: str, workspace_id: str, limit: int = 500) -> list[WorkspaceContactPoint]:
        return (
            db.query(WorkspaceContactPoint)
            .filter(
                WorkspaceContactPoint.workspace_type == workspace_type,
                WorkspaceContactPoint.workspace_id == workspace_id,
            )
            .order_by(
                WorkspaceContactPoint.is_primary.desc(),
                WorkspaceContactPoint.sort_order.asc(),
                WorkspaceContactPoint.created_at.asc(),
            )
            .limit(max(1, min(int(limit), 5000)))
            .all()
        )

    def _list_address_rows(self, db: Session, *, workspace_type: str, workspace_id: str, limit: int = 500) -> list[WorkspaceAddress]:
        return (
            db.query(WorkspaceAddress)
            .filter(
                WorkspaceAddress.workspace_type == workspace_type,
                WorkspaceAddress.workspace_id == workspace_id,
            )
            .order_by(
                WorkspaceAddress.is_primary.desc(),
                WorkspaceAddress.sort_order.asc(),
                WorkspaceAddress.created_at.asc(),
            )
            .limit(max(1, min(int(limit), 5000)))
            .all()
        )

    def _get_org_row(self, db: Session, *, workspace_type: str, workspace_id: str, actor: str) -> WorkspaceOrganizationProfile:
        self.get_or_create_organization_profile(db, workspace_type=workspace_type, workspace_id=workspace_id, actor=actor)
        row = (
            db.query(WorkspaceOrganizationProfile)
            .filter(
                WorkspaceOrganizationProfile.workspace_type == workspace_type,
                WorkspaceOrganizationProfile.workspace_id == workspace_id,
            )
            .first()
        )
        if row is None:
            raise ValueError("workspace_org_profile_not_found")
        return row

    def _sync_primary_contact_from_org(self, db: Session, *, row: WorkspaceOrganizationProfile, actor: str) -> None:
        primary = (
            db.query(WorkspaceContactPoint)
            .filter(
                WorkspaceContactPoint.workspace_type == row.workspace_type,
                WorkspaceContactPoint.workspace_id == row.workspace_id,
                WorkspaceContactPoint.is_primary == True,  # noqa: E712
            )
            .order_by(WorkspaceContactPoint.sort_order.asc(), WorkspaceContactPoint.created_at.asc())
            .first()
        )
        now = self._now()
        if primary is None:
            primary = WorkspaceContactPoint(
                workspace_type=row.workspace_type,
                workspace_id=row.workspace_id,
                contact_kind="GENERAL",
                label="Primary",
                email=row.contact_email,
                phone=row.contact_phone,
                website_url=row.website_url,
                is_primary=True,
                is_public=True,
                sort_order=0,
                metadata_json={},
                created_by=str(actor or "unknown"),
                updated_by=str(actor or "unknown"),
                created_at=now,
                updated_at=now,
            )
            db.add(primary)
            db.flush()
            return

        primary.contact_kind = primary.contact_kind or "GENERAL"
        primary.label = primary.label or "Primary"
        primary.email = row.contact_email
        primary.phone = row.contact_phone
        primary.website_url = row.website_url
        primary.is_primary = True
        primary.updated_by = str(actor or "unknown")
        primary.updated_at = now
        db.flush()

    def _sync_primary_address_from_org(self, db: Session, *, row: WorkspaceOrganizationProfile, actor: str) -> None:
        primary = (
            db.query(WorkspaceAddress)
            .filter(
                WorkspaceAddress.workspace_type == row.workspace_type,
                WorkspaceAddress.workspace_id == row.workspace_id,
                WorkspaceAddress.is_primary == True,  # noqa: E712
            )
            .order_by(WorkspaceAddress.sort_order.asc(), WorkspaceAddress.created_at.asc())
            .first()
        )
        now = self._now()
        if primary is None:
            primary = WorkspaceAddress(
                workspace_type=row.workspace_type,
                workspace_id=row.workspace_id,
                address_kind="REGISTERED",
                label="Registered",
                country_code=row.address_country_code,
                line1=row.address_line1,
                line2=row.address_line2,
                city=row.address_city,
                postal_code=row.address_postal_code,
                is_primary=True,
                is_public=False,
                sort_order=0,
                metadata_json={},
                created_by=str(actor or "unknown"),
                updated_by=str(actor or "unknown"),
                created_at=now,
                updated_at=now,
            )
            db.add(primary)
            db.flush()
            return

        primary.address_kind = primary.address_kind or "REGISTERED"
        primary.label = primary.label or "Registered"
        primary.country_code = row.address_country_code
        primary.line1 = row.address_line1
        primary.line2 = row.address_line2
        primary.city = row.address_city
        primary.postal_code = row.address_postal_code
        primary.is_primary = True
        primary.updated_by = str(actor or "unknown")
        primary.updated_at = now
        db.flush()

    def _sync_org_from_primary_contact(self, db: Session, *, org: WorkspaceOrganizationProfile, actor: str) -> None:
        rows = self._list_contact_rows(db, workspace_type=org.workspace_type, workspace_id=org.workspace_id, limit=500)
        primary = next((x for x in rows if bool(x.is_primary)), rows[0] if rows else None)
        if primary is not None and not bool(primary.is_primary):
            primary.is_primary = True
            primary.updated_by = str(actor or "unknown")
            primary.updated_at = self._now()
            db.flush()

        org.contact_email = primary.email if primary is not None else None
        org.contact_phone = primary.phone if primary is not None else None
        org.website_url = primary.website_url if primary is not None else None
        org.updated_by = str(actor or "unknown")
        org.updated_at = self._now()
        db.flush()

    def _sync_org_from_primary_address(self, db: Session, *, org: WorkspaceOrganizationProfile, actor: str) -> None:
        rows = self._list_address_rows(db, workspace_type=org.workspace_type, workspace_id=org.workspace_id, limit=500)
        primary = next((x for x in rows if bool(x.is_primary)), rows[0] if rows else None)
        if primary is not None and not bool(primary.is_primary):
            primary.is_primary = True
            primary.updated_by = str(actor or "unknown")
            primary.updated_at = self._now()
            db.flush()

        org.address_country_code = primary.country_code if primary is not None else None
        org.address_line1 = primary.line1 if primary is not None else None
        org.address_line2 = primary.line2 if primary is not None else None
        org.address_city = primary.city if primary is not None else None
        org.address_postal_code = primary.postal_code if primary is not None else None
        org.updated_by = str(actor or "unknown")
        org.updated_at = self._now()
        db.flush()

    def _org_to_dict(self, db: Session, row: WorkspaceOrganizationProfile) -> dict[str, Any]:
        contact_rows = self._list_contact_rows(db, workspace_type=row.workspace_type, workspace_id=row.workspace_id, limit=1000)
        address_rows = self._list_address_rows(db, workspace_type=row.workspace_type, workspace_id=row.workspace_id, limit=1000)
        return {
            "id": str(row.id),
            "workspace_type": row.workspace_type,
            "workspace_id": row.workspace_id,
            "legal": {
                "legal_name": row.legal_name,
                "vat_number": row.vat_number,
                "registration_number": row.registration_number,
                "company_size_hint": row.company_size_hint,
                "legal_form": row.company_size_hint,
                "industry": row.industry,
            },
            "contacts": {
                "email": row.contact_email,
                "phone": row.contact_phone,
                "website_url": row.website_url,
            },
            "contact_points": [self._contact_to_dict(x) for x in contact_rows],
            "address": {
                "country_code": row.address_country_code,
                "line1": row.address_line1,
                "line2": row.address_line2,
                "city": row.address_city,
                "postal_code": row.address_postal_code,
            },
            "addresses": [self._address_to_dict(x) for x in address_rows],
            "banking": {
                "account_holder": row.bank_account_holder,
                "iban": row.bank_iban,
                "swift": row.bank_swift,
                "bank_name": row.bank_name,
                "currency": row.bank_currency,
            },
            "presentation": {
                "activity_summary": row.activity_summary,
                "presentation_text": row.presentation_text,
            },
            "metadata": row.metadata_json or {},
            "updated_by": row.updated_by,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def get_or_create_organization_profile(self, db: Session, *, workspace_type: str, workspace_id: str, actor: str) -> dict[str, Any]:
        self._ensure_workspace_exists(db, workspace_type=workspace_type, workspace_id=workspace_id)
        row = (
            db.query(WorkspaceOrganizationProfile)
            .filter(
                WorkspaceOrganizationProfile.workspace_type == workspace_type,
                WorkspaceOrganizationProfile.workspace_id == workspace_id,
            )
            .first()
        )
        if row is None:
            now = self._now()
            tenant = db.query(Tenant).filter(Tenant.id == workspace_id).first() if workspace_type == WORKSPACE_TENANT else None
            row = WorkspaceOrganizationProfile(
                workspace_type=workspace_type,
                workspace_id=workspace_id,
                legal_name=(tenant.name if tenant is not None else "MyData Platform"),
                vat_number=(tenant.vat_number if tenant is not None else None),
                registration_number=None,
                company_size_hint=None,
                industry=None,
                activity_summary=None,
                presentation_text=None,
                contact_email=None,
                contact_phone=None,
                website_url=None,
                address_country_code=None,
                address_line1=None,
                address_line2=None,
                address_city=None,
                address_postal_code=None,
                bank_account_holder=None,
                bank_iban=None,
                bank_swift=None,
                bank_name=None,
                bank_currency=None,
                metadata_json={},
                created_by=str(actor or "unknown"),
                updated_by=str(actor or "unknown"),
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.flush()
        return self._org_to_dict(db, row)

    def update_organization_profile(self, db: Session, *, workspace_type: str, workspace_id: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.get_or_create_organization_profile(db, workspace_type=workspace_type, workspace_id=workspace_id, actor=actor)
        row = (
            db.query(WorkspaceOrganizationProfile)
            .filter(
                WorkspaceOrganizationProfile.workspace_type == workspace_type,
                WorkspaceOrganizationProfile.workspace_id == workspace_id,
            )
            .first()
        )
        if row is None:
            raise ValueError("workspace_org_profile_not_found")

        legal = payload.get("legal") if isinstance(payload.get("legal"), dict) else {}
        contacts = payload.get("contacts") if isinstance(payload.get("contacts"), dict) else {}
        address = payload.get("address") if isinstance(payload.get("address"), dict) else {}
        banking = payload.get("banking") if isinstance(payload.get("banking"), dict) else {}
        presentation = payload.get("presentation") if isinstance(payload.get("presentation"), dict) else {}

        legal_form = self._clean_text(legal.get("legal_form"), 64)
        if legal_form is None and "legal_form" not in legal:
            legal_form = self._clean_text(legal.get("company_size_hint"), 64)

        row.legal_name = self._clean_text(legal.get("legal_name"), 255)
        row.vat_number = self._clean_text(legal.get("vat_number"), 64)
        row.registration_number = self._clean_text(legal.get("registration_number"), 64)
        row.company_size_hint = legal_form
        row.industry = self._clean_text(legal.get("industry"), 128)

        row.contact_email = self._clean_text(contacts.get("email"), 255)
        row.contact_phone = self._clean_text(contacts.get("phone"), 64)
        row.website_url = self._clean_text(contacts.get("website_url"), 1024)

        row.address_country_code = self._clean_text(address.get("country_code"), 8)
        row.address_line1 = self._clean_text(address.get("line1"), 255)
        row.address_line2 = self._clean_text(address.get("line2"), 255)
        row.address_city = self._clean_text(address.get("city"), 128)
        row.address_postal_code = self._clean_text(address.get("postal_code"), 32)

        row.bank_account_holder = self._clean_text(banking.get("account_holder"), 255)
        row.bank_iban = self._clean_text(banking.get("iban"), 64)
        row.bank_swift = self._clean_text(banking.get("swift"), 32)
        row.bank_name = self._clean_text(banking.get("bank_name"), 255)
        row.bank_currency = self._clean_text(banking.get("currency"), 16)

        row.activity_summary = self._clean_text(presentation.get("activity_summary"), 2000)
        row.presentation_text = self._clean_text(presentation.get("presentation_text"), 5000)

        if isinstance(payload.get("metadata"), dict):
            row.metadata_json = dict(payload.get("metadata") or {})

        row.updated_by = str(actor or "unknown")
        row.updated_at = self._now()
        db.flush()

        self._sync_primary_contact_from_org(db, row=row, actor=actor)
        self._sync_primary_address_from_org(db, row=row, actor=actor)
        return self._org_to_dict(db, row)

    def list_contact_points(self, db: Session, *, workspace_type: str, workspace_id: str, actor: str, limit: int = 500) -> list[dict[str, Any]]:
        self._get_org_row(db, workspace_type=workspace_type, workspace_id=workspace_id, actor=actor)
        rows = self._list_contact_rows(db, workspace_type=workspace_type, workspace_id=workspace_id, limit=limit)
        return [self._contact_to_dict(x) for x in rows]

    def upsert_contact_point(
        self,
        db: Session,
        *,
        workspace_type: str,
        workspace_id: str,
        actor: str,
        payload: dict[str, Any],
        contact_id: str | None = None,
    ) -> dict[str, Any]:
        org = self._get_org_row(db, workspace_type=workspace_type, workspace_id=workspace_id, actor=actor)
        now = self._now()

        row: WorkspaceContactPoint | None = None
        existing_count = int(
            db.query(WorkspaceContactPoint)
            .filter(
                WorkspaceContactPoint.workspace_type == workspace_type,
                WorkspaceContactPoint.workspace_id == workspace_id,
            )
            .count()
        )
        if contact_id is not None:
            cid = self._parse_uuid(contact_id, "contact_id")
            row = (
                db.query(WorkspaceContactPoint)
                .filter(
                    WorkspaceContactPoint.id == cid,
                    WorkspaceContactPoint.workspace_type == workspace_type,
                    WorkspaceContactPoint.workspace_id == workspace_id,
                )
                .first()
            )
            if row is None:
                raise ValueError("contact_not_found")

        if row is None:
            row = WorkspaceContactPoint(
                workspace_type=workspace_type,
                workspace_id=workspace_id,
                contact_kind=(self._clean_text(payload.get("contact_kind"), 32) or "GENERAL").upper(),
                label=self._clean_text(payload.get("label"), 128),
                email=self._clean_text(payload.get("email"), 255),
                phone=self._clean_text(payload.get("phone"), 64),
                website_url=self._clean_text(payload.get("website_url"), 1024),
                is_primary=bool(payload.get("is_primary", existing_count == 0)),
                is_public=bool(payload.get("is_public", False)),
                sort_order=self._clean_sort_order(payload.get("sort_order"), default=0),
                metadata_json=(dict(payload.get("metadata") or {}) if isinstance(payload.get("metadata"), dict) else {}),
                created_by=str(actor or "unknown"),
                updated_by=str(actor or "unknown"),
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.flush()
        else:
            if "contact_kind" in payload:
                row.contact_kind = (self._clean_text(payload.get("contact_kind"), 32) or row.contact_kind or "GENERAL").upper()
            if "label" in payload:
                row.label = self._clean_text(payload.get("label"), 128)
            if "email" in payload:
                row.email = self._clean_text(payload.get("email"), 255)
            if "phone" in payload:
                row.phone = self._clean_text(payload.get("phone"), 64)
            if "website_url" in payload:
                row.website_url = self._clean_text(payload.get("website_url"), 1024)
            if "is_primary" in payload:
                row.is_primary = bool(payload.get("is_primary"))
            if "is_public" in payload:
                row.is_public = bool(payload.get("is_public"))
            if "sort_order" in payload:
                row.sort_order = self._clean_sort_order(payload.get("sort_order"), default=int(row.sort_order or 0))
            if "metadata" in payload and isinstance(payload.get("metadata"), dict):
                row.metadata_json = dict(payload.get("metadata") or {})
            row.updated_by = str(actor or "unknown")
            row.updated_at = now

        if bool(row.is_primary):
            (
                db.query(WorkspaceContactPoint)
                .filter(
                    WorkspaceContactPoint.workspace_type == workspace_type,
                    WorkspaceContactPoint.workspace_id == workspace_id,
                    WorkspaceContactPoint.id != row.id,
                )
                .update({WorkspaceContactPoint.is_primary: False}, synchronize_session=False)
            )

        db.flush()
        self._sync_org_from_primary_contact(db, org=org, actor=actor)
        return self._contact_to_dict(row)

    def delete_contact_point(self, db: Session, *, workspace_type: str, workspace_id: str, actor: str, contact_id: str) -> dict[str, Any]:
        org = self._get_org_row(db, workspace_type=workspace_type, workspace_id=workspace_id, actor=actor)
        cid = self._parse_uuid(contact_id, "contact_id")
        row = (
            db.query(WorkspaceContactPoint)
            .filter(
                WorkspaceContactPoint.id == cid,
                WorkspaceContactPoint.workspace_type == workspace_type,
                WorkspaceContactPoint.workspace_id == workspace_id,
            )
            .first()
        )
        if row is None:
            raise ValueError("contact_not_found")
        out = self._contact_to_dict(row)
        db.delete(row)
        db.flush()
        self._sync_org_from_primary_contact(db, org=org, actor=actor)
        return out

    def list_addresses(self, db: Session, *, workspace_type: str, workspace_id: str, actor: str, limit: int = 500) -> list[dict[str, Any]]:
        self._get_org_row(db, workspace_type=workspace_type, workspace_id=workspace_id, actor=actor)
        rows = self._list_address_rows(db, workspace_type=workspace_type, workspace_id=workspace_id, limit=limit)
        return [self._address_to_dict(x) for x in rows]

    def upsert_address(
        self,
        db: Session,
        *,
        workspace_type: str,
        workspace_id: str,
        actor: str,
        payload: dict[str, Any],
        address_id: str | None = None,
    ) -> dict[str, Any]:
        org = self._get_org_row(db, workspace_type=workspace_type, workspace_id=workspace_id, actor=actor)
        now = self._now()

        row: WorkspaceAddress | None = None
        existing_count = int(
            db.query(WorkspaceAddress)
            .filter(
                WorkspaceAddress.workspace_type == workspace_type,
                WorkspaceAddress.workspace_id == workspace_id,
            )
            .count()
        )
        if address_id is not None:
            aid = self._parse_uuid(address_id, "address_id")
            row = (
                db.query(WorkspaceAddress)
                .filter(
                    WorkspaceAddress.id == aid,
                    WorkspaceAddress.workspace_type == workspace_type,
                    WorkspaceAddress.workspace_id == workspace_id,
                )
                .first()
            )
            if row is None:
                raise ValueError("address_not_found")

        if row is None:
            row = WorkspaceAddress(
                workspace_type=workspace_type,
                workspace_id=workspace_id,
                address_kind=(self._clean_text(payload.get("address_kind"), 32) or "REGISTERED").upper(),
                label=self._clean_text(payload.get("label"), 128),
                country_code=self._clean_text(payload.get("country_code"), 8),
                line1=self._clean_text(payload.get("line1"), 255),
                line2=self._clean_text(payload.get("line2"), 255),
                city=self._clean_text(payload.get("city"), 128),
                postal_code=self._clean_text(payload.get("postal_code"), 32),
                is_primary=bool(payload.get("is_primary", existing_count == 0)),
                is_public=bool(payload.get("is_public", False)),
                sort_order=self._clean_sort_order(payload.get("sort_order"), default=0),
                metadata_json=(dict(payload.get("metadata") or {}) if isinstance(payload.get("metadata"), dict) else {}),
                created_by=str(actor or "unknown"),
                updated_by=str(actor or "unknown"),
                created_at=now,
                updated_at=now,
            )
            db.add(row)
        else:
            if "address_kind" in payload:
                row.address_kind = (self._clean_text(payload.get("address_kind"), 32) or row.address_kind or "REGISTERED").upper()
            if "label" in payload:
                row.label = self._clean_text(payload.get("label"), 128)
            if "country_code" in payload:
                row.country_code = self._clean_text(payload.get("country_code"), 8)
            if "line1" in payload:
                row.line1 = self._clean_text(payload.get("line1"), 255)
            if "line2" in payload:
                row.line2 = self._clean_text(payload.get("line2"), 255)
            if "city" in payload:
                row.city = self._clean_text(payload.get("city"), 128)
            if "postal_code" in payload:
                row.postal_code = self._clean_text(payload.get("postal_code"), 32)
            if "is_primary" in payload:
                row.is_primary = bool(payload.get("is_primary"))
            if "is_public" in payload:
                row.is_public = bool(payload.get("is_public"))
            if "sort_order" in payload:
                row.sort_order = self._clean_sort_order(payload.get("sort_order"), default=int(row.sort_order or 0))
            if "metadata" in payload and isinstance(payload.get("metadata"), dict):
                row.metadata_json = dict(payload.get("metadata") or {})
            row.updated_by = str(actor or "unknown")
            row.updated_at = now

        db.flush()

        if bool(row.is_primary):
            (
                db.query(WorkspaceAddress)
                .filter(
                    WorkspaceAddress.workspace_type == workspace_type,
                    WorkspaceAddress.workspace_id == workspace_id,
                    WorkspaceAddress.id != row.id,
                )
                .update({WorkspaceAddress.is_primary: False}, synchronize_session=False)
            )
            db.flush()

        self._sync_org_from_primary_address(db, org=org, actor=actor)
        return self._address_to_dict(row)

    def delete_address(self, db: Session, *, workspace_type: str, workspace_id: str, actor: str, address_id: str) -> dict[str, Any]:
        org = self._get_org_row(db, workspace_type=workspace_type, workspace_id=workspace_id, actor=actor)
        aid = self._parse_uuid(address_id, "address_id")
        row = (
            db.query(WorkspaceAddress)
            .filter(
                WorkspaceAddress.id == aid,
                WorkspaceAddress.workspace_type == workspace_type,
                WorkspaceAddress.workspace_id == workspace_id,
            )
            .first()
        )
        if row is None:
            raise ValueError("address_not_found")
        out = self._address_to_dict(row)
        db.delete(row)
        db.flush()
        self._sync_org_from_primary_address(db, org=org, actor=actor)
        return out
