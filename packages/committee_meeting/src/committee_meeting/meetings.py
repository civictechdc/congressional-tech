"""Proceedings, sitting details and participants' meeting-specific roles."""
from typing import Literal

from .common import Chamber, Count, Location, Model, PositiveInt, Ref, ReportedTime, Text
from .provenance import Provenance, Record


class ConveningCommittee(Model):
    committee: Ref[Literal["committee_term"]]
    role: Literal["host", "cohost", "participating", "unknown"] = "unknown"
    provenance: Provenance


class MeetingSitting(Model):
    """Additional sitting/day when a proceeding spans multiple sittings."""

    label: str | None = None
    status: Literal["scheduled", "rescheduled", "postponed", "canceled", "held", "not_held", "unknown"] = "unknown"
    access: Literal["open", "closed", "partly_closed", "unknown"] = "unknown"
    scheduled_start: ReportedTime | None = None
    scheduled_end: ReportedTime | None = None
    actual_start: ReportedTime | None = None
    actual_end: ReportedTime | None = None
    location: Location | None = None


class Meeting(Record):
    """A proceeding, retaining its provider IDs and sitting details directly."""

    kind: Literal["meeting"] = "meeting"
    title: Text | None = None
    congress: PositiveInt | None = None
    congress_session: Literal[1, 2, 3] | None = None
    chamber: Chamber = "unknown"
    meeting_type: Literal["meeting", "hearing", "markup", "business", "briefing", "field_hearing", "roundtable", "other", "unknown"] = "unknown"
    source_type: str | None = None
    status: Literal["scheduled", "rescheduled", "postponed", "canceled", "held", "not_held", "unknown"] = "unknown"
    source_status: str | None = None
    access: Literal["open", "closed", "partly_closed", "unknown"] = "unknown"
    scheduled_start: ReportedTime | None = None
    scheduled_end: ReportedTime | None = None
    actual_start: ReportedTime | None = None
    actual_end: ReportedTime | None = None
    location: Location | None = None
    occurrences: tuple[MeetingSitting, ...] = ()
    committees: tuple[ConveningCommittee, ...] = ()


class MeetingOccurrence(Record):
    """One scheduled sitting/day; changes to its schedule remain in source versions.

    Retained for multi-sitting or separate sitting provenance when needed; single-sitting
    proceedings fold sitting fields directly into Meeting.
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


class RecordedName(Model):
    display: Text
    honorific: str | None = None
    given: str | None = None
    middle: str | None = None
    family: str | None = None
    suffix: str | None = None
    retired: str | None = None


class Affiliation(Model):
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
    panel_label: str | None = None
    panel_order: Count | None = None
    person: Ref[Literal["person"]] | None = None
    person_bioguide_id: str | None = None
    name: RecordedName
    roles: tuple[Literal["witness", "nominee", "chair", "ranking_member", "member", "staff", "clerk", "other", "unknown"], ...] = ()
    participation: Literal["listed", "invited", "present", "testified", "absent", "withdrawn", "unknown"] = "unknown"
    affiliation: Affiliation | None = None
    position: str | None = None
    organization_name: str | None = None
    on_behalf_of: str | None = None
    location: str | None = None
    order: Count | None = None
