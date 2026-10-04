from datetime import datetime, time, timedelta
from html import escape
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.schemas import ApplicationFields, normalize_url
from app.time_utils import local_input, utc_now
from bot.formatting import STATUSES, card, reminder_buttons, reminder_text, status_buttons

HELP = (
    "Keep your applications here, and I'll remind you when it's time to follow up.\n\n"
    "/new — save a job\n/list — your saved jobs\n/list Applied — filter by status\n"
    "/search Python — find a job\n/edit 1 — change job details\n/history 1 — status changes\n"
    "/view 1 — open a job\n/remind 1 — set a reminder\n/today — things to follow up on\n"
    "/reminders — browse reminders\n/reminders failed — delivery problems\n"
    "/reschedule 1 — change a reminder's time\n"
    "/withdraw 1 — mark a job as withdrawn (keeps reminders)\n"
    "/done 1 — finish a reminder\n/stats — last 30 days\n/export — download jobs as CSV\n"
    "/cancel — stop the current form"
)


class NewJob(StatesGroup):
    company = State()
    position = State()
    url = State()
    location = State()
    salary = State()
    notes = State()
    confirm = State()


class NewReminder(StatesGroup):
    due = State()
    text = State()


def record_id(args):
    if args and args.strip().isdigit() and int(args) > 0:
        return int(args)
    return None


