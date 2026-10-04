# Development notes

## What changed in 0.2

The first version could save jobs and send follow-ups, but correcting a typo or finding an older application required opening the API. The bot now handles search, basic edits, status history, reminder lists, and CSV exports. Failed reminders can be retried after fixing chat access; reminders can also be moved to a new time.

No database migration was needed. These features use the existing tables and fields. Existing application records and reminder state remain in place.

## Why the code stays fairly plain

Most bot actions are regular functions with a few `if` checks. The edit form has an explicit list of five fields. Validation and message construction repeat in some handlers. This could be tidied up later, but a shared form framework would be harder to follow than the repetition it replaces.

`app/store.py` handles several kinds of records in one file. Splitting it into application and reminder modules is a reasonable next cleanup if more features are added. At the current size, the SQL is still easy to find.

The bot's salary form only accepts annual USD ranges. Search returns the first ten matches and asks for a narrower query. These are small-project compromises, not simulated bugs. Authentication, transactions, and reminder state checks are still enforced.

## Checks actually run

The local test suite covers API requests and Telegram-shaped updates without a real token. A separate runtime test starts Uvicorn and makes HTTP requests. Ruff checks imports and formatting. CSV tests include formula prefixes, quotes, and multiline notes.

The installed Starlette version emits a deprecation warning about the test client's httpx compatibility. Tests still pass; migrating the test client is a future dependency-maintenance task rather than an application failure.

Live Telegram delivery, a Docker build/run, and GitHub-hosted CI still need to be checked in their actual environments. No commit dates, production usage, or completed public release have been invented.
