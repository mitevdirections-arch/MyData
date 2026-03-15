from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class MarketplaceModule(Base):
    __tablename__ = "marketplace_modules"
    __table_args__ = (
        Index("ix_marketplace_modules_active_class", "is_active", "module_class"),
    )

    module_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    module_class: Mapped[str] = mapped_column(String(64), nullable=False, default="GENERAL")
    description: Mapped[str | None] = mapped_column(String(4000), nullable=True)

    default_license_type: Mapped[str] = mapped_column(String(32), nullable=False, default="MODULE_PAID")
    base_price_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="EUR")
    billing_period: Mapped[str] = mapped_column(String(16), nullable=False, default="MONTH")

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class MarketplaceOffer(Base):
    __tablename__ = "marketplace_offers"
    __table_args__ = (
        UniqueConstraint("code", name="uq_marketplace_offer_code"),
        Index("ix_marketplace_offers_status_window", "status", "starts_at", "ends_at"),
        Index("ix_marketplace_offers_module_status", "module_code", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str | None] = mapped_column(String(5000), nullable=True)

    module_code: Mapped[str | None] = mapped_column(ForeignKey("marketplace_modules.module_code", ondelete="SET NULL"), nullable=True)
    offer_type: Mapped[str] = mapped_column(String(32), nullable=False, default="DISCOUNT")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")

    discount_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trial_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_override_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)

    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_apply: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


__all__ = [
    "MarketplaceModule",
    "MarketplaceOffer",
]
