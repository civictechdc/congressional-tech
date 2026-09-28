"""Source records, citations and explicit explanations for selected values."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from .common import Identifier, Model, Ref, ReportedTime, Sha256, Text, WebUrl


class RetainedContent(Model):
    """Digest pins the exact bytes at uri, including an imported input artifact."""

    uri: Text
    sha256: Sha256


class SourceRecord(Model):
    """One version of one provider record, not a mutable provider URL alone.

    `payload` preserves public, source-native fields, including unknown fields.
    A source file can instead be retained by digest; a citation locates its record.
    Import time does not establish when the source was fetched or published.
    """

    kind: Literal["source_record"] = "source_record"
    id: Text
    provider: Text
    identifier: Identifier
    input_snapshot_id: Text | None = None
    url: WebUrl | None = None
    retrieved_at: AwareDatetime | None = None
    imported_at: AwareDatetime | None = None
    source_modified_at: ReportedTime | None = None
    payload: JsonValue | None = None
    retained: RetainedContent | None = None

    @model_validator(mode="after")
    def retained_evidence(self):
        if self.payload is None and self.retained is None:
            raise ValueError("retain the source payload or a digest-pinned artifact")
        return self


class Citation(Model):
    source: Ref[Literal["source_record"]]
    selector_type: Literal["json_pointer", "xpath", "css", "row_key", "page", "time", "text"] | None = None
    selector: Text | None = None
    quote: str | None = None

    @model_validator(mode="after")
    def selector_pair(self):
        if (self.selector_type is None) != (self.selector is None):
            raise ValueError("provide both selector_type and selector")
        return self


class Method(Model):
    name: Text
    version: Text


class Provenance(Model):
    citations: Annotated[tuple[Citation, ...], Field(min_length=1)]
    basis: Literal["reported", "observed", "derived", "inferred", "curated"]
    method: Method | None = None
    explanation: str | None = None

    @model_validator(mode="after")
    def explain_derivation(self):
        if self.basis in ("derived", "inferred") and self.method is None:
            raise ValueError("derived/inferred values require a named, versioned method")
        return self


class AlternativeValue(Model):
    value: JsonValue
    provenance: Provenance


class FieldEvidence(Model):
    """Optional field override; record provenance supplies the ordinary case.

    Alternatives preserve disagreements without wrapping every domain value in
    a generic claim. The selected value remains in the domain record itself.
    """

    path: Annotated[str, Field(pattern=r"^/")]  # JSON Pointer within the record.
    selected: Provenance
    alternatives: tuple[AlternativeValue, ...] = ()
    selection_reason: str | None = None


class Record(Model):
    id: Text
    identifiers: tuple[Identifier, ...] = ()
    provenance: Provenance
    field_evidence: tuple[FieldEvidence, ...] = ()
