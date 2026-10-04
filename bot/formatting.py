from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

STATUSES = ("Saved", "Applied", "Interview", "Offer", "Rejected", "Withdrawn")


def card(job):
    lines = [
        f"<b>#{job['id']} · {escape(job['company'])}</b>",
        escape(job["position"]),
        f"Status: {job['status']}",
    ]
    if job.get("location"):
        lines.append(escape(job["location"]))
    if job.get("salary_min") is not None or job.get("salary_max") is not None:
        low = f"{job['salary_min']:,}" if job.get("salary_min") is not None else "?"
        high = f"{job['salary_max']:,}" if job.get("salary_max") is not None else "?"
        lines.append(
            f"{low}–{high} {job.get('currency', 'USD')} / {job.get('salary_period', 'annual')}"
        )
    lines.append(escape(job["url"]))
    if job.get("notes"):
        notes = job["notes"]
        if len(notes) > 1000:
            notes = notes[:1000] + "… (full notes are available through the API)"
        lines.extend(["", escape(notes)])
    return "\n".join(lines)


def status_buttons(row_id):
    buttons = [
        InlineKeyboardButton(text=status, callback_data=f"status:{row_id}:{status}")
        for status in STATUSES
    ]
    rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    rows.append([InlineKeyboardButton(text="Set reminder", callback_data=f"remind:{row_id}")])
    rows.append(
        [
            InlineKeyboardButton(text="Edit details", callback_data=f"editjob:{row_id}"),
            InlineKeyboardButton(text="Status history", callback_data=f"history:{row_id}"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reminder_buttons(row_id, state="sent"):
    if state in {"completed", "cancelled"}:
        return None
    rows = [
        [
            InlineKeyboardButton(text="Done", callback_data=f"done:{row_id}"),
            InlineKeyboardButton(text="Cancel reminder", callback_data=f"cancelreminder:{row_id}"),
        ]
    ]
    if state != "sending":
        rows.append(
            [InlineKeyboardButton(text="Change time", callback_data=f"reschedule:{row_id}")]
        )
    if state == "failed":
        rows.append([InlineKeyboardButton(text="Retry delivery", callback_data=f"retry:{row_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reminder_text(reminder, timezone):
    due = datetime.fromisoformat(reminder["due_at"]).astimezone(ZoneInfo(timezone))
    state = "due" if reminder["state"] == "sending" else reminder["state"]
    result = (
        f"<b>#{reminder['id']} · {escape(reminder['company'])}</b>\n"
        f"{escape(reminder['position'])}\n"
        f"{escape(reminder['text'])}\n"
        f"{due:%b %d, %H:%M %Z} · {state}"
    )
    if reminder.get("last_error"):
        result += "\nLast delivery: " + escape(reminder["last_error"])
    return result
