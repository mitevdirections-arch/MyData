from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class PublicProfileSettings(Base):
    __tablename__ = "public_profile_settings"

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    show_company_info: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_fleet: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    show_contacts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_price_list: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    show_working_hours: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class OnboardingApplication(Base):
    __tablename__ = "onboarding_applications"
    __table_args__ = (
        Index("ix_onboarding_status_created", "status", "created_at"),
        Index("ix_onboarding_country", "country_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="SUBMITTED")

    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False)
    seat_count: Mapped[int] = mapped_column(nullable=False)
    core_plan_code: Mapped[str] = mapped_column(String(32), nullable=False)

    default_locale: Mapped[str] = mapped_column(String(32), nullable=False)
    default_time_zone: Mapped[str] = mapped_column(String(64), nullable=False)
    date_style: Mapped[str] = mapped_column(String(8), nullable=False)
    time_style: Mapped[str] = mapped_column(String(8), nullable=False)
    unit_system: Mapped[str] = mapped_column(String(16), nullable=False)

    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class I18nWorkspacePolicy(Base):
    __tablename__ = "i18n_workspace_policies"
    __table_args__ = (
        Index("ix_i18n_workspace_scope", "workspace_type", "workspace_id"),
    )

    workspace_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)

    default_locale: Mapped[str] = mapped_column(String(32), nullable=False, default="en")
    fallback_locale: Mapped[str] = mapped_column(String(32), nullable=False, default="en")
    enabled_locales_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class PublicWorkspaceSettings(Base):
    __tablename__ = "public_workspace_settings"

    workspace_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)

    show_company_info: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_fleet: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    show_contacts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_price_list: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    show_working_hours: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class PublicBrandAsset(Base):
    __tablename__ = "public_brand_assets"
    __table_args__ = (
        Index("ix_public_brand_asset_scope_kind_status", "workspace_type", "workspace_id", "asset_kind", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    workspace_type: Mapped[str] = mapped_column(String(16), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False)

    asset_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="LOGO")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING_UPLOAD")

    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(128), nullable=True)

    storage_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="minio")
    bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)

    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class PublicPageDraft(Base):
    __tablename__ = "public_page_drafts"
    __table_args__ = (
        UniqueConstraint("workspace_type", "workspace_id", "locale", "page_code", name="uq_public_page_draft_scope"),
        Index("ix_public_page_draft_scope", "workspace_type", "workspace_id", "locale", "page_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    workspace_type: Mapped[str] = mapped_column(String(16), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False)

    locale: Mapped[str] = mapped_column(String(32), nullable=False, default="en")
    page_code: Mapped[str] = mapped_column(String(32), nullable=False, default="HOME")

    content_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class PublicPagePublished(Base):
    __tablename__ = "public_page_published"
    __table_args__ = (
        Index("ix_public_page_published_scope", "workspace_type", "workspace_id", "locale", "page_code", "version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    workspace_type: Mapped[str] = mapped_column(String(16), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False)

    locale: Mapped[str] = mapped_column(String(32), nullable=False, default="en")
    page_code: Mapped[str] = mapped_column(String(32), nullable=False, default="HOME")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    content_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    publish_note: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    published_by: Mapped[str] = mapped_column(String(255), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


__all__ = [
    "I18nWorkspacePolicy",
    "OnboardingApplication",
    "PublicBrandAsset",
    "PublicPageDraft",
    "PublicPagePublished",
    "PublicProfileSettings",
    "PublicWorkspaceSettings",
]
