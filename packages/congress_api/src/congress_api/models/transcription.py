"""Typed transcription source results and the shared extracted transcript format.

Unknown publisher/model fields and role labels remain available. Numeric values
remain numeric; strings are not silently converted into timestamps or counts.
"""
from __future__ import annotations

import json
from pydantic import Field
from .base import SourceModel
from .content import RawContent

SCHEMA_VERSION = "1.0"


class Person(SourceModel):
    """A member, witness or other participant. `role` follows the print's conventions."""
    name: str                       # as printed / spoken: "Ben Cline", "Martha Williams"
    role: str                       # chair | ranking_member | member | witness | staff | clerk | other | unknown
    honorific: str = ""             # Mr. | Ms. | Mrs. | Dr. | Senator | The Chairman ...
    surname: str = ""               # the print attributes turns by surname: "Cline"
    party: str = ""                 # R | D | I, members only
    state: str = ""                 # members only
    bioguide_id: str = ""           # members only, when resolved
    organization: str = ""          # witnesses
    position: str = ""              # witnesses
    speaker_label: str = ""         # the diarization label this person was mapped from (machine transcripts)
    confidence: float | int | None = None  # how sure the mapping is, 0-1 (machine transcripts)


class Turn(SourceModel):
    """One speaker turn; times are seconds into the recording and, unlike WebVTT, start/end order is not validated."""
    speaker: str                    # key into Transcript.participants, or a raw label ("spk:3") when unresolved
    text: str
    start: float | int | None = None
    end: float | int | None = None
    kind: str = "speech"            # speech | statement (a witness's opening statement) | direction (bracketed stage direction)


class Insert(SourceModel):
    """Material the print includes that wasn't spoken: prepared statements, letters, questions for the record."""
    kind: str                       # prepared_statement | submission | questions_for_the_record | graphic | other
    title: str
    text: str = ""
    for_person: str = ""            # key into participants when the insert belongs to someone


class Header(SourceModel):
    title: str
    chamber: str                    # house | senate | joint
    congress: int | None = None
    session: int | None = None
    committee: str = ""             # "Committee on the Judiciary"
    committee_code: str = ""        # hsju00
    subcommittee: str = ""
    date: str = ""                  # ISO date
    time_convened: str = ""         # "2:02 p.m."
    time_adjourned: str = ""
    location: str = ""              # "Room 2141, Rayburn House Office Building"
    presiding: str = ""             # key into participants
    present: list[str] = Field(default_factory=list)   # keys into participants
    serial: str = ""                # print citation, when there is one
    package_id: str = ""            # GPO package, when there is one
    event_id: str = ""              # Congress.gov event ID


class Source(SourceModel):
    kind: str                       # gpo_print | gemini_transcription | youtube_captions | senate_captions
    url: str = ""
    video_id: str = ""
    model: str = ""
    generated_at: str = ""
    notes: str = ""


class Transcript(SourceModel):
    header: Header
    participants: dict[str, Person]  # key: a slug like "cline", "williams-martha"
    turns: list[Turn]
    inserts: list[Insert] = Field(default_factory=list)
    source: Source = Field(default_factory=lambda: Source(kind="unknown"))
    schema_version: str = SCHEMA_VERSION

    def to_json(self, **kw) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, indent=kw.pop("indent", 1), **kw)

    @classmethod
    def from_json(cls, text: str) -> "Transcript":
        return cls.model_validate_json(text)


class GeminiTurn(SourceModel):
    speaker: str
    role: str
    confidence: float | int = Field(ge=0, le=1)
    start: float | int
    end: float | int | None = None
    text: str


class GeminiEvent(SourceModel):
    seconds: float | int
    kind: str
    text: str


class GeminiUsage(SourceModel):
    input_tokens: int = Field(alias='in')
    output_tokens: int = Field(alias='out')


class GeminiTranscriptResponse(SourceModel):
    turns: list[GeminiTurn]
    events: list[GeminiEvent]
    usage: GeminiUsage | None = None


class GeminiResponseCapture(SourceModel):
    """Full SDK-returned HTTP response text plus the generated JSON text."""
    model: str
    start: float | int
    end: float | int
    observed_at: str
    response: RawContent | None
    generated: RawContent | None


class YoutubeRegionRestriction(SourceModel):
    allowed: list[str] | None = None
    blocked: list[str] | None = None


class YoutubeContentDetails(SourceModel):
    """The complete contentDetails part; rating authorities are native keys.

    https://developers.google.com/youtube/v3/docs/videos#contentDetails
    """
    duration: str
    dimension: str | None = None
    definition: str | None = None
    caption: str | None = None
    licensed_content: bool | None = Field(default=None, alias='licensedContent')
    region_restriction: YoutubeRegionRestriction | None = Field(default=None, alias='regionRestriction')
    content_rating: dict[str, str | list[str]] | None = Field(default=None, alias='contentRating')
    projection: str | None = None
    has_custom_thumbnail: bool | None = Field(default=None, alias='hasCustomThumbnail')


class YoutubeVideoItem(SourceModel):
    kind: str | None = None
    etag: str | None = None
    id: str | None = None
    content_details: YoutubeContentDetails = Field(alias='contentDetails')


class YoutubePageInfo(SourceModel):
    total_results: int | None = Field(default=None, alias='totalResults')
    results_per_page: int | None = Field(default=None, alias='resultsPerPage')


class YoutubeVideoResponse(SourceModel):
    kind: str | None = None
    etag: str | None = None
    next_page_token: str | None = Field(default=None, alias='nextPageToken')
    previous_page_token: str | None = Field(default=None, alias='prevPageToken')
    page_info: YoutubePageInfo | None = Field(default=None, alias='pageInfo')
    items: list[YoutubeVideoItem] = Field(default_factory=list)


class YtdlpVideoInfo(SourceModel):
    """SDK extraction result; retain every extractor-specific field unchanged."""
    id: str | None = None
    title: str | None = None
    duration: float | int | None = None
    webpage_url: str | None = None
    extractor: str | None = None
    extractor_key: str | None = None
