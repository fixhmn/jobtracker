import argparse
import asyncio
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.time_utils import utc_now
from bot.api_client import ApiClient
from worker.main import deliver_one


class DemoTelegram:
    async def send_message(self, chat_id, text, **kwargs):
        print("\nTelegram preview (not sent):\n" + text)


async def run_demo(path: Path):
    if path.exists():
        raise ValueError("Demo database already exists. Choose a new --database path.")
    settings = Settings(
        api_key="offline-demo-" + "x" * 24, database_path=path, owner_telegram_id=123
    )
    app = create_app(settings)
    with TestClient(app, headers={"X-API-Key": settings.api_key}) as client:
        response = client.post(
            "/applications",
            json={
                "company": "Example Labs",
                "position": "Junior Python Developer",
                "url": "https://example.com/jobs/python-1",
                "location": "Austin, TX",
                "salary_min": 75000,
                "salary_max": 90000,
                "notes": "Synthetic demo job",
            },
        )
        response.raise_for_status()
        job = response.json()
        row_id = job["id"]
        client.patch(f"/applications/{row_id}", json={"status": "Applied"}).raise_for_status()
        reminder = client.post(
            f"/applications/{row_id}/reminders",
            json={
                "text": "Follow up about the application",
                "due_at": utc_now().isoformat(),
            },
        )
        reminder.raise_for_status()
        reminder_id = reminder.json()["id"]
        api = ApiClient("http://demo", settings.api_key, transport=httpx.ASGITransport(app=app))
        try:
            await deliver_one(api, DemoTelegram(), settings)
        finally:
            await api.close()
        completed = client.post(f"/reminders/{reminder_id}/complete")
        completed.raise_for_status()
        print(f"\nJob #{row_id}: Applied; reminder #{reminder_id}: {completed.json()['state']}")
        print(f"Demo data saved to {path}. No network calls or Telegram token were used.")


def main():
    parser = argparse.ArgumentParser(description="Run the application-to-reminder flow offline")
    parser.add_argument("--database", type=Path, default=Path("data/demo.db"))
    args = parser.parse_args()
    try:
        asyncio.run(run_demo(args.database))
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
