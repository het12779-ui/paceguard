from __future__ import annotations

import os
import tempfile

# Environment must be set before paceguard.config/db are imported: the engine is
# created at import time from DATABASE_URL.
_TEST_DIR = tempfile.mkdtemp(prefix="paceguard-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DIR}/test.db"
os.environ["PACEGUARD_SEED"] = "0"
os.environ["PACEGUARD_DEMO"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from paceguard.config import Settings  # noqa: E402
from paceguard.db import Base, SessionLocal, engine  # noqa: E402
from paceguard.main import create_app  # noqa: E402
from paceguard.models import Account  # noqa: E402
from paceguard.tenant import hash_api_key  # noqa: E402

ACME_KEY = "test-acme-key"
NOVA_KEY = "test-nova-key"


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def session() -> Session:
    with SessionLocal() as db:
        yield db


@pytest.fixture
def tenants(session: Session) -> tuple[Account, Account]:
    acme = Account(name="Acme Retail", slug="acme", api_key_hash=hash_api_key(ACME_KEY))
    nova = Account(name="Nova Travel", slug="nova", api_key_hash=hash_api_key(NOVA_KEY))
    session.add_all([acme, nova])
    session.commit()
    session.refresh(acme)
    session.refresh(nova)
    return acme, nova


@pytest.fixture
def app():
    return create_app(Settings(demo_mode=True, seed_demo_data=False))


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def acme_client(client, tenants):
    client.headers.update({"X-API-Key": ACME_KEY})
    return client


@pytest.fixture
def nova_client(app, tenants):
    with TestClient(app) as test_client:
        test_client.headers.update({"X-API-Key": NOVA_KEY})
        yield test_client


def make_campaign(client, **overrides) -> dict:
    payload = {
        "external_id": "CMP-001",
        "name": "Test Campaign",
        "channel": "google",
        "total_budget_cents": 10_000_000,
        "pacing_mode": "even",
        "start_date": "2026-10-01",
        "end_date": "2026-10-31",
        "currency": "INR",
    }
    payload.update(overrides)
    response = client.post("/api/v1/campaigns", json=payload)
    assert response.status_code == 201, response.text
    return response.json()
