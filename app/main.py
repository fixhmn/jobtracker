import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from fastapi.security import APIKeyHeader
from pydantic import ValidationError

from app.config import Settings
from app.database import Database
from app.export import applications_csv
from app.schemas import (
    ApplicationFields,
    ApplicationPatch,
    DeliveryResult,
    ReminderCreate,
    ReminderPatch,
    ReminderState,
    Status,
)
from app.store import Store, StoreError, is_busy
from app.time_utils import timestamp, utc_now


def create_app(settings: Settings | None = None, clock=utc_now) -> FastAPI:
    settings = settings or Settings.from_env()
    database = Database(settings.database_path)
    store = Store(database)

    @asynccontextmanager
    async def lifespan(app):
        database.initialize()
        yield

    app = FastAPI(title="JobTracker", version="0.2.0", lifespan=lifespan)
    app.state.store = store
    header = APIKeyHeader(name="X-API-Key", auto_error=False)

    def authorize(key: Annotated[str | None, Depends(header)]):
        if key is None or not secrets.compare_digest(key.encode(), settings.api_key.encode()):
            raise HTTPException(401, "Missing or invalid API key")

    router = APIRouter(dependencies=[Depends(authorize)])

    @app.exception_handler(StoreError)
    async def store_error(request, error):
        return JSONResponse(status_code=error.status, content={"detail": error.detail})

    @app.exception_handler(ValidationError)
    async def validation_error(request, error):
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]}
                    for e in error.errors()
                ]
            },
        )

    @app.exception_handler(sqlite3.OperationalError)
    async def database_error(request, error):
        if is_busy(error):
            return JSONResponse(
                status_code=503,
                content={"detail": "Database is busy. Try again."},
                headers={"Retry-After": "2"},
            )
        return JSONResponse(status_code=500, content={"detail": "Database operation failed"})

    @app.get("/health", tags=["health"])
    def health():
        return {"status": "ok"}

    @router.post("/applications", status_code=201, tags=["applications"])
    def create_application(data: ApplicationFields):
        return store.create_application(data, clock())

    @router.get("/applications", tags=["applications"])
    def applications(
        status: Status | None = None,
        company: str | None = None,
        q: str | None = None,
        limit: int = Query(10, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        return store.applications(status=status, company=company, q=q, limit=limit, offset=offset)

    @router.get("/applications/export.csv", tags=["applications"])
    def export_applications(status: Status | None = None):
        page = store.applications(status=status, limit=5000)
        if page["total"] > 5000:
            raise HTTPException(413, "Export is limited to 5000 jobs. Filter by status.")
        content = applications_csv(page["items"])
        return Response(
            content=content.encode("utf-8-sig"),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="applications.csv"',
                "Cache-Control": "no-store",
            },
        )

    @router.get("/applications/{row_id}", tags=["applications"])
    def application(row_id: int):
        return store.application(row_id)

    @router.patch("/applications/{row_id}", tags=["applications"])
    def patch_application(row_id: int, data: ApplicationPatch):
        return store.patch_application(row_id, data, clock())

    @router.get("/applications/{row_id}/history", tags=["applications"])
    def history(row_id: int):
        return store.history(row_id)

    @router.post("/applications/{row_id}/reminders", status_code=201, tags=["reminders"])
    def create_reminder(row_id: int, data: ReminderCreate):
        return store.create_reminder(row_id, data, clock())

    @router.get("/reminders", tags=["reminders"])
    def reminders(
        state: ReminderState | None = None,
        due_before: datetime | None = None,
        active: bool = False,
        application_id: int | None = Query(None, ge=1),
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        if due_before is not None:
            try:
                timestamp(due_before)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
        return store.reminders(
            state=state,
            due_before=due_before,
            active=active,
            application_id=application_id,
            limit=limit,
            offset=offset,
        )

    @router.get("/reminders/{row_id}", tags=["reminders"])
    def reminder(row_id: int):
        return store.reminder(row_id)

    @router.patch("/reminders/{row_id}", tags=["reminders"])
    def patch_reminder(row_id: int, data: ReminderPatch):
        return store.patch_reminder(row_id, data, clock())

    @router.post("/reminders/{row_id}/retry", tags=["reminders"])
    def retry_reminder(row_id: int):
        return store.retry_reminder(row_id, clock())

    @router.post("/reminders/{row_id}/complete", tags=["reminders"])
    def complete(row_id: int):
        return store.finish_reminder(row_id, "completed", clock())

    @router.post("/reminders/{row_id}/cancel", tags=["reminders"])
    def cancel(row_id: int):
        return store.finish_reminder(row_id, "cancelled", clock())

    @router.post("/internal/reminders/claim", tags=["worker"])
    def claim(limit: int = Query(1, ge=1, le=10)):
        return store.claim_reminders(clock(), limit)

    @router.post("/internal/reminders/{row_id}/delivery", tags=["worker"])
    def delivery(row_id: int, data: DeliveryResult):
        return store.record_delivery(row_id, data, clock())

    @router.get("/stats", tags=["stats"])
    def stats(
        start: Annotated[datetime | None, Query(alias="from")] = None,
        end: Annotated[datetime | None, Query(alias="to")] = None,
    ):
        end = end or clock()
        start = start or end - timedelta(days=30)
        try:
            return store.stats(start, end)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    app.include_router(router)
    return app
