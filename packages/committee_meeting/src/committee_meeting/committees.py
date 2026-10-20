"""Committee identity is separate from its name, hierarchy and members in a Congress."""
from typing import Literal

from .common import Chamber, DateRange, PositiveInt, Ref, Text, WebUrl
from .provenance import Record


class Committee(Record):
    kind: Literal["committee"] = "committee"
    label: Text


class CommitteeTerm(Record):
    kind: Literal["committee_term"] = "committee_term"
    committee: Ref[Literal["committee"]] | None = None
    congress: PositiveInt
    name: Text | None = None
    chamber: Chamber
    committee_code: Text | None = None
    committee_level: Literal["full", "subcommittee", "unknown"] = "unknown"
    committee_type: Literal[
        "standing", "select", "special", "joint", "subcommittee",
        "commission_or_caucus", "task_force", "other", "unknown",
    ] = "unknown"
    source_committee_type: Text | None = None
    parent: Ref[Literal["committee_term"]] | None = None
    active: DateRange | None = None
    jurisdiction: str | None = None
    website: WebUrl | None = None


class Channel(Record):
    kind: Literal["channel"] = "channel"
    provider: Text  # Open provider namespace, e.g. youtube or senate-isvp.
    title: str | None = None
    url: WebUrl
