from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock

import httpx
import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import SendMessage

from app.main import create_app
from app.time_utils import local_input
from bot.api_client import ApiClient
from worker.main import deliver_one


def new_reminder(client, job, clock):
    response = client.post(
        f"/applications/{job['id']}/reminders",
        json={
            "text": "Follow up with recruiter",
            "due_at": clock.now.isoformat(),
        },
    )
    assert response.status_code == 201
    return response.json()


def test_reminder_validation_and_foreign_key(client, clock):
    payload = {"text": "Follow up", "due_at": clock.now.isoformat()}
    assert client.post("/applications/999/reminders", json=payload).status_code == 404
    payload["due_at"] = "2026-10-04T09:00:00"
    assert client.post("/applications/999/reminders", json=payload).status_code == 422


def test_claim_success_and_completion(client, job, clock):
    reminder = new_reminder(client, job, clock)
    claimed = client.post("/internal/reminders/claim").json()
    assert len(claimed) == 1
    assert client.post("/internal/reminders/claim").json() == []
    delivered = client.post(
        f"/internal/reminders/{reminder['id']}/delivery",
        json={
            "lease_token": claimed[0]["lease_token"],
            "success": True,
        },
    ).json()
    assert delivered["state"] == "sent"
    assert delivered["completed_at"] is None
    assert client.get("/reminders", params={"active": True}).json()["total"] == 1
    assert client.post(f"/reminders/{reminder['id']}/complete").json()["state"] == "completed"
    assert client.post(f"/reminders/{reminder['id']}/complete").status_code == 200
    assert client.get("/reminders", params={"active": True}).json()["total"] == 0


def test_cancel_invalidates_claim(client, job, clock):
    reminder = new_reminder(client, job, clock)
    item = client.post("/internal/reminders/claim").json()[0]
    client.post(f"/reminders/{reminder['id']}/cancel")
    assert (
        client.post(
            f"/internal/reminders/{reminder['id']}/delivery",
            json={
                "lease_token": item["lease_token"],
                "success": True,
            },
        ).status_code
        == 409
    )
    clock.advance(minutes=3)
    assert client.post("/internal/reminders/claim").json() == []


def test_claim_recovery_and_stale_worker(client, app, job, clock, settings):
    reminder = new_reminder(client, job, clock)
    old = client.post("/internal/reminders/claim").json()[0]
    clock.advance(minutes=3)
    # Restarting the API doesn't lose leased records.
    restarted = create_app(settings, clock)
    item = restarted.state.store.claim_reminders(clock())[0]
    assert item["id"] == reminder["id"] and item["lease_token"] != old["lease_token"]
    assert (
        client.post(
            f"/internal/reminders/{reminder['id']}/delivery",
            json={
                "lease_token": old["lease_token"],
                "success": True,
            },
        ).status_code
        == 409
    )


def test_two_claims_do_not_get_same_reminder(client, app, job, clock):
    new_reminder(client, job, clock)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: app.state.store.claim_reminders(clock()), range(2)))
    assert sorted(len(items) for items in claims) == [0, 1]


def test_bounded_retries(client, job, clock):
    reminder = new_reminder(client, job, clock)
    for attempt in range(1, 6):
        item = client.post("/internal/reminders/claim").json()[0]
        result = client.post(
            f"/internal/reminders/{reminder['id']}/delivery",
            json={
                "lease_token": item["lease_token"],
                "success": False,
                "error": "Network unavailable",
            },
        ).json()
        assert result["attempt_count"] == attempt
        assert result["state"] == ("failed" if attempt == 5 else "pending")
        assert client.post("/internal/reminders/claim").json() == []
        clock.advance(hours=1)
    assert client.post("/internal/reminders/claim").json() == []


@pytest.mark.parametrize(
    "text,expected",
    [
        ("2026-10-12 09:00", "2026-10-12T14:00:00+00:00"),
        ("2026-12-12 09:00", "2026-12-12T15:00:00+00:00"),
    ],
)
def test_austin_time(text, expected):
    assert local_input(text, "America/Chicago").isoformat() == expected


@pytest.mark.parametrize("text", ["2026-03-08 02:30", "2026-11-01 01:30", "not a date"])
def test_dst_gap_overlap_and_invalid_date(text):
    with pytest.raises(ValueError):
        local_input(text, "America/Chicago")


@pytest.mark.parametrize(
    "failure,state,error",
    [
        (None, "sent", None),
        (
            TelegramNetworkError(method=SendMessage(chat_id=123, text="test"), message="Offline"),
            "pending",
            "Telegram is temporarily unavailable",
        ),
        (
            TelegramBadRequest(
                method=SendMessage(chat_id=123, text="test"), message="Invalid chat"
            ),
            "failed",
            "Telegram rejected the message; check chat access",
        ),
        (
            TelegramRetryAfter(
                method=SendMessage(chat_id=123, text="test"), message="Slow down", retry_after=60
            ),
            "pending",
            "Telegram rate limit",
        ),
    ],
)
async def test_worker_with_mock_telegram(client, app, settings, job, clock, failure, state, error):
    new_reminder(client, job, clock)
    api = ApiClient("http://test", settings.api_key, transport=httpx.ASGITransport(app=app))
    bot = AsyncMock()
    bot.send_message.side_effect = failure
    try:
        assert await deliver_one(api, bot, settings)
        row = client.get("/reminders").json()["items"][0]
        assert row["state"] == state and row["last_error"] == error
        if not failure:
            assert not await deliver_one(api, bot, settings)
            bot.send_message.assert_awaited_once()
    finally:
        await api.close()
