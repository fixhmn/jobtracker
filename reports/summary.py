import argparse
import asyncio
from collections import Counter
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config import Settings
from app.time_utils import utc_now
from bot.api_client import ApiClient, ApiError


def cell(value):
    # Keep user text inside its table cell, rather than treating it as Markdown.
    text = " ".join(str(value).split())
    for character in ("\\", "`", "*", "_", "[", "]", "|", "~"):
        text = text.replace(character, "\\" + character)
    return escape(text)


async def fetch_pages(api, path, **params):
    rows = []
    while True:
        page = await api.request("GET", path, params={**params, "limit": 100, "offset": len(rows)})
        if page["total"] > 5000:
            raise ValueError("Reports are limited to 5000 records per collection.")
        rows.extend(page["items"])
        if len(rows) >= page["total"]:
            return rows
        if not page["items"]:
            raise ValueError("Records changed during report generation. Try again.")


def render_summary(jobs, reminders, now, timezone, days):
    zone = ZoneInfo(timezone)
    local_now = now.astimezone(zone)
    counts = Counter(job["status"] for job in jobs)
    lines = [
        "# JobTracker summary",
        "",
        f"Generated: {local_now:%Y-%m-%d %H:%M %Z}",
        "",
        "## Current application statuses",
        "",
        f"Total saved jobs: {len(jobs)}",
        "",
        "| Status | Jobs |",
        "|---|---:|",
    ]
    for status in ("Saved", "Applied", "Interview", "Offer", "Rejected", "Withdrawn"):
        lines.append(f"| {status} | {counts[status]} |")
    lines.extend(
        [
            "",
            f"## Unfinished follow-ups: overdue and next {days} days",
            "",
            "| Reminder | Company | Due | State | Overdue |",
            "|---|---|---|---|---|",
        ]
    )
    for item in sorted(
        reminders, key=lambda row: (datetime.fromisoformat(row["due_at"]), row["id"])
    ):
        due = datetime.fromisoformat(item["due_at"])
        local_due = due.astimezone(zone)
        lines.append(
            f"| #{item['id']} | {cell(item['company'])} | {local_due:%Y-%m-%d %H:%M %Z} "
            f"| {cell(item['state'])} | {'Yes' if due < now else 'No'} |"
        )
    if not reminders:
        lines.extend(["", "No unfinished follow-ups in this window."])
    lines.extend(
        [
            "",
            "This is a current snapshot, not a weekly conversion report. "
            "API reads are separate, so records may change while it is generated.",
            "Notes, job links, reminder text, and API credentials are not included. "
            "Company names are included; keep the report private.",
        ]
    )
    return "\n".join(lines) + "\n"


async def build_summary(api, settings, *, days=7, now=None):
    if not 1 <= days <= 30:
        raise ValueError("Choose between 1 and 30 days.")
    now = now or utc_now()
    jobs = await fetch_pages(api, "/applications")
    reminders = await fetch_pages(
        api, "/reminders", active="true", due_before=(now + timedelta(days=days)).isoformat()
    )
    return render_summary(jobs, reminders, now, settings.timezone, days)


async def run(args):
    settings = Settings.from_env()
    api = ApiClient(settings.api_base_url, settings.api_key)
    try:
        report = await build_summary(api, settings, days=args.days)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as file:
                file.write(report)
            print(f"Saved report to {args.output}")
        else:
            print(report, end="")
    finally:
        await api.close()


def main():
    parser = argparse.ArgumentParser(description="Create a read-only JobTracker Markdown summary.")
    parser.add_argument("--days", type=int, choices=range(1, 31), default=7)
    parser.add_argument(
        "--output", type=Path, help="New output file; existing files are not replaced"
    )
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except (ApiError, ValueError, OSError) as error:
        parser.exit(1, f"Could not create report: {error}\n")


if __name__ == "__main__":
    main()
