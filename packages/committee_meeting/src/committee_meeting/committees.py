"""Committee identity is separate from its name, hierarchy and members in a Congress."""
from typing import Literal

from .common import Chamber, DateRange, PositiveInt, Ref, Text, WebUrl
from .provenance import Record


class Committee(Record):
    kind: Literal["committee"] = "committee"
    label: Text


class CommitteeTerm(Record):
    kind: Literal["committee_term"] = "committee_term"
    committee: Ref[Literal["committee"]]
    congress: PositiveInt
    name: Text | None = None
    chamber: Chamber
    committee_type: Literal["standing", "select", "special", "joint", "subcommittee", "other", "unknown"] = "unknown"
    parent: Ref[Literal["committee_term"]] | None = None
    active: DateRange | None = None
    jurisdiction: str | None = None
    website: WebUrl | None = None


class CommitteeRelation(Record):
    kind: Literal["committee_relation"] = "committee_relation"
    predecessor: Ref[Literal["committee"]]
    successor: Ref[Literal["committee"]]
    relation: Literal["renamed", "replaced", "split", "merged"]
    effective: DateRange | None = None


class Channel(Record):
    kind: Literal["channel"] = "channel"
    provider: Text  # Open provider namespace, e.g. youtube or senate-isvp.
    title: str | None = None
    url: WebUrl


class CommitteeChannel(Record):
    kind: Literal["committee_channel"] = "committee_channel"
    committee: Ref[Literal["committee_term"]]
    channel: Ref[Literal["channel"]]
    role: Literal["official", "majority", "minority", "member", "archive", "other", "unknown"] = "unknown"
    active: DateRange | None = None


class CommitteeMembership(Record):
    kind: Literal["committee_membership"] = "committee_membership"
    committee: Ref[Literal["committee_term"]]
    person: Ref[Literal["person"]]
    roles: tuple[Literal["chair", "ranking_member", "member", "ex_officio", "staff", "other"], ...] = ()
    active: DateRange | None = None
    party: str | None = None
    state: str | None = None
    district: str | None = None
