from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def test_authentication(app, client):
    with TestClient(app) as anonymous:
        assert anonymous.get("/health").status_code == 200
        assert anonymous.get("/applications").status_code == 401
        assert anonymous.get("/applications", headers={"X-API-Key": "wrong"}).status_code == 401


def test_url_normalization_duplicates_and_job_parameters(client, job):
    assert job["url"] == "https://example.com/jobs?id=1"
    duplicate = client.post(
        "/applications",
        json={
            "company": "Another name",
            "position": "Developer",
            "url": "https://EXAMPLE.com/jobs?id=1&utm_medium=email",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["application_id"] == job["id"]
    assert (
        client.post(
            "/applications",
            json={
                "company": "Another name",
                "position": "Developer",
                "url": "https://example.com/jobs?id=2",
            },
        ).status_code
        == 201
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"company": " "},
        {"url": "file:///tmp/job"},
        {"url": "https://user:pass@example.com"},
        {"url": "https://example.com:bad/jobs"},
        {"salary_min": 100, "salary_max": 50},
        {"salary_min": "100"},
        {"status": "Unknown"},
        {"applied_at": "2026-10-01T12:00:00"},
        {"unexpected": "value"},
    ],
)
def test_invalid_creation(client, changes):
    values = {"company": "Example", "position": "Developer", "url": "https://example.com"}
    assert client.post("/applications", json=values | changes).status_code == 422


def test_patch_history_and_applied_date(client, job, clock):
    path = f"/applications/{job['id']}"
    applied = client.patch(path, json={"status": "Applied"}).json()
    assert applied["applied_at"] == clock.now.isoformat(timespec="microseconds")
    clock.advance(days=3)
    interview = client.patch(path, json={"status": "Interview"}).json()
    assert interview["applied_at"] == applied["applied_at"]
    client.patch(path, json={"status": "Interview"})
    history = client.get(path + "/history").json()
    assert [item["new_status"] for item in history] == ["Saved", "Applied", "Interview"]
    # A partial change must still be checked against the stored salary range.
    assert client.patch(path, json={"salary_min": 95000}).status_code == 422
    assert client.get(path).json()["salary_min"] == 75000
    assert client.patch(path, json={"company": None}).status_code == 422


def test_filters_pagination_and_missing_records(client, job):
    client.post(
        "/applications",
        json={
            "company": "Second",
            "position": "Backend",
            "url": "https://example.com/2",
            "status": "Applied",
        },
    )
    assert client.get("/applications", params={"company": "example"}).json()["total"] == 1
    assert client.get("/applications", params={"q": "Python"}).json()["total"] == 1
    assert client.get("/applications", params={"q": "' OR 1=1 --"}).json()["total"] == 0
    assert client.get("/applications", params={"status": "Applied"}).json()["total"] == 1
    page = client.get("/applications", params={"limit": 1, "offset": 1}).json()
    assert page["total"] == 2 and page["items"][0]["id"] == job["id"]
    assert client.get("/applications", params={"limit": 0}).status_code == 422
    assert client.get("/applications/999").status_code == 404
    assert client.get("/applications/999/history").status_code == 404


def test_data_survives_restart(client, job, settings, clock):
    with TestClient(create_app(settings, clock), headers={"X-API-Key": settings.api_key}) as other:
        assert other.get(f"/applications/{job['id']}").json()["company"] == "Example Co"


def test_stats_count_first_interview_only(client, job, clock):
    start = clock.now - timedelta(days=1)
    path = f"/applications/{job['id']}"
    client.patch(path, json={"status": "Applied"})
    client.patch(path, json={"status": "Interview"})
    clock.advance(days=2)
    client.patch(path, json={"status": "Applied"})
    client.patch(path, json={"status": "Interview"})
    end = clock.now + timedelta(seconds=1)
    whole = client.get("/stats", params={"from": start.isoformat(), "to": end.isoformat()}).json()
    assert whole["applications"] == 1 and whole["interviews"] == 1
    recent = client.get(
        "/stats",
        params={
            "from": clock.now.isoformat(),
            "to": end.isoformat(),
        },
    ).json()
    assert recent["interviews"] == 0
    assert recent["current_statuses"] == {"Interview": 1}
    assert (
        client.get("/stats", params={"from": end.isoformat(), "to": start.isoformat()}).status_code
        == 422
    )
    assert client.get("/stats", params={"from": "2026-10-01T00:00:00"}).status_code == 422
