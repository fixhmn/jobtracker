from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.schemas import normalize_url
from app.time_utils import local_input, utc_now
from bot.formatting import STATUSES, card, reminder_buttons, reminder_text, status_buttons
from bot.handlers import record_id


class EditJob(StatesGroup):
    choose = State()
    value = State()


class MoveReminder(StatesGroup):
    due = State()


async def begin_edit(message, row_id, state, api):
    job = await api.request("GET", f"/applications/{row_id}")
    await state.clear()
    await state.update_data(edit_job_id=row_id)
    await state.set_state(EditJob.choose)
    rows = []
    # A plain list is enough for five fields; there is no dynamic form engine here.
    for field, label in [
        ("company", "Company"),
        ("position", "Job title"),
        ("location", "Location"),
        ("url", "Job link"),
        ("notes", "Notes"),
    ]:
        rows.append([InlineKeyboardButton(text=label, callback_data=f"editfield:{row_id}:{field}")])
    await message.answer(
        f"Edit {escape(job['company'])}: choose a field. /cancel stops the form.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


async def show_history(message, row_id, api, settings):
    job = await api.request("GET", f"/applications/{row_id}")
    history = await api.request("GET", f"/applications/{row_id}/history")
    lines = [f"<b>{escape(job['company'])} · status history</b>"]
    for item in history[-20:]:
        date = datetime.fromisoformat(item["changed_at"]).astimezone(ZoneInfo(settings.timezone))
        previous = item["previous_status"] or "Created"
        lines.append(f"{date:%b %d, %Y %H:%M %Z}: {previous} → {item['new_status']}")
    if len(history) > 20:
        lines.append("Showing the last 20 changes.")
    await message.answer("\n".join(lines))


async def show_reminders(message, api, settings, offset=0, filter_state=None):
    params = {"limit": 5, "offset": offset}
    if filter_state:
        params["state"] = filter_state
    else:
        params["active"] = "true"
    page = await api.request("GET", "/reminders", params=params)
    if not page["items"]:
        await message.answer("No reminders match that filter.")
        return
    for item in page["items"]:
        await message.answer(
            reminder_text(item, settings.timezone),
            reply_markup=reminder_buttons(item["id"], item["state"]),
        )
    rows = []
    if offset:
        rows.append(
            InlineKeyboardButton(
                text="Previous", callback_data=f"rempage:{offset - 5}:{filter_state or ''}"
            )
        )
    if offset + 5 < page["total"]:
        rows.append(
            InlineKeyboardButton(
                text="Next", callback_data=f"rempage:{offset + 5}:{filter_state or ''}"
            )
        )
    if rows:
        await message.answer(
            f"{offset + 1}–{offset + len(page['items'])} of {page['total']} reminders",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[rows]),
        )


async def begin_reschedule(message, row_id, state, api, settings):
    item = await api.request("GET", f"/reminders/{row_id}")
    if item["state"] in {"sending", "completed", "cancelled"}:
        await message.answer("That reminder is being sent or already finished. Create a new one.")
        return
    await state.clear()
    await state.update_data(move_reminder_id=row_id)
    await state.set_state(MoveReminder.due)
    example = utc_now().astimezone(ZoneInfo(settings.timezone)).date() + timedelta(days=1)
    await message.answer(
        f"New time for reminder #{row_id}? Use YYYY-MM-DD HH:MM in {settings.timezone}.\n"
        f"Example: {example} 09:00. /cancel keeps the current time."
    )


