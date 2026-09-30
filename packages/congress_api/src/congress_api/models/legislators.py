"""Native unitedstates/congress-legislators records; no name or party rewriting."""

from collections import defaultdict
from datetime import date

from pydantic import Field, TypeAdapter

from .base import SourceModel


class LegislatorIdentifiers(SourceModel):
    bioguide: str
    thomas: str | None = None
    lis: str | None = None
    govtrack: int | None = None
    opensecrets: str | None = None
    votesmart: int | None = None
    fec: list[str] | None = None
    cspan: int | None = None
    wikipedia: str | None = None
    house_history: int | None = None
    ballotpedia: str | None = None
    maplight: int | None = None
    icpsr: int | None = None
    wikidata: str | None = None
    google_entity_id: str | None = None
    pictorial: int | None = None


class LegislatorName(SourceModel):
    first: str
    last: str
    official_full: str | None = None
    middle: str | None = None
    nickname: str | None = None
    suffix: str | None = None


class LegislatorBio(SourceModel):
    birthday: str | None = None
    gender: str | None = None


class PartyAffiliation(SourceModel):
    start: str
    end: str
    party: str
    caucus: str | None = None


class LegislatorTerm(SourceModel):
    type: str
    start: str
    end: str
    state: str
    district: int | None = None
    party: str | None = None
    senate_class: int | None = Field(None, alias="class")
    url: str | None = None
    address: str | None = None
    phone: str | None = None
    fax: str | None = None
    contact_form: str | None = None
    office: str | None = None
    state_rank: str | None = None
    rss_url: str | None = None
    caucus: str | None = None
    how: str | None = None
    end_type: str | None = Field(None, alias="end-type")
    party_affiliations: list[PartyAffiliation] | None = None


class LeadershipRole(SourceModel):
    title: str
    chamber: str
    start: str
    end: str | None = None


class FamilyMember(SourceModel):
    name: str
    relation: str


class Legislator(SourceModel):
    id: LegislatorIdentifiers
    name: LegislatorName
    bio: LegislatorBio | None = None
    terms: list[LegislatorTerm]
    leadership_roles: list[LeadershipRole] | None = None
    family: list[FamilyMember] | None = None


LEGISLATORS = TypeAdapter(list[Legislator])


def parse_legislators(data: str | bytes) -> list[Legislator]:
    return LEGISLATORS.validate_json(data)


def member_surnames_by_congress(legislators: list[Legislator]) -> dict[str, tuple[str, ...]]:
    """Use retained service dates to select surname vocabulary for each Congress."""
    names = defaultdict(set)
    def start_of(congress):
        return date(1789 + 2 * (congress - 1), 1, 3) if congress >= 74 else date(1789 + 2 * (congress - 1), 3, 4)
    for member in legislators:
        for term in member.terms:
            start, end = date.fromisoformat(term.start), date.fromisoformat(term.end)
            first = max(1, (start.year - 1789) // 2)
            last = (end.year - 1789) // 2 + 1
            for congress in range(first, last + 1):
                if start < start_of(congress + 1) and end > start_of(congress):
                    names[str(congress)].add(member.name.last)
    return {congress: tuple(sorted(surnames)) for congress, surnames in sorted(names.items(), key=lambda row: int(row[0]))}
