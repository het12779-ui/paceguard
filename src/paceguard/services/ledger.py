"""Read-model layer: turn spend facts into pacing snapshots.

Two performance decisions live here:

1. **Range predicates, not ``DATE(column)``.** Filtering with
   ``occurred_at >= day_start AND occurred_at < day_end`` is sargable, so the
   index on ``(campaign_id, occurred_at)`` is used. ``WHERE DATE(occurred_at)=?``
   would scan. This also keeps the SQL portable to SQL Server.
2. **Two queries per overview, not 2N.** Lifetime spend and today's spend are
   each one ``GROUP BY``, so an account with 10k campaigns costs the same number
   of round trips as one with ten. Pacing is then computed in Python from the
   two maps.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from paceguard.models import Campaign, SpendEvent
from paceguard.services.pacing import PacingInput, PacingMode, PacingSnapshot, compute_pacing


def day_start(day: date) -> datetime:
    """Naive UTC midnight - the storage convention (see ``models.utcnow``)."""
    return datetime.combine(day, time.min)


def day_end(day: date) -> datetime:
    return day_start(day) + timedelta(days=1)


@dataclass
class SpendContext:
    total_by_campaign: dict[int, int]
    today_by_campaign: dict[int, int]


def load_spend_context(session: Session, account_id: int, as_of: date) -> SpendContext:
    total_rows = session.execute(
        select(SpendEvent.campaign_id, func.coalesce(func.sum(SpendEvent.amount_cents), 0))
        .where(
            SpendEvent.account_id == account_id,
            SpendEvent.occurred_at < day_end(as_of),
        )
        .group_by(SpendEvent.campaign_id)
    ).all()

    today_rows = session.execute(
        select(SpendEvent.campaign_id, func.coalesce(func.sum(SpendEvent.amount_cents), 0))
        .where(
            SpendEvent.account_id == account_id,
            SpendEvent.occurred_at >= day_start(as_of),
            SpendEvent.occurred_at < day_end(as_of),
        )
        .group_by(SpendEvent.campaign_id)
    ).all()

    return SpendContext(
        total_by_campaign={campaign_id: int(cents) for campaign_id, cents in total_rows},
        today_by_campaign={campaign_id: int(cents) for campaign_id, cents in today_rows},
    )


def snapshot_from_context(
    campaign: Campaign, context: SpendContext, as_of: date
) -> PacingSnapshot:
    spent = context.total_by_campaign.get(campaign.id, 0)
    spent_today = context.today_by_campaign.get(campaign.id, 0)

    return compute_pacing(
        PacingInput(
            campaign_id=campaign.id,
            mode=PacingMode(campaign.pacing_mode),
            total_budget_cents=campaign.total_budget_cents,
            start_date=campaign.start_date,
            end_date=campaign.end_date,
            as_of=as_of,
            spent_to_date_cents=spent,
            spent_today_cents=spent_today,
        )
    )


def build_snapshots(
    session: Session, account_id: int, as_of: date
) -> list[tuple[Campaign, PacingSnapshot]]:
    campaigns = session.scalars(
        select(Campaign)
        .where(Campaign.account_id == account_id, Campaign.status != "archived")
        .order_by(Campaign.start_date, Campaign.id)
    ).all()

    context = load_spend_context(session, account_id, as_of)
    return [(campaign, snapshot_from_context(campaign, context, as_of)) for campaign in campaigns]


def daily_series(
    session: Session, account_id: int, campaign: Campaign, as_of: date
) -> list[tuple[date, int]]:
    """Spend per flight day, zero-filled, for the detail chart."""

    if campaign.start_date > as_of:
        return []

    first = campaign.start_date
    last = min(campaign.end_date, as_of)

    rows = session.execute(
        select(SpendEvent.occurred_at, SpendEvent.amount_cents).where(
            SpendEvent.account_id == account_id,
            SpendEvent.campaign_id == campaign.id,
            SpendEvent.occurred_at >= day_start(first),
            SpendEvent.occurred_at < day_end(last),
        )
    ).all()

    buckets: dict[date, int] = defaultdict(int)
    for occurred_at, cents in rows:
        buckets[occurred_at.date()] += int(cents)

    series: list[tuple[date, int]] = []
    cursor = first
    while cursor <= last:
        series.append((cursor, buckets.get(cursor, 0)))
        cursor += timedelta(days=1)
    return series
