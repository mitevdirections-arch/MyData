from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class VerificationSubjectType(str, Enum):
    TENANT = "TENANT"
    PARTNER = "PARTNER"
    EXTERNAL = "EXTERNAL"


class ProviderStatus(str, Enum):
    VERIFIED = "VERIFIED"
    NOT_VERIFIED = "NOT_VERIFIED"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PARTIAL_MATCH = "PARTIAL_MATCH"


class SummaryStatus(str, Enum):
    GOOD = "GOOD"
    WARNING = "WARNING"
    PENDING = "PENDING"
    UNKNOWN = "UNKNOWN"


class ViesApplicabilityStatus(str, Enum):
    VIES_ELIGIBLE = "VIES_ELIGIBLE"
    VIES_NOT_APPLICABLE = "VIES_NOT_APPLICABLE"
    VIES_FORMAT_SUSPECT = "VIES_FORMAT_SUSPECT"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class VerificationTargetUpsertInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    subject_type: VerificationSubjectType
    subject_id: str
    owner_company_id: str | None = None
    global_company_id: str | None = None
    legal_name: str
    country_code: str
    vat_number: str | None = None
    registration_number: str | None = None
    address_line: str | None = None
    postal_code: str | None = None
    city: str | None = None
    website_url: str | None = None


class VerificationTargetDTO(BaseModel):
    id: str
    subject_type: VerificationSubjectType
    subject_id: str
    owner_company_id: str | None = None
    global_company_id: str | None = None
    legal_name: str
    normalized_legal_name: str
    country_code: str
    vat_number: str | None = None
    vat_number_normalized: str | None = None
    registration_number: str | None = None
    registration_number_normalized: str | None = None
    address_line: str | None = None
    postal_code: str | None = None
    city: str | None = None
    website_url: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ProviderCheckResultDTO(BaseModel):
    provider_code: str
    check_type: str
    status: ProviderStatus
    checked_at: datetime
    expires_at: datetime | None = None
    match_score: float | None = None
    provider_reference: str | None = None
    provider_message_code: str | None = None
    provider_message_text: str | None = None
    evidence_json: dict[str, Any] = Field(default_factory=dict)


class VerificationCheckDTO(BaseModel):
    id: str
    target_id: str
    provider_code: str
    check_type: str
    status: ProviderStatus
    checked_at: str
    expires_at: str | None = None
    match_score: float | None = None
    provider_reference: str | None = None
    provider_message_code: str | None = None
    provider_message_text: str | None = None
    evidence_json: dict[str, Any]
    created_by_user_id: str | None = None


class VerificationSummaryDTO(BaseModel):
    target_id: str
    overall_status: SummaryStatus
    last_checked_at: str | None = None
    last_verified_at: str | None = None
    next_recommended_check_at: str | None = None
    verified_provider_count: int
    warning_provider_count: int
    unavailable_provider_count: int
    overall_confidence: float | None = None
    badges_json: dict[str, Any] = Field(default_factory=dict)
    updated_at: str | None = None


class InflightAcquireResultDTO(BaseModel):
    acquired: bool
    dedup_hit: bool
    cooldown_active: bool = False
    reason: str
    target_id: str
    provider_code: str
    lease_expires_at: str | None = None


class VerificationProviderRunDTO(BaseModel):
    acquired: bool
    dedup_hit: bool
    provider_called: bool
    reason: str
    applicability_status: ViesApplicabilityStatus
    check: VerificationCheckDTO | None = None
    summary: VerificationSummaryDTO | None = None


class VerificationTargetUpsertResponseDTO(BaseModel):
    ok: bool = True
    target: VerificationTargetDTO


class VerificationTargetDetailResponseDTO(BaseModel):
    ok: bool = True
    target: VerificationTargetDTO


class VerificationSummaryResponseDTO(BaseModel):
    ok: bool = True
    target_id: str
    summary: VerificationSummaryDTO


class VerificationCheckListItemDTO(BaseModel):
    id: str
    target_id: str
    provider_code: str
    check_type: str
    status: ProviderStatus
    checked_at: str
    expires_at: str | None = None
    match_score: float | None = None
    provider_reference: str | None = None
    provider_message_code: str | None = None
    provider_message_text: str | None = None
    applicability_status: ViesApplicabilityStatus | None = None
    evidence_json: dict[str, Any] | None = None


class VerificationChecksResponseDTO(BaseModel):
    ok: bool = True
    target_id: str
    items: list[VerificationCheckListItemDTO] = Field(default_factory=list)


class VerificationRecheckRequestDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider_code: str = "VIES"
    request_id: str | None = None


class VerificationProviderCheckResponseDTO(BaseModel):
    ok: bool = True
    result: VerificationProviderRunDTO


class PartnerVerificationSummaryDTO(BaseModel):
    partner_id: str
    target_id: str
    overall_status: SummaryStatus
    last_checked_at: str | None = None
    last_verified_at: str | None = None
    next_recommended_check_at: str | None = None
    provider_status: ProviderStatus | None = None
    applicability_status: ViesApplicabilityStatus | None = None
    provider_code: str = "VIES"
    non_blocking: bool = True


class PartnerVerificationSummaryResponseDTO(BaseModel):
    ok: bool = True
    result: PartnerVerificationSummaryDTO


class PartnerVerificationRecheckResponseDTO(BaseModel):
    ok: bool = True
    result: PartnerVerificationSummaryDTO
    acquired: bool
    dedup_hit: bool
    provider_called: bool
    reason: str


class CompanyVerificationSummaryDTO(BaseModel):
    target_id: str
    overall_status: SummaryStatus
    last_checked_at: str | None = None
    last_verified_at: str | None = None
    next_recommended_check_at: str | None = None
    provider_status: ProviderStatus | None = None
    applicability_status: ViesApplicabilityStatus | None = None
    provider_code: str = "VIES"
    non_blocking: bool = True


class CompanyVerificationSummaryResponseDTO(BaseModel):
    ok: bool = True
    result: CompanyVerificationSummaryDTO


class CompanyVerificationRecheckResponseDTO(BaseModel):
    ok: bool = True
    result: CompanyVerificationSummaryDTO
    acquired: bool
    dedup_hit: bool
    provider_called: bool
    reason: str
