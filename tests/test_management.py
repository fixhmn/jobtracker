import csv
import io
from datetime import timedelta

import pytest
from aiogram.methods import SendDocument

from app.export import safe_cell


def reminder(client, job, clock):
    return client.post(
        f"/applications/{job['id']}/reminders",
        json={
            "text": "Follow up",
            "due_at": clock.now.isoformat(),
        },
    ).json()


def test_reschedule_sent_reminder(client, job, clock):
    row = reminder(client, job, clock)
    path = f"/reminders/{row['id']}"
    item = client.post("/internal/reminders/claim").json()[0]
    client.post(
        f"/internal/reminders/{row['id']}/delivery",
        json={
            "lease_token": item["lease_token"],
            "success": True,
        },
    )
    assert client.get(path).json()["state"] == "sent"
    future = clock.now + timedelta(days=1)
    updated = client.patch(path, json={"due_at": future.isoformat()}).json()
    assert updated["state"] == "pending" and updated["attempt_count"] == 0
    assert updated["delivered_at"] is None and updated["text"] == "Follow up"
    assert client.post("/internal/reminders/claim").json() == []
    clock.advance(days=1)
    assert client.post("/internal/reminders/claim").json()[0]["id"] == row["id"]


@pytest.mark.parametrize("state", ["sending", "completed", "cancelled"])
def test_editing_active_claim_or_finished_reminder_is_rejected(client, job, clock, state):
    row = reminder(client, job, clock)
    if state == "sending":
        client.post("/internal/reminders/claim")
    else:
        client.post(f"/reminders/{row['id']}/{'complete' if state == 'completed' else 'cancel'}")
    response = client.patch(
        f"/reminders/{row['id']}",
        json={
            "due_at": (clock.now + timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 409
    assert client.get(f"/reminders/{row['id']}").json()["state"] == state


@pytest.mark.parametrize(
    "patch",
    [
        {},
        {"text": None},
        {"due_at": None},
        {"text": " "},
        {"due_at": "2026-10-05T09:00:00"},
        {"state": "pending"},
    ],
)
def test_invalid_reminder_changes(client, job, clock, patch):
    row = reminder(client, job, clock)
    assert client.patch(f"/reminders/{row['id']}", json=patch).status_code == 422


def test_reminder_retry_and_job_filter(client, job, clock):
    row = reminder(client, job, clock)
    assert client.post(f"/reminders/{row['id']}/retry").status_code == 409
    item = client.post("/internal/reminders/claim").json()[0]
    client.post(
        f"/internal/reminders/{row['id']}/delivery",
        json={
            "lease_token": item["lease_token"],
            "success": False,
            "permanent": True,
            "error": "No access",
        },
    )
    retried = client.post(f"/reminders/{row['id']}/retry").json()
    assert retried["state"] == "pending" and retried["last_error"] is None
    assert retried["attempt_count"] == 0
    assert client.get("/reminders", params={"application_id": job["id"]}).json()["total"] == 1
    assert client.get("/reminders", params={"application_id": 999}).json()["total"] == 0
    assert client.get("/reminders/999").status_code == 404
    assert client.post("/internal/reminders/claim").json()[0]["id"] == row["id"]


def test_text_edit_does_not_change_schedule_and_past_time_rejected(client, job, clock):
    row = reminder(client, job, clock)
    path = f"/reminders/{row['id']}"
    changed = client.patch(path, json={"text": "Prepare interview questions"}).json()
    assert changed["due_at"] == row["due_at"] and changed["text"] == "Prepare interview questions"
    assert client.patch(path, json={"due_at": clock.now.isoformat()}).status_code == 422
    assert client.get(path).json()["text"] == "Prepare interview questions"


def test_csv_export_round_trip_and_filter(client, job):
    client.patch(f"/applications/{job['id']}", json={"notes": '=HYPERLINK("bad")\nsecond line'})
    response = client.get("/applications/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["cache-control"] == "no-store"
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert len(rows) == 1 and rows[0]["company"] == job["company"]
    assert rows[0]["notes"].startswith("'=HYPERLINK") and "\nsecond line" in rows[0]["notes"]
    filtered = client.get("/applications/export.csv", params={"status": "Applied"})
    assert list(csv.DictReader(io.StringIO(filtered.content.decode("utf-8-sig")))) == []


@pytest.mark.parametrize("value", ["=1+1", "+cmd", "-cmd", "@SUM(1)", "  =1", "\tvalue", "\nvalue"])
def test_csv_formula_prefixes_are_neutralized(value):
    assert safe_cell(value).startswith("'")


async def test_bot_search_edit_and_history(bot_setup, client, job):
    send, session = bot_setup
    await send("/search Python")
    assert "Found 1" in session.calls[-1].text
    await send(f"/edit {job['id']}")
    await send(callback=f"editfield:{job['id']}:notes")
    await send("Ask about <remote> days")
    assert client.get(f"/applications/{job['id']}").json()["notes"] == "Ask about <remote> days"
    assert "&lt;remote&gt;" in session.calls[-1].text
    await send(f"/history {job['id']}")
    assert "Created → Saved" in session.calls[-1].text
    await send(callback=f"history:{job['id']}")
    assert "status history" in session.calls[-1].text


async def test_bot_edit_cancel_stale_button_and_clear(bot_setup, client, job):
    send, session = bot_setup
    await send(f"/edit {job['id']}")
    await send(callback=f"editfield:{job['id']}:company")
    await send("/cancel")
    assert client.get(f"/applications/{job['id']}").json()["company"] == job["company"]
    await send(callback=f"editfield:{job['id']}:company")
    assert "form is closed" in session.calls[-1].text
    await send(f"/edit {job['id']}")
    await send(callback=f"editfield:{job['id']}:location")
    await send("-")
    assert client.get(f"/applications/{job['id']}").json()["location"] is None


async def test_bot_failed_reminder_retry_and_reschedule(bot_setup, client, job, clock, monkeypatch):
    import bot.manage

    monkeypatch.setattr(bot.manage, "utc_now", clock)
    row = reminder(client, job, clock)
    item = client.post("/internal/reminders/claim").json()[0]
    client.post(
        f"/internal/reminders/{row['id']}/delivery",
        json={
            "lease_token": item["lease_token"],
            "success": False,
            "permanent": True,
            "error": "No access",
        },
    )
    send, session = bot_setup
    await send("/reminders failed")
    assert "No access" in session.calls[-1].text
    await send(callback=f"retry:{row['id']}")
    assert client.get(f"/reminders/{row['id']}").json()["state"] == "pending"
    await send(f"/reschedule {row['id']}")
    await send("2026-10-05 09:00")
    updated = client.get(f"/reminders/{row['id']}").json()
    assert updated["due_at"].startswith("2026-10-05T14:00")
    assert updated["text"] == "Follow up"


async def test_bot_exports_only_to_owner(bot_setup, client, job):
    send, session = bot_setup
    await send("/export", user_id=999)
    assert not session.calls
    await send("/export")
    assert isinstance(session.calls[-1], SendDocument)
    content = session.calls[-1].document.data.decode("utf-8-sig")
    assert job["company"] in content


async def test_reminder_pagination_has_no_duplicate_items(bot_setup, client, job, clock):
    for index in range(6):
        client.post(
            f"/applications/{job['id']}/reminders",
            json={
                "text": f"Reminder {index}",
                "due_at": clock.now.isoformat(),
            },
        )
    send, session = bot_setup
    await send("/reminders")
    first_texts = [getattr(call, "text", "") for call in session.calls]
    assert sum("Reminder " in text for text in first_texts) == 5
    await send(callback="rempage:5:")
    assert "Reminder 5" in session.calls[-2].text
