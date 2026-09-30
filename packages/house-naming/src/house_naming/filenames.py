"""Typed access to the shared literal filename reader.

All extraction grammar and precedence live in house_naming. This module adapts
its observations to Pydantic models; corpus helpers use that same reader.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict
from house_naming.corpus import filename_tokens as _filename_tokens, shared_token_pattern
from house_naming.extraction import EXTENSION, date_candidates, member_title_pattern
from .naming import HOUSE_NAMING


class FilenameField(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    name: str
    raw: str
    start: int
    end: int
    candidates: tuple[str, ...] = ()
    note: str | None = None
    code: str | None = None
    label: str | None = None
    context: str | None = None
    vocabulary_url: str | None = None


class FilenameMatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    rule: str
    start: int
    end: int
    fields: tuple[FilenameField, ...]
    scope: str = ''
    description: str = ''


class SuppressedFilenameMatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    rule: str
    raw: str
    start: int
    end: int
    reason: str
    fields: tuple[FilenameField, ...]


class FilenamePiece(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    kind: str
    raw: str
    start: int
    end: int


class RejectedNamingCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    kind: str
    priority: int
    code: str
    message: str
    details: tuple[dict[str, Any], ...] = ()


class ParsedFilename(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    filename: str
    stem_end: int
    matches: tuple[FilenameMatch, ...]
    pieces: tuple[FilenamePiece, ...]
    suppressed: tuple[SuppressedFilenameMatch, ...] = ()
    issues: tuple[str, ...] = ()
    rejected_candidates: tuple[RejectedNamingCandidate, ...] = ()


def parse_filename(filename: str, *, member_surnames: Mapping[str, Sequence[str]] | None = None) -> ParsedFilename:
    """Return the engine's literal observations, including rejected alternatives.

    `matches` means extracted source syntax, not convention-valid records.
    Use HOUSE_NAMING.parse for renderable records. Issues and rejected candidates
    report convention validation; neither invalidity nor fallback implies that
    this filename was discarded.
    """
    result = HOUSE_NAMING.extract(filename, member_surnames=member_surnames)
    matches = tuple(FilenameMatch.model_validate(match) for match in result['observations'])
    return ParsedFilename(filename=result['input'], stem_end=result['stem_end'], matches=matches,
                          pieces=result['pieces'], suppressed=result['suppressed'],
                          issues=result['issues'], rejected_candidates=result['rejected_candidates'])


def resolve_unmatched_filename(parsed: ParsedFilename) -> FilenameMatch | None:
    """Select an existing engine fallback; never parse the filename a second way."""
    return next((match for match in parsed.matches
                 if match.scope in {'unmatched-date', 'unmatched-stem'}), None)


def date_readings(raw: str) -> tuple[tuple[str, ...], str]:
    candidates, _, note = date_candidates(raw)
    return tuple(candidates), note


def filename_tokens(parsed: ParsedFilename) -> tuple[FilenamePiece, ...]:
    result = {'stem_end': parsed.stem_end, 'pieces': [p.model_dump() for p in parsed.pieces]}
    return tuple(FilenamePiece.model_validate(piece) for piece in _filename_tokens(result))


def registry() -> list[dict]:
    """Return the engine catalog's extraction rules, with no application copy."""
    return [dict(rule, flags=['IGNORECASE', 'ASCII']) for rule in HOUSE_NAMING.extraction_rules()]
