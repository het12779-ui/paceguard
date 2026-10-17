from __future__ import annotations

from paceguard.models import Campaign
from paceguard.schemas import DailyPoint, PacingOut
from paceguard.services.pacing import PacingSnapshot


def pacing_out(campaign: Campaign, snapshot: PacingSnapshot) -> PacingOut:
    return PacingOut(
        campaign_id=campaign.id,
        campaign_name=campaign.name,
        channel=campaign.channel,
        as_of=snapshot.as_of,
        mode=snapshot.mode.value,
        state=snapshot.state.value,
        flight_days=snapshot.flight_days,
        flight_day=snapshot.flight_day,
        elapsed_fraction=round(snapshot.elapsed_fraction, 4),
        total_budget_cents=snapshot.total_budget_cents,
        spent_to_date_cents=snapshot.spent_to_date_cents,
        spent_today_cents=snapshot.spent_today_cents,
        target_to_date_cents=snapshot.target_to_date_cents,
        remaining_budget_cents=snapshot.remaining_budget_cents,
        today_budget_cents=snapshot.today_budget_cents,
        remaining_today_cents=snapshot.remaining_today_cents,
        projected_final_spend_cents=snapshot.projected_final_spend_cents,
        projected_overspend_cents=snapshot.projected_overspend_cents,
        progress_ratio=round(snapshot.progress_ratio, 4),
    )


def daily_points(
    campaign: Campaign, series: list[tuple], snapshot: PacingSnapshot
) -> list[DailyPoint]:
    """Attach the cumulative-curve target to each day for the chart."""
    from paceguard.services.pacing import cumulative_fraction

    total_days = snapshot.flight_days
    points: list[DailyPoint] = []
    for day, spend_cents in series:
        day_index = (day - campaign.start_date).days + 1
        target = int(round(campaign.total_budget_cents * cumulative_fraction(
            campaign.pacing_mode, min(max(day_index / total_days, 0.0), 1.0)
        )))
        points.append(DailyPoint(day=day, spend_cents=spend_cents, target_cents=target))
    return points