async def show_list(message, api, offset=0, status=None):
    params = {"offset": offset, "limit": 5}
    if status:
        params["status"] = status
    page = await api.request("GET", "/applications", params=params)
    if not page["items"]:
        await message.answer("Nothing here yet. Save your first job with /new.")
        return
    rows = []
    for job in page["items"]:
        label = f"#{job['id']} · {job['company']} — {job['position']} ({job['status']})"
        rows.append([InlineKeyboardButton(text=label[:100], callback_data=f"view:{job['id']}")])
    navigation = []
    if offset:
        navigation.append(
            InlineKeyboardButton(text="Previous", callback_data=f"page:{offset - 5}:{status or ''}")
        )
    if offset + 5 < page["total"]:
        navigation.append(
            InlineKeyboardButton(text="Next", callback_data=f"page:{offset + 5}:{status or ''}")
        )
    if navigation:
        rows.append(navigation)
    await message.answer(
        f"Your jobs · {page['total']} total",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


def make_router() -> Router:
    router = Router()

    @router.message(Command("start", "help"))
    async def help_message(message: Message):
        await message.answer(HELP)

    @router.message(Command("cancel"))
    async def cancel(message: Message, state: FSMContext):
        active = await state.get_state()
        await state.clear()
        await message.answer("Cancelled. Nothing was saved." if active else "No form is open.")

    @router.message(Command("new"))
    async def new(message: Message, state: FSMContext):
        await state.clear()
        await state.set_state(NewJob.company)
        await message.answer("Which company?\nYou can stop at any point with /cancel.")

    @router.message(Command("list"))
    async def list_jobs(message: Message, command: CommandObject, api):
        status = command.args.strip().title() if command.args else None
        if status and status not in STATUSES:
            await message.answer("Use a status: " + ", ".join(STATUSES))
            return
        await show_list(message, api, status=status)

    @router.message(Command("view"))
    async def view(message: Message, command: CommandObject, api):
        row_id = record_id(command.args)
        if row_id is None:
            await message.answer("Use /view followed by a job number, for example /view 1.")
            return
        job = await api.request("GET", f"/applications/{row_id}")
        await message.answer(card(job), reply_markup=status_buttons(row_id))

    async def begin_reminder(message, row_id, state, api, settings):
        job = await api.request("GET", f"/applications/{row_id}")
        await state.clear()
        await state.update_data(application_id=row_id)
        await state.set_state(NewReminder.due)
        example = utc_now().astimezone(ZoneInfo(settings.timezone)).date() + timedelta(days=1)
        await message.answer(
            f"When should I remind you about {escape(job['company'])}?\n"
            f"Use YYYY-MM-DD HH:MM, in {settings.timezone}. Example: {example} 09:00."
        )

    @router.message(Command("remind"))
    async def remind(message: Message, command: CommandObject, state: FSMContext, api, settings):
        row_id = record_id(command.args)
        if row_id is None:
            await message.answer("Use /remind followed by a job number, for example /remind 1.")
            return
        await begin_reminder(message, row_id, state, api, settings)

    @router.message(Command("today"))
    async def today(message: Message, api, settings):
        zone = ZoneInfo(settings.timezone)
        tomorrow = utc_now().astimezone(zone).date() + timedelta(days=1)
        end = datetime.combine(tomorrow, time.min, tzinfo=zone)
        page = await api.request(
            "GET",
            "/reminders",
            params={
                "active": "true",
                "due_before": end.isoformat(),
                "limit": 20,
            },
        )
        if not page["items"]:
            await message.answer("Nothing to follow up on today.")
            return
        for item in page["items"]:
            await message.answer(
                reminder_text(item, settings.timezone),
                reply_markup=reminder_buttons(item["id"], item["state"]),
            )
        if page["total"] > len(page["items"]):
            await message.answer(
                f"Showing the first 20 of {page['total']} reminders. "
                "Finish a few, then run /today again."
            )

    @router.message(Command("done"))
    async def done(message: Message, command: CommandObject, api):
        row_id = record_id(command.args)
        if row_id is None:
            await message.answer("Use /done followed by a reminder number, for example /done 1.")
            return
        await api.request("POST", f"/reminders/{row_id}/complete")
        await message.answer("Marked as done.")

    @router.message(Command("stats"))
    async def stats(message: Message, api):
        result = await api.request("GET", "/stats")
        lines = [
            "<b>Last 30 days</b>",
            f"Applications sent: {result['applications']}",
            f"First interviews: {result['interviews']}",
            f"First offers: {result['offers']}",
            "",
            "<b>Current statuses · all saved jobs</b>",
        ]
        lines.extend(
            f"{status}: {result['current_statuses'].get(status, 0)}" for status in STATUSES
        )
        await message.answer("\n".join(lines))

    @router.message(F.text.startswith("/"))
    async def unknown_command(message: Message):
        await message.answer("I don't know that command. Use /help, or /cancel to stop a form.")

    @router.message(NewJob.company, F.text)
    async def company(message: Message, state: FSMContext):
        value = message.text.strip()
        if not 1 <= len(value) <= 160:
            await message.answer("Enter a company name, up to 160 characters.")
            return
        await state.update_data(company=value)
        await state.set_state(NewJob.position)
        await message.answer("What's the job title?")

    @router.message(NewJob.position, F.text)
    async def position(message: Message, state: FSMContext):
        value = message.text.strip()
        if not 1 <= len(value) <= 160:
            await message.answer("Enter a job title, up to 160 characters.")
            return
        await state.update_data(position=value)
        await state.set_state(NewJob.url)
        await message.answer("Send the job link.")

    @router.message(NewJob.url, F.text)
    async def url(message: Message, state: FSMContext):
        try:
            value = normalize_url(message.text)
            if len(value) > 2048:
                raise ValueError("That link is too long.")
        except ValueError:
            await message.answer("That doesn't look like a job link. Use a full https:// URL.")
            return
        await state.update_data(url=value)
        await state.set_state(NewJob.location)
        await message.answer("Location? For example Austin, TX or Remote. Send - to skip.")

    @router.message(NewJob.location, F.text)
    async def location(message: Message, state: FSMContext):
        value = message.text.strip()
        if not value or len(value) > 160:
            await message.answer("Keep the location under 160 characters, or send - to skip.")
            return
        await state.update_data(location=None if value == "-" else value)
        await state.set_state(NewJob.salary)
        await message.answer("Annual salary range in USD? Use 75000-90000, or - to skip.")

    @router.message(NewJob.salary, F.text)
    async def salary(message: Message, state: FSMContext):
        text = message.text.strip()
        values = {}
        if text != "-":
            try:
                low, high = (int(n.strip()) for n in text.split("-"))
                if not 0 <= low <= high <= 10_000_000:
                    raise ValueError
                values = {"salary_min": low, "salary_max": high}
            except ValueError:
                await message.answer("Use a range like 75000-90000, or - to skip.")
                return
        await state.update_data(**values)
        await state.set_state(NewJob.notes)
        await message.answer("Any notes? Send - to skip.")

    @router.message(NewJob.notes, F.text)
    async def notes(message: Message, state: FSMContext):
        value = message.text.strip()
        if not value or len(value) > 2000:
            await message.answer("Keep notes under 2000 characters, or send - to skip.")
            return
        await state.update_data(notes=None if value == "-" else value)
        data = ApplicationFields.model_validate(await state.get_data()).model_dump(mode="json")
        await state.set_state(NewJob.confirm)
        preview = {"id": "new", **data}
        await message.answer(
            card(preview) + "\n\nSave this job?",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="Save job", callback_data="savejob"),
                        InlineKeyboardButton(text="Discard", callback_data="discardjob"),
                    ]
                ]
            ),
        )

    @router.message(NewJob.confirm)
    async def confirm_hint(message: Message):
        await message.answer("Use Save job or Discard above. /cancel also discards the draft.")

    @router.callback_query(F.data.in_({"savejob", "discardjob"}))
    async def save(callback: CallbackQuery, state: FSMContext, api):
        if await state.get_state() != NewJob.confirm.state:
            await callback.answer("This form is closed. Use /new for another job.")
            return
        if callback.data == "discardjob":
            await state.clear()
            await callback.answer()
            await callback.message.answer("Discarded. Nothing was saved.")
            return
        job = await api.request("POST", "/applications", json=await state.get_data())
        await state.clear()
        await callback.answer("Saved")
        await callback.message.answer(card(job), reply_markup=status_buttons(job["id"]))

    @router.message(NewReminder.due, F.text)
    async def reminder_due(message: Message, state: FSMContext, settings):
        try:
            due = local_input(message.text, settings.timezone)
            if due <= utc_now():
                raise ValueError("Pick a time in the future.")
        except ValueError as error:
            await message.answer("Use YYYY-MM-DD HH:MM. " + escape(str(error)))
            return
        await state.update_data(due_at=due.isoformat())
        await state.set_state(NewReminder.text)
        await message.answer(
            "What should I remind you to do? For example: follow up with the recruiter."
        )

    @router.message(NewReminder.text, F.text)
    async def reminder_body(message: Message, state: FSMContext, api):
        text = message.text.strip()
        if not 1 <= len(text) <= 500:
            await message.answer("Keep the reminder between 1 and 500 characters.")
            return
        data = await state.get_data()
        await api.request(
            "POST",
            f"/applications/{data['application_id']}/reminders",
            json={"text": text, "due_at": data["due_at"]},
        )
        await state.clear()
        await message.answer("Reminder set. You'll also find it in /today when it's due.")

    @router.callback_query(F.data.startswith("view:"))
    async def view_callback(callback: CallbackQuery, api):
        row_id = int(callback.data.split(":")[1])
        job = await api.request("GET", f"/applications/{row_id}")
        await callback.answer()
        await callback.message.answer(card(job), reply_markup=status_buttons(row_id))

    @router.callback_query(F.data.startswith("page:"))
    async def page_callback(callback: CallbackQuery, api):
        _, offset, status = callback.data.split(":")
        await callback.answer()
        await show_list(callback.message, api, int(offset), status or None)

    @router.callback_query(F.data.startswith("status:"))
    async def change_status(callback: CallbackQuery, api):
        _, row_id, status = callback.data.split(":")
        current = await api.request("GET", f"/applications/{int(row_id)}")
        if current["status"] == status:
            await callback.answer("Already set to " + status)
            return
        job = await api.request("PATCH", f"/applications/{int(row_id)}", json={"status": status})
        await callback.answer("Status updated")
        await callback.message.edit_text(card(job), reply_markup=status_buttons(job["id"]))

    @router.callback_query(F.data.startswith("remind:"))
    async def remind_callback(callback: CallbackQuery, state: FSMContext, api, settings):
        await callback.answer()
        await begin_reminder(
            callback.message, int(callback.data.split(":")[1]), state, api, settings
        )

    @router.callback_query(F.data.startswith("done:") | F.data.startswith("cancelreminder:"))
    async def finish_callback(callback: CallbackQuery, api):
        action, row_id = callback.data.split(":")
        path = "complete" if action == "done" else "cancel"
        await api.request("POST", f"/reminders/{int(row_id)}/{path}")
        await callback.answer("Done" if path == "complete" else "Cancelled")
        await callback.message.edit_reply_markup(reply_markup=None)

    @router.message()
    async def fallback(message: Message, state: FSMContext):
        if await state.get_state():
            await message.answer("Send a text message to continue, or /cancel to stop.")
        else:
            await message.answer("Use /new to save a job, or /help for the commands.")

    return router
