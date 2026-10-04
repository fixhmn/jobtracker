import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE applications (
    id INTEGER PRIMARY KEY,
    company TEXT NOT NULL,
    position TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    location TEXT,
    salary_min INTEGER,
    salary_max INTEGER,
    currency TEXT NOT NULL,
    salary_period TEXT NOT NULL,
    status TEXT NOT NULL,
    applied_at TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE status_history (
    id INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES applications(id),
    previous_status TEXT,
    new_status TEXT NOT NULL,
    changed_at TEXT NOT NULL
);
CREATE TABLE reminders (
    id INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES applications(id),
    text TEXT NOT NULL,
    due_at TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    lease_until TEXT,
    lease_token TEXT,
    delivered_at TEXT,
    completed_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX applications_status ON applications(status);
CREATE INDEX applications_applied ON applications(applied_at);
CREATE INDEX history_application ON status_history(application_id, changed_at);
CREATE INDEX reminders_due ON reminders(state, next_attempt_at);
"""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def connect(self, *, write=False):
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            if write:
                connection.commit()
        except Exception:
            if write:
                connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("BEGIN IMMEDIATE")
            try:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version > 1:
                    raise RuntimeError("Database was created by a newer JobTracker version")
                if version == 0:
                    for statement in SCHEMA.split(";"):
                        if statement.strip():
                            connection.execute(statement)
                    connection.execute("PRAGMA user_version = 1")
                connection.commit()
            except Exception:
                connection.rollback()
                raise
