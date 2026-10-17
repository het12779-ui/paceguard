"""Pacing mathematics.

This module is pure: no database, no I/O, no clock. Every function takes the
data it needs, which is what makes the money maths testable to the cent.

Design notes
------------
* All money is integer **cents**. Floats never touch a budget.
* A flight is `[start_date, end_date]` inclusive, in the campaign's own
  accounting timezone (UTC in this demo).
* Pacing is expressed as a cumulative spend curve ``F(t)`` where ``t`` is the
  fraction of the flight that has elapsed. ``F(0) = 0`` and ``F(1) = 1``.
* The daily cap is derived from the *remaining* curve weights, so a campaign
  that underspent yesterday automatically gets a slightly larger cap today
  instead of blowing through its budget at the finish line.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from math import exp


class PacingMode(str, Enum):
    """How aggressively a campaign is allowed to spend its budget."""

    EVEN = "even"
    FRONT_LOADED = "front_loaded"
    ASAP = "asap"


class PacingState(str, Enum):
    NOT_STARTED = "not_started"
    ON_TRACK = "on_track"
    UNDERSPENDING = "underspending"
    OVERSPENDING = "overspending"
    EXHAUSTED = "exhausted"
    COMPLETED = "completed"


#: Decay constant for front-loaded flights. k=2.5 puts ~55% of the budget into
#: the first third of the flight, which matches how launch campaigns actually
#: behave (awareness burst first, then sustain).
FRONT_LOAD_K = 2.5

#: A campaign within +/-10% of its curve is "on track". Tighter than this and
#: every campaign alerts daily, which is how alert fatigue starts.
ON_TRACK_BAND = 0.10


def cumulative_fraction(mode: PacingMode | str, elapsed_fraction: float) -> float:
    """Return the share of total budget that should be spent by ``t``."""

    mode = PacingMode(mode)
    t = min(max(elapsed_fraction, 0.0), 1.0)

    if mode is PacingMode.ASAP:
        # Spend as fast as delivery allows: the whole budget is fair game on
        # day one. F(0) is still 0 so "before launch" stays coherent.
        return 1.0 if t > 0 else 0.0

    if mode is PacingMode.FRONT_LOADED:
        numerator = 1.0 - exp(-FRONT_LOAD_K * t)
        denominator = 1.0 - exp(-FRONT_LOAD_K)
        return numerator / denominator

    return t  # EVEN


def day_weight(mode: PacingMode | str, day_index: int, total_days: int) -> float:
    """Share of the total budget that belongs to flight day ``day_index`` (1-based)."""

    if total_days <= 0:
        return 0.0

    mode = PacingMode(mode)
    if mode is PacingMode.ASAP:
        return 1.0 if day_index == 1 else 0.0

    return cumulative_fraction(mode, day_index / total_days) - cumulative_fraction(
        mode, (day_index - 1) / total_days
    )


def remaining_weight(mode: PacingMode | str, from_day: int, total_days: int) -> float:
    """Sum of curve weights for flight days ``from_day..total_days``."""

    return sum(day_weight(mode, day, total_days) for day in range(from_day, total_days + 1))


@dataclass(frozen=True, slots=True)
class PacingInput:
    campaign_id: int
    mode: PacingMode
    total_budget_cents: int
    start_date: date
    end_date: date
    as_of: date
    spent_to_date_cents: int
    spent_today_cents: int


@dataclass(frozen=True, slots=True)
class PacingSnapshot:
    campaign_id: int
    as_of: date
    mode: PacingMode
    state: PacingState
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

    def as_dict(self) -> dict:
        return {
            "campaign_id": self.campaign_id,
            "as_of": self.as_of.isoformat(),
            "mode": self.mode.value,
            "state": self.state.value,
            "flight_days": self.flight_days,
            "flight_day": self.flight_day,
            "elapsed_fraction": round(self.elapsed_fraction, 4),
            "total_budget_cents": self.total_budget_cents,
            "spent_to_date_cents": self.spent_to_date_cents,
            "spent_today_cents": self.spent_today_cents,
            "target_to_date_cents": self.target_to_date_cents,
            "remaining_budget_cents": self.remaining_budget_cents,
            "today_budget_cents": self.today_budget_cents,
            "remaining_today_cents": self.remaining_today_cents,
            "projected_final_spend_cents": self.projected_final_spend_cents,
            "projected_overspend_cents": self.projected_overspend_cents,
            "progress_ratio": round(self.progress_ratio, 4),
        }


def project_final_spend(
    spent_to_date_cents: int,
    total_budget_cents: int,
    target_to_date_cents: int,
    flight_day: int,
) -> int:
    """Forecast final spend along the campaign's own curve.

    The naive forecast (``spend / days_elapsed * total_days``) assumes a flat
    daily rate. That is badly wrong for front-loaded flights, where the early
    days are *supposed* to be the expensive ones - every healthy burst campaign
    would look like it was going to overspend.

    Instead, project the remaining curve budget at the campaign's current pace:

        remaining_curve = budget - target_to_date
        pace            = spent_to_date / target_to_date
        projected       = spent_to_date + remaining_curve * pace

    ``pace = 1.0`` means the campaign is exactly on plan and will land on budget.
    An exhausted campaign stops delivering, so its projection is simply what it
    has already spent.
    """

    if flight_day <= 0:
        return 0
    if spent_to_date_cents >= total_budget_cents:
        return spent_to_date_cents
    if target_to_date_cents <= 0:
        return spent_to_date_cents

    pace = spent_to_date_cents / target_to_date_cents
    remaining_curve = max(0, total_budget_cents - target_to_date_cents)
    return int(round(spent_to_date_cents + remaining_curve * pace))


def compute_pacing(data: PacingInput) -> PacingSnapshot:
    """Build a full pacing snapshot for one campaign on one day."""

    flight_days = max(1, (data.end_date - data.start_date).days + 1)
    flight_day = min(max((data.as_of - data.start_date).days + 1, 0), flight_days)
    elapsed_fraction = flight_day / flight_days

    target = int(
        round(data.total_budget_cents * cumulative_fraction(data.mode, elapsed_fraction))
    )
    target = min(target, data.total_budget_cents)

    remaining_budget = max(0, data.total_budget_cents - data.spent_to_date_cents)

    # What today's delivery is allowed to be, given the curve. `spent_today` is
    # part of today, so the cap is computed from the budget that existed before
    # today started - otherwise spending early looks like it earns extra budget.
    today_budget = 0
    if 1 <= flight_day <= flight_days:
        today_weight = day_weight(data.mode, flight_day, flight_days)
        weights_ahead = remaining_weight(data.mode, flight_day, flight_days)
        if weights_ahead > 0:
            spent_before_today = max(0, data.spent_to_date_cents - data.spent_today_cents)
            budget_before_today = max(0, data.total_budget_cents - spent_before_today)
            today_budget = int(round(budget_before_today * today_weight / weights_ahead))

    remaining_today = max(0, today_budget - data.spent_today_cents)

    projected = project_final_spend(
        data.spent_to_date_cents, data.total_budget_cents, target, flight_day
    )

    progress_ratio = (data.spent_to_date_cents / target) if target > 0 else 0.0

    if data.as_of < data.start_date:
        state = PacingState.NOT_STARTED
    elif data.as_of > data.end_date:
        state = PacingState.COMPLETED
    elif data.spent_to_date_cents >= data.total_budget_cents:
        state = PacingState.EXHAUSTED
    elif progress_ratio > 1 + ON_TRACK_BAND:
        state = PacingState.OVERSPENDING
    elif progress_ratio < 1 - ON_TRACK_BAND:
        state = PacingState.UNDERSPENDING
    else:
        state = PacingState.ON_TRACK

    return PacingSnapshot(
        campaign_id=data.campaign_id,
        as_of=data.as_of,
        mode=data.mode,
        state=state,
        flight_days=flight_days,
        flight_day=flight_day,
        elapsed_fraction=elapsed_fraction,
        total_budget_cents=data.total_budget_cents,
        spent_to_date_cents=data.spent_to_date_cents,
        spent_today_cents=data.spent_today_cents,
        target_to_date_cents=target,
        remaining_budget_cents=remaining_budget,
        today_budget_cents=today_budget,
        remaining_today_cents=remaining_today,
        projected_final_spend_cents=projected,
        projected_overspend_cents=max(0, projected - data.total_budget_cents),
        progress_ratio=progress_ratio,
    )
