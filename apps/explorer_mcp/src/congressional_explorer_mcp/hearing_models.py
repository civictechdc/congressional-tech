"""Release-bound hearing and passage requests."""
from typing import Literal

from pydantic import Field, StrictInt, StrictStr, field_validator

from .models import Query, exact_scalar


class HearingQuery(Query):
    event_id: StrictInt | StrictStr
    release_id: str | None = Field(default=None, pattern='^[a-f0-9]{64}$')

    @field_validator('event_id', mode='before')
    @classmethod
    def event(cls, value):
        return exact_scalar(value, 'BIGINT', 'event_id')


class TranscriptQuery(HearingQuery):
    kind: Literal['official', 'committee', 'captions'] | None = None
    source_id: str | None = Field(default=None, pattern='^[a-f0-9]{64}$')
    offset: int = Field(default=0, ge=0, le=100_000_000)
    limit: int = Field(default=25, ge=1, le=100)
    page: int | None = Field(default=None, ge=1, le=100000)
    max_chars: int = Field(default=8000, ge=1, le=32768)
    cursor: str | None = Field(default=None, max_length=4096)

    @field_validator('offset', 'limit', 'page', 'max_chars', mode='before')
    @classmethod
    def integer(cls, value, info):
        return None if value is None else exact_scalar(value, 'INTEGER', info.field_name)


SECTIONS = ('meeting', 'committees', 'witnesses', 'prepared_testimony', 'official_transcripts',
            'committee_transcripts', 'captions', 'recordings', 'coverage')


class HearingBundleQuery(HearingQuery):
    include: list[Literal['meeting', 'committees', 'witnesses', 'prepared_testimony', 'official_transcripts',
                          'committee_transcripts', 'captions', 'recordings', 'coverage']] = Field(default_factory=lambda: list(SECTIONS))
    limit: int = Field(default=10, ge=1, le=50)
    offsets: dict[str, int] = Field(default_factory=dict, max_length=len(SECTIONS))

    @field_validator('limit', mode='before')
    @classmethod
    def integer(cls, value):
        return exact_scalar(value, 'INTEGER', 'limit')

    @field_validator('offsets', mode='before')
    @classmethod
    def section_offsets(cls, value):
        for section, offset in value.items():
            if section not in SECTIONS or exact_scalar(offset, 'INTEGER', section) < 0:
                raise ValueError('offsets must name hearing sections with nonnegative integer positions')
        return value


class CitationQuery(Query):
    citation: dict = Field(max_length=20)
