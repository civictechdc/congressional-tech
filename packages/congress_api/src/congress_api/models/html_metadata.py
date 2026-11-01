"""Publisher-declared metadata read from one retained HTML body, without page context."""
from typing import Any, Literal, NamedTuple

from pydantic import Field

from .base import SourceModel

METADATA_SCHEMA = 1


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
    outcome: Literal['marked', 'marked_no_content', 'conflicting_candidates', 'fallback_extractor', 'none']
    body_sha256: str
    text: str | None
    selector: str | None
    property: str | None
    candidates: list[ContentCandidate]
    fallback_reason: str | None

    def ref(self, reader_version: str | None = None) -> MainContentRef:
        from hashlib import sha256
        encoded = self.text.encode('utf-8') if self.text is not None else None
        snippet = None
        if self.text:
            snippet = self.text[:280]
            if len(self.text) > 280:
                snippet = snippet.rsplit(None, 1)[0] if ' ' in snippet else snippet
        return MainContentRef(body_sha256=self.body_sha256, reader_version=reader_version, outcome=self.outcome,
                              selector=self.selector, property=self.property,
                              text_sha256=sha256(encoded).hexdigest() if encoded is not None else None,
                              text_bytes=len(encoded) if encoded is not None else None, snippet=snippet)
