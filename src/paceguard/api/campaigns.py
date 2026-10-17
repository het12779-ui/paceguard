from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from paceguard.api.serializers import daily_points, pacing_out
from paceguard.db import get_session
from paceguard.models import Account, Alert, AuditLog, Campaign
from paceguard.schemas import (
    AuditOut,
    CampaignCreate,
    CampaignDetailOut,
    CampaignOut,
    CampaignUpdate,
)
from paceguard.services.ledger import daily_series, load_spend_context, snapshot_from_context
from paceguard.tenant import get_tenant

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


def get_campaign_or_404(session: Session, account: Account, campaign_id: int) -> Campaign:
    campaign = session.scalar(
        select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.account_id == account.id,  # tenant guard, never optional
        )
    )
    if campaign is None:
        # 404 rather than 403: never confirm that another tenant's id exists.
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


@router.get("", response_model=list[CampaignOut])
def list_campaigns(
    account: Account = Depends(get_tenant),
    session: Session = Depends(get_session),
    campaign_status: str | None = Query(default=None, alias="status"),
    channel: str | None = None,
) -> list[Campaign]:
    stmt = select(Campaign).where(Campaign.account_id == account.id)
    if campaign_status:
        stmt = stmt.where(Campaign.status == campaign_status)
    if channel:
        stmt = stmt.where(Campaign.channel == channel)
    return list(session.scalars(stmt.order_by(Campaign.start_date.desc(), Campaign.id)).all())


@router.post("", response_model=CampaignOut, status_code=status.HTTP_201_CREATED)
def create_campaign(
    payload: CampaignCreate,
    account: Account = Depends(get_tenant),
    session: Session = Depends(get_session),
) -> Campaign:
    campaign = Campaign(account_id=account.id, **payload.model_dump())
    session.add(campaign)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"external_id '{payload.external_id}' already exists for this account",
        ) from exc

    session.add(
        AuditLog(
            account_id=account.id,
            actor=f"api:{account.slug}",
            action="campaign.create",
            entity="campaign",
            entity_id=campaign.id,
            before_value=None,
            after_value=str(payload.total_budget_cents),
        )
    )
    session.commit()
    session.refresh(campaign)
    return campaign


@router.get("/{campaign_id}", response_model=CampaignDetailOut)
def get_campaign(
    campaign_id: int,
    account: Account = Depends(get_tenant),
    session: Session = Depends(get_session),
    as_of: date | None = Query(default=None, description="Evaluate as of this date (UTC)"),
) -> CampaignDetailOut:
    campaign = get_campaign_or_404(session, account, campaign_id)
    as_of = as_of or datetime.now(timezone.utc).date()

    context = load_spend_context(session, account.id, as_of)
    snapshot = snapshot_from_context(campaign, context, as_of)

    base = pacing_out(campaign, snapshot)
    audit = session.scalars(
        select(AuditLog)
        .where(
            AuditLog.account_id == account.id,
            AuditLog.entity == "campaign",
            AuditLog.entity_id == campaign.id,
            AuditLog.action == "campaign.budget_change",
        )
        .order_by(AuditLog.created_at.desc())
        .limit(20)
    ).all()

    return CampaignDetailOut(
        **base.model_dump(),
        daily=daily_points(campaign, daily_series(session, account.id, campaign, as_of), snapshot),
        budget_changes=[AuditOut.model_validate(row) for row in audit],
    )


@router.patch("/{campaign_id}", response_model=CampaignOut)
def update_campaign(
    campaign_id: int,
    payload: CampaignUpdate,
    account: Account = Depends(get_tenant),
    session: Session = Depends(get_session),
) -> Campaign:
    campaign = get_campaign_or_404(session, account, campaign_id)
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)

    if not changes:
        return campaign

    if campaign.status == "archived" and changes.get("status") != "active":
        raise HTTPException(status_code=409, detail="Archived campaigns are read-only")

    before_budget = campaign.total_budget_cents
    for field, value in changes.items():
        setattr(campaign, field, value)

    if "total_budget_cents" in changes and changes["total_budget_cents"] != before_budget:
        session.add(
            AuditLog(
                account_id=account.id,
                actor=f"api:{account.slug}",
                action="campaign.budget_change",
                entity="campaign",
                entity_id=campaign.id,
                before_value=str(before_budget),
                after_value=str(changes["total_budget_cents"]),
            )
        )
        # A budget cut can invalidate open projections; they are recomputed on
        # the next evaluate call, which is cheap and keeps this endpoint small.

    session.commit()
    session.refresh(campaign)
    return campaign


@router.get("/{campaign_id}/alerts")
def campaign_alerts(
    campaign_id: int,
    account: Account = Depends(get_tenant),
    session: Session = Depends(get_session),
) -> list[dict]:
    get_campaign_or_404(session, account, campaign_id)
    rows = session.scalars(
        select(Alert)
        .where(Alert.account_id == account.id, Alert.campaign_id == campaign_id)
        .order_by(Alert.created_at.desc())
        .limit(50)
    ).all()
    return [
        {
            "id": row.id,
            "kind": row.kind,
            "severity": row.severity,
            "message": row.message,
            "created_at": row.created_at,
            "resolved_at": row.resolved_at,
        }
        for row in rows
    ]
