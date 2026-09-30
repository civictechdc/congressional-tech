"""Congress.gov JSON shapes, retaining publisher spelling and scalar types.

The meeting and committee endpoints are distinct from our normalized entities.
Optional fields describe sparse publisher records; absent and null remain distinct
on ``source_dict()``. Field types were checked against the retained full corpus.
"""

from pydantic import Field

from .base import SourceModel
from .content import RawContent


class Pagination(SourceModel):
    count: int | None = None
    next: str | None = None
    previous: str | None = None


class RequestInfo(SourceModel):
    congress: str | int | None = None
    chamber: str | None = None
    contentType: str | None = None
    format: str | None = None
    systemCode: str | None = None
    eventId: str | None = None


class CommitteeReference(SourceModel):
    systemCode: str
    name: str | None = None
    url: str | None = None


class CommitteeRecord(CommitteeReference):
    chamber: str | None = None
    committeeTypeCode: str | None = None
    updateDate: str | None = None
    parent: CommitteeReference | None = None
    subcommittees: list[CommitteeReference] | None = None


class CountLink(SourceModel):
    count: int | None = None
    url: str | None = None


class CommitteeHistory(SourceModel):
    officialName: str | None = None
    locName: str | None = None
    libraryOfCongressName: str | None = None
    startDate: str | None = None
    endDate: str | None = None
    updateDate: str | None = None
    committeeTypeCode: str | None = None
    establishingAuthority: str | None = None
    superintendentDocumentNumber: str | None = None
    locLinkedDataId: str | None = None
    naraId: str | None = None


class CommitteeDetail(CommitteeRecord):
    committeeWebsiteUrl: str | None = None
    type: str | None = None
    isCurrent: bool | None = None
    bills: CountLink | None = None
    communications: CountLink | None = None
    reports: CountLink | None = None
    nominations: CountLink | None = None
    history: list[CommitteeHistory] | None = None


class CommitteeSnapshot(SourceModel):
    congress: int
    committee: CommitteeRecord
    source_url: str | None = Field(None, alias="_url")
    retrieved_at: str | None = None


class MeetingLocation(SourceModel):
    building: str | None = None
    room: str | None = None
    # The API supplies JSON encoded *inside a string* for field hearings.
    address: str | None = None


class MeetingDocument(SourceModel):
    documentType: str | None = None
    format: str | None = None
    name: str | None = None
    description: str | None = None
    url: str | None = None


class MeetingWitness(SourceModel):
    name: str
    position: str | None = None
    organization: str | None = None


class MeetingVideo(SourceModel):
    name: str | None = None
    url: str


class HearingTranscriptReference(SourceModel):
    jacketNumber: int
    url: str | None = None


class BillReference(SourceModel):
    congress: int
    type: str
    # Current JSON is string-valued; retained/imported records may use numbers.
    # A strict union keeps either literal rather than coercing one into the other.
    number: str | int
    url: str | None = None


class NominationReference(SourceModel):
    congress: int
    number: int
    part: str | None = None
    url: str | None = None


class TreatyReference(SourceModel):
    congress: int
    number: int
    url: str | None = None


class RelatedItems(SourceModel):
    bills: list[BillReference] | None = None
    nominations: list[NominationReference] | None = None
    treaties: list[TreatyReference] | None = None


class MeetingContinuation(SourceModel):
    continuationDate: str | None = None


class MeetingSummary(SourceModel):
    url: str
    eventId: str | None = None
    congress: int | None = None
    chamber: str | None = None
    updateDate: str | None = None


class CommitteeMeeting(SourceModel):
    eventId: str
    congress: int
    chamber: str
    title: str | None = None
    type: str | None = None
    meetingStatus: str | None = None
    date: str | None = None
    updateDate: str | None = None
    isManuallyCurated: bool | str | None = None
    committees: list[CommitteeReference] | None = None
    location: MeetingLocation | None = None
    continuations: list[MeetingContinuation] | None = None
    hearingTranscript: list[HearingTranscriptReference] | None = None
    meetingDocuments: list[MeetingDocument] | None = None
    witnessDocuments: list[MeetingDocument] | None = None
    witnesses: list[MeetingWitness] | None = None
    videos: list[MeetingVideo] | None = None
    relatedItems: RelatedItems | None = None
    source_url: str | None = Field(None, alias="_url")
    retrieved_at: str | None = Field(None, alias="_retrieved_at")
    # XML recovery uses the same meeting field layout, with exact source bytes
    # retained so interpreted numeric fields never masquerade as native JSON.
    source_xml: RawContent | None = Field(None, alias="_source_xml")


class MeetingsPage(SourceModel):
    committeeMeetings: list[MeetingSummary]
    pagination: Pagination | None = None
    request: RequestInfo | None = None


class MeetingResponse(SourceModel):
    committeeMeeting: CommitteeMeeting
    request: RequestInfo | None = None


class CommitteesPage(SourceModel):
    committees: list[CommitteeRecord]
    pagination: Pagination | None = None
    request: RequestInfo | None = None


class CommitteeResponse(SourceModel):
    committee: CommitteeDetail
    request: RequestInfo | None = None


def parse_response(value: dict) -> MeetingsPage | MeetingResponse | CommitteesPage | CommitteeResponse:
    """Validate an endpoint response without guessing a shape from its URL."""
    for key, model in (("committeeMeetings", MeetingsPage), ("committeeMeeting", MeetingResponse),
                       ("committees", CommitteesPage), ("committee", CommitteeResponse)):
        if key in value:
            return model.model_validate(value)
    raise ValueError("Congress.gov response has no supported meeting or committee field")
