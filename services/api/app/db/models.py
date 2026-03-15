from __future__ import annotations

"""
Compatibility ORM entrypoint for runtime + Alembic metadata loading.

Split Prep Contract (v1):
- `app.db.models` remains the single stable import path for ORM models.
- Models can be split domain-by-domain into app.db.model_parts while app.db.models remains the stable compat bridge.
- `app.db.model_parts` contains only split scaffolding/placeholders.
- Future domain-by-domain moves must preserve this compat bridge.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.model_parts.loader import MODEL_SPLIT_PREP_VERSION
from app.db.model_parts.ai import EidonAIQualityEvent, EidonPatternPublishArtifact, EidonTemplateSubmissionStaging
from app.db.model_parts.marketplace import MarketplaceModule, MarketplaceOffer
from app.db.model_parts.payments import PaymentInvoice, PaymentInvoiceSequence, TenantCreditAccount
from app.db.model_parts.support_onboarding_public import (
    I18nWorkspacePolicy,
    OnboardingApplication,
    PublicBrandAsset,
    PublicPageDraft,
    PublicPagePublished,
    PublicProfileSettings,
    PublicWorkspaceSettings,
)

MODELS_SPLIT_PREP_LAYER = MODEL_SPLIT_PREP_VERSION



def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    vat_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class License(Base):
    __tablename__ = "licenses"
    __table_args__ = (
        Index("ix_licenses_tenant_status", "tenant_id", "status"),
        Index("ix_licenses_tenant_type", "tenant_id", "license_type"),
        Index("ix_licenses_tenant_type_status_validto_cover", "tenant_id", "license_type", "status", "valid_to"),
        Index("ix_licenses_tenant_module_status_validto_cover", "tenant_id", "module_code", "status", "valid_to"),
        Index("ix_licenses_visual_code", "license_visual_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    license_type: Mapped[str] = mapped_column(String(64), nullable=False)
    module_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    license_visual_code: Mapped[str | None] = mapped_column(String(96), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class LicenseIssuancePolicy(Base):
    __tablename__ = "license_issuance_policies"

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="SEMI")
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class LicenseIssueRequest(Base):
    __tablename__ = "license_issue_requests"
    __table_args__ = (
        Index("ix_license_issue_req_tenant_status", "tenant_id", "status", "requested_at"),
        Index("ix_license_issue_req_status_requested", "status", "requested_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    request_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")

    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)

    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)




class PaymentAllocation(Base):
    __tablename__ = "payment_allocations"
    __table_args__ = (
        Index("ix_payment_alloc_invoice_paid", "invoice_id", "paid_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payment_invoices.id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False, default="MANUAL")
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    paid_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "order_no", name="uq_orders_tenant_order_no"),
        Index("ix_orders_tenant_created", "tenant_id", "created_at"),
        Index("ix_orders_tenant_status_created", "tenant_id", "status", "created_at"),
        Index("ix_orders_tenant_mode_created", "tenant_id", "transport_mode", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    order_no: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    transport_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="ROAD")
    direction: Mapped[str] = mapped_column(String(16), nullable=False, default="OUTBOUND")

    customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pickup_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delivery_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cargo_description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    reference_no: Mapped[str | None] = mapped_column(String(128), nullable=True)

    scheduled_pickup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)

class SecurityAlertQueue(Base):
    __tablename__ = "security_alert_queue"
    __table_args__ = (
        Index("ix_security_alert_queue_status_next", "status", "next_attempt_at"),
        Index("ix_security_alert_queue_incident", "incident_id", "status"),
        Index("ix_security_alert_queue_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="LOG")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")

    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=8)

    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    last_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class GuardHeartbeat(Base):
    __tablename__ = "guard_heartbeats"
    __table_args__ = (
        UniqueConstraint("tenant_id", "device_id", name="uq_guard_heartbeat_tenant_device"),
        Index("ix_guard_heartbeat_tenant", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    device_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OK")
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GuardBehaviorState(Base):
    __tablename__ = "guard_behavior_states"
    __table_args__ = (
        Index("ix_guard_behavior_due", "session_open", "next_heartbeat_due_at"),
    )

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    good_since: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    suspicion_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_suspicion_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    current_multiplier: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    recommended_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=1800)
    next_heartbeat_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session_open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_event: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_device_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_flags_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class GuardBotCheck(Base):
    __tablename__ = "guard_bot_checks"
    __table_args__ = (
        Index("ix_guard_bot_checks_tenant_checked", "tenant_id", "checked_at"),
        Index("ix_guard_bot_checks_run_checked", "run_id", "checked_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    bot_id: Mapped[str] = mapped_column(String(128), nullable=False, default="guard-bot")
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="SCHEDULED")
    state: Mapped[str] = mapped_column(String(16), nullable=False)

    missing_heartbeat: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stale_heartbeat: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bad_status: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stale_enforced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    summary_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    notes: Mapped[str | None] = mapped_column(String(512), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class GuardBotCredential(Base):
    __tablename__ = "guard_bot_credentials"
    __table_args__ = (
        UniqueConstraint("tenant_id", "bot_id", name="uq_guard_bot_credential_tenant_bot"),
        Index("ix_guard_bot_credential_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    bot_id: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")

    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_fail_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_warning_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GuardBotNonce(Base):
    __tablename__ = "guard_bot_nonces"
    __table_args__ = (
        UniqueConstraint("bot_id", "nonce", name="uq_guard_bot_nonce_bot_nonce"),
        Index("ix_guard_bot_nonce_expires", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    bot_id: Mapped[str] = mapped_column(String(128), nullable=False)
    nonce: Mapped[str] = mapped_column(String(128), nullable=False)
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DeviceLease(Base):
    __tablename__ = "device_leases"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_device_lease_tenant_user"),
        Index("ix_device_lease_tenant_user", "tenant_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    device_id: Mapped[str] = mapped_column(String(128), nullable=False)
    device_class: Mapped[str] = mapped_column(String(32), nullable=False, default="desktop")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    leased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class StorageObjectMeta(Base):
    __tablename__ = "storage_object_meta"
    __table_args__ = (
        Index("ix_storage_object_tenant_status", "tenant_id", "status"),
        Index("ix_storage_object_retention", "retention_until"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    purpose: Mapped[str] = mapped_column(String(64), nullable=False, default="verification_doc")

    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(128), nullable=True)

    storage_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="minio")
    bucket: Mapped[str] = mapped_column(String(128), nullable=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING_UPLOAD")
    retention_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incidents_tenant_status_created", "tenant_id", "status", "created_at"),
        Index("ix_incidents_status_severity_created", "status", "severity", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN")
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="MEDIUM")
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="OTHER")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="TENANT")

    title: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str] = mapped_column(String(5000), nullable=False)
    resolution_note: Mapped[str | None] = mapped_column(String(4000), nullable=True)

    evidence_object_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    acknowledged_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)



class SupportRequest(Base):
    __tablename__ = "support_requests"
    __table_args__ = (
        Index("ix_support_requests_tenant_status_created", "tenant_id", "status", "requested_at"),
        Index("ix_support_requests_status_door", "status", "door_expires_at", "requested_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="NEW")
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="LIVE_ACCESS")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="MEDIUM")

    title: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str] = mapped_column(String(5000), nullable=False)

    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)

    door_opened_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    door_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    door_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session_started_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    session_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    closed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class SupportSession(Base):
    __tablename__ = "support_sessions"
    __table_args__ = (
        Index("ix_support_sessions_tenant_status_exp", "tenant_id", "status", "expires_at"),
        Index("ix_support_sessions_request_started", "request_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("support_requests.id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")

    started_by: Mapped[str] = mapped_column(String(255), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    ended_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    capabilities_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class SupportMessage(Base):
    __tablename__ = "support_messages"
    __table_args__ = (
        Index("ix_support_messages_request_created", "request_id", "created_at"),
        Index("ix_support_messages_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("support_requests.id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("support_sessions.id", ondelete="SET NULL"), nullable=True)

    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="CHAT_HUMAN")
    sender_type: Mapped[str] = mapped_column(String(32), nullable=False)
    sender_id: Mapped[str] = mapped_column(String(255), nullable=False)

    body: Mapped[str] = mapped_column(String(8000), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class SupportFaqEntry(Base):
    __tablename__ = "support_faq_entries"
    __table_args__ = (
        Index("ix_support_faq_locale_status_sort", "locale", "status", "sort_order"),
        Index("ix_support_faq_status_updated", "status", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))

    locale: Mapped[str] = mapped_column(String(32), nullable=False, default="en")
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="GENERAL")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PUBLISHED")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    question: Mapped[str] = mapped_column(String(512), nullable=False)
    answer: Mapped[str] = mapped_column(String(8000), nullable=False)
    tags_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)

class StorageGrant(Base):
    __tablename__ = "storage_grants"
    __table_args__ = (
        Index("ix_storage_grants_tenant_status_exp", "tenant_id", "status", "expires_at"),
        Index("ix_storage_grants_status_exp", "status", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ISSUED")

    object_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StorageDeleteQueue(Base):
    __tablename__ = "storage_delete_queue"
    __table_args__ = (
        Index("ix_storage_delete_queue_status_next", "status", "next_attempt_at"),
        Index("ix_storage_delete_queue_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    object_meta_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)

    reason: Mapped[str] = mapped_column(String(64), nullable=False, default="retention")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(nullable=False, default=8)

    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    last_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdminProfile(Base):
    __tablename__ = "admin_profiles"
    __table_args__ = (
        UniqueConstraint("workspace_type", "workspace_id", "user_id", name="uq_admin_profile_workspace_user"),
        Index("ix_admin_profile_workspace", "workspace_type", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    workspace_type: Mapped[str] = mapped_column(String(16), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False)

    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(128), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    preferred_locale: Mapped[str] = mapped_column(String(32), nullable=False, default="en")
    preferred_time_zone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    date_style: Mapped[str] = mapped_column(String(8), nullable=False, default="YMD")
    time_style: Mapped[str] = mapped_column(String(8), nullable=False, default="H24")
    unit_system: Mapped[str] = mapped_column(String(16), nullable=False, default="metric")

    notification_prefs_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class WorkspaceOrganizationProfile(Base):
    __tablename__ = "workspace_organization_profiles"
    __table_args__ = (
        UniqueConstraint("workspace_type", "workspace_id", name="uq_workspace_org_profile_scope"),
        Index("ix_workspace_org_profile_scope", "workspace_type", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    workspace_type: Mapped[str] = mapped_column(String(16), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False)

    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vat_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    registration_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    company_size_hint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(128), nullable=True)
    activity_summary: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    presentation_text: Mapped[str | None] = mapped_column(String(5000), nullable=True)

    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    address_country_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    address_postal_code: Mapped[str | None] = mapped_column(String(32), nullable=True)

    bank_account_holder: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bank_iban: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bank_swift: Mapped[str | None] = mapped_column(String(32), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bank_currency: Mapped[str | None] = mapped_column(String(16), nullable=True)

    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class WorkspaceContactPoint(Base):
    __tablename__ = "workspace_contact_points"
    __table_args__ = (
        Index("ix_workspace_contact_scope", "workspace_type", "workspace_id"),
        Index("ix_workspace_contact_scope_public", "workspace_type", "workspace_id", "is_public"),
        Index("ix_workspace_contact_scope_primary", "workspace_type", "workspace_id", "is_primary"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    workspace_type: Mapped[str] = mapped_column(String(16), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False)

    contact_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="GENERAL")
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class WorkspaceAddress(Base):
    __tablename__ = "workspace_addresses"
    __table_args__ = (
        Index("ix_workspace_address_scope", "workspace_type", "workspace_id"),
        Index("ix_workspace_address_scope_public", "workspace_type", "workspace_id", "is_public"),
        Index("ix_workspace_address_scope_primary", "workspace_type", "workspace_id", "is_primary"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    workspace_type: Mapped[str] = mapped_column(String(16), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False)

    address_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="REGISTERED")
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(32), nullable=True)

    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class WorkspaceUserProfile(Base):
    __tablename__ = "workspace_user_profiles"
    __table_args__ = (
        UniqueConstraint("workspace_type", "workspace_id", "user_id", name="uq_workspace_user_profile_scope_user"),
        Index("ix_workspace_user_profile_scope", "workspace_type", "workspace_id"),
        Index("ix_workspace_user_profile_scope_user", "workspace_type", "workspace_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    workspace_type: Mapped[str] = mapped_column(String(16), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)

    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    date_of_birth: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)

    address_country_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    address_postal_code: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Payroll details (personal, not company profile)
    bank_account_holder: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bank_iban: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bank_swift: Mapped[str | None] = mapped_column(String(32), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bank_currency: Mapped[str | None] = mapped_column(String(16), nullable=True)

    employee_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(128), nullable=True)
    department: Mapped[str | None] = mapped_column(String(128), nullable=True)
    employment_status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")

    preferred_locale: Mapped[str | None] = mapped_column(String(32), nullable=True)
    preferred_time_zone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    date_style: Mapped[str | None] = mapped_column(String(8), nullable=True)
    time_style: Mapped[str | None] = mapped_column(String(8), nullable=True)
    unit_system: Mapped[str | None] = mapped_column(String(16), nullable=True)

    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class WorkspaceUserContactChannel(Base):
    __tablename__ = "workspace_user_contact_channels"
    __table_args__ = (
        Index("ix_workspace_user_contact_scope", "workspace_type", "workspace_id", "user_id"),
        Index("ix_workspace_user_contact_scope_public", "workspace_type", "workspace_id", "user_id", "is_public"),
        Index("ix_workspace_user_contact_scope_primary", "workspace_type", "workspace_id", "user_id", "is_primary"),
        Index("ix_workspace_user_contact_scope_type", "workspace_type", "workspace_id", "user_id", "channel_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    workspace_type: Mapped[str] = mapped_column(String(16), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)

    channel_type: Mapped[str] = mapped_column(String(32), nullable=False, default="EMAIL")
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)

    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class WorkspaceUserAddress(Base):
    __tablename__ = "workspace_user_addresses"
    __table_args__ = (
        Index("ix_workspace_user_address_scope", "workspace_type", "workspace_id", "user_id"),
        Index("ix_workspace_user_address_scope_public", "workspace_type", "workspace_id", "user_id", "is_public"),
        Index("ix_workspace_user_address_scope_primary", "workspace_type", "workspace_id", "user_id", "is_primary"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    workspace_type: Mapped[str] = mapped_column(String(16), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)

    address_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="HOME")
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(32), nullable=True)

    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class WorkspaceUserDocument(Base):
    __tablename__ = "workspace_user_documents"
    __table_args__ = (
        Index("ix_workspace_user_doc_scope", "workspace_type", "workspace_id", "user_id"),
        Index("ix_workspace_user_doc_scope_kind", "workspace_type", "workspace_id", "user_id", "doc_kind"),
        Index("ix_workspace_user_doc_scope_valid_until", "workspace_type", "workspace_id", "user_id", "valid_until"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    workspace_type: Mapped[str] = mapped_column(String(16), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)

    doc_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    doc_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    issuer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    issued_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")

    storage_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    bucket: Mapped[str | None] = mapped_column(String(128), nullable=True)
    object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(128), nullable=True)

    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class WorkspaceUserNextOfKin(Base):
    __tablename__ = "workspace_user_next_of_kin"
    __table_args__ = (
        Index("ix_workspace_user_nok_scope", "workspace_type", "workspace_id", "user_id"),
        Index("ix_workspace_user_nok_scope_primary", "workspace_type", "workspace_id", "user_id", "is_primary"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    workspace_type: Mapped[str] = mapped_column(String(16), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)

    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    relation: Mapped[str] = mapped_column(String(64), nullable=False)

    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)

    address_country_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    address_postal_code: Mapped[str | None] = mapped_column(String(32), nullable=True)

    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class WorkspaceUserCredential(Base):
    __tablename__ = "workspace_user_credentials"
    __table_args__ = (
        UniqueConstraint("workspace_type", "workspace_id", "user_id", name="uq_workspace_user_cred_scope_user"),
        UniqueConstraint("workspace_type", "workspace_id", "username", name="uq_workspace_user_cred_scope_username"),
        Index("ix_workspace_user_cred_scope", "workspace_type", "workspace_id"),
        Index("ix_workspace_user_cred_scope_status", "workspace_type", "workspace_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    workspace_type: Mapped[str] = mapped_column(String(16), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)

    username: Mapped[str] = mapped_column(String(128), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    password_salt: Mapped[str] = mapped_column(String(256), nullable=False)
    hash_alg: Mapped[str] = mapped_column(String(32), nullable=False, default="PBKDF2_SHA256")
    hash_iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=210000)

    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    password_set_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    password_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class WorkspaceRole(Base):
    __tablename__ = "workspace_roles"
    __table_args__ = (
        UniqueConstraint("workspace_type", "workspace_id", "role_code", name="uq_workspace_role_scope_code"),
        Index("ix_workspace_role_scope", "workspace_type", "workspace_id"),
        Index("ix_workspace_role_scope_code_cover", "workspace_type", "workspace_id", "role_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    workspace_type: Mapped[str] = mapped_column(String(16), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False)

    role_code: Mapped[str] = mapped_column(String(64), nullable=False)
    role_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    permissions_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class WorkspaceUser(Base):
    __tablename__ = "workspace_users"
    __table_args__ = (
        UniqueConstraint("workspace_type", "workspace_id", "user_id", name="uq_workspace_user_scope_user"),
        Index("ix_workspace_user_scope", "workspace_type", "workspace_id"),
        Index("ix_workspace_user_scope_user_cover", "workspace_type", "workspace_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    workspace_type: Mapped[str] = mapped_column(String(16), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False)

    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(128), nullable=True)
    department: Mapped[str | None] = mapped_column(String(128), nullable=True)
    employment_status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    direct_permissions_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    meta_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class WorkspaceUserRole(Base):
    __tablename__ = "workspace_user_roles"
    __table_args__ = (
        UniqueConstraint("workspace_type", "workspace_id", "user_id", "role_code", name="uq_workspace_user_role_scope"),
        Index("ix_workspace_user_role_scope_user", "workspace_type", "workspace_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    workspace_type: Mapped[str] = mapped_column(String(16), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False)

    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    role_code: Mapped[str] = mapped_column(String(64), nullable=False)

    assigned_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)



class WorkspaceUserEffectivePermission(Base):
    __tablename__ = "workspace_user_effective_permissions"
    __table_args__ = (
        Index("ix_workspace_user_eff_scope", "workspace_type", "workspace_id"),
        Index("ix_workspace_user_eff_scope_updated", "workspace_type", "workspace_id", "updated_at"),
    )

    workspace_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)

    employment_status: Mapped[str] = mapped_column(String(32), nullable=False, default="INACTIVE")
    effective_permissions_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    source_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_hash_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)




