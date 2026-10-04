import secrets
import sqlite3
from datetime import datetime, timedelta

from app.database import Database
from app.schemas import (
    ApplicationFields,
    ApplicationPatch,
    DeliveryResult,
    ReminderCreate,
    ReminderPatch,
)
from app.time_utils import timestamp


class StoreError(Exception):
    def __init__(self, status: int, detail):
        self.status = status
        self.detail = detail


def required(connection, table: str, row_id: int):
    # Table names are constants at call sites; user values are always parameters.
    row = connection.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    if row is None:
        raise StoreError(404, "Record not found")
    return dict(row)


class Store:
    def __init__(self, database: Database):
        self.db = database

    def create_application(self, data: ApplicationFields, now: datetime):
        values = data.model_dump()
        stamp = timestamp(now)
        values["applied_at"] = (
            timestamp(data.applied_at)
            if data.applied_at
            else stamp
            if data.status == "Applied"
            else None
        )
        values.update(created_at=stamp, updated_at=stamp)
        with self.db.connect(write=True) as connection:
            duplicate = connection.execute(
                "SELECT id FROM applications WHERE url = ?", (values["url"],)
            ).fetchone()
            if duplicate:
                raise StoreError(409, {"message": "Already saved", "application_id": duplicate[0]})
            columns = ", ".join(values)
            placeholders = ", ".join("?" for _ in values)
            result = connection.execute(
                f"INSERT INTO applications ({columns}) VALUES ({placeholders})",
                tuple(values.values()),
            )
            row_id = result.lastrowid
            connection.execute(
                "INSERT INTO status_history (application_id, new_status, changed_at) "
                "VALUES (?,?,?)",
                (row_id, values["status"], stamp),
            )
            return required(connection, "applications", row_id)

    def application(self, row_id: int):
        with self.db.connect() as connection:
            return required(connection, "applications", row_id)

    def applications(self, *, status=None, company=None, q=None, limit=10, offset=0):
        clauses, values = [], []
        if status:
            clauses.append("status = ?")
            values.append(status)
        if company:
            clauses.append("instr(lower(company), lower(?)) > 0")
            values.append(company)
        if q:
            clauses.append(
                "(instr(lower(company), lower(?)) > 0 OR instr(lower(position), lower(?)) > 0)"
            )
            values.extend([q, q])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.db.connect() as connection:
            total = connection.execute(
                "SELECT count(*) FROM applications" + where, values
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM applications" + where + " ORDER BY id DESC LIMIT ? OFFSET ?",
                [*values, limit, offset],
            ).fetchall()
        return {
            "items": [dict(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def patch_application(self, row_id: int, patch: ApplicationPatch, now: datetime):
        with self.db.connect(write=True) as connection:
            old = required(connection, "applications", row_id)
            fields = ApplicationFields.model_fields
            changes = patch.model_dump(exclude_unset=True)
            merged = ApplicationFields.model_validate(
                {key: changes.get(key, old[key]) for key in fields}
            )
            values = merged.model_dump()
            stamp = timestamp(now)
            if merged.applied_at:
                values["applied_at"] = timestamp(merged.applied_at)
            elif merged.status == "Applied":
                values["applied_at"] = stamp
            if values["url"] != old["url"]:
                duplicate = connection.execute(
                    "SELECT id FROM applications WHERE url = ? AND id != ?",
                    (values["url"], row_id),
                ).fetchone()
                if duplicate:
                    raise StoreError(
                        409, {"message": "Already saved", "application_id": duplicate[0]}
                    )
            values["updated_at"] = stamp
            assignments = ", ".join(f"{key} = ?" for key in values)
            connection.execute(
                f"UPDATE applications SET {assignments} WHERE id = ?",
                [*values.values(), row_id],
            )
            if merged.status != old["status"]:
                connection.execute(
                    "INSERT INTO status_history "
                    "(application_id, previous_status, new_status, changed_at) VALUES (?,?,?,?)",
                    (row_id, old["status"], merged.status, stamp),
                )
            return required(connection, "applications", row_id)

    def history(self, row_id: int):
        with self.db.connect() as connection:
            required(connection, "applications", row_id)
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM status_history WHERE application_id = ? ORDER BY id", (row_id,)
                )
            ]

    def create_reminder(self, row_id: int, data: ReminderCreate, now: datetime):
        with self.db.connect(write=True) as connection:
            required(connection, "applications", row_id)
            due = timestamp(data.due_at)
            result = connection.execute(
                "INSERT INTO reminders (application_id, text, due_at, next_attempt_at, created_at) "
                "VALUES (?,?,?,?,?)",
                (row_id, data.text, due, due, timestamp(now)),
            )
            return required(connection, "reminders", result.lastrowid)

    def reminders(
        self, *, state=None, due_before=None, active=False, application_id=None, limit=50, offset=0
    ):
        clauses, params = [], []
        if application_id is not None:
            clauses.append("r.application_id = ?")
            params.append(application_id)
        if state:
            clauses.append("r.state = ?")
            params.append(state)
        if active:
            clauses.append("r.state NOT IN ('completed', 'cancelled')")
        if due_before:
            clauses.append("r.due_at < ?")
            params.append(timestamp(due_before))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.db.connect() as connection:
            total = connection.execute(
                "SELECT count(*) FROM reminders r" + where, params
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT r.*, a.company, a.position FROM reminders r "
                "JOIN applications a ON a.id = r.application_id"
                + where
                + " ORDER BY r.due_at, r.id LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        return {
            "items": [dict(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def finish_reminder(self, row_id: int, state: str, now: datetime):
        with self.db.connect(write=True) as connection:
            row = required(connection, "reminders", row_id)
            if row["state"] == state:
                return row
            if row["state"] in {"completed", "cancelled"}:
                raise StoreError(409, "This reminder is already finished")
            connection.execute(
                "UPDATE reminders SET state = ?, completed_at = ?, "
                "lease_until = NULL, lease_token = NULL WHERE id = ?",
                (state, timestamp(now) if state == "completed" else None, row_id),
            )
            return required(connection, "reminders", row_id)

    def reminder(self, row_id: int):
        with self.db.connect() as connection:
            row = required(connection, "reminders", row_id)
            job = required(connection, "applications", row["application_id"])
            row.update(company=job["company"], position=job["position"])
            return row

    def patch_reminder(self, row_id: int, patch: ReminderPatch, now: datetime):
        with self.db.connect(write=True) as connection:
            row = required(connection, "reminders", row_id)
            if row["state"] in {"sending", "completed", "cancelled"}:
                raise StoreError(409, "A sending or finished reminder cannot be edited")
            changes = patch.model_dump(exclude_unset=True)
            if patch.due_at is not None:
                if patch.due_at <= now:
                    raise StoreError(422, "Choose a reminder time in the future")
                changes["due_at"] = timestamp(patch.due_at)
                changes.update(
                    next_attempt_at=changes["due_at"],
                    state="pending",
                    attempt_count=0,
                    delivered_at=None,
                    last_error=None,
                    lease_until=None,
                    lease_token=None,
                )
            assignments = ", ".join(f"{key} = ?" for key in changes)
            connection.execute(
                f"UPDATE reminders SET {assignments} WHERE id = ?", [*changes.values(), row_id]
            )
            return required(connection, "reminders", row_id)

    def retry_reminder(self, row_id: int, now: datetime):
        with self.db.connect(write=True) as connection:
            row = required(connection, "reminders", row_id)
            if row["state"] != "failed":
                raise StoreError(409, "Only a failed reminder can be retried")
            connection.execute(
                "UPDATE reminders SET state = 'pending', next_attempt_at = ?, attempt_count = 0, "
                "last_error = NULL, lease_token = NULL, lease_until = NULL WHERE id = ?",
                (timestamp(now), row_id),
            )
            return required(connection, "reminders", row_id)

    def claim_reminders(self, now: datetime, limit=1):
        stamp = timestamp(now)
        lease_until = timestamp(now + timedelta(minutes=2))
        with self.db.connect(write=True) as connection:
            connection.execute(
                "UPDATE reminders SET state = CASE WHEN attempt_count >= 5 THEN 'failed' "
                "ELSE 'pending' END, lease_until = NULL, lease_token = NULL "
                "WHERE state = 'sending' AND lease_until <= ?",
                (stamp,),
            )
            rows = connection.execute(
                "SELECT id FROM reminders WHERE state = 'pending' AND next_attempt_at <= ? "
                "ORDER BY due_at, id LIMIT ?",
                (stamp, limit),
            ).fetchall()
            claimed = []
            for row in rows:
                connection.execute(
                    "UPDATE reminders SET state = 'sending', attempt_count = attempt_count + 1, "
                    "lease_until = ?, lease_token = ? WHERE id = ?",
                    (lease_until, secrets.token_urlsafe(16), row["id"]),
                )
                reminder = required(connection, "reminders", row["id"])
                application = required(connection, "applications", reminder["application_id"])
                reminder.update(company=application["company"], position=application["position"])
                claimed.append(reminder)
            return claimed

    def record_delivery(self, row_id: int, data: DeliveryResult, now: datetime):
        stamp = timestamp(now)
        with self.db.connect(write=True) as connection:
            row = required(connection, "reminders", row_id)
            if (
                row["state"] != "sending"
                or row["lease_token"] != data.lease_token
                or row["lease_until"] <= stamp
            ):
                raise StoreError(409, "Reminder claim expired or changed")
            if data.success:
                state, error, delivered = "sent", None, stamp
            else:
                state = "failed" if data.permanent or row["attempt_count"] >= 5 else "pending"
                error, delivered = data.error or "Delivery failed", None
            delay = max(data.retry_after or 0, min(30 * 2 ** (row["attempt_count"] - 1), 900))
            connection.execute(
                "UPDATE reminders SET state = ?, last_error = ?, delivered_at = ?, "
                "next_attempt_at = ?, lease_until = NULL, lease_token = NULL WHERE id = ?",
                (state, error, delivered, timestamp(now + timedelta(seconds=delay)), row_id),
            )
            return required(connection, "reminders", row_id)

    def stats(self, start: datetime, end: datetime):
        bounds = (timestamp(start), timestamp(end))
        if start >= end:
            raise StoreError(422, "Start must be before end")
        with self.db.connect() as connection:
            applied = connection.execute(
                "SELECT count(*) FROM applications WHERE applied_at >= ? AND applied_at < ?",
                bounds,
            ).fetchone()[0]
            reached = {}
            for status in ("Interview", "Offer"):
                reached[status] = connection.execute(
                    "SELECT count(*) FROM (SELECT min(changed_at) AS first_at FROM status_history "
                    "WHERE new_status = ? GROUP BY application_id) "
                    "WHERE first_at >= ? AND first_at < ?",
                    (status, *bounds),
                ).fetchone()[0]
            current = {
                row[0]: row[1]
                for row in connection.execute(
                    "SELECT status, count(*) FROM applications GROUP BY status"
                )
            }
        return {
            "from": bounds[0],
            "to": bounds[1],
            "applications": applied,
            "interviews": reached["Interview"],
            "offers": reached["Offer"],
            "current_statuses": current,
        }


def is_busy(error: sqlite3.OperationalError) -> bool:
    return "locked" in str(error).lower() or "busy" in str(error).lower()
