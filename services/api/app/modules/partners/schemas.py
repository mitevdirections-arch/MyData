from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class PartnerRoleCode(str, Enum):
    CARRIER = "CARRIER"
    FORWARDER = "FORWARDER"
    WAREHOUSE = "WAREHOUSE"
    CUSTOMER = "CUSTOMER"
    SUPPLIER = "SUPPLIER"
    CUSTOMS = "CUSTOMS"
    INSURER = "INSURER"
    OTHER = "OTHER"


class PartnerAddressDTO(BaseModel):
    id: str | None = None
    address_type: str = "HQ"
    label: str | None = None
    country_code: str | None = None
    line1: str | None = None
    line2: str | None = None
    city: str | None = None
    postal_code: str | None = None
    is_primary: bool = False
    sort_order: int = 0
    created_at: str | None = None
    updated_at: str | None = None
    archived_at: str | None = None


class PartnerBankAccountDTO(BaseModel):
    id: str | None = None
    account_holder: str | None = None
    iban: str | None = None
    swift: str | None = None
    bank_name: str | None = None
    bank_country_code: str | None = None
    currency: str | None = None
    is_primary: bool = False
    note: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    archived_at: str | None = None


class PartnerContactDTO(BaseModel):
    id: str | None = None
    contact_name: str
    contact_role: str | None = None
    email: str | None = None
    phone: str | None = None
    is_primary: bool = False
    sort_order: int = 0
    note: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    archived_at: str | None = None


class PartnerDocumentDTO(BaseModel):
    id: str | None = None
    doc_type: str
    file_name: str
    content_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    storage_key: str
    uploaded_by_user_id: str | None = None
    note: str | None = None
    created_at: str | None = None
    archived_at: str | None = None


class TenantPartnerRatingSummaryDTO(BaseModel):
    partner_id: str
    rating_count: int
    avg_execution_quality: float | None = None
    avg_communication_docs: float | None = None
    avg_payment_discipline: float | None = None
    avg_overall_score: float | None = None
    last_rating_at: str | None = None
    payment_issue_count: int
    updated_at: str | None = None


class GlobalCompanySignalDTO(BaseModel):
    global_company_id: str
    canonical_name: str
    legal_name: str | None = None
    country_code: str
    vat_number: str | None = None
    registration_number: str | None = None
    status: str
    total_tenants: int
    total_completed_orders_rated: int
    avg_execution_quality: float | None = None
    avg_communication_docs: float | None = None
    avg_payment_discipline: float | None = None
    global_overall_score: float | None = None
    risk_payment_count: int
    risk_quality_count: int
    blacklist_signal_count: int
    updated_at: str | None = None


class PartnerSummaryDTO(BaseModel):
    id: str
    company_id: str
    global_company_id: str | None = None
    partner_code: str
    display_name: str
    legal_name: str | None = None
    country_code: str
    vat_number: str | None = None
    registration_number: str | None = None
    website_url: str | None = None
    main_email: str | None = None
    main_phone: str | None = None
    status: str
    is_blacklisted: bool
    is_watchlisted: bool
    blacklist_reason: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    archived_at: str | None = None


class PartnerDetailDTO(PartnerSummaryDTO):
    internal_note: str | None = None
    roles: list[PartnerRoleCode] = Field(default_factory=list)
    addresses: list[PartnerAddressDTO] = Field(default_factory=list)
    bank_accounts: list[PartnerBankAccountDTO] = Field(default_factory=list)
    contacts: list[PartnerContactDTO] = Field(default_factory=list)
    documents: list[PartnerDocumentDTO] = Field(default_factory=list)
    rating_summary: TenantPartnerRatingSummaryDTO | None = None


class PartnerCreateRequestDTO(BaseModel):
    partner_code: str | None = None
    display_name: str
    legal_name: str | None = None
    country_code: str
    vat_number: str | None = None
    registration_number: str | None = None
    website_url: str | None = None
    main_email: str | None = None
    main_phone: str | None = None
    status: str | None = None
    is_blacklisted: bool = False
    is_watchlisted: bool = False
    blacklist_reason: str | None = None
    internal_note: str | None = None
    roles: list[PartnerRoleCode] = Field(default_factory=list)
    addresses: list[PartnerAddressDTO] = Field(default_factory=list)
    bank_accounts: list[PartnerBankAccountDTO] = Field(default_factory=list)
    contacts: list[PartnerContactDTO] = Field(default_factory=list)
    documents: list[PartnerDocumentDTO] = Field(default_factory=list)


class PartnerUpdateRequestDTO(BaseModel):
    display_name: str | None = None
    legal_name: str | None = None
    country_code: str | None = None
    vat_number: str | None = None
    registration_number: str | None = None
    website_url: str | None = None
    main_email: str | None = None
    main_phone: str | None = None
    status: str | None = None
    internal_note: str | None = None
    addresses: list[PartnerAddressDTO] | None = None
    bank_accounts: list[PartnerBankAccountDTO] | None = None
    contacts: list[PartnerContactDTO] | None = None
    documents: list[PartnerDocumentDTO] | None = None


class PartnerRoleSetRequestDTO(BaseModel):
    roles: list[PartnerRoleCode] = Field(default_factory=list)


class PartnerBlacklistRequestDTO(BaseModel):
    is_blacklisted: bool
    blacklist_reason: str | None = None


class PartnerWatchlistRequestDTO(BaseModel):
    is_watchlisted: bool


class PartnerRatingCreateRequestDTO(BaseModel):
    order_id: str | None = None
    execution_quality_stars: int = Field(ge=1, le=6)
    communication_docs_stars: int = Field(ge=1, le=6)
    payment_discipline_stars: int | None = Field(default=None, ge=1, le=6)
    payment_expected: bool = False
    short_comment: str | None = None
    issue_flags_json: dict[str, object] | None = None


class PartnersListResponseDTO(BaseModel):
    ok: bool
    tenant_id: str
    items: list[PartnerSummaryDTO] = Field(default_factory=list)


class PartnerDetailResponseDTO(BaseModel):
    ok: bool
    tenant_id: str
    partner: PartnerDetailDTO


class PartnerRatingCreateResponseDTO(BaseModel):
    ok: bool
    tenant_id: str
    partner_id: str
    rating_id: str
    tenant_summary: TenantPartnerRatingSummaryDTO
    global_signal: GlobalCompanySignalDTO | None = None


class PartnerRatingSummaryResponseDTO(BaseModel):
    ok: bool
    tenant_id: str
    partner_id: str
    summary: TenantPartnerRatingSummaryDTO | None = None


class PartnerGlobalSignalResponseDTO(BaseModel):
    ok: bool
    tenant_id: str
    partner_id: str
    global_signal: GlobalCompanySignalDTO | None = None
