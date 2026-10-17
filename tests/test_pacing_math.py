from __future__ import annotations

from datetime import date, timedelta

import pytest

from paceguard.services.pacing import (
    PacingInput,
    PacingMode,
    PacingState,
    compute_pacing,
    cumulative_fraction,
    day_weight,
    project_final_spend,
    remaining_weight,
)

START = date(2026, 10, 1)


def make_input(**overrides) -> PacingInput:
    defaults = dict(
        campaign_id=1,
        mode=PacingMode.EVEN,
        total_budget_cents=100_000,
        start_date=START,
        end_date=START + timedelta(days=9),  # 10-day flight
        as_of=START + timedelta(days=4),  # day 5
        spent_to_date_cents=30_000,
        spent_today_cents=6_000,
    )
    defaults.update(overrides)
    return PacingInput(**defaults)


@pytest.mark.parametrize("mode", [PacingMode.EVEN, PacingMode.FRONT_LOADED, PacingMode.ASAP])
def test_curve_starts_at_zero_and_ends_at_one(mode):
    assert cumulative_fraction(mode, 0.0) == pytest.approx(0.0)
    assert cumulative_fraction(mode, 1.0) == pytest.approx(1.0)


@pytest.mark.parametrize("mode", [PacingMode.EVEN, PacingMode.FRONT_LOADED])
def test_curve_is_monotonic(mode):
    values = [cumulative_fraction(mode, step / 100) for step in range(101)]
    assert all(later >= earlier for earlier, later in zip(values, values[1:]))
    assert all(0.0 <= value <= 1.0 for value in values)


def test_even_curve_is_linear():
    assert cumulative_fraction("even", 0.25) == pytest.approx(0.25)


def test_front_loaded_spends_faster_early():
    assert cumulative_fraction("front_loaded", 0.33) > cumulative_fraction("even", 0.33)


@pytest.mark.parametrize("mode", ["even", "front_loaded"])
def test_day_weights_sum_to_one(mode):
    assert sum(day_weight(mode, day, 10) for day in range(1, 11)) == pytest.approx(1.0)
    assert remaining_weight(mode, 5, 10) == pytest.approx(
        sum(day_weight(mode, day, 10) for day in range(5, 11))
    )


def test_even_flight_target_is_exactly_half_budget_at_midpoint():
    snapshot = compute_pacing(make_input())
    assert snapshot.target_to_date_cents == 50_000
    assert snapshot.flight_day == 5
    assert snapshot.flight_days == 10
    assert snapshot.elapsed_fraction == pytest.approx(0.5)


def test_underspending_state_and_cap_redistribution():
    snapshot = compute_pacing(make_input())
    assert snapshot.state is PacingState.UNDERSPENDING
    assert snapshot.progress_ratio == pytest.approx(0.6)
    assert snapshot.remaining_budget_cents == 70_000
    # 24,000 spent before today leaves 76,000 across the 6 remaining days by
    # curve weight (0.1 of 0.6): 12,666.67 -> 12,667.
    assert snapshot.today_budget_cents == 12_667
    assert snapshot.remaining_today_cents == 6_667


def test_overspending_state_and_projection():
    snapshot = compute_pacing(
        make_input(spent_to_date_cents=70_000, spent_today_cents=14_000)
    )
    assert snapshot.state is PacingState.OVERSPENDING
    assert snapshot.projected_final_spend_cents == 140_000
    assert snapshot.projected_overspend_cents == 40_000


def test_not_started_before_flight():
    snapshot = compute_pacing(make_input(as_of=START - timedelta(days=3), spent_to_date_cents=0))
    assert snapshot.state is PacingState.NOT_STARTED
    assert snapshot.flight_day == 0
    assert snapshot.target_to_date_cents == 0


def test_exhausted_when_budget_is_gone():
    snapshot = compute_pacing(make_input(spent_to_date_cents=100_000))
    assert snapshot.state is PacingState.EXHAUSTED
    assert snapshot.remaining_budget_cents == 0


def test_completed_after_flight_end():
    snapshot = compute_pacing(
        make_input(as_of=START + timedelta(days=20), spent_to_date_cents=98_000)
    )
    assert snapshot.state is PacingState.COMPLETED
    assert snapshot.flight_day == snapshot.flight_days


def test_zero_budget_does_not_divide_by_zero():
    snapshot = compute_pacing(make_input(total_budget_cents=0, spent_to_date_cents=0))
    assert snapshot.target_to_date_cents == 0
    assert snapshot.progress_ratio == 0.0


def test_asap_mode_targets_full_budget_immediately():
    snapshot = compute_pacing(make_input(mode=PacingMode.ASAP, spent_to_date_cents=0))
    assert snapshot.target_to_date_cents == 100_000
    assert snapshot.state is PacingState.UNDERSPENDING


def test_projection_follows_the_curve_not_a_flat_daily_rate():
    # A front-loaded flight at its midpoint has already spent ~77.7% of budget.
    # A flat-rate forecast would project ~155% spend and fire a false alert.
    target = int(round(100_000 * cumulative_fraction("front_loaded", 0.5)))
    assert project_final_spend(target, 100_000, target, 5) == 100_000


def test_projection_scales_the_remaining_curve_by_pace():
    # 40% ahead of plan: 70k spent vs 50k target, 50k of curve left.
    assert project_final_spend(70_000, 100_000, 50_000, 5) == 140_000


def test_exhausted_campaign_does_not_project_more_spend():
    assert project_final_spend(100_000, 100_000, 50_000, 5) == 100_000


def test_projection_before_launch_is_zero():
    assert project_final_spend(0, 100_000, 0, 0) == 0
