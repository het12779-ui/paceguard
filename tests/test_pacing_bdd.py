"""Step definitions for ``features/pacing.feature``.

The scenarios exercise the pure engine and the rule functions - no HTTP, no
database - so they run in milliseconds and describe behaviour in the language
an ad-ops stakeholder would use.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from paceguard.services.governance import evaluate_rules
from paceguard.services.pacing import PacingInput, PacingMode, compute_pacing

scenarios("features/pacing.feature")

START = date(2026, 10, 1)


@pytest.fixture
def ctx() -> dict:
    return {}


@given(
    parsers.parse(
        "an even-paced campaign with a {flight_days:d} day flight and a {budget:d} cent budget"
    )
)
def even_campaign(ctx, flight_days: int, budget: int):
    ctx.update(
        mode=PacingMode.EVEN,
        budget=budget,
        flight_days=flight_days,
        start=START,
        end=START + timedelta(days=flight_days - 1),
        campaign=SimpleNamespace(name="BDD Campaign", status="active"),
    )


@given(parsers.parse("{spent:d} cents spent by day {day:d}"))
def spent_by_day(ctx, spent: int, day: int):
    ctx["spent"] = spent
    ctx["per_day"] = spent // day


@when(parsers.parse("I evaluate pacing on day {day:d}"))
def evaluate(ctx, day: int):
    as_of = ctx["start"] + timedelta(days=day - 1)
    ctx["snapshot"] = compute_pacing(
        PacingInput(
            campaign_id=1,
            mode=ctx["mode"],
            total_budget_cents=ctx["budget"],
            start_date=ctx["start"],
            end_date=ctx["end"],
            as_of=as_of,
            spent_to_date_cents=ctx["spent"],
            spent_today_cents=ctx["per_day"],
        )
    )
    ctx["alerts"] = evaluate_rules(ctx["campaign"], ctx["snapshot"])


@then(parsers.parse('the pacing state is "{state}"'))
def pacing_state(ctx, state: str):
    assert ctx["snapshot"].state.value == state


@then(parsers.parse("the target to date is {cents:d} cents"))
def target_to_date(ctx, cents: int):
    assert ctx["snapshot"].target_to_date_cents == cents


@then(parsers.parse("the projected overspend is {cents:d} cents"))
def projected_overspend(ctx, cents: int):
    assert ctx["snapshot"].projected_overspend_cents == cents


@then(parsers.parse('the guardrail raises an "{kind}" alert'))
def raises_alert(ctx, kind: str):
    assert kind in {draft.kind for draft in ctx["alerts"]}


@then(parsers.parse('the guardrail raises a "{kind}" alert'))
def raises_a_alert(ctx, kind: str):
    assert kind in {draft.kind for draft in ctx["alerts"]}


@then("no guardrail alert is raised")
def no_alert(ctx):
    assert ctx["alerts"] == [], [draft.kind for draft in ctx["alerts"]]
