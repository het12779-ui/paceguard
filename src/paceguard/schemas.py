"""Request/response contracts.

Money crosses the API boundary as integer cents; formatting is a presentation
concern. ``extra="forbid"`` on request models means a typo like ``budget_cents``
fails loudly instead of silently becoming a default.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PacingModeLiteral = Literal["even", "front_loaded", "asap"]
CampaignStatusLiteral = Literal["active", "paused", "archived"]


class CampaignCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    channel: str = Field(min_length=1, max_length=40)
    total_budget_cents: int = Field(gt=0, le=10_000_000_000)
    pacing_mode: PacingModeLiteral = "even"
    start_date: date
    end_date: date
    currency: str = Field(default="INR", min_length=3, max_length=3)

    @model_validator(mode="after")
    def check_flight(self) -> "CampaignCreate":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if (self.end_date - self.start_date).days > 730:
            raise ValueError("flights longer than 730 days are not supported")
        return self


class CampaignUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=160)
    total_budget_cents: int | None = Field(default=None, gt=0, le=10_000_000_000)
    pacing_mode: PacingModeLiteral | None = None
    status: CampaignStatusLiteral | None = None


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    name: str
    channel: str
    currency: str
    total_budget_cents: int
    pacing_mode: str
    start_date: date
    end_date: date
    status: str


class SpendEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_uid: str = Field(min_length=1, max_length=80)
    campaign_external_id: str = Field(min_length=1, max_length=80)
    amount_cents: int = Field(gt=0, le=100_000_000)
    occurred_at: datetime
    source: str = Field(default="platform_sync", max_length=40)

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("occurred_at must include a timezone offset")
        return value


class SpendBatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[SpendEventIn] = Field(min_length=1, max_length=500)


class SpendIngestResult(BaseModel):
    accepted: int
    duplicates: int
    rejected: int
    errors: list[str] = Field(default_factory=list)


class PacingOut(BaseModel):
    campaign_id: int
    campaign_name: str
    channel: str
    as_of: date
    mode: str
    state: str
    flight_days: int
    flight_day: int
    elapsed_fraction: float
    total_budget_cents: int
    spent_to_date_cents: int
    spent_today_cents: int
    target_to_date_cents: int
    remaining_budget_cents: int
    today_budget_cents: int
    remaining_today_cents: int
    projected_final_spend_cents: int
    projected_overspend_cents: int
    progress_ratio: float


class DailyPoint(BaseModel):
    day: date
    spend_cents: int
    target_cents: int


class CampaignDetailOut(PacingOut):
    daily: list[DailyPoint]
    budget_changes: list["AuditOut"] = Field(default_factory=list)


class OverviewTotals(BaseModel):
    campaigns: int
    total_budget_cents: int
    spent_to_date_cents: int
    projected_final_spend_cents: int
    projected_overspend_cents: int
    open_alerts: int


class PacingOverviewOut(BaseModel):
    as_of: date
    totals: OverviewTotals
    items: list[PacingOut]


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: int | None
    kind: str
    severity: str
    message: str
    created_at: datetime
    resolved_at: datetime | None


class EvaluateOut(BaseModel):
    as_of: date
    campaigns_evaluated: int
    alerts_created: int
    alerts_existing: int


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    plan: str


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor: str
    action: str
    entity: str
    entity_id: int
    before_value: str | None
    after_value: str | None
    created_at: datetime


CampaignDetailOut.model_rebuild()
