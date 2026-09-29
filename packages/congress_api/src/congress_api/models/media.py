"""Player query values, caption source structures and acquisition receipts."""
from typing import Annotated

from pydantic import Field, model_validator

from .base import SourceModel
from .content import RawContent


class SenatePlayerQuery(SourceModel):
    comm: str = ""
    filename: str = ""
    type: str | None = None
    stt: str | None = None
    auto_play: str | None = None
    poster: str | None = None
    wmode: str | None = None


class HLSRendition(SourceModel):
    type: str = Field(alias="TYPE")
    uri: str | None = Field(default=None, alias="URI")
    group_id: str | None = Field(default=None, alias="GROUP-ID")
    name: str | None = Field(default=None, alias="NAME")
    language: str | None = Field(default=None, alias="LANGUAGE")
    assoc_language: str | None = Field(default=None, alias="ASSOC-LANGUAGE")
    default: str | None = Field(default=None, alias="DEFAULT")
    autoselect: str | None = Field(default=None, alias="AUTOSELECT")
    forced: str | None = Field(default=None, alias="FORCED")
    instream_id: str | None = Field(default=None, alias="INSTREAM-ID")
    characteristics: str | None = Field(default=None, alias="CHARACTERISTICS")
    channels: str | None = Field(default=None, alias="CHANNELS")


class MediaTextSource(SourceModel):
    url: str
    text: str
    raw_body: RawContent | None = None
    status_code: int | None = None


class SenateCaptionSources(SourceModel):
    master: MediaTextSource
    master_checks: list[MediaTextSource] = Field(default_factory=list)
    prior_responses: list[MediaTextSource] = Field(default_factory=list)
    playlist: MediaTextSource | None = None
    segments: list[MediaTextSource] = Field(default_factory=list)


Timestamp = Annotated[str, Field(pattern=r"^(?:\d{2,}:)?[0-5]\d:[0-5]\d\.\d{3}$")]


class WebVTTCue(SourceModel):
    start: Timestamp
    end: Timestamp
    text: list[str]
    identifier: str | None = None
    settings: str = ""

    @model_validator(mode="after")
    def positive_duration(self):
        def seconds(value):
            return sum(float(part) * 60 ** index for index, part in enumerate(reversed(value.split(":"))))
        if seconds(self.end) <= seconds(self.start):
            raise ValueError("WebVTT cue ends before it starts")
        return self


class CaptionScope(SourceModel):
    kind: str
    master_url: str | None = None
    playlist_url: str | None = None
    segment_urls: list[str] = Field(default_factory=list)
    includes_embedded_archive_captions: bool | None = None
    video_url: str | None = None
    includes_manual: bool | None = None
    includes_automatic: bool | None = None


class CaptionError(SourceModel):
    type: str
    message: str


class CaptionReceipt(SourceModel):
    schema_version: str | None = None
    capture_version: str | None = None
    filename: str | None = None
    comm: str | None = None
    player_url: str | None = None
    video_id: str | None = None
    scope: CaptionScope
    observed_at: str | None = None
    outcome: str | None = None
    kind: str | None = None
    characters: Annotated[int, Field(ge=0)] | None = None
    source_file: str | None = None
    metadata_file: str | None = None
    source_responses: list[MediaTextSource] = Field(default_factory=list)
    reason: str | None = None
    selected_track: str | None = None
    track_files: list[str] = Field(default_factory=list)
    error: CaptionError | str | None = None
    last_successful: "CaptionReceipt | None" = None


class ArchiveProbe(SourceModel):
    urls: list[str]
    checked: str
    source: str
