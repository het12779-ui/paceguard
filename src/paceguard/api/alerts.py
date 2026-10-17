from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from paceguard.db import get_session
from paceguard.models import Account, Alert
from paceguard.schemas import AlertOut
from paceguard.tenant import get_tenant

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertOut])
def list_alerts(
    account: Account = Depends(get_tenant),
    session: Session = Depends(get_session),
    open_only: bool = Query(default=True, alias="open"),
    severity: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[Alert]:
    stmt = select(Alert).where(Alert.account_id == account.id)
    if open_only:
        stmt = stmt.where(Alert.resolved_at.is_(None))
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    return list(session.scalars(stmt.order_by(Alert.created_at.desc()).limit(limit)).all())


@router.post("/{alert_id}/resolve", response_model=AlertOut)
def resolve_alert(
    alert_id: int,
    account: Account = Depends(get_tenant),
    session: Session = Depends(get_session),
) -> Alert:
    alert = session.scalar(
        select(Alert).where(Alert.id == alert_id, Alert.account_id == account.id)
    )
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    if alert.resolved_at is None:
        alert.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.commit()
        session.refresh(alert)
    return alert
