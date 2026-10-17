from __future__ import annotations

from datetime import date, timedelta

from tests.conftest import make_campaign

DAY = "2026-10-15"


def _spend(client, external_id: str, uid: str, cents: int, when: str = "2026-10-15T10:00:00+00:00"):
    return client.post(
        "/api/v1/spend",
        json={
            "event_uid": uid,
            "campaign_external_id": external_id,
            "amount_cents": cents,
            "occurred_at": when,
        },
    )


def test_create_campaign_returns_201_and_is_listed(acme_client):
    created = make_campaign(acme_client)
    assert created["external_id"] == "CMP-001"
    assert created["total_budget_cents"] == 10_000_000

    listed = acme_client.get("/api/v1/campaigns").json()
    assert [row["id"] for row in listed] == [created["id"]]


def test_duplicate_external_id_is_a_409(acme_client):
    make_campaign(acme_client)
    response = acme_client.post(
        "/api/v1/campaigns",
        json={
            "external_id": "CMP-001",
            "name": "Duplicate",
            "channel": "meta",
            "total_budget_cents": 1_000,
            "start_date": "2026-10-01",
            "end_date": "2026-10-02",
        },
    )
    assert response.status_code == 409


def test_flight_in_the_past_is_rejected(acme_client):
    response = acme_client.post(
        "/api/v1/campaigns",
        json={
            "external_id": "BAD-1",
            "name": "Bad flight",
            "channel": "google",
            "total_budget_cents": 1_000,
            "start_date": "2026-10-10",
            "end_date": "2026-10-01",
        },
    )
    assert response.status_code == 422


def test_unknown_field_is_rejected_rather_than_ignored(acme_client):
    response = acme_client.post(
        "/api/v1/campaigns",
        json={
            "external_id": "TYPO-1",
            "name": "Typo",
            "channel": "google",
            "budget_cents": 1_000,  # typo for total_budget_cents
            "start_date": "2026-10-01",
            "end_date": "2026-10-02",
        },
    )
    assert response.status_code == 422


def test_budget_change_is_audited(acme_client):
    campaign = make_campaign(acme_client)
    response = acme_client.patch(
        f"/api/v1/campaigns/{campaign['id']}", json={"total_budget_cents": 12_500_000}
    )
    assert response.status_code == 200
    assert response.json()["total_budget_cents"] == 12_500_000

    detail = acme_client.get(
        f"/api/v1/campaigns/{campaign['id']}", params={"as_of": DAY}
    ).json()
    assert len(detail["budget_changes"]) == 1
    change = detail["budget_changes"][0]
    assert change["action"] == "campaign.budget_change"
    assert change["before_value"] == "10000000"
    assert change["after_value"] == "12500000"


def test_spend_ingest_is_idempotent(acme_client):
    make_campaign(acme_client)

    first = _spend(acme_client, "CMP-001", "evt-1", 250_000)
    assert first.status_code == 201
    assert first.json() == {"accepted": 1, "duplicates": 0, "rejected": 0, "errors": []}

    second = _spend(acme_client, "CMP-001", "evt-1", 250_000)
    assert second.status_code == 201
    assert second.json()["accepted"] == 0
    assert second.json()["duplicates"] == 1


