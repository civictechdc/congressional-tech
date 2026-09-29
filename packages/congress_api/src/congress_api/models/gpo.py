"""GovInfo source records and the MODS fields consumed by this package.

This is an extraction model, not the complete Library of Congress MODS schema.
The ordered XML element tree retains attributes, repeated and unknown elements,
text and tails; ``raw_xml`` retains the exact original bytes separately. Values
remain strings until a downstream parser explicitly interprets them.
"""
from __future__ import annotations

from pydantic import Field

from .base import SourceModel
from .content import RawContent
from .xml import XmlElement


class ModsName(SourceModel):
    type: str | None = None
    text: str | None = None


class ModsSubcommittee(SourceModel):
    names: list[ModsName] = Field(default_factory=list)


class ModsCommittee(SourceModel):
    authority_id: str | None = Field(default=None, alias='authorityId')
    chamber: str | None = None
    congress: str | None = None
    type: str | None = None
    names: list[ModsName] = Field(default_factory=list)
    subcommittees: list[ModsSubcommittee] = Field(default_factory=list)


class ModsMember(SourceModel):
    bio_guide_id: str | None = Field(default=None, alias='bioGuideId')
    chamber: str | None = None
    party: str | None = None
    state: str | None = None
    congress: str | None = None
    role: str | None = None
    names: list[ModsName] = Field(default_factory=list)


class ModsRendition(SourceModel):
    url: str | None = None
    display_label: str | None = Field(default=None, alias='displayLabel')
    access: str | None = None
    usage: str | None = None


class ModsSerial(SourceModel):
    number: str | None = None
    text: str | None = None


class ModsTitle(SourceModel):
    type: str | None = None
    title: str | None = None
    subtitle: str | None = None
    part_name: str | None = Field(default=None, alias='partName')
    part_number: str | None = Field(default=None, alias='partNumber')
    non_sort: str | None = Field(default=None, alias='nonSort')


class ModsRoleTerm(SourceModel):
    type: str | None = None
    authority: str | None = None
    text: str | None = None


class ModsAgent(SourceModel):
    """A MODS name with its native role terms, independent of attendance."""
    type: str | None = None
    name_parts: list[ModsName] = Field(default_factory=list)
    roles: list[list[ModsRoleTerm]] = Field(default_factory=list)


class ModsBill(SourceModel):
    congress: str | None = None
    context: str | None = None
    number: str | None = None
    type: str | None = None
    text: str | None = None


class ModsNominee(SourceModel):
    state: str | None = None
    names: list[ModsName] = Field(default_factory=list)
    positions: list[str | None] = Field(default_factory=list)


class ModsScope(SourceModel):
    attributes: dict[str, str] = Field(default_factory=dict)
    relation_type: str | None = None
    titles: list[ModsTitle] = Field(default_factory=list)
    search_titles: list[str | None] = Field(default_factory=list)
    preferred_citations: list[str | None] = Field(default_factory=list)
    held_dates: list[str | None] = Field(default_factory=list)
    congresses: list[str | None] = Field(default_factory=list)
    chambers: list[str | None] = Field(default_factory=list)
    source_types: list[str | None] = Field(default_factory=list)
    sessions: list[str | None] = Field(default_factory=list)
    event_ids: list[str | None] = Field(default_factory=list)
    date_ingested: list[str | None] = Field(default_factory=list)
    document_classes: list[str | None] = Field(default_factory=list)
    granule_classes: list[str | None] = Field(default_factory=list)
    errata: list[str | None] = Field(default_factory=list)
    is_errata: list[str | None] = Field(default_factory=list)
    is_nomination: list[str | None] = Field(default_factory=list)
    agents: list[ModsAgent] = Field(default_factory=list)
    bills: list[ModsBill] = Field(default_factory=list)
    nominees: list[ModsNominee] = Field(default_factory=list)
    committees: list[ModsCommittee] = Field(default_factory=list)
    members: list[ModsMember] = Field(default_factory=list)
    witnesses: list[str | None] = Field(default_factory=list)
    renditions: list[ModsRendition] = Field(default_factory=list)
    serials: list[ModsSerial] = Field(default_factory=list)

    def first(self, field: str) -> str:
        values = getattr(self, field)
        return (values[0] or '').strip() if values else ''


class ModsDocument(SourceModel):
    root: ModsScope
    related_items: list[ModsScope] = Field(default_factory=list)
    members: list[ModsMember] = Field(default_factory=list)
    witnesses: list[str] = Field(default_factory=list)
    xml: XmlElement
    content: RawContent

    @property
    def raw_xml(self) -> bytes:
        return self.content.body_bytes()

    @property
    def constituents(self) -> list[ModsScope]:
        return [part for part in self.related_items if part.relation_type == 'constituent']


class GpoCollectionPackage(SourceModel):
    package_id: str = Field(alias='packageId')
    last_modified: str = Field(alias='lastModified')
    package_link: str | None = Field(default=None, alias='packageLink')
    congress: str | None = None
    date_issued: str | None = Field(default=None, alias='dateIssued')
    document_class: str | None = Field(default=None, alias='docClass')
    title: str | None = None


class GpoCollectionPage(SourceModel):
    packages: list[GpoCollectionPackage]
    count: int | None = None
    next_page: str | None = Field(default=None, alias='nextPage')
    previous_page: str | None = Field(default=None, alias='previousPage')


class GpoEvidenceObservation(RawContent):
    url: str
    retrieved_at: str | None
    acquisition: str
    error: str | None = None


class GpoListingObservation(SourceModel):
    payload: GpoCollectionPackage
    retrieved_at: str
    url: str


class GpoEvidenceRecord(SourceModel):
    package_id: str
    parser_version: str | None = None
    mods: GpoEvidenceObservation | None = None
    failed_mods: GpoEvidenceObservation | None = None
    transcripts: dict[str, GpoEvidenceObservation] = Field(default_factory=dict)
    listing: GpoListingObservation | None = None


class GpoTranscriptDates(SourceModel):
    """Dates/name extracted from HTML; this does not assert complete transcript text."""
    hearing_dates: str
    committee_name: str


class GpoTranscriptText(SourceModel):
    """Plain text extracted from a source HTML page, including short/stub pages."""
    source: RawContent
    text: str


class MetsFileLocation(SourceModel):
    """An exact file locator in a GovInfo ZIP's METS manifest."""
    attributes: dict[str, str]
    href: str | None = None


class MetsFile(SourceModel):
    attributes: dict[str, str]
    locations: list[MetsFileLocation]


class GpoPackageManifest(SourceModel):
    """Published package file list; MODS can omit files that this list contains."""
    attributes: dict[str, str]
    files: list[MetsFile]
    xml: XmlElement
    content: RawContent
