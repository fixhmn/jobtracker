from datetime import UTC, datetime, timedelta

import httpx
import pytest
from aiogram.methods import AnswerCallbackQuery

from bot.api_client import ApiClient, ApiError
from bot.formatting import card


async def test_new_job_status_and_reminder_flow(bot_setup, client):
    send, session = bot_setup
    for text in [
        "/new",
        "Example & Co",
        "Python Developer",
        "bad-link",
        "https://example.com/job",
        "Austin, TX",
        "-",
        "Follow up next week",
    ]:
        await send(text)
    assert client.get("/applications").json()["total"] == 0
    await send(callback="savejob")
    job = client.get("/applications").json()["items"][0]
    assert job["company"] == "Example & Co"
    await send(callback=f"status:{job['id']}:Applied")
    assert client.get(f"/applications/{job['id']}").json()["status"] == "Applied"
    await send(f"/remind {job['id']}")
    # Pick a future winter date, away from DST transitions.
    future = datetime.now(UTC) + timedelta(days=400)
    await send(future.strftime("%Y-%m-%d 12:00"))
    await send("Check for an answer")
    reminders = client.get("/reminders").json()["items"]
    assert len(reminders) == 1 and reminders[0]["text"] == "Check for an answer"
    await send(callback=f"done:{reminders[0]['id']}")
    assert client.get("/reminders").json()["items"][0]["state"] == "completed"
    assert any("Example &amp; Co" in getattr(call, "text", "") for call in session.calls)


async def test_owner_only_and_private_chat(bot_setup, client):
    send, session = bot_setup
    await send("/new", user_id=999)
    await send(callback="status:1:Applied", user_id=999)
    await send("/new", chat_type="group")
    assert len(session.calls) == 1  # Only the rejected callback gets an acknowledgement.
    assert client.get("/applications").json()["total"] == 0


async def test_cancel_and_stale_save_button(bot_setup, client):
    send, _ = bot_setup
    await send("/new")
    await send("Example")
    await send("/cancel")
    await send(callback="savejob")
    assert client.get("/applications").json()["total"] == 0


async def test_today_keeps_sent_reminders_until_done(bot_setup, client, job, clock, monkeypatch):
    import bot.handlers

    monkeypatch.setattr(bot.handlers, "utc_now", clock)
    reminder = client.post(
        f"/applications/{job['id']}/reminders",
        json={
            "text": "Follow up today",
            "due_at": clock.now.isoformat(),
        },
    ).json()
    item = client.post("/internal/reminders/claim").json()[0]
    client.post(
        f"/internal/reminders/{reminder['id']}/delivery",
        json={
            "lease_token": item["lease_token"],
            "success": True,
        },
    )
    send, session = bot_setup
    await send("/today")
    assert "Follow up today" in session.calls[-1].text
    await send(f"/done {reminder['id']}")
    await send("/today")
    assert "Nothing to follow up" in session.calls[-1].text


async def test_repeating_status_button_is_harmless(bot_setup, client, job):
    send, session = bot_setup
    await send(callback=f"status:{job['id']}:Saved")
    assert isinstance(session.calls[-1], AnswerCallbackQuery)
    assert "Already set" in session.calls[-1].text
    assert len(client.get(f"/applications/{job['id']}/history").json()) == 1


async def test_api_client_network_error():
    def offline(request):
        raise httpx.ConnectError("Offline", request=request)

    api = ApiClient("http://test", "test", transport=httpx.MockTransport(offline))
    try:
        with pytest.raises(ApiError, match="Can't reach"):
            await api.request("GET", "/applications")
    finally:
        await api.close()


def test_user_text_is_escaped():
    result = card(
        {
            "id": 1,
            "company": "<script>",
            "position": "A & B",
            "status": "Saved",
            "url": "https://example.com",
            "notes": "<b>not markup</b>",
        }
    )
    assert "&lt;script&gt;" in result and "A &amp; B" in result
    assert "&lt;b&gt;not markup&lt;/b&gt;" in result
