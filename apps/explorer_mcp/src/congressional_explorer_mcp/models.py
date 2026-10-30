"""Queries use the release's identifiers; no legacy catalog identities."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

MAX_BYTES = 128 << 10
ENTITY_KEYS = {
    'meetings': 'event_id', 'witnesses': 'witness_key', 'recordings': 'video_key',
    'committees': 'system_code', 'members': 'bioguide_id', 'bills': 'bill_id',
    'nominations': 'nomination_id',
}
DOCUMENT_LINKS = {
    'meetings': 'meeting_keys', 'witnesses': 'witness_keys', 'committees': 'committee_keys',
    'members': 'bioguide_ids', 'bills': 'measure_keys', 'nominations': 'measure_keys',
}


class ExplorerError(ValueError):
    pass


class Query(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Page(Query):
    limit: int = Field(default=25, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=4096)


class DocumentSearch(Page):
    text: str = Field(default='', max_length=2000)
    congress: int | None = Field(default=None, ge=1, le=999)
    format: str | None = None
    document_kind: str | None = None
    committee_key: str | None = None
    meeting_key: str | None = None
    measure_key: str | None = None
    witness_key: str | None = None
    bioguide_id: str | None = None
    include_hidden: bool = False


class DocumentQuery(Page):
    link_key: str = Field(pattern='^[a-fA-F0-9]{16}$')
    release_id: str = Field(pattern='^[a-f0-9]{64}$')
    section: Literal['summary', 'sources', 'recoveries'] = 'summary'


class EntitySearch(Page):
    table: str
    text: str = Field(default='', max_length=2000)
    filters: dict[str, str | int | bool] = Field(default_factory=dict, max_length=12)


class EntityQuery(Page):
    table: str
    id: str | int
    section: Literal['record', 'documents'] = 'record'


class SqlQuery(Query):
    sql: str = Field(min_length=1, max_length=32768)
    parameters: list[Any] = Field(default_factory=list, max_length=100)
    limit: int = Field(default=100, ge=1, le=200)
