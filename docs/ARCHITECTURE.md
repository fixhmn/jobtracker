# How it fits together

```text
Telegram user → bot → FastAPI → SQLite
                     ↑
Telegram user ← worker
```

The bot handles conversations and calls the API. The worker asks the API for due reminders and sends them through Telegram. Neither process opens the database. This keeps the rules for status changes and reminders in one place.

## Why SQLite

This is one person's application tracker, so a separate database server would add setup without much benefit. SQL is written explicitly, values are bound as parameters, and each operation opens a short-lived connection. WAL mode allows readers while a writer is active. Writes use `BEGIN IMMEDIATE`, with a five-second busy timeout. A busy database returns 503 rather than silently losing an operation.

Schema version 1 is installed transactionally on first startup. There are no automatic migrations beyond that initial version yet. A newer schema version is rejected rather than opened by older code.

## Status changes

The current status is stored on the application; each change gets a history row in the same transaction. Setting the same status again adds no history. `applied_at` is retained when progressing through interviews and offers. A user can correct it explicitly through the API.

Stats count applications by `applied_at` and interviews/offers by their first occurrence in history. They don't label a ratio of unrelated date-period counts as conversion.

## Reminder claims

The worker claims one reminder at a time. The API locks the write transaction, picks a due item, and gives it a two-minute lease with a random token. A delivery report must contain the current token and arrive before the lease expires. An expired worker can't overwrite a newer claim.

Successful delivery becomes `sent`; completing the task becomes `completed`. Transient Telegram failures are retried with backoff; permanent errors or five failed attempts become `failed`. Leases expire after a crash, so reminders don't stay stuck in `sending` forever.

There is no transaction spanning Telegram and SQLite. A crash between those systems can create a duplicate message. The README says so. A queue or another database alone would not remove that uncertainty.

## Access

The bot's outer middleware checks the owner ID and private chat before commands or callbacks run. The API has a shared key for the bot and worker and is bound to localhost by default. This is not an Internet-facing, multi-tenant service.

## What would change for multiple users

Add authenticated identities and ownership checks to every operation; don't trust a submitted Telegram ID. Separate worker privileges from user API access. Consider PostgreSQL and migration tooling when concurrency and deployment require them.
