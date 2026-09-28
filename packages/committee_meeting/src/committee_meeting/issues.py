"""Evidence-backed limitations and corrections, separate from availability checks."""
from typing import Literal

from pydantic import AwareDatetime, model_validator

from .common import Model, Ref, ReportedTime, Text
from .provenance import Provenance, Record

IssueSubject = Literal[
    "committee", "committee_term", "committee_relation", "channel", "committee_channel", "committee_membership",
    "meeting", "occurrence", "meeting_relation", "panel", "person", "organization", "appearance",
    "material", "material_version", "representation", "material_link", "material_relation", "speaker_attribution",
    "legislative_item", "meeting_subject", "amendment", "amendment_group", "vote", "assessment", "source_record",
]


class IssueResolution(Model):
    decided_at: AwareDatetime
    explanation: Text
    provenance: Provenance


class DataIssue(Record):
    """A known limitation, supported expectation or documented correction.

    Missing requires a reason to expect the item; null fields alone are not
    defects. Conflicting facts are not proof that either source is incorrect.
    Closing an issue retains its original evidence and a separate decision.
    """

    kind: Literal["data_issue"] = "data_issue"
    subject: Ref[IssueSubject]
    field_path: str | None = None  # Optional JSON Pointer within the subject.
    category: Literal["missing", "unverified", "conflicting", "incorrect", "stale", "unlinked", "duplicate"]
    impact: Literal["blocks_use", "affects_interpretation", "informational"] = "affects_interpretation"
    status: Literal["open", "resolved", "dismissed"] = "open"
    summary: Text
    explanation: str | None = None
    expected: Text | None = None
    detected_at: AwareDatetime
    last_checked_at: AwareDatetime | ReportedTime | None = None
    resolution: IssueResolution | None = None

    @model_validator(mode="after")
    def supported_issue(self):
        if self.field_path is not None and not self.field_path.startswith("/"):
            raise ValueError("field_path must be a JSON Pointer")
        if self.category == "missing" and self.expected is None:
            raise ValueError("a missing-data issue requires a supported expectation")
        if self.category == "incorrect" and self.provenance.basis == "inferred":
            raise ValueError("an inference alone cannot establish an incorrect value")
        if (self.status == "open") != (self.resolution is None):
            raise ValueError("closed issues require a resolution; open issues have none")
        if self.resolution and self.resolution.decided_at < self.detected_at:
            raise ValueError("resolution precedes issue detection")
        return self
