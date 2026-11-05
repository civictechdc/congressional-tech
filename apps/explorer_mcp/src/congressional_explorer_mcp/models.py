"""Queries use the release's identifiers; no legacy catalog identities."""
from typing import Any, Literal
import re
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator

MAX_BYTES = 128 << 10


class ExplorerError(ValueError):
    pass


def exact_scalar(value, column_type, field):
    """Normalize integer spellings before SQL; never let a comparison round an ID."""
    bits = {'TINYINT': 8, 'SMALLINT': 16, 'INTEGER': 32, 'BIGINT': 64, 'HUGEINT': 128}.get(column_type.removeprefix('U'))
    if bits is not None:
        message = f'{field} requires a base-10 integer within {column_type} range; decimals, exponents and booleans are not accepted'
        if isinstance(value, str) and re.fullmatch(r'[+-]?[0-9]+', value.strip()):
            try:
                value = int(value.strip())
            except ValueError:
                raise ExplorerError(message) from None
        unsigned = column_type.startswith('U')
        lower, upper = (0, 2**bits) if unsigned else (-2**(bits-1), 2**(bits-1))
        if type(value) is not int or not lower <= value < upper:
            raise ExplorerError(message)
    elif column_type == 'VARCHAR':
        if not isinstance(value, str):
            raise ExplorerError(f'{field} requires text; preserve the published identifier or value exactly')
        name = field.split('.')[-1]
        if name in {'system_code', 'parent_system_code', 'committee_key', 'bill_id', 'nomination_id', 'measure_key', 'witness_key', 'link_key'}:
            return value.strip().lower()
        if name in {'bioguide_id', 'sponsor_bioguide_id', 'sponsor_bioguide'}:
            return value.strip().upper()
    elif column_type == 'BOOLEAN' and type(value) is not bool:
        raise ExplorerError(f'{field} requires a boolean (true or false)')
    return value


class Query(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Page(Query):
    limit: int = Field(default=25, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=4096)

    @field_validator('limit', mode='before')
    @classmethod
    def _limit(cls, value):
        return exact_scalar(value, 'INTEGER', 'limit')


class DocumentSearch(Page):
    text: str = Field(default='', max_length=2000)
    congress: int | None = Field(default=None, ge=1, le=999)
    format: str | None = Field(default=None, min_length=1, max_length=64)
    document_kind: str | None = Field(default=None, min_length=1, max_length=64)
    committee_key: str | None = Field(default=None, min_length=1, max_length=64)
    meeting_key: StrictStr | StrictInt | None = None
    measure_key: str | None = Field(default=None, min_length=1, max_length=64)
    witness_key: str | None = Field(default=None, min_length=1, max_length=256)
    bioguide_id: str | None = Field(default=None, min_length=1, max_length=32)
    include_hidden: StrictBool = False

    @field_validator('congress', mode='before')
    @classmethod
    def _congress(cls, value):
        return None if value is None else exact_scalar(value, 'SMALLINT', 'congress')

    @field_validator('meeting_key', mode='before')
    @classmethod
    def _meeting_key(cls, value):
        return None if value is None else str(exact_scalar(value, 'BIGINT', 'meeting_key'))

    @field_validator('committee_key', 'measure_key', 'witness_key', 'bioguide_id', mode='before')
    @classmethod
    def _keys(cls, value, info):
        return None if value is None else exact_scalar(value, 'VARCHAR', info.field_name)

    @field_validator('include_hidden', mode='before')
    @classmethod
    def _include_hidden(cls, value):
        return exact_scalar(value, 'BOOLEAN', 'include_hidden')


class DocumentQuery(Page):
    link_key: str = Field(pattern='^[a-fA-F0-9]{16}$')
    release_id: str = Field(pattern='^[a-f0-9]{64}$')
    section: Literal['summary', 'sources', 'recoveries', 'text', 'page_metadata', 'selected_text'] = 'summary'
    query: StrictStr | None = Field(default=None, max_length=2000)
    page: int | None = Field(default=None, ge=1, le=100000)
    offset: int = Field(default=0, ge=0, le=100_000_000)
    max_chars: int = Field(default=8000, ge=1, le=65536)

    @field_validator('link_key', mode='after')
    @classmethod
    def _link_key(cls, value):
        return value.lower()

    @field_validator('page', mode='before')
    @classmethod
    def _page(cls, value):
        return None if value is None else exact_scalar(value, 'INTEGER', 'page')

    @field_validator('offset', mode='before')
    @classmethod
    def _offset(cls, value):
        return exact_scalar(value, 'INTEGER', 'offset')

    @field_validator('max_chars', mode='before')
    @classmethod
    def _max_chars(cls, value):
        return exact_scalar(value, 'INTEGER', 'max_chars')


class EntitySearch(Page):
    table: str
    text: str = Field(default='', max_length=2000)
    filters: dict[str, StrictStr | StrictInt | StrictBool] = Field(default_factory=dict, max_length=12)


class EntityQuery(Page):
    table: str
    id: StrictStr | StrictInt
    section: Literal['record', 'documents'] = 'record'


class SqlQuery(Query):
    sql: str = Field(min_length=1, max_length=32768)
    parameters: list[Any] = Field(default_factory=list, max_length=100)
    limit: int = Field(default=100, ge=1, le=200)

    @field_validator('limit', mode='before')
    @classmethod
    def _limit(cls, value):
        return exact_scalar(value, 'INTEGER', 'limit')
