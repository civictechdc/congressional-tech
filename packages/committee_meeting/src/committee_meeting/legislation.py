"""Legislative references and committee actions, without requiring parsed files."""
from typing import Literal

from pydantic import model_validator

from .common import Count, Model, PositiveInt, Ref, ReportedTime, Text
from .provenance import Provenance, Record


class LegislativeItem(Record):
    kind: Literal["legislative_item"] = "legislative_item"
    congress: PositiveInt
    item_type: Literal["bill", "resolution", "nomination", "treaty", "other", "unknown"] = "unknown"
    designation: Text  # Exact printed designation, e.g. H.R. 1306 or PN123-4.
    title: str | None = None


class MeetingSubject(Record):
    kind: Literal["meeting_subject"] = "meeting_subject"
    meeting: Ref[Literal["meeting"]]
    item: Ref[Literal["legislative_item"]]
    relationship: Literal["considered", "mentioned", "related", "unknown"] = "unknown"


class AmendmentSponsor(Model):
    person: Ref[Literal["person"]] | None = None
    name: str | None = None
    role: Literal["sponsor", "cosponsor", "offered_by", "unknown"] = "unknown"
    provenance: Provenance

    @model_validator(mode="after")
    def identified_or_named(self):
        if self.person is None and not (self.name and self.name.strip()):
            raise ValueError("a sponsor needs an identifier-backed person or recorded name")
        return self


class Amendment(Record):
    """Local numbers are scoped to a meeting; amendments may lack file URLs."""

    kind: Literal["amendment"] = "amendment"
    meeting: Ref[Literal["meeting"]]
    occurrence: Ref[Literal["occurrence"]] | None = None
    target: Ref[Literal["legislative_item", "amendment"]] | None = None
    number: str | None = None
    description: str | None = None
    amendment_type: str | None = None
    sponsors: tuple[AmendmentSponsor, ...] = ()
    disposition: Literal["offered", "adopted", "rejected", "withdrawn", "not_offered", "other", "unknown"] = "unknown"


class AmendmentGroup(Record):
    """An en-bloc group; retain a label even if the source omits its membership."""

    kind: Literal["amendment_group"] = "amendment_group"
    meeting: Ref[Literal["meeting"]]
    label: Text
    members: tuple[Ref[Literal["amendment"]], ...] = ()


class VoteTally(Model):
    """Absent counts stay unknown; no implicit zero or assumed full roll call."""

    yeas: Count | None = None
    nays: Count | None = None
    present: Count | None = None
    not_voting: Count | None = None


class Ballot(Model):
    person: Ref[Literal["person"]] | None = None
    recorded_name: Text | None = None
    choice: Literal["yea", "nay", "present", "not_voting", "other", "unknown"] = "unknown"
    raw_choice: str | None = None
    provenance: Provenance

    @model_validator(mode="after")
    def identified_or_named(self):
        if self.person is None and self.recorded_name is None:
            raise ValueError("a ballot needs a person or recorded name")
        return self


class Vote(Record):
    """A recorded committee action; a vote attachment need not include a tally."""

    kind: Literal["vote"] = "vote"
    meeting: Ref[Literal["meeting"]]
    occurrence: Ref[Literal["occurrence"]] | None = None
    committee: Ref[Literal["committee_term"]] | None = None
    subject: Ref[Literal["legislative_item", "amendment", "amendment_group"]] | None = None
    number: str | None = None
    question: str | None = None
    method: Literal["roll_call", "voice", "unanimous_consent", "division", "other", "unknown"] = "unknown"
    outcome: Literal["agreed", "rejected", "tied", "other", "unknown"] = "unknown"
    held_at: ReportedTime | None = None
    tally: VoteTally | None = None
    ballots: tuple[Ballot, ...] = ()