def make_management_router():
    router = Router()

    @router.message(Command("export"))
    async def export(message: Message, command: CommandObject, api):
        status = command.args.strip().title() if command.args else None
        if status and status not in STATUSES:
            await message.answer("Use /export, or a status such as /export Applied.")
            return
        content = await api.export_csv(status)
        await message.answer_document(
            BufferedInputFile(content, filename="applications.csv"),
            caption="Your saved jobs. This file includes your notes.",
        )

    @router.message(Command("search"))
    async def search(message: Message, command: CommandObject, api):
        query = command.args.strip() if command.args else ""
        if not query or len(query) > 160:
            await message.answer(
                "Use /search followed by a company or job title, like /search Python."
            )
            return
        page = await api.request("GET", "/applications", params={"q": query, "limit": 10})
        if not page["items"]:
            await message.answer("No matching jobs. Try a company name or a shorter job title.")
            return
        rows = []
        for job in page["items"]:
            text = f"#{job['id']} · {job['company']} — {job['position']}"
            rows.append([InlineKeyboardButton(text=text[:100], callback_data=f"view:{job['id']}")])
        count = page["total"]
        text = f"Found {count} jobs for “{escape(query)}”."
        if count > 10:
            text += " Showing the newest 10; narrow your search for more specific results."
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

    @router.message(Command("edit"))
    async def edit(message: Message, command: CommandObject, state: FSMContext, api):
        row_id = record_id(command.args)
        if row_id is None:
            await message.answer("Use /edit followed by a job number, for example /edit 1.")
            return
        await begin_edit(message, row_id, state, api)

    @router.callback_query(F.data.startswith("editjob:"))
    async def edit_callback(callback: CallbackQuery, state: FSMContext, api):
        await callback.answer()
        await begin_edit(callback.message, int(callback.data.split(":")[1]), state, api)

    @router.callback_query(F.data.startswith("editfield:"))
    async def select_field(callback: CallbackQuery, state: FSMContext, api):
        _, row_id, field = callback.data.split(":")
        data = await state.get_data()
        if await state.get_state() != EditJob.choose.state or data.get("edit_job_id") != int(
            row_id
        ):
            await callback.answer("This form is closed. Open /edit again.")
            return
        if field not in {"company", "position", "url", "location", "notes"}:
            await callback.answer("Unknown field.")
            return
        job = await api.request("GET", f"/applications/{row_id}")
        await state.update_data(edit_field=field)
        await state.set_state(EditJob.value)
        await callback.answer()
        current = job.get(field) or "Not set"
        prompt = f"Current {field}:\n{escape(current)}\n\nSend the replacement."
        if field in {"notes", "location"}:
            prompt += " Send - to clear it."
        await callback.message.answer(prompt)

    @router.message(EditJob.value, F.text, ~F.text.startswith("/"))
    async def save_field(message: Message, state: FSMContext, api):
        data = await state.get_data()
        field = data["edit_field"]
        value = message.text.strip()
        maximum = 2000 if field == "notes" else 2048 if field == "url" else 160
        if not value or len(value) > maximum:
            await message.answer(f"Enter between 1 and {maximum} characters, or use /cancel.")
            return
        if field == "url":
            try:
                value = normalize_url(value)
            except ValueError:
                await message.answer("Use a full http:// or https:// job link.")
                return
        if field in {"notes", "location"} and value == "-":
            value = None
        row_id = data["edit_job_id"]
        job = await api.request("PATCH", f"/applications/{row_id}", json={field: value})
        await state.clear()
        await message.answer("Updated.\n\n" + card(job), reply_markup=status_buttons(row_id))

    @router.message(EditJob.choose, F.text, ~F.text.startswith("/"))
    async def choose_hint(message: Message):
        await message.answer("Choose a field using the buttons above, or /cancel.")

    @router.message(Command("history"))
    async def history(message: Message, command: CommandObject, api, settings):
        row_id = record_id(command.args)
        if row_id is None:
            await message.answer("Use /history followed by a job number, for example /history 1.")
            return
        await show_history(message, row_id, api, settings)

    @router.callback_query(F.data.startswith("history:"))
    async def history_callback(callback: CallbackQuery, api, settings):
        await callback.answer()
        await show_history(callback.message, int(callback.data.split(":")[1]), api, settings)

    @router.message(Command("reminders"))
    async def reminders(message: Message, command: CommandObject, api, settings):
        filter_state = command.args.strip().lower() if command.args else None
        if filter_state and filter_state not in {
            "pending",
            "sending",
            "sent",
            "failed",
            "completed",
            "cancelled",
        }:
            await message.answer("Use /reminders, or a state such as /reminders failed.")
            return
        await show_reminders(message, api, settings, filter_state=filter_state)

    @router.callback_query(F.data.startswith("rempage:"))
    async def reminder_page(callback: CallbackQuery, api, settings):
        _, offset, filter_state = callback.data.split(":")
        await callback.answer()
        await show_reminders(callback.message, api, settings, int(offset), filter_state or None)

    @router.message(Command("reschedule"))
    async def reschedule(
        message: Message, command: CommandObject, state: FSMContext, api, settings
    ):
        row_id = record_id(command.args)
        if row_id is None:
            await message.answer(
                "Use /reschedule followed by a reminder number, like /reschedule 1."
            )
            return
        await begin_reschedule(message, row_id, state, api, settings)

    @router.callback_query(F.data.startswith("reschedule:"))
    async def reschedule_callback(callback: CallbackQuery, state: FSMContext, api, settings):
        await callback.answer()
        await begin_reschedule(
            callback.message, int(callback.data.split(":")[1]), state, api, settings
        )

    @router.message(MoveReminder.due, F.text, ~F.text.startswith("/"))
    async def save_time(message: Message, state: FSMContext, api, settings):
        try:
            due = local_input(message.text, settings.timezone)
            if due <= utc_now():
                raise ValueError("Pick a time in the future.")
        except ValueError as error:
            await message.answer("Use YYYY-MM-DD HH:MM. " + escape(str(error)))
            return
        data = await state.get_data()
        row_id = data["move_reminder_id"]
        await api.request("PATCH", f"/reminders/{row_id}", json={"due_at": due.isoformat()})
        await state.clear()
        await message.answer("Reminder moved. Its text hasn't changed.")

    @router.callback_query(F.data.startswith("retry:"))
    async def retry(callback: CallbackQuery, api, settings):
        row_id = int(callback.data.split(":")[1])
        await api.request("POST", f"/reminders/{row_id}/retry")
        item = await api.request("GET", f"/reminders/{row_id}")
        await callback.answer("Queued for another attempt")
        await callback.message.edit_text(
            reminder_text(item, settings.timezone),
            reply_markup=reminder_buttons(row_id, item["state"]),
        )

    return router
