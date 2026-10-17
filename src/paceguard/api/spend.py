"""Spend ingest.

Ad platforms deliver spend at-least-once. The idempotency key is
``(account_id, event_uid)`` and the database unique constraint is the source of
truth. A batch uses a SAVEPOINT per event so one bad row does not roll back the
other 499 - the caller gets per-row counts instead of an all-or-nothing 500.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from paceguard.db import get_session
from paceguard.metrics import METRICS
from paceguard.models import Account, Campaign, SpendEvent
from paceguard.schemas import SpendBatchIn, SpendEventIn, SpendIngestResult
from paceguard.tenant import get_tenant

router = APIRouter(prefix="/spend", tags=["spend"])


def _campaign_by_external_id(session: Session, account_id: int, external_id: str) -> Campaign | None:
    return session.scalar(
        select(Campaign).where(
            Campaign.account_id == account_id, Campaign.external_id == external_id
        )
    )


def _normalise(occurred_at: datetime) -> datetime:
    return occurred_at.astimezone(timezone.utc).replace(tzinfo=None)


def _ingest_one(
    session: Session, account: Account, event: SpendEventIn, result: SpendIngestResult
) -> None:
    campaign = _campaign_by_external_id(session, account.id, event.campaign_external_id)
    if campaign is None:
        result.rejected += 1
        result.errors.append(f"{event.event_uid}: unknown campaign '{event.campaign_external_id}'")
        return

    already = session.scalar(
        select(SpendEvent.id).where(
            SpendEvent.account_id == account.id, SpendEvent.event_uid == event.event_uid
        )
    )
    if already is not None:
        result.duplicates += 1
        METRICS.inc("spend_events_duplicate_total")
        return

    savepoint = session.begin_nested()
    try:
        session.add(
            SpendEvent(
                account_id=account.id,
                campaign_id=campaign.id,
                event_uid=event.event_uid,
                amount_cents=event.amount_cents,
                occurred_at=_normalise(event.occurred_at),
                source=event.source,
            )
        )
        savepoint.commit()
        result.accepted += 1
        METRICS.inc("spend_events_ingested_total", channel=campaign.channel)
    except IntegrityError:
        # Concurrent writer won the race; the event still exists exactly once.
        savepoint.rollback()
        result.duplicates += 1
        METRICS.inc("spend_events_duplicate_total")


@router.post("", response_model=SpendIngestResult, status_code=201)
def ingest_event(
    event: SpendEventIn,
    account: Account = Depends(get_tenant),
    session: Session = Depends(get_session),
) -> SpendIngestResult:
    result = SpendIngestResult(accepted=0, duplicates=0, rejected=0)
    _ingest_one(session, account, event, result)
    session.commit()
    if result.rejected:
        raise HTTPException(status_code=422, detail=result.errors[0])
    return result


@router.post("/batch", response_model=SpendIngestResult, status_code=201)
def ingest_batch(
    payload: SpendBatchIn,
    account: Account = Depends(get_tenant),
    session: Session = Depends(get_session),
) -> SpendIngestResult:
    result = SpendIngestResult(accepted=0, duplicates=0, rejected=0)
    for event in payload.events:
        _ingest_one(session, account, event, result)
    session.commit()
    return result
