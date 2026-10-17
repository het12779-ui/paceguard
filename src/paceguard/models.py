"""ORM models.

Multi-tenancy rule: every business table carries ``account_id`` and every query
in the repository layer filters on it. ``test_tenant_isolation.py`` asserts both
the isolation behaviour and that new tables do not forget the column.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from paceguard.db import Base


def utcnow() -> datetime:
    """Naive UTC.

    Convention for the whole service: timestamps are stored naive in UTC and
    converted at the edges. Mixing aware/naive values is the classic source of
    "why is this campaign a day off" bugs, and SQL Server's ``datetime2`` has no
    offset either.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: Plan only affects UI quotas in the demo; kept to show tenant metadata.
    plan: Mapped[str] = mapped_column(String(30), default="growth", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    campaigns: Mapped[list["Campaign"]] = relationship(back_populates="account")


class Campaign(Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        UniqueConstraint("account_id", "external_id", name="uq_campaign_account_external"),
        Index("ix_campaign_account_status", "account_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    channel: Mapped[str] = mapped_column(String(40), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    total_budget_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    pacing_mode: Mapped[str] = mapped_column(String(20), default="even", nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    account: Mapped[Account] = relationship(back_populates="campaigns")
    spend_events: Mapped[list["SpendEvent"]] = relationship(back_populates="campaign")


class SpendEvent(Base):
    """Append-only spend fact.

    ``event_uid`` is the idempotency key supplied by the ad platform sync job.
    At-least-once delivery is normal in ad tech, so ingest must be idempotent:
    the unique constraint is the enforcement, not application-level checking.
    """

    __tablename__ = "spend_events"
    __table_args__ = (
        UniqueConstraint("account_id", "event_uid", name="uq_spend_account_event_uid"),
        Index("ix_spend_campaign_occurred", "campaign_id", "occurred_at"),
        Index("ix_spend_account_occurred", "account_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    event_uid: Mapped[str] = mapped_column(String(80), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="platform_sync", nullable=False)

    campaign: Mapped[Campaign] = relationship(back_populates="spend_events")


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        # Dedupe key is date-bucketed: re-evaluating pacing 40 times a day must
        # produce one alert, not 40. This is the alert-fatigue guard.
        UniqueConstraint("account_id", "dedupe_key", name="uq_alert_account_dedupe"),
        Index("ix_alert_account_open", "account_id", "resolved_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[int | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(180), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    @property
    def is_open(self) -> bool:
        return self.resolved_at is None


class AuditLog(Base):
    """Who changed a budget, before and after. Ad spend is money; changes need receipts."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_account_created", "account_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor: Mapped[str] = mapped_column(String(80), nullable=False)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    entity: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    before_value: Mapped[str | None] = mapped_column(String(80), nullable=True)
    after_value: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


__all__ = [
    "Account",
    "Alert",
    "AuditLog",
    "Campaign",
    "SpendEvent",
    "utcnow",
]
