from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.time_utils import timestamp

Status = Literal["Saved", "Applied", "Interview", "Offer", "Rejected", "Withdrawn"]
ReminderState = Literal["pending", "sending", "sent", "failed", "completed", "cancelled"]
Name = Annotated[str, Field(min_length=1, max_length=160)]
Salary = Annotated[int, Field(ge=0, le=10_000_000, strict=True)]


def normalize_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError("Use a complete http:// or https:// job link")
    if parts.username or parts.password or any(c.isspace() for c in value):
        raise ValueError("Job links cannot contain credentials or whitespace")
    port = parts.port
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    if port and (parts.scheme.lower(), port) not in {("http", 80), ("https", 443)}:
        host += f":{port}"
    query = [
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"gclid", "fbclid"}
    ]
    return urlunsplit((parts.scheme.lower(), host, parts.path or "/", urlencode(query), ""))


class ApplicationFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    company: Name
    position: Name
    url: Annotated[str, Field(max_length=2048)]
    location: Annotated[str, Field(max_length=160)] | None = None
    salary_min: Salary | None = None
    salary_max: Salary | None = None
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] = "USD"
    salary_period: Literal["annual", "hourly"] = "annual"
    status: Status = "Saved"
    applied_at: datetime | None = None
    notes: Annotated[str, Field(max_length=2000)] | None = None

    @field_validator("url")
    @classmethod
    def job_url(cls, value):
        return normalize_url(value)

    @field_validator("applied_at")
    @classmethod
    def aware_date(cls, value):
        if value is not None:
            timestamp(value)
        return value

    @model_validator(mode="after")
    def salary_range(self):
        if self.salary_min is not None and self.salary_max is not None:
            if self.salary_min > self.salary_max:
                raise ValueError("Minimum salary cannot exceed maximum salary")
        return self


class ApplicationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    company: Name | None = None
    position: Name | None = None
    url: Annotated[str, Field(max_length=2048)] | None = None
    location: Annotated[str, Field(max_length=160)] | None = None
    salary_min: Salary | None = None
    salary_max: Salary | None = None
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] | None = None
    salary_period: Literal["annual", "hourly"] | None = None
    status: Status | None = None
    applied_at: datetime | None = None
    notes: Annotated[str, Field(max_length=2000)] | None = None


class ReminderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: Annotated[str, Field(min_length=1, max_length=500)]
    due_at: datetime

    @field_validator("due_at")
    @classmethod
    def aware_date(cls, value):
        timestamp(value)
        return value


class DeliveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lease_token: str
    success: bool
    permanent: bool = False
    error: Annotated[str, Field(max_length=200)] | None = None
    retry_after: Annotated[int, Field(ge=1, le=86400)] | None = None


class ReminderPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    due_at: datetime | None = None

    @model_validator(mode="after")
    def valid_patch(self):
        if not self.model_fields_set:
            raise ValueError("Choose a new time or reminder text")
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("Reminder fields cannot be null")
        if self.due_at is not None:
            timestamp(self.due_at)
        return self
