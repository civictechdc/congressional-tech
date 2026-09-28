"""Proceedings, dated occurrences and participants' meeting-specific roles."""
from typing import Literal

from .common import Chamber, Count, Location, Model, PositiveInt, Ref, ReportedTime, Text
from .provenance import Provenance, Record


class ConveningCommittee(Model):
    committee: Ref[Literal["committee_term"]]
    role: Literal["host", "cohost", "participating", "unknown"] = "unknown"
    provenance: Provenance


class Meeting(Record):
    """A proceeding, retaining its provider IDs even when another entry describes it."""

    kind: Literal["meeting"] = "meeting"
    title: Text | None = None
    congress: PositiveInt | None = None
    congress_session: Literal[1, 2, 3] | None = None
    chamber: Chamber = "unknown"
    meeting_type: Literal["hearing", "markup", "business", "briefing", "field_hearing", "other", "unknown"] = "unknown"
    committees: tuple[ConveningCommittee, ...] = ()


class MeetingOccurrence(Record):
    """One scheduled sitting/day; changes to its schedule remain in source versions.

    A rescheduled notice alone is not proof that a second sitting took place.
    Multi-day proceedings may have several occurrences under one meeting.
    """

    kind: Literal["occurrence"] = "occurrence"
    meeting: Ref[Literal["meeting"]]
    label: str | None = None
    status: Literal["scheduled", "rescheduled", "postponed", "canceled", "held", "not_held", "unknown"] = "unknown"
    access: Literal["open", "closed", "partly_closed", "unknown"] = "unknown"
    scheduled_start: ReportedTime | None = None
    scheduled_end: ReportedTime | None = None
    actual_start: ReportedTime | None = None
    actual_end: ReportedTime | None = None
    location: Location | None = None


class MeetingRelation(Record):
    kind: Literal["meeting_relation"] = "meeting_relation"
    subject: Ref[Literal["meeting"]]
    related: Ref[Literal["meeting"]]
    relation: Literal["same_proceeding", "continuation_of", "rescheduled_to", "related"]


class Panel(Record):
    kind: Literal["panel"] = "panel"
    meeting: Ref[Literal["meeting"]]
    occurrence: Ref[Literal["occurrence"]] | None = None
    label: str | None = None
    order: Count | None = None


class Person(Record):
    """Create only with a supported identity; a name-only appearance needs no Person."""

    kind: Literal["person"] = "person"
    name: str | None = None  # An authoritative ID can be known before the name.


class Organization(Record):
    kind: Literal["organization"] = "organization"
    name: Text


class RecordedName(Model):
    display: Text
    honorific: str | None = None
    given: str | None = None
    middle: str | None = None
    family: str | None = None
    suffix: str | None = None
    retired: str | None = None


class Affiliation(Model):
    organization: Ref[Literal["organization"]] | None = None
    organization_name: str | None = None
    position: str | None = None
    on_behalf_of: str | None = None
    location: str | None = None


class Appearance(Record):
    """What a source says about someone's participation in this meeting.

    Name and affiliation are historical observations, not live Person properties.
    A nominee named in a title is not automatically a person who testified.
    """

    kind: Literal["appearance"] = "appearance"
    meeting: Ref[Literal["meeting"]]
    occurrence: Ref[Literal["occurrence"]] | None = None
    panel: Ref[Literal["panel"]] | None = None
    person: Ref[Literal["person"]] | None = None
    name: RecordedName
    roles: tuple[Literal["witness", "nominee", "chair", "ranking_member", "member", "staff", "clerk", "other", "unknown"], ...] = ()
    participation: Literal["listed", "invited", "present", "testified", "absent", "withdrawn", "unknown"] = "unknown"
    affiliation: Affiliation | None = None
    order: Count | None = None
