"""Dated coverage findings; absence and inferred availability remain explicit."""
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, model_validator

from .common import Ref, ReportedTime, Text
from .provenance import Record


class Assessment(Record):
    kind: Literal["assessment"] = "assessment"
    subject: Ref[Literal["meeting", "occurrence", "committee_term", "channel", "material", "representation"]]
    aspect: Literal["recording", "transcript", "captions", "witnesses", "documents", "event_id", "reachability", "content"]
    status: Literal["available", "not_found", "unknown", "not_applicable", "blocked", "error"]
    evaluated_at: AwareDatetime  # When this conclusion was produced.
    observed_at: AwareDatetime | ReportedTime | None = None  # Preserve day-only checks.
    provider: Text | None = None
    scope: Text | None = None  # What was checked: page, endpoint, caption type, period, etc.
    explanation: str | None = None
    results: tuple[Ref[Literal["material", "representation", "appearance"]], ...] = ()

    @model_validator(mode="after")
    def bounded_negative(self):
        if self.status == "not_found" and (self.observed_at is None or self.scope is None):
            raise ValueError("not_found requires a dated check and explicit search scope")
        if isinstance(self.observed_at, datetime) and self.observed_at > self.evaluated_at:
            raise ValueError("an observation cannot follow the assessment that uses it")
        if self.results and self.status != "available":
            raise ValueError("positive result references require available status")
        return self
