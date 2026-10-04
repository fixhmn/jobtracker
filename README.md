# JobTracker

[![Tests](https://github.com/fixhmn/jobtracker/actions/workflows/tests.yml/badge.svg)](https://github.com/fixhmn/jobtracker/actions/workflows/tests.yml)

A small Telegram bot for keeping track of job applications. Save a job link, update its status, and set a reminder to follow up. The backend is FastAPI; the data lives in SQLite.

The local application and tests work. A real Telegram account still needs to be connected before using the bot day to day.

## Try it without Telegram

Python 3.11 or newer. Run these commands from this folder. On Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m scripts.demo
```

On macOS/Linux, replace `.\.venv\Scripts\python.exe` with `.venv/bin/python`.

The demo creates a made-up job, marks it Applied, runs the reminder worker with a fake Telegram sender, and completes the reminder. It uses `data/demo.db` and makes no network requests. It won't overwrite an existing demo database; use `--database data/demo-2.db` to run it again.

## Run the API

Copy `.env.example` to `.env`. Generate a key and put it in `API_KEY`:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --reload
```

Open http://127.0.0.1:8000/docs and click **Authorize** to enter the key. Create an application with:

```json
{
  "company": "Example Labs",
  "position": "Junior Python Developer",
  "url": "https://example.com/jobs/python-1",
  "location": "Austin, TX",
  "salary_min": 75000,
  "salary_max": 90000
}
```

This is a fictional company and job. All working endpoints require `X-API-Key`; `/health` is public. There is no public deployment or job-board scraping.

## Connect Telegram

1. Create a bot with Telegram's BotFather and add its token to `TELEGRAM_BOT_TOKEN` in `.env`.
2. Set `OWNER_TELEGRAM_ID` to your numeric user ID. If you don't know it, the discovery script below prints sender IDs of recent messages to your own bot.
3. Open a private chat with the bot and send `/start` before running the worker.
4. Keep the API running, then start these in separate terminals:

```powershell
.\.venv\Scripts\python.exe -m bot.main
.\.venv\Scripts\python.exe -m worker.main
```

The discovery command is `.\.venv\Scripts\python.exe -m scripts.telegram_id`. Run it before starting the polling bot; two processes must not call `getUpdates` for the same bot at once. It prints IDs only, not message contents.

| Command | What it does |
|---|---|
| `/new` | Save a job through a short form |
| `/list` or `/list Applied` | Browse jobs or filter by status |
| `/search Python` | Find saved jobs by company or title |
| `/view 1` | Open a job and change its status with buttons |
| `/edit 1` | Change a company, title, location, link, or notes |
| `/history 1` | Show the last 20 status changes |
| `/withdraw 1` | Mark a job as Withdrawn without deleting it or its reminders |
| `/remind 1` | Set a follow-up for job #1 |
| `/today` | Show today's and overdue unfinished reminders |
| `/reminders` or `/reminders failed` | Browse active reminders or filter by state |
| `/reschedule 1` | Change the time of reminder #1 |
| `/done 1` | Complete reminder #1 |
| `/stats` | Applications, first interviews, and first offers in the last 30 days |
| `/export` or `/export Applied` | Download saved jobs as CSV |
| `/cancel` | Discard the current form |

Only the configured owner can use the bot, and only in a private chat. Bot dates use `America/Chicago` by default. Ambiguous or nonexistent times during daylight saving changes are rejected. The API accepts timestamps with an explicit offset.

Editing a field replaces its contents; `/cancel` leaves it unchanged. Send `-` to clear notes or location. Reminder numbers are separate from job numbers. A failed reminder has a Retry delivery button; changing its time also gives it a fresh delivery attempt. Sending, cancelled, and completed reminders cannot be edited.

CSV exports include notes and links, so keep downloaded files private. They contain at most 5000 jobs; use a status filter for larger lists. Cells that could be interpreted as spreadsheet formulas are prefixed with an apostrophe. The API also serves exports at `GET /applications/export.csv` with the same API key.

## Docker

With `.env` configured:

```text
docker compose up --build -d
docker compose --profile telegram up --build -d
```

The first command starts just the API. The second starts the bot and worker too. The API port is bound to localhost and the database has its own volume. `docker compose down` preserves that volume; adding `-v` deletes it. Do not run a second polling bot outside Docker.

## Checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

Tests use temporary databases, a controlled clock, and fake Telegram replies. They cover bot forms, owner checks, search, history, editing, CSV exports, reminder retries and rescheduling, lease recovery, and Austin's daylight saving changes. One check starts a real local HTTP server. GitHub Actions runs these checks on pushes and pull requests.

## Markdown summary

With the API running and `.env` configured, generate a read-only report:

```powershell
.\.venv\Scripts\python.exe -m reports.summary --days 7 --output exports/summary.md
```

Omit `--output` to print it in the terminal. `--days` accepts 1–30 and includes overdue unfinished reminders too. The report shows current status counts and follow-ups in the selected window, not period conversions. Reads are paginated and capped at 5000 records per collection; they are not one atomic database snapshot. Existing output files are never overwritten.

Reports include company names, but not notes, job links, reminder text, or credentials. Keep them private; `exports/` is ignored by Git. No Telegram token is needed. The implementation lives in [`reports/`](reports/).

## Backups

For a locally running API:

```powershell
.\.venv\Scripts\python.exe -m scripts.backup data/jobtracker.db backups/jobtracker-2026-10-04.db
```

The command uses SQLite's backup API and checks the resulting file. It refuses to overwrite an existing backup. To restore locally, stop the API, bot, and worker; copy the backup to a new destination, point `DATABASE_PATH` at it, and restart. Keep the old database until you have checked the restored records.

For Docker, run the backup script in the API container, then copy the file out with `docker compose cp`. See [operations](docs/OPERATIONS.md).

## A few limits

- This is a single-user tool. Keys and tokens stay in `.env`; databases, exports, and backups stay out of Git.
- Sending a reminder doesn't mean the task is done. It stays in `/today` until completed or cancelled.
- Deliveries have five attempts at most. A crash after Telegram accepts a message but before success is recorded can cause a duplicate. Cancelling cannot retract a message already in flight.
- Draft forms are held in memory. Restarting the bot discards unfinished input, not saved jobs.
- The bot takes an annual USD salary range. Other currencies and hourly rates can be entered through the API.
- Salary and application dates can be corrected through the API; the bot's edit form handles the other job details. Long notes are shortened in Telegram cards but stored in full.
- Search returns the newest 10 matches. Status history shows the last 20 changes; older changes remain in the API. Reminder lists have pagination. SQLite's case-insensitive search is primarily suited to English company names and titles.

[Architecture](docs/ARCHITECTURE.md) · [Task list](TASKS.md) · [Specification](docs/SPEC.md) · [Development notes](docs/DEVELOPMENT.md)
