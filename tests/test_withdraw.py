import pytest


async def test_withdraw_records_history_and_keeps_reminders(bot_setup, client, job, clock):
    reminder = client.post(
        f"/applications/{job['id']}/reminders",
        json={"text": "Check response", "due_at": clock.now.isoformat()},
    ).json()
    client.patch(f"/applications/{job['id']}", json={"company": "Example <Co>"})
    send, session = bot_setup
    await send(f"/withdraw {job['id']}")
    assert "Example &lt;Co&gt;" in session.calls[-1].text
    assert "Reminders are unchanged" in session.calls[-1].text
    assert client.get(f"/applications/{job['id']}").json()["status"] == "Withdrawn"
    history = client.get(f"/applications/{job['id']}/history").json()
    assert history[-1]["new_status"] == "Withdrawn"
    await send(f"/withdraw {job['id']}")
    assert client.get(f"/applications/{job['id']}/history").json() == history
    assert client.get(f"/reminders/{reminder['id']}").json()["state"] == "pending"


@pytest.mark.parametrize("command", ["/withdraw", "/withdraw 0", "/withdraw nope"])
async def test_withdraw_requires_valid_id(bot_setup, client, job, command):
    send, session = bot_setup
    await send(command)
    assert "Use /withdraw" in session.calls[-1].text
    assert client.get(f"/applications/{job['id']}").json()["status"] == "Saved"


async def test_withdraw_rejects_other_users_and_missing_jobs(bot_setup, client, job):
    send, session = bot_setup
    await send(f"/withdraw {job['id']}", user_id=999)
    assert not session.calls
    assert client.get(f"/applications/{job['id']}").json()["status"] == "Saved"
    await send("/withdraw 999")
    assert client.get(f"/applications/{job['id']}").json()["status"] == "Saved"
    assert session.calls
