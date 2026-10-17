"""Benchmark ``GET /api/v1/pacing/overview`` end to end.

Runs the real FastAPI app against a temporary SQLite database, so the measured
number includes query planning, ORM hydration, pacing maths, Pydantic
serialisation and JSON encoding - i.e. what a dashboard request actually pays.

Usage:
    python scripts/bench_overview.py
    python scripts/bench_overview.py --sizes 10 100 1000 10000 --iterations 15
"""

from __future__ import annotations

import argparse
import os
import statistics
import tempfile
import time
from datetime import date, datetime, timedelta, timezone

_WORKDIR = tempfile.mkdtemp(prefix="paceguard-bench-")
os.environ["DATABASE_URL"] = f"sqlite:///{_WORKDIR}/bench.db"
os.environ["PACEGUARD_SEED"] = "0"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import insert  # noqa: E402

from paceguard.config import Settings  # noqa: E402
from paceguard.db import Base, SessionLocal, engine  # noqa: E402
from paceguard.main import create_app  # noqa: E402
from paceguard.models import Account, Campaign, SpendEvent  # noqa: E402
from paceguard.tenant import hash_api_key  # noqa: E402

API_KEY = "bench-key"
TODAY = date.today()


def seed(campaign_count: int) -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    with SessionLocal() as session:
        account = Account(
            name="Bench", slug="bench", api_key_hash=hash_api_key(API_KEY), plan="scale"
        )
        session.add(account)
        session.flush()

        campaigns = [
            {
                "account_id": account.id,
                "external_id": f"BENCH-{index:05d}",
                "name": f"Benchmark campaign {index}",
                "channel": "google" if index % 2 else "meta",
                "currency": "INR",
                "total_budget_cents": 5_000_000 + index,
                "pacing_mode": "even",
                "start_date": TODAY - timedelta(days=20),
                "end_date": TODAY + timedelta(days=10),
                "status": "active",
                "created_at": datetime.now(timezone.utc).replace(tzinfo=None),
            }
            for index in range(campaign_count)
        ]
        session.execute(insert(Campaign), campaigns)

        ids = session.execute(
            Campaign.__table__.select().with_only_columns(Campaign.id)
        ).scalars().all()

        events = []
        for campaign_id in ids:
            for offset in (0, 1, 2):
                events.append(
                    {
                        "account_id": account.id,
                        "campaign_id": campaign_id,
                        "event_uid": f"{campaign_id}-{offset}",
                        "amount_cents": 40_000 + offset * 1_000,
                        "occurred_at": datetime.combine(
                            TODAY - timedelta(days=offset), datetime.min.time()
                        ),
                        "source": "bench",
                    }
                )
        session.execute(insert(SpendEvent), events)
        session.commit()


def measure(campaign_count: int, iterations: int) -> dict:
    seed(campaign_count)
    app = create_app(Settings(demo_mode=False, seed_demo_data=False))

    with TestClient(app) as client:
        client.headers.update({"X-API-Key": API_KEY})
        url = f"/api/v1/pacing/overview?as_of={TODAY.isoformat()}"

        for _ in range(3):  # warm caches, JIT the JSON encoder
            assert client.get(url).status_code == 200

        samples = []
        for _ in range(iterations):
            started = time.perf_counter()
            response = client.get(url)
            samples.append((time.perf_counter() - started) * 1000)
            assert response.status_code == 200
            assert len(response.json()["items"]) == campaign_count

    samples.sort()
    return {
        "campaigns": campaign_count,
        "p50_ms": statistics.median(samples),
        "p95_ms": samples[max(0, int(len(samples) * 0.95) - 1)],
        "max_ms": max(samples),
        "bytes": len(response.content),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", type=int, nargs="+", default=[10, 100, 1000, 5000])
    parser.add_argument("--iterations", type=int, default=20)
    args = parser.parse_args()

    print(f"PaceGuard overview benchmark · {args.iterations} iterations per size")
    print()
    print("| campaigns | p50 | p95 | max | payload |")
    print("|---:|---:|---:|---:|---:|")
    for size in args.sizes:
        result = measure(size, args.iterations)
        print(
            f"| {result['campaigns']:,} | {result['p50_ms']:.1f} ms | "
            f"{result['p95_ms']:.1f} ms | {result['max_ms']:.1f} ms | "
            f"{result['bytes'] / 1024:.0f} KB |"
        )


if __name__ == "__main__":
    main()