def test_batch_ingest_reports_mixed_results(acme_client):
    make_campaign(acme_client)
    response = acme_client.post(
        "/api/v1/spend/batch",
        json={
            "events": [
                {
                    "event_uid": "b-1",
                    "campaign_external_id": "CMP-001",
                    "amount_cents": 10_000,
                    "occurred_at": "2026-10-14T08:00:00Z",
                },
                {
                    "event_uid": "b-1",
                    "campaign_external_id": "CMP-001",
                    "amount_cents": 10_000,
                    "occurred_at": "2026-10-14T08:00:00Z",
                },
                {
                    "event_uid": "b-2",
                    "campaign_external_id": "NOT-A-CAMPAIGN",
                    "amount_cents": 5_000,
                    "occurred_at": "2026-10-14T08:00:00Z",
                },
            ]
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["accepted"] == 1
    assert body["duplicates"] == 1
    assert body["rejected"] == 1
    assert "NOT-A-CAMPAIGN" in body["errors"][0]


def test_spend_requires_timezone(acme_client):
    make_campaign(acme_client)
    response = acme_client.post(
        "/api/v1/spend",
        json={
            "event_uid": "naive-1",
            "campaign_external_id": "CMP-001",
            "amount_cents": 1_000,
            "occurred_at": "2026-10-14T08:00:00",
        },
    )
    assert response.status_code == 422


def test_overview_reports_tenant_totals(acme_client):
    make_campaign(acme_client)
    for day in range(1, 11):
        when = f"2026-10-{day:02d}T09:00:00+00:00"
        _spend(acme_client, "CMP-001", f"o-{day}", 300_000, when)

    body = acme_client.get("/api/v1/pacing/overview", params={"as_of": "2026-10-10"}).json()

    assert body["as_of"] == "2026-10-10"
    assert body["totals"]["campaigns"] == 1
    assert body["totals"]["total_budget_cents"] == 10_000_000
    assert body["totals"]["spent_to_date_cents"] == 3_000_000
    item = body["items"][0]
    assert item["flight_day"] == 10
    assert item["state"] == "on_track"  # target at day 10/31 is 3,225,806


def test_evaluate_creates_alerts_and_dedupes(acme_client):
    make_campaign(
        acme_client,
        external_id="PACE-1",
        name="Underpacing Campaign",
        total_budget_cents=1_000_000,
        start_date="2026-10-01",
        end_date="2026-10-10",
    )
    for day in range(1, 6):
        _spend(acme_client, "PACE-1", f"e-{day}", 60_000, f"2026-10-{day:02d}T09:00:00Z")

    first = acme_client.post("/api/v1/pacing/evaluate", params={"as_of": "2026-10-06"})
    assert first.status_code == 200
    assert first.json()["alerts_created"] >= 1

    alerts = acme_client.get("/api/v1/alerts", params={"open": True}).json()
    kinds = {alert["kind"] for alert in alerts}
    assert "UNDER_PACE" in kinds
    assert "DELIVERY_STALLED" in kinds  # no spend recorded on the 6th

    second = acme_client.post("/api/v1/pacing/evaluate", params={"as_of": "2026-10-06"})
    assert second.json()["alerts_created"] == 0
    assert second.json()["alerts_existing"] >= 1


def test_resolved_alert_reopens_when_condition_returns(acme_client):
    make_campaign(
        acme_client,
        external_id="PACE-2",
        name="Underpacing Again",
        total_budget_cents=1_000_000,
        start_date="2026-10-01",
        end_date="2026-10-10",
    )
    _spend(acme_client, "PACE-2", "r-1", 60_000, "2026-10-02T09:00:00Z")
    acme_client.post("/api/v1/pacing/evaluate", params={"as_of": "2026-10-03"})

    alert = next(
        row
        for row in acme_client.get("/api/v1/alerts").json()
        if row["kind"] == "UNDER_PACE"
    )
    resolved = acme_client.post(f"/api/v1/alerts/{alert['id']}/resolve")
    assert resolved.status_code == 200
    assert resolved.json()["resolved_at"] is not None

    acme_client.post("/api/v1/pacing/evaluate", params={"as_of": "2026-10-03"})
    reopened = acme_client.get("/api/v1/alerts").json()
    assert any(row["id"] == alert["id"] for row in reopened)


def test_campaign_detail_has_zero_filled_daily_series(acme_client):
    campaign = make_campaign(
        acme_client,
        external_id="SERIES-1",
        start_date="2026-10-01",
        end_date="2026-10-05",
    )
    _spend(acme_client, "SERIES-1", "s-1", 700_000, "2026-10-02T09:00:00Z")

    detail = acme_client.get(
        f"/api/v1/campaigns/{campaign['id']}", params={"as_of": "2026-10-05"}
    ).json()
    daily = detail["daily"]
    assert [point["day"] for point in daily] == [
        "2026-10-01",
        "2026-10-02",
        "2026-10-03",
        "2026-10-04",
        "2026-10-05",
    ]
    assert [point["spend_cents"] for point in daily] == [0, 700_000, 0, 0, 0]
    assert daily[-1]["target_cents"] == 10_000_000  # curve completes at flight end


def test_health_and_readiness(acme_client):
    assert acme_client.get("/healthz").json() == {"status": "ok"}
    assert acme_client.get("/readyz").status_code == 200

    metrics = acme_client.get("/metrics").text
    assert "http_requests_total" in metrics
    assert "http_request_duration_seconds_count" in metrics
