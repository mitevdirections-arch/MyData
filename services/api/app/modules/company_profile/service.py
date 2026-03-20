from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.modules.entity_verification.schemas import (
    VerificationSubjectType,
    VerificationTargetDTO,
    VerificationTargetUpsertInput,
)
from app.modules.entity_verification.service import service as verification_service
from app.modules.profile.service import service as profile_service
from app.modules.profile.service_constants import WORKSPACE_TENANT


class CompanyProfileService:
    def _clean(self, value: object, size: int) -> str:
        return str(value or "").strip()[:size]

    def _clean_opt(self, value: object, size: int) -> str | None:
        out = self._clean(value, size)
        return out if out else None

    def _country_from_vat(self, vat_number: str | None) -> str | None:
        raw = self._clean(vat_number, 64).upper()
        if len(raw) >= 2 and raw[0:2].isalpha():
            return raw[0:2]
        return None

    def resolve_tenant_company_verification_target(
        self,
        db: Session,
        *,
        workspace_type: str,
        workspace_id: str,
        actor: str,
    ) -> VerificationTargetDTO:
        if workspace_type != WORKSPACE_TENANT:
            raise ValueError("tenant_workspace_required")

        org = profile_service.get_or_create_organization_profile(
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            actor=actor,
        )
        legal = dict(org.get("legal") or {})
        address = dict(org.get("address") or {})

        legal_name = self._clean_opt(legal.get("legal_name"), 255) or workspace_id
        vat_number = self._clean_opt(legal.get("vat_number"), 64)
        country_code = self._clean_opt(address.get("country_code"), 8) or self._country_from_vat(vat_number) or "ZZ"

        payload = VerificationTargetUpsertInput(
            subject_type=VerificationSubjectType.TENANT,
            subject_id=workspace_id,
            owner_company_id=workspace_id,
            global_company_id=None,
            legal_name=legal_name,
            country_code=country_code,
            vat_number=vat_number,
            registration_number=self._clean_opt(legal.get("registration_number"), 64),
            address_line=self._clean_opt(address.get("line1"), 255),
            postal_code=self._clean_opt(address.get("postal_code"), 32),
            city=self._clean_opt(address.get("city"), 128),
            website_url=self._clean_opt((org.get("contacts") or {}).get("website_url"), 1024),
        )
        return verification_service.upsert_verification_target(db, payload=payload)


service = CompanyProfileService()

