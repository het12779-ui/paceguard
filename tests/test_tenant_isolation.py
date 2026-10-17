"""Multi-tenancy is a security property, so it gets its own test module.

Three layers are checked:
1. API: a valid key for tenant B cannot read or mutate tenant A's rows.
2. Ingest: a tenant cannot post spend against another tenant's campaign.
3. Schema: every business table carries ``account_id`` - this catches the
   future mistake of adding a table and forgetting the tenant column.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from paceguard.config import Settings
from paceguard.db import Base
from paceguard.main import create_app
from tests.conftest import ACME_KEY, make_campaign


def test_cross_tenant_read_is_a_404(acme_client, nova_client):
    campaign = make_campaign(acme_client)

    response = nova_client.get(f"/api/v1/campaigns/{campaign['id']}")
    assert response.status_code == 404
    assert nova_client.get("/api/v1/campaigns").json() == []


def test_cross_tenant_update_is_a_404(acme_client, nova_client):
    campaign = make_campaign(acme_client)
    response = nova_client.patch(
        f"/api/v1/campaigns/{campaign['id']}", json={"total_budget_cents": 1}
    )
    assert response.status_code == 404


def test_cross_tenant_alert_resolution_is_a_404(acme_client, nova_client):
    make_campaign(
        acme_client,
        external_id="ISO-1",
        total_budget_cents=1_000_000,
        start_date="2026-10-01",
        end_date="2026-10-10",
    )
    acme_client.post(
        "/api/v1/spend",
        json={
            "event_uid": "iso-1",
            "campaign_external_id": "ISO-1",
            "amount_cents": 10_000,
            "occurred_at": "2026-10-02T09:00:00Z",
        },
    )
    acme_client.post("/api/v1/pacing/evaluate", params={"as_of": "2026-10-03"})
    alert = acme_client.get("/api/v1/alerts").json()[0]

    assert nova_client.post(f"/api/v1/alerts/{alert['id']}/resolve").status_code == 404


def test_spend_cannot_target_another_tenants_campaign(acme_client, nova_client):
    make_campaign(acme_client)
    response = nova_client.post(
        "/api/v1/spend",
        json={
            "event_uid": "cross-1",
            "campaign_external_id": "CMP-001",
            "amount_cents": 5_000,
            "occurred_at": "2026-10-05T09:00:00Z",
        },
    )
    assert response.status_code == 422
    assert "unknown campaign" in response.json()["detail"]


def test_unknown_api_key_is_rejected(client):
    response = client.get("/api/v1/campaigns", headers={"X-API-Key": "not-a-key"})
    assert response.status_code == 401


def test_missing_credentials_are_rejected(client):
    assert client.get("/api/v1/campaigns").status_code == 401


def test_demo_header_does_not_work_when_demo_mode_is_off(tenants):
    strict_app = create_app(Settings(demo_mode=False, seed_demo_data=False))
    with TestClient(strict_app) as strict_client:
        response = strict_client.get(
            "/api/v1/campaigns", headers={"X-Account-Id": str(tenants[0].id)}
        )
    assert response.status_code == 401


def test_demo_accounts_endpoint_hidden_when_demo_mode_off(tenants):
    strict_app = create_app(Settings(demo_mode=False, seed_demo_data=False))
    with TestClient(strict_app) as strict_client:
        assert strict_client.get("/api/v1/demo/accounts").json() == []


def test_every_business_table_has_an_account_column():
    exempt = {"accounts"}
    missing = [
        table.name
        for table in Base.metadata.sorted_tables
        if table.name not in exempt and "account_id" not in table.c
    ]
    assert missing == [], f"tables missing account_id: {missing}"
