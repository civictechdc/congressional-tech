"""Small values shared by the proposed model; no source or storage dependencies."""
from __future__ import annotations

from datetime import date as CalendarDate, time as ClockTime
from typing import Annotated, Generic, Literal, TypeVar
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictInt, model_validator

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Count = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
Seconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Chamber = Literal["house", "senate", "joint", "unknown"]


def _http_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("expected an absolute HTTP(S) URL")
    return value  # Preserve spelling, scheme, escapes and query; do not normalize.


WebUrl = Annotated[Text, AfterValidator(_http_url)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True, revalidate_instances="always")


Kind = TypeVar("Kind", bound=str)


class Ref(Model, Generic[Kind]):
    """A typed reference, not a nested copy of the referenced record."""

    kind: Kind
    id: Text


class Identifier(Model):
    """An exact provider identifier. Scope is part of identity, never decoration."""

    scheme: Text
    value: Text
    scope: Text | None = None


class ReportedTime(Model):
    """Keep date-only and unzoned local times without inventing midnight or UTC."""

    date: CalendarDate
    time: ClockTime | None = None
    timezone: Text | None = None  # IANA zone or the source's timezone designation.
    precision: Literal["day", "minute", "second"] = "day"
    approximate: bool = False
    original: str | None = None

    @model_validator(mode="after")
    def precision_matches_value(self):
        if (self.time is None) != (self.precision == "day"):
            raise ValueError("day precision has no time; minute/second precision requires a time")
        if self.time and self.precision == "minute" and (self.time.second or self.time.microsecond):
            raise ValueError("minute precision cannot contain seconds")
        return self


class DateRange(Model):
    start: CalendarDate | None = None
    end: CalendarDate | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.start and self.end and self.end < self.start:
            raise ValueError("end precedes start")
        return self


class Location(Model):
    label: str | None = None
    building: str | None = None
    room: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    mode: Literal["in_person", "remote", "hybrid", "unknown"] = "unknown"
    access_url: WebUrl | None = None


class Extent(Model):
    """A portion of an exact file/stream, not interchangeable PDF/HTML pagination."""

    representation: Ref[Literal["representation"]]
    first_page: PositiveInt | None = None
    last_page: PositiveInt | None = None
    start_seconds: Seconds | None = None
    end_seconds: Seconds | None = None
    label: str | None = None  # Printed page labels, chapter or part names.

    @model_validator(mode="after")
    def ordered(self):
        if self.last_page is not None and (self.first_page is None or self.last_page < self.first_page):
            raise ValueError("last_page requires an earlier/equal first_page")
        if self.end_seconds is not None and (self.start_seconds is None or self.end_seconds < self.start_seconds):
            raise ValueError("end_seconds requires an earlier/equal start_seconds")
        return self
