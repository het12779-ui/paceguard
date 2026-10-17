from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from paceguard.api.serializers import pacing_out
from paceguard.db import get_session
from paceguard.models import Account, Alert
from paceguard.schemas import EvaluateOut, OverviewTotals, PacingOverviewOut
from paceguard.services.governance import evaluate_account
from paceguard.services.ledger import build_snapshots
from paceguard.tenant import get_tenant

router = APIRouter(prefix="/pacing", tags=["pacing"])


def _today() -> date:
    return datetime.now(timezone.utc).date()


@router.get("/overview", response_model=PacingOverviewOut)
def overview(
    account: Account = Depends(get_tenant),
    session: Session = Depends(get_session),
    as_of: date | None = Query(default=None),
) -> PacingOverviewOut:
    as_of = as_of or _today()
    snapshots = build_snapshots(session, account.id, as_of)

    open_alerts = session.scalar(
        select(func.count(Alert.id)).where(
            Alert.account_id == account.id, Alert.resolved_at.is_(None)
        )
    )

    items = [pacing_out(campaign, snapshot) for campaign, snapshot in snapshots]
    totals = OverviewTotals(
        campaigns=len(items),
        total_budget_cents=sum(item.total_budget_cents for item in items),
        spent_to_date_cents=sum(item.spent_to_date_cents for item in items),
        projected_final_spend_cents=sum(item.projected_final_spend_cents for item in items),
        projected_overspend_cents=sum(item.projected_overspend_cents for item in items),
        open_alerts=int(open_alerts or 0),
    )
    return PacingOverviewOut(as_of=as_of, totals=totals, items=items)


@router.post("/evaluate", response_model=EvaluateOut)
def evaluate(
    account: Account = Depends(get_tenant),
    session: Session = Depends(get_session),
    as_of: date | None = Query(default=None),
) -> EvaluateOut:
    as_of = as_of or _today()
    snapshots = build_snapshots(session, account.id, as_of)
    created, existing = evaluate_account(session, account.id, snapshots, as_of)
    return EvaluateOut(
        as_of=as_of,
        campaigns_evaluated=len(snapshots),
        alerts_created=created,
        alerts_existing=existing,
    )
