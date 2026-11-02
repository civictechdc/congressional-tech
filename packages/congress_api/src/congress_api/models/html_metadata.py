"""Publisher-declared metadata read from one retained HTML body, without page context."""
from hashlib import sha256
from typing import Any, Literal, NamedTuple

from pydantic import Field

from .base import SourceModel

METADATA_SCHEMA = 1
SNIPPET_CHARS = 280


class FormatResult(SourceModel):
    """One extractor's outcome; ``absent``, ``failed`` and ``skipped`` never collapse."""
    status: Literal['ok', 'absent', 'failed', 'skipped']
    basis: Literal['extractor', 'marker'] = 'extractor'
    items: list[Any] = Field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None
    skip_reason: str | None = None
    urls_resolved_against_base: bool = False


class HtmlMetadata(SourceModel):
    """Literal declarations: URLs are as published and nothing is selected here."""
    schema_version: int
    body_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    body_bytes: int
    encoding: str | None
    document_kind: Literal['html', 'non_html']
    error_title_hint: bool
    title: str | None
    declared_base: str | None
    formats: dict[str, FormatResult]
    head_meta: list[dict[str, str]]
    head_links: list[dict[str, str]]
    document_truncated: bool
    extruct_version: str | None  # provenance on the reading; never in a source payload

    @property
    def wall_clock_dependent(self) -> bool:
        return any(result.error_type in {'format_timeout', 'MemoryError'} for result in self.formats.values())


class PageFact(NamedTuple):
    """One declared value; ``path`` is a JSON Pointer into ``HtmlMetadata.source_dict()``."""
    field: str
    value: Any
    format: str
    path: str


class ContentLink(SourceModel):
    href: str
    text: str


class ContentCandidate(SourceModel):
    """An explicitly marked article body. ``selector`` is an XPath, or a JSON Pointer for JSON-LD."""
    selector: str
    property: str
    text: str
    char_count: int
    links: list[ContentLink]
    rdfa_confirmed: bool


class MainContentRef(SourceModel):
    """Bounded citation for a selected text; the full text stays with its owner."""
    body_sha256: str
    reader_version: str | None
    outcome: str
    selector: str | None
    property: str | None
    text_sha256: str | None
    text_bytes: int | None
    snippet: str | None


class MainContent(SourceModel):
    outcome: Literal['marked', 'marked_no_content', 'fallback_required', 'failed', 'none']
    body_sha256: str
    text: str | None
    selector: str | None
    property: str | None
    candidates: list[ContentCandidate]
    fallback_reason: str | None

    def ref(self, reader_version: str | None = None) -> MainContentRef:
        text = self.text
        if self.outcome == 'marked_no_content':
            text = next(candidate.text for candidate in self.candidates if candidate.selector == self.selector)
        encoded = text.encode('utf-8') if text is not None else None
        snippet = text
        if snippet and len(snippet) > SNIPPET_CHARS:
            cut = snippet[:SNIPPET_CHARS]
            snippet = cut.rsplit(None, 1)[0] if len(cut.split(None, 1)) > 1 else cut
        return MainContentRef(body_sha256=self.body_sha256, reader_version=reader_version, outcome=self.outcome,
                              selector=self.selector, property=self.property,
                              text_sha256=sha256(encoded).hexdigest() if encoded is not None else None,
                              text_bytes=len(encoded) if encoded is not None else None, snippet=snippet)
