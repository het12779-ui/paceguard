"""Deterministic demo dataset.

Seed data is generated relative to *today* so the dashboard always shows live
pacing, and with a fixed RNG seed so screenshots and tests are reproducible.
Spend events use UUID5 keys, which makes re-seeding idempotent.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from paceguard.models import Account, Campaign, SpendEvent
from paceguard.services.governance import evaluate_account
from paceguard.services.ledger import build_snapshots
from paceguard.services.pacing import day_weight
from paceguard.tenant import hash_api_key

DEMO_ACCOUNTS = [
    ("acme-retail", "Acme Retail", "pg_demo_acme_key", "growth"),
    ("nova-travel", "Nova Travel", "pg_demo_nova_key", "scale"),
]

_EVENT_NAMESPACE = uuid.UUID("6f1c2a54-1d3e-4c8a-9a6f-2b7d0e5c9a11")


@dataclass(frozen=True)
class CampaignSpec:
    external_id: str
    name: str
    channel: str
    budget_cents: int
    mode: str
    start_offset: int  # days relative to today
    end_offset: int
    #: Multiplier on the theoretical curve. 1.0 = follows plan, 1.55 = burns hot,
    #: 0.42 = under-delivers. Chosen so the demo shows every pacing state.
    burn: float = 1.0


ACME_SPECS = [
    CampaignSpec("ACR-SRCH-01", "Always-On Brand Search", "google", 30_000_000, "even", -25, 5, 1.0),
    CampaignSpec("ACR-META-02", "Monsoon Awareness Burst", "meta", 80_000_000, "front_loaded", -12, 3, 1.0),
    CampaignSpec("ACR-DSP-03", "Product Retargeting", "display", 12_000_000, "even", -10, 10, 1.55),
    CampaignSpec("ACR-PMAX-04", "Festive Marketplace Push", "google", 20_000_000, "asap", -6, 14, 1.0),
    CampaignSpec("ACR-EML-05", "Loyalty Winback", "email", 6_000_000, "even", -8, 12, 0.42),
    CampaignSpec("ACR-SRCH-06", "Autumn Launch", "google", 40_000_000, "even", 3, 33, 1.0),
]

NOVA_SPECS = [
    CampaignSpec("NVT-SRCH-01", "Destination Search", "google", 50_000_000, "even", -18, 7, 0.98),
    CampaignSpec("NVT-META-02", "Influencer Whitelisting", "meta", 35_000_000, "front_loaded", -9, 6, 1.25),
]


def _daily_amount(spec: CampaignSpec, day_index: int, total_days: int, rng: random.Random) -> int:
    if spec.mode == "asap":
        # Delivery-constrained: the budget is gone in two days by design, so
        # this is the one case where a hard split beats the curve weights.
        base = spec.budget_cents * (0.55 if day_index == 1 else 0.45) if day_index <= 2 else 0
    else:
        base = spec.budget_cents * day_weight(spec.mode, day_index, total_days)

    jitter = rng.uniform(0.85, 1.15)
    return max(1, int(base * spec.burn * jitter))


def _seed_campaign(
    session: Session,
    account: Account,
    spec: CampaignSpec,
    today: date,
    rng: random.Random,
) -> Campaign:
    start = today + timedelta(days=spec.start_offset)
    end = today + timedelta(days=spec.end_offset)
    campaign = Campaign(
        account_id=account.id,
        external_id=spec.external_id,
        name=spec.name,
        channel=spec.channel,
        currency="INR",
        total_budget_cents=spec.budget_cents,
        pacing_mode=spec.mode,
        start_date=start,
        end_date=end,
        status="active",
    )
    session.add(campaign)
    session.flush()

    total_days = (end - start).days + 1
    last_day = min(today, end)
    cursor = start
    while cursor <= last_day:
        day_index = (cursor - start).days + 1
        amount = _daily_amount(spec, day_index, total_days, rng)
        if amount <= 0:
            cursor += timedelta(days=1)
            continue
        session.add(
            SpendEvent(
                account_id=account.id,
                campaign_id=campaign.id,
                event_uid=str(uuid.uuid5(_EVENT_NAMESPACE, f"{account.slug}:{spec.external_id}:{cursor}")),
                amount_cents=amount,
                occurred_at=datetime.combine(cursor, time(hour=18)),
                source="platform_sync",
            )
        )
        cursor += timedelta(days=1)

    return campaign


def seed_demo(session: Session, today: date | None = None, force: bool = False) -> bool:
    """Populate the demo. Returns True when data was written."""

    if not force and session.scalar(select(func.count(Account.id))) > 0:
        return False

    today = today or date.today()
    rng = random.Random(20261017)

    accounts: dict[str, Account] = {}
    for slug, name, api_key, plan in DEMO_ACCOUNTS:
        account = Account(
            name=name, slug=slug, api_key_hash=hash_api_key(api_key), plan=plan
        )
        session.add(account)
        session.flush()
        accounts[slug] = account

    for spec in ACME_SPECS:
        _seed_campaign(session, accounts["acme-retail"], spec, today, rng)
    for spec in NOVA_SPECS:
        _seed_campaign(session, accounts["nova-travel"], spec, today, rng)

    session.commit()

    # Materialise the first round of guardrail alerts so the dashboard is not
    # empty on a cold start.
    for account in accounts.values():
        snapshots = build_snapshots(session, account.id, today)
        evaluate_account(session, account.id, snapshots, today)

    return True


def ensure_seeded(session: Session) -> bool:
    return seed_demo(session)
