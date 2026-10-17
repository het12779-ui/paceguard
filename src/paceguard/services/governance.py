"""Guardrail rules.

Each rule is a pure function of a pacing snapshot, so the thresholds can be
unit-tested and tuned without a database. Persistence (dedupe + auto-resolve)
happens in ``evaluate_account``.

Thresholds are deliberately conservative: an alerting system that cries wolf is
worse than no alerting system, because operators mute it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from paceguard.models import Alert, Campaign
from paceguard.services.pacing import PacingSnapshot, PacingState

#: Projection must exceed the budget by this share before it is worth an alert.
OVERSPEND_WARN = 0.05
OVERSPEND_CRITICAL = 0.20
#: Under-pacing only matters once enough of the flight has run to be credible.
UNDERPACE_PROGRESS = 0.80
UNDERPACE_MIN_ELAPSED = 0.25
#: Today's spend versus today's allowance.
DAILY_BREACH_MULTIPLIER = 1.10


@dataclass(frozen=True)
class AlertDraft:
    kind: str
    severity: str
    message: str
    detail: str


CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}


def _money(cents: int, currency: str = "INR") -> str:
    """Format minor units for human-readable alert copy.

    Full i18n formatting lives in the UI; alert text needs to be readable in a
    Slack message or an email, so a symbol + thousands separators is enough.
    """
    return f"{CURRENCY_SYMBOLS.get(currency, currency + ' ')}{cents / 100:,.2f}"


def evaluate_rules(campaign: Campaign, snapshot: PacingSnapshot) -> list[AlertDraft]:
    drafts: list[AlertDraft] = []
    currency = getattr(campaign, "currency", "INR")

    if campaign.status != "active":
        return drafts

    if snapshot.state is PacingState.EXHAUSTED:
        drafts.append(
            AlertDraft(
                kind="BUDGET_EXHAUSTED",
                severity="critical",
                message=f"{campaign.name} has spent its full budget",
                detail=(
                    f"Spent {_money(snapshot.spent_to_date_cents, currency)} of "
                    f"{_money(snapshot.total_budget_cents, currency)} with "
                    f"{max(0, snapshot.flight_days - snapshot.flight_day)} flight days left."
                ),
            )
        )

    if snapshot.total_budget_cents > 0:
        overspend_ratio = snapshot.projected_overspend_cents / snapshot.total_budget_cents
        if overspend_ratio >= OVERSPEND_WARN and snapshot.state is not PacingState.EXHAUSTED:
            drafts.append(
                AlertDraft(
                    kind="PROJECTED_OVERSPEND",
                    severity="critical" if overspend_ratio >= OVERSPEND_CRITICAL else "warning",
                    message=(
                        f"{campaign.name} is projected to overspend by "
                        f"{_money(snapshot.projected_overspend_cents, currency)}"
                    ),
                    detail=(
                        f"Projected final spend {_money(snapshot.projected_final_spend_cents, currency)} "
                        f"against a {_money(snapshot.total_budget_cents, currency)} budget "
                        f"({overspend_ratio * 100:.1f}% over)."
                    ),
                )
            )

    if (
        snapshot.elapsed_fraction >= UNDERPACE_MIN_ELAPSED
        and snapshot.progress_ratio < UNDERPACE_PROGRESS
        and snapshot.state is PacingState.UNDERSPENDING
    ):
        shortfall = max(0, snapshot.target_to_date_cents - snapshot.spent_to_date_cents)
        drafts.append(
            AlertDraft(
                kind="UNDER_PACE",
                severity="warning",
                message=f"{campaign.name} has delivered {snapshot.progress_ratio * 100:.0f}% of plan",
                detail=(
                    f"{_money(shortfall, currency)} behind the pacing curve at day "
                    f"{snapshot.flight_day} of {snapshot.flight_days}."
                ),
            )
        )

    if (
        snapshot.today_budget_cents > 0
        and snapshot.spent_today_cents > snapshot.today_budget_cents * DAILY_BREACH_MULTIPLIER
    ):
        drafts.append(
            AlertDraft(
                kind="DAILY_CAP_BREACH",
                severity="warning",
                message=f"{campaign.name} exceeded today's pacing allowance",
                detail=(
                    f"Spent {_money(snapshot.spent_today_cents, currency)} today against an allowance of "
                    f"{_money(snapshot.today_budget_cents, currency)}."
                ),
            )
        )

    if (
        campaign.status == "active"
        and snapshot.flight_day >= 2
        and snapshot.spent_today_cents == 0
        and snapshot.flight_day <= snapshot.flight_days
    ):
        drafts.append(
            AlertDraft(
                kind="DELIVERY_STALLED",
                severity="critical",
                message=f"{campaign.name} has no spend recorded today",
                detail=(
                    "Possible tracking outage, rejected creatives, or a paused line item. "
                    "Check the platform sync job before assuming the campaign is simply quiet."
                ),
            )
        )

    return drafts


def dedupe_key(campaign_id: int, kind: str, as_of: date) -> str:
    """One alert per campaign/kind/day, however often evaluation runs."""
    return f"{campaign_id}:{kind}:{as_of.isoformat()}"


def evaluate_account(
    session: Session, account_id: int, snapshots: list[tuple[Campaign, PacingSnapshot]], as_of: date
) -> tuple[int, int]:
    """Persist rule output. Returns ``(created, already_existing)``."""

    existing = {
        alert.dedupe_key: alert
        for alert in session.scalars(select(Alert).where(Alert.account_id == account_id)).all()
    }

    created = 0
    existing_hits = 0
    live_keys: set[str] = set()

    for campaign, snapshot in snapshots:
        for draft in evaluate_rules(campaign, snapshot):
            key = dedupe_key(campaign.id, draft.kind, as_of)
            live_keys.add(key)

            current = existing.get(key)
            if current is not None:
                existing_hits += 1
                # Re-opening a resolved alert of the same day is intentional:
                # the condition came back, so the operator should see it again.
                if current.resolved_at is not None:
                    current.resolved_at = None
                continue

            session.add(
                Alert(
                    account_id=account_id,
                    campaign_id=campaign.id,
                    kind=draft.kind,
                    severity=draft.severity,
                    dedupe_key=key,
                    message=draft.message,
                    detail=draft.detail,
                )
            )
            created += 1

    # Auto-resolve stale open alerts for this account: the condition cleared.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for alert in existing.values():
        if alert.resolved_at is None and alert.dedupe_key not in live_keys:
            alert.resolved_at = now

    session.commit()
    return created, existing_hits
